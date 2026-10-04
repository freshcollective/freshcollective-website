"""Expiry reconciliation for finite complimentary Creator grants.

The product need
----------------
An admin can grant a creator complimentary Creator access for a fixed
period ("6 months"). Until this module existed, ``ends_at`` was
informational only: nothing in the backend compared it to the clock, so
the grant ran indefinitely until someone revoked it by hand. The
intended lifecycle is:

    Community → complimentary Creator (finite) → Community again

Why a separate reconciler
-------------------------
``creator_subscription_grace_reconcile.py`` sweeps ``past_due →
unpaid`` on ``grace_expires_at``. That is Stripe payment failure: a
different predicate, a different domain, and a far lower blast radius
than revoking entitlements. Keeping grant expiry in its own narrowly
scoped job means it can be deployed without being armed, dry-run
independently, and scheduled only once its affected rows have been
reviewed.

What expiry does, and does not, do
----------------------------------
Expiry **cancels the grant row** and nothing else. It does not write a
replacement subscription, because ``plan_guards.resolve_creator_plan``
already falls back to the cheapest active plan — Community — for a
creator with no active subscription. Writing a Community row would be
actively harmful: ``activate_creator_plan`` raises
``ActivationConflictError`` when a different active plan already
exists and no caller cancels first, so the creator's later paid upgrade
would fail *after* they had been charged.

Consequently expiry never: deletes the account, removes the
``creator`` role, touches World Builders membership (an ``auto_role``
membership keyed on the role, which does not change), deletes a
Collective or any content, creates a Stripe subscription, or charges
anyone. There is no Stripe interaction on this path at all.

Failing safe
------------
Three conditions make a due grant **unsafe** to expire automatically.
In each case the row is left exactly as it is and reported for an admin
to resolve deliberately:

1. *Community is not the cheapest active plan.* The downgrade relies on
   the resolver's cheapest-active-plan fallback. If the Community row
   were missing or deactivated, cancelling the grant would silently
   resolve the creator to whatever is now cheapest — possibly a *more*
   capable paid tier. Refuse rather than guess.

2. *More Collectives than Community allows.* This mirrors the refusal
   already enforced by ``admin.routes.change_creator_plan_atomic``,
   whose comment is the governing principle: "this endpoint never picks
   which Collectives to close." Neither does this one.

3. *The creator is selling something.* Community forbids paid offers,
   and the platform has no read-side plan gate that retires existing
   paid content on downgrade (see the acknowledged gap near the Offer
   Page read path in ``spaces/routes.py``). Worse,
   ``creator_plan_guard_enabled`` — which decides whether a creator
   with no active subscription gets a hard 409 at checkout or a silent
   ``fee_bps=0`` fallback — is a deployment-time setting this code
   cannot read. So the post-expiry fate of live paid content is not
   knowable here: under one setting checkout breaks for buyers mid-
   purchase, under the other the creator keeps selling on a plan that
   prohibits it. Both are unacceptable to do automatically, and
   deleting or unpublishing their content is worse still. Leave it to
   an admin.

Audit trail
-----------
A system expiry is distinguishable from an admin revocation by
``revoked_by_user_id IS NULL``: every admin path sets the acting admin.
Both write a ``creator_plan_grants`` row with ``action='revoked'`` —
the CHECK constraint from migration 082 allows only ``granted |
extended | revoked``, so no migration is needed to record this — and
the system path leaves ``actor_user_id`` NULL alongside an explicit
``revoked_reason``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.admin.service import record_grant_event
from app.creator.plan_config import get_plan_capability
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.platform import Space
from app.services.creator_paid_content import creator_has_commercial_content

logger = logging.getLogger(__name__)


# Only these two grant reasons mean "time-boxed complimentary access".
#
# The other six in ``admin.schemas.PLAN_GRANT_REASONS`` are deliberately
# excluded. ``migration``, ``correction`` and ``replacement`` are
# remediation — access the platform owes someone, where an end date is
# more likely a note than an intention. ``beta`` may outlive its
# nominal window while a programme is still running. ``internal`` is
# staff tooling. ``other`` is unknowable by definition. Expiring any of
# them on an ``ends_at`` that was never meant to be enforced would
# revoke entitlements nobody decided to revoke.
EXPIRABLE_GRANT_REASONS: frozenset[str] = frozenset({"comp", "temporary"})

# Plans that never expire through this path.
#
#   * ``founding-creator`` and ``organisation`` are the two
#     non-purchasable, non-self-service tiers — bespoke arrangements,
#     excluded explicitly by product decision.
#   * ``community`` is the downgrade *target*; expiring a Community
#     grant would be a no-op at best.
NEVER_EXPIRE_PLAN_SLUGS: frozenset[str] = frozenset({
    "founding-creator", "organisation", "community",
})

#: Natural post-grace expiry. Deliberately distinct from
#: ``superseded_by_paid_subscription`` (conversion) and from an admin
#: revoke, so the audit trail says which of the three happened.
SYSTEM_REVOKED_REASON = "complimentary_term_expired"

#: The creator is invited to continue this far before ``ends_at``.
RENEWAL_WINDOW = timedelta(days=14)

#: Creator access continues this far past ``ends_at`` while they decide.
GRACE_PERIOD = timedelta(days=7)


def classify_grant(
    sub: CreatorSubscription,
    plan_slug: str,
    now: datetime,
    *,
    has_paid_subscription: bool = False,
) -> str:
    """Where this grant sits in the complimentary lifecycle.

    Pure and side-effect free, so the dry-run report and the reconciler
    describe rows identically — the report cannot flatter the job.
    """
    if sub.source != "manual_grant":
        return "excluded: not a manual grant"
    if sub.status not in (
        CreatorSubscriptionStatus.active,
        CreatorSubscriptionStatus.trialing,
    ):
        return f"excluded: status={_status_value(sub)}"
    if plan_slug in NEVER_EXPIRE_PLAN_SLUGS:
        return f"excluded: plan={plan_slug}"
    if sub.grant_reason not in EXPIRABLE_GRANT_REASONS:
        return f"excluded: reason={sub.grant_reason}"
    if sub.ends_at is None:
        return "excluded: indefinite"
    if has_paid_subscription:
        return "excluded: paid subscription already active"
    if now < sub.ends_at - RENEWAL_WINDOW:
        return "active"
    if now < sub.ends_at:
        return "renewal window"
    if now < sub.ends_at + GRACE_PERIOD:
        return "grace"
    return "would fall back"


def _status_value(sub: CreatorSubscription) -> str:
    return (
        sub.status.value if hasattr(sub.status, "value") else str(sub.status)
    )


def has_active_paid_subscription(db: Session, user_id: str) -> bool:
    """Does this creator already hold a Stripe-paid subscription?

    The decisive exclusion. A creator who elected to continue has a
    ``stripe_paid`` row — ``past_due`` while an early election's trial
    runs, ``active`` once the first invoice is collected — and must
    never be dropped to Community by this job. ``past_due`` is included
    deliberately: during a deferred-start trial that is exactly the
    state of a creator who has committed and simply has not been
    charged yet.
    """
    return db.query(
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.user_id == user_id,
            CreatorSubscription.source == "stripe_paid",
            CreatorSubscription.status.in_([
                CreatorSubscriptionStatus.active,
                CreatorSubscriptionStatus.trialing,
                CreatorSubscriptionStatus.past_due,
            ]),
        )
        .exists()
    ).scalar()


@dataclass(frozen=True)
class SurveyedGrant:
    """One manual grant, described for the pre-arming report."""
    subscription_id: str
    user_id: str
    user_email: str | None
    plan_slug: str
    source: str
    status: str
    grant_reason: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    has_paid_subscription: bool
    lifecycle: str


def survey_manual_grants(db: Session, now: datetime | None = None) -> list[SurveyedGrant]:
    """Describe every manual grant in the system, read-only.

    Deliberately wider than the reconciler's own predicate: it reports
    *all* manual grants, including the ones that are excluded, with the
    reason. The point is to be able to see — before arming anything —
    that Founding Creator and indefinite grants are classified out, and
    that nothing unexpected is sitting in "would fall back".

    Shares ``classify_grant`` with the job, so the report cannot
    describe a row differently from the way the job would treat it.
    """
    from app.models.user import User

    now = now or datetime.utcnow()
    rows = (
        db.query(CreatorSubscription, CreatorPlan, User)
        .join(CreatorPlan, CreatorPlan.id == CreatorSubscription.creator_plan_id)
        .join(User, User.id == CreatorSubscription.user_id)
        .filter(CreatorSubscription.source == "manual_grant")
        .order_by(CreatorSubscription.ends_at.is_(None), CreatorSubscription.ends_at)
        .all()
    )
    out: list[SurveyedGrant] = []
    for sub, plan, user in rows:
        paid = has_active_paid_subscription(db, sub.user_id)
        out.append(SurveyedGrant(
            subscription_id=sub.id,
            user_id=sub.user_id,
            user_email=user.email,
            plan_slug=plan.slug,
            source=sub.source,
            status=_status_value(sub),
            grant_reason=sub.grant_reason,
            starts_at=sub.starts_at,
            ends_at=sub.ends_at,
            has_paid_subscription=paid,
            lifecycle=classify_grant(sub, plan.slug, now, has_paid_subscription=paid),
        ))
    return out


@dataclass(frozen=True)
class GrantRow:
    """Flat description of a grant the reconciler considered."""
    subscription_id: str
    user_id: str
    plan_slug: str
    grant_reason: str | None
    starts_at: datetime | None
    ends_at: datetime | None


@dataclass(frozen=True)
class SkippedGrant:
    grant: GrantRow
    reason: str


@dataclass
class ExpiryReport:
    """What the run did, or would do when ``applied`` is False."""
    applied: bool
    expired: list[GrantRow] = field(default_factory=list)
    skipped: list[SkippedGrant] = field(default_factory=list)
    #: Set when a precondition stops the whole run rather than one row.
    halted_reason: str | None = None
    #: Grants currently inside the 14-day renewal window.
    in_renewal: int = 0
    #: Grants past their end date but still inside the 7-day grace.
    in_grace: int = 0
    #: Lifecycle notifications queued this run (deduped, so a daily
    #: schedule sends each creator each message once per term).
    notified: int = 0

    @property
    def expired_count(self) -> int:
        return len(self.expired)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


def community_is_the_fallback(db: Session) -> bool:
    """Would cancelling a grant land the creator on Community?

    ``resolve_creator_plan`` picks the cheapest *active* plan when no
    subscription remains. This verifies that plan is Community, so the
    downgrade cannot silently resolve somewhere more capable.
    """
    cheapest = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.is_active.is_(True))
        .order_by(CreatorPlan.monthly_price_cents)
        .first()
    )
    return cheapest is not None and cheapest.slug == "community"


def find_due_grants(db: Session, now: datetime) -> list[CreatorSubscription]:
    """Active, finite, complimentary Creator grants whose term has passed.

    Rows are locked ``FOR UPDATE`` so a concurrent admin change cannot
    interleave between selection and mutation. Callers re-check the
    predicate after locking.
    """
    return (
        db.query(CreatorSubscription)
        .join(CreatorPlan, CreatorPlan.id == CreatorSubscription.creator_plan_id)
        .filter(
            CreatorSubscription.source == "manual_grant",
            CreatorSubscription.status.in_([
                CreatorSubscriptionStatus.active,
                CreatorSubscriptionStatus.trialing,
            ]),
            # Redundant against the comparison below — in SQL
            # ``NULL <= now`` is NULL, so an indefinite grant is already
            # excluded. Kept because "indefinite grants never expire" is
            # a product rule that should be readable in the predicate
            # rather than inferred from three-valued logic, and because
            # it survives a future rewrite that wraps the comparison
            # (COALESCE, a date cast) and loses the NULL behaviour.
            # Mutation-testing note: removing this line alone does not
            # fail the suite, for exactly that reason.
            CreatorSubscription.ends_at.is_not(None),
            # Grace: a grant is only *due* once its term has ended AND
            # the 7-day continuation window has passed. Expressed as an
            # offset on the comparison rather than persisted state, so
            # there is no new column and no migration — ``ends_at`` plus
            # the constant is the whole lifecycle.
            CreatorSubscription.ends_at <= now - GRACE_PERIOD,
            CreatorSubscription.grant_reason.in_(sorted(EXPIRABLE_GRANT_REASONS)),
            CreatorPlan.slug.notin_(sorted(NEVER_EXPIRE_PLAN_SLUGS)),
        )
        .with_for_update(of=CreatorSubscription)
        .order_by(CreatorSubscription.ends_at)
        .all()
    )


def blocking_reason(sub: CreatorSubscription, db: Session) -> str | None:
    """Why this grant must not be expired automatically, or None."""
    # Checked first, and the only one of these that is about the
    # creator's own decision rather than their data: if they elected to
    # continue, there is a ``stripe_paid`` row and this job has no
    # business touching them. Belt-and-braces alongside the supersede in
    # ``plan_activation`` — that cancels the grant on conversion, so a
    # converted creator normally never reaches here at all. This covers
    # the window of an early election whose trial has not yet been
    # charged, where the grant is deliberately still active.
    if has_active_paid_subscription(db, sub.user_id):
        return "paid_subscription_active"

    capability = get_plan_capability("community")
    if capability is None:
        return "community_capability_missing"

    if capability.active_collective_limit is not None:
        owned = (
            db.query(func.count(Space.id))
            .filter(
                Space.creator_id == sub.user_id,
                Space.status != "archived",
            )
            .scalar() or 0
        )
        if owned > capability.active_collective_limit:
            return (
                f"collectives_exceed_community_limit"
                f" ({owned} > {capability.active_collective_limit})"
            )

    if creator_has_commercial_content(sub.user_id, db):
        return "creator_has_paid_content"

    return None


def expire_grant(sub: CreatorSubscription, db: Session, now: datetime) -> None:
    """Cancel one grant, mirroring the admin revoke path.

    Idempotent by construction: callers only reach here for a row still
    ``active``, and the write sets a terminal status. Does not commit —
    the caller owns the transaction boundary.
    """
    sub.status = CreatorSubscriptionStatus.cancelled
    sub.revoked_at = now
    # NULL actor is the signal that this was the system, not an admin.
    sub.revoked_by_user_id = None
    sub.revoked_reason = (
        f"Complimentary grant reached its end date ({sub.ends_at:%Y-%m-%d}). "
        "Automatically returned to the Community plan."
    )
    sub.updated_at = now
    record_grant_event(
        db,
        subscription=sub,
        action="revoked",
        reason=SYSTEM_REVOKED_REASON,
        note=(
            "Automatic expiry of a finite complimentary grant. The creator "
            "keeps their account, Creator role, Collective, content and "
            "World Builders membership, and resolves to the Community plan "
            "via the cheapest-active-plan fallback. No Stripe subscription "
            "was created and no charge was made."
        ),
        actor_user_id=None,
    )


# ---------------------------------------------------------------------------
# Lifecycle notifications
# ---------------------------------------------------------------------------

#: In-app notification types for the three states a creator should hear
#: about. Conversion to paid is already announced by
#: ``plan_activation._notify_creator`` on the ``stripe_paid`` path, so it
#: is deliberately not duplicated here.
NOTIFY_ENDING_SOON = "creator_complimentary_ending_soon"
NOTIFY_GRACE = "creator_complimentary_grace"
NOTIFY_ENDED = "creator_complimentary_ended"

_BILLING_URL = "/creator-studio/billing"


def _already_notified(
    db: Session, user_id: str, notification_type: str, since: datetime,
) -> bool:
    """Has this creator already had this notification for this term?

    Dedup is by (user, type, created_at >= since) with ``since`` derived
    from the grant's own dates, so a daily reconciler run is idempotent
    without storing any new state. A creator who receives a second,
    later grant gets a fresh ``since`` and so is notified again, which
    is correct.
    """
    from app.models.notification import Notification

    return db.query(
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.notification_type == notification_type,
            Notification.created_at >= since,
        )
        .exists()
    ).scalar()


def _notify_once(
    db: Session,
    *,
    user_id: str,
    notification_type: str,
    title: str,
    message: str,
    since: datetime,
) -> bool:
    """Queue one in-app notification unless it has already been sent.

    Writes the row directly rather than through
    ``notification_service.create_notification``, which commits — the
    reconciler owns its own transaction boundary and must not have it
    broken mid-run.
    """
    from app.models.notification import Notification

    if _already_notified(db, user_id, notification_type, since):
        return False
    db.add(Notification(
        id=str(uuid4()),
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        url=_BILLING_URL,
        is_read=False,
    ))
    return True


def _fmt(d: datetime | None) -> str:
    return d.strftime("%-d %B %Y") if d else "soon"


def notify_lifecycle(
    db: Session,
    sub: CreatorSubscription,
    lifecycle: str,
    *,
    plan_price_label: str = "$19 AUD/month",
) -> str | None:
    """Send the notification this lifecycle phase calls for, once.

    Returns the notification type sent, or None. Copy mirrors the
    Billing panel: it names the date, offers the choice, and never
    suggests an automatic charge or any loss of work.
    """
    ends_at = sub.ends_at
    if ends_at is None:
        return None

    if lifecycle == "renewal window":
        # ``since`` is the window opening, so one notification per term.
        sent = _notify_once(
            db,
            user_id=sub.user_id,
            notification_type=NOTIFY_ENDING_SOON,
            title="Your complimentary Creator access is ending",
            message=(
                f"Your complimentary Creator access ends on {_fmt(ends_at)}. "
                f"Continue with Creator for {plan_price_label} to keep your "
                "paid offers and commercial tools active. If you don't "
                "continue, you'll have a 7-day grace period before your "
                "account moves to the free Community plan — your Collective "
                "and content remain."
            ),
            since=ends_at - RENEWAL_WINDOW,
        )
        return NOTIFY_ENDING_SOON if sent else None

    if lifecycle == "grace":
        sent = _notify_once(
            db,
            user_id=sub.user_id,
            notification_type=NOTIFY_GRACE,
            title="Your complimentary Creator access has ended",
            message=(
                f"Your complimentary access ended on {_fmt(ends_at)}. You have "
                f"until {_fmt(ends_at + GRACE_PERIOD)} to continue on Creator "
                f"for {plan_price_label} before your account moves to the free "
                "Community plan. Your Collective and content will remain either "
                "way."
            ),
            since=ends_at,
        )
        return NOTIFY_GRACE if sent else None

    return None


def notify_fallback(db: Session, sub: CreatorSubscription) -> bool:
    """Tell the creator their account has moved to Community."""
    if sub.ends_at is None:
        return False
    return _notify_once(
        db,
        user_id=sub.user_id,
        notification_type=NOTIFY_ENDED,
        title="Your account has moved to the Community plan",
        message=(
            "Your complimentary Creator access has finished, so your account "
            "is now on the free Community plan. Your Collective, Pathways, "
            "Gatherings and everything you've made are all still here. You "
            "can move back to Creator whenever you're ready."
        ),
        since=sub.ends_at,
    )


def _lifecycle_candidates(db: Session) -> list[tuple[CreatorSubscription, CreatorPlan]]:
    """Finite manual grants still holding the active slot.

    Intentionally broader than ``find_due_grants`` — this feeds the
    notification scan, which cares about grants that are *approaching*
    or *just past* their end date, not only the ones due for fallback.
    No locking: nothing here mutates entitlements.
    """
    return (
        db.query(CreatorSubscription, CreatorPlan)
        .join(CreatorPlan, CreatorPlan.id == CreatorSubscription.creator_plan_id)
        .filter(
            CreatorSubscription.source == "manual_grant",
            CreatorSubscription.status.in_([
                CreatorSubscriptionStatus.active,
                CreatorSubscriptionStatus.trialing,
            ]),
            CreatorSubscription.ends_at.is_not(None),
            CreatorSubscription.grant_reason.in_(sorted(EXPIRABLE_GRANT_REASONS)),
            CreatorPlan.slug.notin_(sorted(NEVER_EXPIRE_PLAN_SLUGS)),
        )
        .all()
    )


def reconcile_expired_grants(
    db: Session,
    now: datetime | None = None,
    *,
    apply: bool = False,
) -> ExpiryReport:
    """Find and (optionally) expire due complimentary grants.

    ``apply=False`` — the default — inspects and reports without writing
    anything, so the affected rows can be reviewed before any
    entitlement changes. Safe to run repeatedly in either mode: an
    already-cancelled grant no longer matches the predicate.
    """
    now = now or datetime.utcnow()
    report = ExpiryReport(applied=apply)

    if not community_is_the_fallback(db):
        # Whole-run halt, not a per-row skip: without Community as the
        # cheapest active plan, no downgrade here is trustworthy.
        report.halted_reason = "community_is_not_the_cheapest_active_plan"
        logger.error(
            "creator_grant_expiry: refusing to run — Community is not the "
            "cheapest active creator plan, so cancelling a grant would not "
            "resolve to Community."
        )
        return report

    # Lifecycle scan — notification only, no entitlement change. Covers
    # the renewal window and grace, which are *states* rather than
    # transitions: there is nothing to mutate, only something to say.
    # Runs in both dry-run and apply modes for counting, but only writes
    # when applying.
    for surveyed_sub, surveyed_plan in _lifecycle_candidates(db):
        phase = classify_grant(
            surveyed_sub, surveyed_plan.slug, now,
            has_paid_subscription=has_active_paid_subscription(
                db, surveyed_sub.user_id,
            ),
        )
        if phase == "renewal window":
            report.in_renewal += 1
        elif phase == "grace":
            report.in_grace += 1
        else:
            continue
        if apply and notify_lifecycle(db, surveyed_sub, phase) is not None:
            report.notified += 1

    for sub in find_due_grants(db, now):
        plan = (
            db.query(CreatorPlan)
            .filter(CreatorPlan.id == sub.creator_plan_id)
            .first()
        )
        plan_slug = plan.slug if plan else "<unknown>"
        row = GrantRow(
            subscription_id=sub.id,
            user_id=sub.user_id,
            plan_slug=plan_slug,
            grant_reason=sub.grant_reason,
            starts_at=sub.starts_at,
            ends_at=sub.ends_at,
        )

        blocked = blocking_reason(sub, db)
        if blocked is not None:
            report.skipped.append(SkippedGrant(grant=row, reason=blocked))
            logger.warning(
                "creator_grant_expiry: skipping subscription=%s user=%s — %s",
                sub.id, sub.user_id, blocked,
            )
            continue

        if apply:
            expire_grant(sub, db, now)
            if notify_fallback(db, sub):
                report.notified += 1
        report.expired.append(row)
        logger.info(
            "creator_grant_expiry: %s subscription=%s user=%s plan=%s ends_at=%s",
            "expired" if apply else "would expire",
            sub.id, sub.user_id, plan_slug, sub.ends_at,
        )

    return report
