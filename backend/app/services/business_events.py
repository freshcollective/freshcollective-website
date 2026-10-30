"""Recording what happened, once, in the caller's transaction.

Every producer here is one call at the site of a business operation, and
each one obeys three rules:

**It is atomic with the operation it describes.** The insert is added to
the caller's ``Session`` and commits with the caller's own work. There
is no second transaction and no background task, so a membership cannot
end without the event, and an event cannot describe a removal that was
rolled back.

**It is idempotent.** Every insert is ``ON CONFLICT DO NOTHING`` on a
unique ``dedupe_key``. A Stripe retry, a re-run, or two concurrent
writers produce exactly one row, and neither caller sees an error. No
exception handling and no savepoints — which matters practically as well
as aesthetically, because ``begin_nested()`` is unusable under the test
fixture once a session has committed, so an exception-based design could
not be tested honestly.

**It distinguishes a repeat from a retry.** The dedupe key for a
lifecycle transition includes the moment it happened, so join → leave →
rejoin → leave is four rows while the same webhook delivered twice is
one. The key for anything Stripe-driven includes the provider's own
event id, which is the only identifier that reliably separates those two
cases.

Privacy
-------
``payload`` takes identifiers, amounts and enum values. The schema check
below is an allowlist per event type, so member-authored content — a
message, a reflection, a removal note — cannot enter the analytics layer
even by accident. User ids live in the typed columns, never in the
payload, because those columns are ``ON DELETE SET NULL`` and a payload
copy would survive the account deletion that is supposed to remove it.

Failure
-------
A validation failure is a programming error and raises, in tests and in
production alike: an event whose shape is wrong is worse than no event,
because it would be counted. A *database* failure is not swallowed
either — it propagates and takes the caller's transaction with it. That
is deliberate. The alternative is a membership change that silently
leaves no history, which is the exact failure this release exists to
prevent.

The one escape hatch is ``settings.business_events_enabled``, which
defaults to ``True`` so that an absent configuration records rather than
loses. When it is off every producer returns without writing and logs a
warning naming the event it dropped, so a disabled recorder is visible
in the logs rather than silently becoming the normal state.
"""

from __future__ import annotations

import enum
import logging
import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.business_event import BusinessEvent

logger = logging.getLogger(__name__)


class BusinessEventType(str, enum.Enum):
    """Every event this release records. Closed set, by design."""

    # Membership — the facts destroyed by rejoining.
    membership_started = "membership.started"
    membership_ended = "membership.ended"
    membership_reactivated = "membership.reactivated"

    # Creator subscription — the facts destroyed by overwriting the plan.
    subscription_started = "subscription.started"
    subscription_plan_changed = "subscription.plan_changed"
    subscription_cancelled = "subscription.cancelled"
    subscription_payment_failed = "subscription.payment_failed"
    # The terminal form of a payment failure: the grace window ran out.
    # Its own type rather than another ``payment_failed``, which would
    # double-count the failure, and rather than ``cancelled``, which it
    # is not — the subscription still exists, it has simply stopped
    # being paid for. MRR has to know the difference.
    subscription_lapsed = "subscription.lapsed"

    # Collective lifecycle and categorisation.
    collective_published = "collective.published"
    collective_archived = "collective.archived"
    collective_themes_changed = "collective.themes_changed"

    # Money. Each carries its own event date, which is what lets the
    # metric registry stop attributing revenue by row-mutation time.
    payment_settled = "payment.settled"
    payment_refunded = "payment.refunded"
    payout_paid = "payout.paid"
    payout_reversed = "payout.reversed"


class SubjectType(str, enum.Enum):
    membership = "membership"
    subscription = "subscription"
    collective = "collective"
    transaction = "transaction"


