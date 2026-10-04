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
from datetime import datetime

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

SYSTEM_REVOKED_REASON = "complimentary_grant_expired"


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
            CreatorSubscription.status == CreatorSubscriptionStatus.active,
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
            CreatorSubscription.ends_at <= now,
            CreatorSubscription.grant_reason.in_(sorted(EXPIRABLE_GRANT_REASONS)),
            CreatorPlan.slug.notin_(sorted(NEVER_EXPIRE_PLAN_SLUGS)),
        )
        .with_for_update(of=CreatorSubscription)
        .order_by(CreatorSubscription.ends_at)
        .all()
    )


def blocking_reason(sub: CreatorSubscription, db: Session) -> str | None:
    """Why this grant must not be expired automatically, or None."""
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
        report.expired.append(row)
        logger.info(
            "creator_grant_expiry: %s subscription=%s user=%s plan=%s ends_at=%s",
            "expired" if apply else "would expire",
            sub.id, sub.user_id, plan_slug, sub.ends_at,
        )

    return report
