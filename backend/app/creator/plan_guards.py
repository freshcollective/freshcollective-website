"""
Backend enforcement of creator plan limits.

Every guard here is a hard check that runs on the request path. Frontend
gates exist for UX; these gates exist so the platform can't be jailbroken by
calling the API directly.

Guards documented and implemented so far:

    guard_active_collective_limit(user, db) — enforces
        `PlanCapability.active_collective_limit` on the create-collective
        paths (POST /api/creator/spaces, POST /api/creator/build-your-
        collective/open).

    guard_location_allowed(user, location, db) — enforces
        `PlanCapability.location_scope`. Rejects Cornerstones for every
        creator plan. Community plan may only pick COMMUNITY Locations;
        Creator/Pro plans may only pick ATLAS Locations.

    guard_paid_offers_enabled(user, db) — enforces
        `PlanCapability.paid_offers_enabled`. Rejects paid pricing types
        on plans that don't allow commercial offers. Runs on both the
        create and the update paths, so a free Collective cannot be
        flipped to paid after the fact.

    guard_member_allowance(space, db) — enforces
        `PlanCapability.member_allowance_per_collective` against the
        owning creator's plan on every learner-admitting path.

Platform Owner (role='admin') bypasses every guard here — Owner does not
belong to any creator plan.

Not yet enforced (see docs/permissions-matrix.md migration checklist):

    - pooled_member_allowance (Organisation; the per-Collective cap is
      enforced by guard_member_allowance)
    - caretaker_limit_per_collective
    - storage_allowance_mb
    - pathways_enabled / gatherings_enabled / resources_enabled
      (currently always allowed at the surface level; a stricter Community
      variant may be added when the exact allowances are chosen)
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.creator.plan_config import (
    PLANS_BY_SLUG,
    PlanCapability,
    get_plan_capability,
)
from app.models.creator_billing import CreatorPlan, CreatorSubscription
from app.models.platform import (
    Location,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User


# ---------------------------------------------------------------------------
# Plan resolution
# ---------------------------------------------------------------------------


def is_platform_owner(user: User) -> bool:
    """Single source of truth for "is this account exempt from creator plan
    guards?". Currently backed by the collapsed `admin` role until the
    Platform Admin / Platform Owner split lands (see permissions matrix)."""
    return user.role == "admin"


# ---------------------------------------------------------------------------
# Which subscription is the current one
# ---------------------------------------------------------------------------

#: Statuses that count as "this creator holds a plan".
CURRENT_SUBSCRIPTION_STATUSES: tuple[str, ...] = ("active", "trialing", "past_due")


def current_subscription_order():
    """Deterministic precedence for picking the current subscription.

    Two rows can legitimately sit in ``CURRENT_SUBSCRIPTION_STATUSES`` at
    once. The case that forced this: a creator on a complimentary grant
    elects to keep paying before their term ends, so Stripe Checkout
    creates the paid subscription with a trial running to the grant's
    ``ends_at``. The local paid row is written ``past_due`` (linked, not
    yet charged) while the grant stays ``active`` — the partial unique
    index permits that, because it only covers ``active``/``trialing``.

    An unordered ``.first()`` then returned either row at random, which
    for a comp-Creator → paid-Pro election meant the resolved *plan*
    flickered between tiers. Ordering by status precedence resolves it
    to the truthful answer: the grant is what the creator holds until
    the first paid invoice is collected, at which point the grant is
    superseded and the paid row becomes the only candidate.

    ``created_at DESC`` breaks any remaining tie in favour of the newest
    assignment, matching ``admin.routes.change_creator_plan_atomic``.
    """
    from sqlalchemy import case
    return (
        case(
            (CreatorSubscription.status == "active", 0),
            (CreatorSubscription.status == "trialing", 1),
            else_=2,          # past_due — linked or in dunning, not current
        ),
        CreatorSubscription.created_at.desc(),
    )


def resolve_creator_plan(user: User, db: Session) -> PlanCapability | None:
    """Return the capability record for this user's active creator plan.

    Returns None if:
      - the user is a Platform Owner (they have no plan)
      - the user has no subscription and no plans exist in the DB
      - the user's subscription points at a plan whose slug is not present
        in `PLANS_BY_SLUG` (unknown plan — treat as "no capability")
    """
    if is_platform_owner(user):
        return None

    subscription = (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.user_id == user.id,
            # ``past_due`` counts as "has plan" during the 7-day FC
            # grace window so ``guard_paid_offers_enabled`` /
            # ``guard_active_collective_limit`` / ``guard_pathway_limit``
            # keep the creator's authoring capability intact. The
            # grace-expiry cron transitions ``past_due → unpaid`` at
            # 7 days; ``unpaid`` remains outside this filter so
            # commercial capability collapses on that boundary, as
            # designed. See the 2026-09-17 grace-lifecycle audit.
            CreatorSubscription.status.in_(CURRENT_SUBSCRIPTION_STATUSES),
        )
        .order_by(*current_subscription_order())
        .first()
    )
    if subscription:
        return get_plan_capability(subscription.plan.slug)

    # No subscription row yet — fall back to the cheapest active plan.
    fallback = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.is_active.is_(True))
        .order_by(CreatorPlan.monthly_price_cents)
        .first()
    )
    if fallback:
        return get_plan_capability(fallback.slug)
    return None


# ---------------------------------------------------------------------------
# Managed-collective count (matches billing usage counter)
# ---------------------------------------------------------------------------


def count_managed_collectives(user: User, db: Session) -> int:
    """Count non-archived collectives this user creates or manages. Mirrors
    the count used by GET /api/creator/billing so users see the same number
    the enforcement path uses."""
    owned_ids = {
        row[0]
        for row in db.query(Space.id)
        .filter(
            Space.creator_id == user.id,
            Space.status.notin_(["archived"]),
        )
        .all()
    }
    member_ids = {
        row[0]
        for row in db.query(SpaceMembership.space_id)
        .join(Space, Space.id == SpaceMembership.space_id)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.role.in_(["creator", "moderator"]),
            SpaceMembership.status == "active",
            Space.status.notin_(["archived"]),
        )
        .all()
    }
    return len(owned_ids | member_ids)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def effective_collective_allowance(user: User, db: Session) -> int | None:
    """Return the enforced maximum number of collectives ``user`` may
    manage — the **same value** ``guard_active_collective_limit`` compares
    against. Exposed so the Creator Subscriptions page can display the
    exact number the guard enforces (no divergence between UI and rule).

    - ``None`` means unlimited (Platform Owner).
    - Otherwise the ``active_collective_limit`` from the user's resolved
      PlanCapability, i.e. what the guard actually blocks against.
    - Raises ``RuntimeError`` for the rare "no plan resolved" case
      (should never happen in production — every creator falls back to
      the cheapest active plan via ``resolve_creator_plan``).
    """
    if is_platform_owner(user):
        return None
    plan = resolve_creator_plan(user, db)
    if plan is None:
        # No plans exist at all — treat as unlimited for display purposes
        # so we don't render a nonsense denominator. The guard will refuse
        # the create-collective action anyway.
        return None
    return plan.active_collective_limit


def guard_active_collective_limit(user: User, db: Session) -> None:
    """Raise 403 if creating another collective would exceed the plan's
    ``active_collective_limit``. Platform Owner is unlimited and bypassed.

    Routes the allowance lookup through :func:`effective_collective_allowance`
    so the display and the guard read the same number by construction.
    """
    allowance = effective_collective_allowance(user, db)
    if allowance is None and not is_platform_owner(user):
        # Distinguish "unlimited via owner" from "no plan resolved".
        # If we got here, the user is not the owner but no plan resolved
        # — refuse rather than silently allow.
        raise HTTPException(
            status_code=403,
            detail=(
                "Your account does not have an active creator plan. "
                "Contact Fresh Collective support."
            ),
        )
    if allowance is None:
        return   # platform owner — unlimited

    current = count_managed_collectives(user, db)
    if current >= allowance:
        plan = resolve_creator_plan(user, db)
        display_name = plan.display_name if plan else "current"
        raise HTTPException(
            status_code=403,
            detail=(
                f"Your {display_name} plan includes "
                f"{allowance} active collective"
                f"{'s' if allowance != 1 else ''}. "
                "Upgrade your plan to create another."
            ),
        )


def guard_location_allowed(user: User, location: Location, db: Session) -> None:
    """Reject Locations the user's plan is not allowed to use.

    Rules:
        Platform Owner        → ATLAS + COMMUNITY + CORNERSTONE (bypass here)
        atlas_and_cornerstones → all (no creator plan uses this scope)
        atlas_full            → ATLAS only (Creator, Pro)
        community_only        → COMMUNITY only (Community/Free)

    Cornerstones are always refused for creator plans regardless of scope.
    """
    if is_platform_owner(user):
        return

    plan = resolve_creator_plan(user, db)
    if plan is None:
        raise HTTPException(
            status_code=403,
            detail="Your account does not have an active creator plan.",
        )

    if location.location_type == "CORNERSTONE":
        raise HTTPException(
            status_code=403,
            detail="Cornerstone Locations are reserved for Fresh Collective.",
        )

    if plan.location_scope == "community_only":
        if location.location_type != "COMMUNITY":
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Your {plan.display_name} plan can only open a collective in a "
                    "Community Location. Upgrade to Creator to unlock the Atlas."
                ),
            )
    elif plan.location_scope == "atlas_full":
        if location.location_type != "ATLAS":
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Community Locations are reserved for the Community plan. "
                    f"Your {plan.display_name} plan chooses from the Atlas."
                ),
            )
    # atlas_and_cornerstones is bypassed above via is_platform_owner.


def guard_paid_offers_enabled(user: User, db: Session, pricing_type: str) -> None:
    """Reject a paid pricing choice on a plan that doesn't allow commercial
    offers. `pricing_type` is the incoming value on the space/pathway body
    ('free' or 'contribution'/'paid'/etc)."""
    if is_platform_owner(user):
        return
    if pricing_type == "free":
        return

    plan = resolve_creator_plan(user, db)
    if plan is None or not plan.paid_offers_enabled:
        plan_name = plan.display_name if plan else "current"
        raise HTTPException(
            status_code=403,
            detail=(
                f"Your {plan_name} plan does not allow paid offers. "
                "Upgrade to Creator to enable commercial checkout."
            ),
        )


def guard_offer_pages_enabled(user: User, db: Session) -> None:
    """Reject Offer Page writes on a plan that doesn't allow commercial
    offers. Community plan → 403; Creator / Pro / Organisation → allowed;
    Platform Owner bypasses.

    Reuses the existing ``paid_offers_enabled`` capability — Offer
    Pages are a commercial surface and align with the same "can this
    creator sell?" distinction that gates paid pricing today. If the
    two ever diverge, add a dedicated ``offer_pages_enabled`` flag on
    :class:`PlanCapability` then.
    """
    if is_platform_owner(user):
        return
    plan = resolve_creator_plan(user, db)
    if plan is None or not plan.paid_offers_enabled:
        plan_name = plan.display_name if plan else "current"
        raise HTTPException(
            status_code=403,
            detail=(
                f"Your {plan_name} plan does not include Offer Pages. "
                "Upgrade to Creator to publish paid offers."
            ),
        )


def guard_pathway_limit(user: User, space: Space, db: Session) -> None:
    """Refuse a new Pathway when the plan caps how many a Collective may
    hold. Community is capped at five; Creator / Pro / Organisation are
    uncapped. Platform Owner bypasses.

    Called from the create-pathway route before insertion. Existing
    Pathways are grandfathered — the guard only fires on creation.
    """
    if is_platform_owner(user):
        return

    plan = resolve_creator_plan(user, db)
    if plan is None or plan.pathways_max_per_collective is None:
        return   # no cap for this plan

    from app.models.platform import Pathway   # local import avoids cycle
    current = (
        db.query(Pathway)
        .filter(Pathway.space_id == space.id)
        .count()
    )
    if current >= plan.pathways_max_per_collective:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Your {plan.display_name} plan includes "
                f"{plan.pathways_max_per_collective} Pathways per Collective. "
                "Upgrade to Creator to add more."
            ),
        )


# ---------------------------------------------------------------------------
# Member allowance
# ---------------------------------------------------------------------------


def count_space_members(space: Space, db: Session) -> int:
    """Count the active learners in ``space``.

    Deliberately the *same* predicate the public Collective cards and the
    About page use (active + role='learner'), so the number a creator is
    blocked against is the number everyone can see. Creators, moderators
    and the owner are not members for this purpose.
    """
    return (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role == SpaceRole.learner,
        )
        .count()
    )


def guard_member_allowance(space: Space, db: Session, *, for_creator: bool = False) -> None:
    """Refuse a new learner admission when the owning creator's plan caps
    members per Collective. Community is capped at 100; Creator / Pro are
    higher; Organisation pools its allowance and is uncapped here.

    Resolves the plan of the Collective's **owner**, not of the person being
    admitted — a visitor joining someone else's Collective is bounded by
    that creator's plan, not their own.

    Bypasses:
      * auto-managed Collectives (World Builders) — membership is computed
        from platform eligibility, not admitted;
      * Collectives owned by a Platform Owner — no creator plan applies;
      * plans whose ``member_allowance_per_collective`` is None — uncapped.

    ``for_creator`` selects the audience for the 403 message. A creator
    adding or approving someone is told which plan limit they hit; a
    visitor joining is told only that the Collective is full, so a
    stranger cannot read the owner's plan tier off an error.

    Callers must invoke this only for genuinely *new* active learners —
    after the already-a-member check — so an existing member is never
    locked out of their own Collective.
    """
    if space.auto_grant_role is not None:
        return

    owner = (
        db.query(User).filter(User.id == space.creator_id).first()
        if space.creator_id
        else None
    )
    if owner is None:
        # Orphaned Collective — no plan to enforce. Refusing here would
        # break joining on data we cannot attribute; the collective-limit
        # guard already owns the "no plan resolved" refusal at create time.
        return

    plan = resolve_creator_plan(owner, db)
    if plan is None or plan.member_allowance_per_collective is None:
        return

    allowance = plan.member_allowance_per_collective
    if count_space_members(space, db) < allowance:
        return

    if for_creator:
        detail = (
            f"Your {plan.display_name} plan includes {allowance} members "
            f"per Collective. Upgrade your plan to add more."
        )
    else:
        detail = "This collective has reached its member limit."
    raise HTTPException(status_code=403, detail=detail)


# ---------------------------------------------------------------------------
# Location filtering (used by GET /options to build the picker list)
# ---------------------------------------------------------------------------


def allowed_location_query(user: User, db: Session):
    """Return a SQLAlchemy query yielding the Locations this user's plan is
    allowed to choose from.

    Platform Owner receives ATLAS + COMMUNITY here; the caller adds
    CORNERSTONE separately so it can render them as their own group.
    Community plan → COMMUNITY only.
    Creator/Pro plan → ATLAS only.
    """
    if is_platform_owner(user):
        return db.query(Location).filter(
            Location.status == "active",
            Location.location_type.in_(("ATLAS", "COMMUNITY")),
        )

    plan = resolve_creator_plan(user, db)
    scope = plan.location_scope if plan else "atlas_full"
    wanted = "COMMUNITY" if scope == "community_only" else "ATLAS"
    return db.query(Location).filter(
        Location.status == "active",
        Location.location_type == wanted,
    )


# ---------------------------------------------------------------------------
# Re-exports (convenience)
# ---------------------------------------------------------------------------


__all__ = [
    "is_platform_owner",
    "resolve_creator_plan",
    "count_managed_collectives",
    "effective_collective_allowance",
    "guard_active_collective_limit",
    "guard_location_allowed",
    "guard_offer_pages_enabled",
    "guard_paid_offers_enabled",
    "allowed_location_query",
    "PLANS_BY_SLUG",
]