#: Allowed payload keys per event type. An allowlist rather than a
#: denylist: a new field has to be declared here, which is the moment
#: somebody notices they are about to store something they should not.
_PAYLOAD_KEYS: dict[BusinessEventType, frozenset[str]] = {
    BusinessEventType.membership_started: frozenset({"role", "source", "status"}),
    BusinessEventType.membership_ended: frozenset(
        {"role", "removal_kind", "rejoin_blocked", "tenure_days"}
    ),
    BusinessEventType.membership_reactivated: frozenset({"role", "source"}),
    BusinessEventType.subscription_started: frozenset(
        {"plan_id", "plan_slug", "source", "status"}
    ),
    BusinessEventType.subscription_plan_changed: frozenset(
        {"from_plan_id", "to_plan_id", "from_plan_slug", "to_plan_slug", "direction"}
    ),
    BusinessEventType.subscription_cancelled: frozenset(
        {"plan_id", "plan_slug", "reason", "at_period_end", "initiated_by"}
    ),
    BusinessEventType.subscription_payment_failed: frozenset(
        {"plan_id", "plan_slug", "status", "provider_invoice_id"}
    ),
    BusinessEventType.subscription_lapsed: frozenset(
        {"plan_id", "plan_slug", "status", "grace_expired_at"}
    ),
    BusinessEventType.collective_published: frozenset({"from_status", "to_status"}),
    BusinessEventType.collective_archived: frozenset({"from_status", "to_status"}),
    BusinessEventType.collective_themes_changed: frozenset(
        {"from_themes", "to_themes", "added", "removed"}
    ),
    BusinessEventType.payment_settled: frozenset(
        {
            "transaction_type",
            "currency",
            "gross_amount_cents",
            "platform_fee_cents",
            "net_creator_amount_cents",
            "processing_fee_cents",
            "stripe_mode",
            "settlement_path",
        }
    ),
    BusinessEventType.payment_refunded: frozenset(
        {
            "currency",
            "refund_delta_cents",
            "refunded_total_cents",
            "refunded_platform_fee_cents",
            "refunded_creator_amount_cents",
            "resulting_status",
            "stripe_mode",
        }
    ),
    BusinessEventType.payout_paid: frozenset(
        {"currency", "amount_cents", "batch_id", "reference"}
    ),
    # No ``reason``: the cancellation reason is free text an operator
    # typed, so it fails the no-free-text rule — and a long one would
    # raise here and roll back the payout cancellation itself, which is
    # a reporting concern breaking a financial operation. The batch row
    # keeps the text; the event keeps the fact.
    BusinessEventType.payout_reversed: frozenset(
        {"currency", "amount_cents", "batch_id"}
    ),
}

#: A payload value may be a scalar, or a list of short strings (theme
#: lists, which is the only list any event carries). Long strings are
#: refused outright because free text is how content leaks in.
_MAX_STRING = 120
_MAX_LIST = 30


class BusinessEventPayloadError(ValueError):
    """The payload is not a shape this event type may carry."""


def _validate(event_type: BusinessEventType, payload: dict) -> dict:
    """Check the shape, bound the size, and return what to store.

    Two different kinds of problem, handled differently on purpose:

    * **Shape** — an undeclared key, or a value that is not a scalar or a
      list of strings — is a *programming* error. Payload keys are
      static literals inside the producers above, so a shape error
      cannot appear at runtime without appearing in the tests first. It
      raises.

    * **Size** — a string longer than the cap, or a list longer than the
      cap — is *data*. An operator can type a long note; a creator can
      pick an unusual theme name. Raising on that would let a reporting
      concern roll back a payment or a payout, which is never an
      acceptable trade. Over-long values are truncated and the list is
      clipped, so the event is still recorded and still carries no free
      prose.

    Returns a new dict; the caller's is never mutated.
    """
    allowed = _PAYLOAD_KEYS[event_type]
    extra = set(payload) - allowed
    if extra:
        raise BusinessEventPayloadError(
            f"{event_type.value}: undeclared payload keys {sorted(extra)}; "
            f"allowed {sorted(allowed)}"
        )

    out: dict = {}
    for key, value in payload.items():
        if value is None or isinstance(value, (int, float, bool)):
            out[key] = value
            continue
        if isinstance(value, str):
            out[key] = value[:_MAX_STRING]
            continue
        if isinstance(value, (list, tuple)):
            clipped = []
            for item in value[:_MAX_LIST]:
                if not isinstance(item, str):
                    raise BusinessEventPayloadError(
                        f"{event_type.value}: {key!r} must be a list of strings, "
                        f"found {type(item).__name__}"
                    )
                clipped.append(item[:_MAX_STRING])
            out[key] = clipped
            continue
        raise BusinessEventPayloadError(
            f"{event_type.value}: {key!r} is {type(value).__name__}; business "
            "events carry scalars and lists of short strings only"
        )
    return out


