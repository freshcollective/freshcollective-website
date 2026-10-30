"""Checking that the history we think we are keeping is actually there.

Thirty-four write sites across membership, subscriptions, Collective
lifecycle and money now call a producer. The risk is not that one of
them is wrong today — it is that a thirty-fifth gets added next year and
nobody notices history stopped being recorded for it. These checks turn
that silence into a number.

Every check is a count of exceptions plus a sample of ids, never a dump.
Nothing here writes.

The activation boundary
-----------------------
The hard part is not detecting a missing event; it is not crying wolf
about the years before any of this existed. Every check is therefore
bounded below by ``activation_floor`` — the earliest ``recorded_at`` in
``business_events`` — and only considers records whose own timestamp
falls after it. A membership that ended in 2025 is *expected* to have no
departure event and is not an exception; one that ends tomorrow and has
none is.

That floor is derived from the data rather than configured, so it cannot
drift out of step with reality, and an empty table reports "not yet
active" instead of tens of thousands of false exceptions.

Three outcomes are distinguished, which is what makes the report
trustworthy:

``pre_activation``
    The record predates recording. Not an exception. Counted so the
    boundary is visible rather than implied.
``unreconstructable``
    After activation, but the event could never have existed — a
    membership whose departure happened before the floor and was then
    rejoined, for instance. Reported separately from a genuine gap.
``missing``
    After activation, should have an event, has none. This is the one
    that means a producer is missing, and the only one worth waking up
    for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.business_event import BusinessEvent
from app.services.business_events import BusinessEventType

#: How many offending ids a check carries back. Enough to start
#: investigating, few enough that the result stays a report.
SAMPLE_LIMIT = 20


@dataclass
class CheckResult:
    name: str
    #: Records that should have an event and do not, after activation.
    missing: int = 0
    #: Records predating activation. Expected, not a problem.
    pre_activation: int = 0
    #: After activation but genuinely unreconstructable. Explained, not
    #: alarming.
    unreconstructable: int = 0
    sample_ids: list[str] = field(default_factory=list)
    note: str | None = None

    @property
    def ok(self) -> bool:
        return self.missing == 0


@dataclass
class ReconciliationReport:
    #: None when nothing has been recorded yet, in which case every
    #: check is skipped rather than reporting the whole database as
    #: broken.
    activation_floor: datetime | None
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def total_missing(self) -> int:
        return sum(c.missing for c in self.checks)


def activation_floor(db: Session) -> datetime | None:
    """The earliest moment anything was recorded, or None if nothing has."""
    return db.execute(
        select(func.min(BusinessEvent.recorded_at))
    ).scalar()


def _sample(rows) -> list[str]:
    return [r[0] for r in rows[:SAMPLE_LIMIT]]


def check_active_memberships_have_a_start(db: Session, floor: datetime) -> CheckResult:
    """Every membership that began after activation should say so."""
    rows = db.execute(
        text(
            """
            SELECT m.id
            FROM space_memberships m
            WHERE m.joined_at > :floor
              AND NOT EXISTS (
                SELECT 1 FROM business_events e
                WHERE e.subject_type = 'membership'
                  AND e.subject_id = m.id
                  AND e.event_type IN ('membership.started', 'membership.reactivated')
              )
            ORDER BY m.joined_at DESC
            """
        ),
        {"floor": floor},
    ).fetchall()
    pre = db.execute(
        text("SELECT count(*) FROM space_memberships WHERE joined_at <= :floor"),
        {"floor": floor},
    ).scalar() or 0
    return CheckResult(
        name="memberships_without_a_start_event",
        missing=len(rows),
        pre_activation=int(pre),
        sample_ids=_sample(rows),
        note="A membership created by a path that never calls a producer.",
    )


def check_removed_memberships_have_an_end(db: Session, floor: datetime) -> CheckResult:
    """Every departure after activation should be recorded.

    Note what this cannot see: a membership removed *and rejoined* loses
    ``removed_at``, so a missed departure on a since-rejoined row is
    invisible here. That is the very loss this release exists to stop,
    and it is why the start-event check above matters as much as this
    one — a rejoin writes ``membership.reactivated``, so the sequence is
    detectable even when the columns are not.
    """
    rows = db.execute(
        text(
            """
            SELECT m.id
            FROM space_memberships m
            WHERE m.removed_at IS NOT NULL
              AND m.removed_at > :floor
              AND NOT EXISTS (
                SELECT 1 FROM business_events e
                WHERE e.subject_type = 'membership'
                  AND e.subject_id = m.id
                  AND e.event_type = 'membership.ended'
              )
            ORDER BY m.removed_at DESC
            """
        ),
        {"floor": floor},
    ).fetchall()
    pre = db.execute(
        text(
            "SELECT count(*) FROM space_memberships "
            "WHERE removed_at IS NOT NULL AND removed_at <= :floor"
        ),
        {"floor": floor},
    ).scalar() or 0
    return CheckResult(
        name="departures_without_an_end_event",
        missing=len(rows),
        pre_activation=int(pre),
        sample_ids=_sample(rows),
        note="A removal path that never calls a producer.",
    )


def check_settled_payments_have_a_settlement(
    db: Session, floor: datetime
) -> CheckResult:
    """Every payment that succeeded after activation should carry one.

    Deliberately checks ``settled_at`` rather than the event: the column
    and the event are written together by ``mark_settled``, so a row with
    no ``settled_at`` means a settlement path was missed — and there are
    eight of them, which is the most likely place for a gap.
    """
    rows = db.execute(
        text(
            """
            SELECT t.id
            FROM payment_transactions t
            WHERE t.status = 'succeeded'
              AND t.created_at > :floor
              AND t.settled_at IS NULL
            ORDER BY t.created_at DESC
            """
        ),
        {"floor": floor},
    ).fetchall()
    pre = db.execute(
        text(
            "SELECT count(*) FROM payment_transactions "
            "WHERE status = 'succeeded' AND created_at <= :floor"
        ),
        {"floor": floor},
    ).scalar() or 0
    return CheckResult(
        name="succeeded_payments_without_a_settlement",
        missing=len(rows),
        pre_activation=int(pre),
        unreconstructable=int(pre),
        sample_ids=_sample(rows),
        note=(
            "A ninth settlement path, or an existing one that stopped "
            "calling mark_settled. Rows before activation are expected to "
            "be NULL — no settlement date was ever observed for them."
        ),
    )


def check_paid_payouts_have_an_event(db: Session, floor: datetime) -> CheckResult:
    """Cash that left should be recorded as having left.

    The payout producer is the one that cannot read its own subject —
    the update is bulk SQL — so it is the easiest to forget.
    """
    rows = db.execute(
        text(
            """
            SELECT t.id
            FROM payment_transactions t
            WHERE t.payout_status = 'paid'
              AND t.payout_marked_at IS NOT NULL
              AND t.payout_marked_at > :floor
              AND NOT EXISTS (
                SELECT 1 FROM business_events e
                WHERE e.subject_type = 'transaction'
                  AND e.subject_id = t.id
                  AND e.event_type = 'payout.paid'
              )
            ORDER BY t.payout_marked_at DESC
            """
        ),
        {"floor": floor},
    ).fetchall()
    pre = db.execute(
        text(
            "SELECT count(*) FROM payment_transactions "
            "WHERE payout_status = 'paid' AND "
            "(payout_marked_at IS NULL OR payout_marked_at <= :floor)"
        ),
        {"floor": floor},
    ).scalar() or 0
    return CheckResult(
        name="paid_payouts_without_an_event",
        missing=len(rows),
        pre_activation=int(pre),
        sample_ids=_sample(rows),
        note="A payout marking path that never calls a producer.",
    )


def check_refunded_payments_have_an_event(
    db: Session, floor: datetime
) -> CheckResult:
    """Money that went back should be recorded as having gone back."""
    rows = db.execute(
        text(
            """
            SELECT t.id
            FROM payment_transactions t
            WHERE t.refunded_amount_cents > 0
              AND t.last_refunded_at IS NOT NULL
              AND t.last_refunded_at > :floor
              AND NOT EXISTS (
                SELECT 1 FROM business_events e
                WHERE e.subject_type = 'transaction'
                  AND e.subject_id = t.id
                  AND e.event_type = 'payment.refunded'
              )
            ORDER BY t.last_refunded_at DESC
            """
        ),
        {"floor": floor},
    ).fetchall()
    pre = db.execute(
        text(
            "SELECT count(*) FROM payment_transactions "
            "WHERE refunded_amount_cents > 0 AND "
            "(last_refunded_at IS NULL OR last_refunded_at <= :floor)"
        ),
        {"floor": floor},
    ).scalar() or 0
    return CheckResult(
        name="refunds_without_an_event",
        missing=len(rows),
        pre_activation=int(pre),
        sample_ids=_sample(rows),
        note=(
            "A refund path that never calls a producer. Only the latest "
            "refund per transaction is visible in the column, so this "
            "cannot detect a missed earlier partial refund."
        ),
    )


def check_subscription_plan_agrees_with_history(
    db: Session, floor: datetime
) -> CheckResult:
    """A subscription's plan should match its last recorded change.

    Divergence means a plan was changed by a path with no producer — the
    exact failure that makes MRR movement unreportable, and the one it
    is hardest to notice from the outside.
    """
    rows = db.execute(
        text(
            """
            WITH last_change AS (
                SELECT DISTINCT ON (e.subject_id)
                       e.subject_id,
                       e.payload ->> 'to_plan_id' AS to_plan_id
                FROM business_events e
                WHERE e.subject_type = 'subscription'
                  AND e.event_type = 'subscription.plan_changed'
                ORDER BY e.subject_id, e.occurred_at DESC, e.sequence_number DESC
            )
            SELECT s.id
            FROM creator_subscriptions s
            JOIN last_change lc ON lc.subject_id = s.id
            WHERE lc.to_plan_id IS NOT NULL
              AND s.creator_plan_id <> lc.to_plan_id
              AND s.updated_at > :floor
            """
        ),
        {"floor": floor},
    ).fetchall()
    return CheckResult(
        name="subscription_plan_disagrees_with_history",
        missing=len(rows),
        sample_ids=_sample(rows),
        note="A plan change written by a path with no producer.",
    )


def check_published_collectives_have_a_date(
    db: Session, floor: datetime
) -> CheckResult:
    """An active Collective should know when it was first published.

    Collectives are created as drafts and published by one route, so a
    gap here is narrow — but ``first_published_at`` is write-once and
    feeds the creator funnel, so a miss is worth seeing.
    """
    rows = db.execute(
        text(
            """
            SELECT s.id
            FROM spaces s
            WHERE s.status = 'active'
              AND s.first_published_at IS NULL
              AND s.updated_at > :floor
            """
        ),
        {"floor": floor},
    ).fetchall()
    pre = db.execute(
        text(
            "SELECT count(*) FROM spaces "
            "WHERE status = 'active' AND first_published_at IS NULL "
            "AND updated_at <= :floor"
        ),
        {"floor": floor},
    ).scalar() or 0
    return CheckResult(
        name="active_collectives_without_a_publication_date",
        missing=len(rows),
        pre_activation=int(pre),
        unreconstructable=int(pre),
        sample_ids=_sample(rows),
        note=(
            "Collectives published before activation have no recoverable "
            "date and are expected here."
        ),
    )


def check_duplicate_events(db: Session, floor: datetime) -> CheckResult:
    """There should be no duplicates. The unique index guarantees it.

    Kept anyway, cheaply: if this ever returns a number, the dedupe key
    is not discriminating what it was supposed to, and that is worth
    finding out from a report rather than from a wrong chart.
    """
    rows = db.execute(
        text(
            """
            SELECT dedupe_key
            FROM business_events
            GROUP BY dedupe_key
            HAVING count(*) > 1
            """
        )
    ).fetchall()
    return CheckResult(
        name="duplicate_dedupe_keys",
        missing=len(rows),
        sample_ids=_sample(rows),
        note="Should be structurally impossible — ux_business_events_dedupe.",
    )


CHECKS = (
    check_active_memberships_have_a_start,
    check_removed_memberships_have_an_end,
    check_settled_payments_have_a_settlement,
    check_paid_payouts_have_an_event,
    check_refunded_payments_have_an_event,
    check_subscription_plan_agrees_with_history,
    check_published_collectives_have_a_date,
    check_duplicate_events,
)


def reconcile(db: Session) -> ReconciliationReport:
    """Run every check. Reads only.

    With nothing recorded yet, returns an empty report rather than
    declaring the whole database inconsistent — the honest answer to
    "is our history complete" before any history exists is "recording
    has not started".
    """
    floor = activation_floor(db)
    if floor is None:
        return ReconciliationReport(activation_floor=None, checks=[])
    return ReconciliationReport(
        activation_floor=floor,
        checks=[check(db, floor) for check in CHECKS],
    )


def event_counts_by_type(db: Session) -> dict[str, int]:
    """What has been recorded, by type. For monitoring that it is running."""
    rows = db.execute(
        select(BusinessEvent.event_type, func.count())
        .group_by(BusinessEvent.event_type)
    ).fetchall()
    counts = {t.value: 0 for t in BusinessEventType}
    counts.update({row[0]: int(row[1]) for row in rows})
    return counts