def _stamp(dt: datetime) -> str:
    """Microsecond precision, so two transitions in the same second stay apart."""
    return dt.strftime("%Y%m%d%H%M%S%f")


def record(
    db: Session,
    *,
    event_type: BusinessEventType,
    occurred_at: datetime,
    subject_type: SubjectType,
    subject_id: str,
    dedupe_key: str,
    payload: dict | None = None,
    actor_user_id: str | None = None,
    user_id: str | None = None,
    space_id: str | None = None,
    creator_user_id: str | None = None,
) -> bool:
    """Append one event. Returns False when the key was already present.

    Adds the insert to ``db`` without flushing or committing, so it
    travels with whatever transaction the caller is already in.
    """
    payload = _validate(event_type, dict(payload or {}))

    if not settings.business_events_enabled:
        # Named explicitly, so a disabled recorder leaves a trail rather
        # than a silence that looks like nothing happened.
        logger.warning(
            "business_events disabled — dropped %s for %s %s",
            event_type.value, subject_type.value, subject_id,
        )
        return False

    stmt = (
        pg_insert(BusinessEvent.__table__)
        .values(
            id=str(uuid.uuid4()),
            event_type=event_type.value,
            occurred_at=occurred_at,
            # Set in Python rather than left to the column's ``now()``
            # default. ``now()`` is evaluated in the database session's
            # timezone and these columns are naive, so on a server set to
            # anything but UTC the default would store local time beside
            # a UTC ``occurred_at`` — putting the reconciliation
            # activation boundary hours into the future and making
            # late-arrival detection meaningless. Both timestamps now
            # come from one clock.
            recorded_at=datetime.utcnow(),
            subject_type=subject_type.value,
            subject_id=subject_id,
            actor_user_id=actor_user_id,
            user_id=user_id,
            space_id=space_id,
            creator_user_id=creator_user_id,
            payload=payload,
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    result = db.execute(stmt)
    return bool(result.rowcount)


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

def membership_started(
    db: Session,
    membership,
    *,
    occurred_at: datetime | None = None,
    actor_user_id: str | None = None,
    creator_user_id: str | None = None,
) -> bool:
    """A membership began. One event per join, including a first join."""
    when = occurred_at or membership.joined_at or datetime.utcnow()
    return record(
        db,
        event_type=BusinessEventType.membership_started,
        occurred_at=when,
        subject_type=SubjectType.membership,
        subject_id=membership.id,
        dedupe_key=f"membership:{membership.id}:started:{_stamp(when)}",
        payload={
            "role": getattr(membership.role, "value", membership.role),
            "source": membership.source,
            "status": getattr(membership.status, "value", membership.status),
        },
        actor_user_id=actor_user_id,
        user_id=membership.user_id,
        space_id=membership.space_id,
        creator_user_id=creator_user_id,
    )


def membership_ended(
    db: Session,
    membership,
    *,
    occurred_at: datetime,
    actor_user_id: str | None = None,
    creator_user_id: str | None = None,
) -> bool:
    """A membership ended.

    The event that did not exist before this release. ``removal_reason``
    and ``removal_note`` are deliberately absent from the payload — the
    reason is free text a creator wrote about a person, which belongs in
    the membership row and not in analytics. ``removal_kind`` is the
    enum, and it is the part a report can count.
    """
    tenure = None
    if membership.joined_at:
        tenure = max(0, (occurred_at - membership.joined_at).days)
    return record(
        db,
        event_type=BusinessEventType.membership_ended,
        occurred_at=occurred_at,
        subject_type=SubjectType.membership,
        subject_id=membership.id,
        dedupe_key=f"membership:{membership.id}:ended:{_stamp(occurred_at)}",
        payload={
            "role": getattr(membership.role, "value", membership.role),
            "removal_kind": membership.removal_kind,
            "rejoin_blocked": bool(membership.rejoin_blocked),
            "tenure_days": tenure,
        },
        actor_user_id=actor_user_id,
        user_id=membership.user_id,
        space_id=membership.space_id,
        creator_user_id=creator_user_id,
    )


def membership_reactivated(
    db: Session,
    membership,
    *,
    occurred_at: datetime,
    actor_user_id: str | None = None,
    creator_user_id: str | None = None,
) -> bool:
    """A removed membership came back.

    Recorded as its own type as well as counting as a start, because
    "rejoined" and "joined for the first time" are different business
    facts and the row cannot tell them apart afterwards.
    """
    return record(
        db,
        event_type=BusinessEventType.membership_reactivated,
        occurred_at=occurred_at,
        subject_type=SubjectType.membership,
        subject_id=membership.id,
        dedupe_key=f"membership:{membership.id}:reactivated:{_stamp(occurred_at)}",
        payload={
            "role": getattr(membership.role, "value", membership.role),
            "source": membership.source,
        },
        actor_user_id=actor_user_id,
        user_id=membership.user_id,
        space_id=membership.space_id,
        creator_user_id=creator_user_id,
    )


# ---------------------------------------------------------------------------
# Creator subscription
# ---------------------------------------------------------------------------

def subscription_started(
    db: Session, sub, *, occurred_at: datetime, plan_slug: str | None = None,
) -> bool:
    return record(
        db,
        event_type=BusinessEventType.subscription_started,
        occurred_at=occurred_at,
        subject_type=SubjectType.subscription,
        subject_id=sub.id,
        dedupe_key=f"subscription:{sub.id}:started:{_stamp(occurred_at)}",
        payload={
            "plan_id": sub.creator_plan_id,
            "plan_slug": plan_slug,
            "source": sub.source,
            "status": getattr(sub.status, "value", sub.status),
        },
        user_id=sub.user_id,
        creator_user_id=sub.user_id,
    )


def subscription_plan_changed(
    db: Session,
    sub,
    *,
    occurred_at: datetime,
    from_plan_id: str | None,
    to_plan_id: str,
    from_plan_slug: str | None = None,
    to_plan_slug: str | None = None,
    direction: str | None = None,
    provider_event_id: str | None = None,
) -> bool:
    """A subscription moved plan.

    The event that makes MRR movement reportable at all. ``direction``
    is the caller's classification (``upgrade`` / ``downgrade`` /
    ``lateral``) rather than something inferred here, because only the
    caller knows whether it compared prices or intent.
    """
    suffix = provider_event_id or _stamp(occurred_at)
    return record(
        db,
        event_type=BusinessEventType.subscription_plan_changed,
        occurred_at=occurred_at,
        subject_type=SubjectType.subscription,
        subject_id=sub.id,
        dedupe_key=f"subscription:{sub.id}:plan_changed:{suffix}",
        payload={
            "from_plan_id": from_plan_id,
            "to_plan_id": to_plan_id,
            "from_plan_slug": from_plan_slug,
            "to_plan_slug": to_plan_slug,
            "direction": direction,
        },
        user_id=sub.user_id,
        creator_user_id=sub.user_id,
    )


def subscription_cancelled(
    db: Session,
    sub,
    *,
    occurred_at: datetime,
    reason: str | None = None,
    at_period_end: bool | None = None,
    initiated_by: str | None = None,
    actor_user_id: str | None = None,
    provider_event_id: str | None = None,
) -> bool:
    """A subscription ended.

    ``reason`` is a short enum-ish token (``grace_expired``,
    ``admin``, ``provider``), never the free-text ``revoked_reason``.
    """
    suffix = provider_event_id or _stamp(occurred_at)
    return record(
        db,
        event_type=BusinessEventType.subscription_cancelled,
        occurred_at=occurred_at,
        subject_type=SubjectType.subscription,
        subject_id=sub.id,
        dedupe_key=f"subscription:{sub.id}:cancelled:{suffix}",
        payload={
            "plan_id": sub.creator_plan_id,
            "reason": reason,
            "at_period_end": at_period_end,
            "initiated_by": initiated_by,
        },
        actor_user_id=actor_user_id,
        user_id=sub.user_id,
        creator_user_id=sub.user_id,
    )


def subscription_payment_failed(
    db: Session,
    sub,
    *,
    occurred_at: datetime,
    provider_invoice_id: str | None = None,
    provider_event_id: str | None = None,
) -> bool:
    suffix = provider_event_id or provider_invoice_id or _stamp(occurred_at)
    return record(
        db,
        event_type=BusinessEventType.subscription_payment_failed,
        occurred_at=occurred_at,
        subject_type=SubjectType.subscription,
        subject_id=sub.id,
        dedupe_key=f"subscription:{sub.id}:payment_failed:{suffix}",
        payload={
            "plan_id": sub.creator_plan_id,
            "status": getattr(sub.status, "value", sub.status),
            "provider_invoice_id": provider_invoice_id,
        },
        user_id=sub.user_id,
        creator_user_id=sub.user_id,
    )


def subscription_lapsed(
    db: Session, sub, *, occurred_at: datetime, grace_expired_at: datetime | None,
) -> bool:
    """A grace window closed without payment."""
    return record(
        db,
        event_type=BusinessEventType.subscription_lapsed,
        occurred_at=occurred_at,
        subject_type=SubjectType.subscription,
        subject_id=sub.id,
        dedupe_key=f"subscription:{sub.id}:lapsed:{_stamp(occurred_at)}",
        payload={
            "plan_id": sub.creator_plan_id,
            "status": getattr(sub.status, "value", sub.status),
            "grace_expired_at": grace_expired_at.isoformat() if grace_expired_at else None,
        },
        user_id=sub.user_id,
        creator_user_id=sub.user_id,
    )


# ---------------------------------------------------------------------------
# Collective
# ---------------------------------------------------------------------------

def collective_status_changed(
    db: Session,
    space,
    *,
    occurred_at: datetime,
    from_status: str,
    to_status: str,
    actor_user_id: str | None = None,
) -> bool:
    """A Collective was published or archived.

    Returns False for any other transition — the draft-to-draft and
    archived-to-draft moves are not business milestones and should not
    fill the log.
    """
    if to_status == "active":
        event_type = BusinessEventType.collective_published
    elif to_status == "archived":
        event_type = BusinessEventType.collective_archived
    else:
        return False
    return record(
        db,
        event_type=event_type,
        occurred_at=occurred_at,
        subject_type=SubjectType.collective,
        subject_id=space.id,
        dedupe_key=f"collective:{space.id}:{to_status}:{_stamp(occurred_at)}",
        payload={"from_status": from_status, "to_status": to_status},
        actor_user_id=actor_user_id,
        space_id=space.id,
        creator_user_id=space.creator_id,
    )


def collective_themes_changed(
    db: Session,
    space,
    *,
    occurred_at: datetime,
    from_themes: list[str],
    to_themes: list[str],
    actor_user_id: str | None = None,
) -> bool:
    """A Collective was recategorised.

    Without this, changing themes rewrites the past: a Collective that
    spent a year under Wellbeing and moved to Movement would report as
    having always been Movement. Recording the transition is what lets a
    later report say what it was *then*.
    """
    before, after = list(from_themes or []), list(to_themes or [])
    if before == after:
        return False
    return record(
        db,
        event_type=BusinessEventType.collective_themes_changed,
        occurred_at=occurred_at,
        subject_type=SubjectType.collective,
        subject_id=space.id,
        dedupe_key=f"collective:{space.id}:themes:{_stamp(occurred_at)}",
        payload={
            "from_themes": before,
            "to_themes": after,
            "added": sorted(set(after) - set(before)),
            "removed": sorted(set(before) - set(after)),
        },
        actor_user_id=actor_user_id,
        space_id=space.id,
        creator_user_id=space.creator_id,
    )


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def payment_settled(
    db: Session, txn, *, occurred_at: datetime, settlement_path: str,
) -> bool:
    """A payment reached ``succeeded``.

    ``settlement_path`` names which of the eight production routes
    settled it — Stripe checkout, an instalment invoice, a ticket
    purchase, a free purchase, or one of the two manual admin grants.
    Reporting does not need it; reconciliation does, because it is how a
    missing producer is traced back to the code that should have called
    one.

    The amounts are copied as they stand on the transaction. This is a
    record of what the payment system decided, never a recalculation of
    it — there is one source of truth for money and it is not here.
    """
    return record(
        db,
        event_type=BusinessEventType.payment_settled,
        occurred_at=occurred_at,
        subject_type=SubjectType.transaction,
        subject_id=txn.id,
        dedupe_key=f"transaction:{txn.id}:settled",
        payload={
            "transaction_type": getattr(
                txn.transaction_type, "value", txn.transaction_type
            ),
            "currency": txn.currency,
            "gross_amount_cents": txn.gross_amount_cents,
            "platform_fee_cents": txn.platform_fee_cents,
            "net_creator_amount_cents": txn.net_creator_amount_cents,
            "processing_fee_cents": txn.processing_fee_cents,
            "stripe_mode": txn.stripe_mode,
            "settlement_path": settlement_path,
        },
        user_id=txn.payer_user_id,
        space_id=txn.space_id,
        creator_user_id=txn.creator_user_id,
    )


def mark_settled(
    db: Session, txn, *, occurred_at: datetime, settlement_path: str,
) -> bool:
    """Stamp an observed settlement and record it, together.

    One call per settlement path, so the column and the event cannot
    drift apart. There are eight such paths in production — Stripe
    checkout, the first and later instalment invoices, ticket purchase,
    free purchase, and two manual admin grants — and the only thing
    stopping a ninth from going unrecorded is the reconciliation check
    for succeeded transactions with no settlement.

    ``settled_at_source`` is always ``'observed'`` here. Nothing in this
    release writes ``'reconstructed'``; a backfill may, and reporting
    can then keep the two apart.
    """
    txn.settled_at = occurred_at
    txn.settled_at_source = "observed"
    return payment_settled(
        db, txn, occurred_at=occurred_at, settlement_path=settlement_path,
    )


def payment_refunded(
    db: Session,
    txn,
    *,
    occurred_at: datetime,
    refund_delta_cents: int,
    provider_event_id: str | None = None,
) -> bool:
    """Money went back.

    One event per refund, not per transaction. Stripe reports the
    *cumulative* refunded amount, so the delta is computed by the caller
    from what the row held before the update — which is what makes a
    second partial refund against the same payment its own event rather
    than an overwrite. The dedupe key carries Stripe's event id so a
    redelivery of the same refund stays one row.

    Attributed to the refund date, deliberately. A closed month's
    revenue should not move because somebody was refunded in the next
    one.
    """
    suffix = provider_event_id or _stamp(occurred_at)
    return record(
        db,
        event_type=BusinessEventType.payment_refunded,
        occurred_at=occurred_at,
        subject_type=SubjectType.transaction,
        subject_id=txn.id,
        dedupe_key=f"transaction:{txn.id}:refunded:{suffix}",
        payload={
            "currency": txn.currency,
            "refund_delta_cents": refund_delta_cents,
            "refunded_total_cents": txn.refunded_amount_cents,
            "refunded_platform_fee_cents": txn.refunded_platform_fee_cents,
            "refunded_creator_amount_cents": txn.refunded_creator_amount_cents,
            "resulting_status": getattr(txn.status, "value", txn.status),
            "stripe_mode": txn.stripe_mode,
        },
        user_id=txn.payer_user_id,
        space_id=txn.space_id,
        creator_user_id=txn.creator_user_id,
    )


def payout_paid(
    db: Session,
    *,
    transaction_id: str,
    occurred_at: datetime,
    amount_cents: int | None,
    currency: str | None,
    batch_id: str,
    reference: str | None,
    creator_user_id: str | None,
    space_id: str | None,
) -> bool:
    """A creator was actually paid.

    Takes plain values rather than a transaction object because the
    payout orchestration marks rows in bulk SQL and never loads them.
    This is the one producer that cannot read its subject, which is also
    why it is the easiest one to forget — the reconciliation check for
    paid transactions without this event exists for exactly that reason.
    """
    return record(
        db,
        event_type=BusinessEventType.payout_paid,
        occurred_at=occurred_at,
        subject_type=SubjectType.transaction,
        subject_id=transaction_id,
        dedupe_key=f"transaction:{transaction_id}:payout_paid:{batch_id}",
        payload={
            "currency": currency,
            "amount_cents": amount_cents,
            "batch_id": batch_id,
            "reference": reference,
        },
        space_id=space_id,
        creator_user_id=creator_user_id,
    )


def payout_reversed(
    db: Session,
    *,
    transaction_id: str,
    occurred_at: datetime,
    amount_cents: int | None,
    currency: str | None,
    batch_id: str,
    creator_user_id: str | None,
    space_id: str | None,
) -> bool:
    """A recorded payout was undone, returning the amount to outstanding."""
    return record(
        db,
        event_type=BusinessEventType.payout_reversed,
        occurred_at=occurred_at,
        subject_type=SubjectType.transaction,
        subject_id=transaction_id,
        dedupe_key=f"transaction:{transaction_id}:payout_reversed:{batch_id}",
        payload={
            "currency": currency,
            "amount_cents": amount_cents,
            "batch_id": batch_id,
        },
        space_id=space_id,
        creator_user_id=creator_user_id,
    )
