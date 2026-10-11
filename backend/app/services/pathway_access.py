"""Canonical Pathway-access rule for Fresh Collective.

One predicate. One place. Every surface that needs to answer
"can this user access this Pathway right now?" — the Pathway page,
Pathway-linked Conversation Channels, the @mention autocomplete for
those Channels, and any future feature scoped to Pathway access —
routes through :func:`compute_pathway_access`.

Recognised access sources:

* platform admin (``User.role == "admin"``);
* Space owner (``Space.creator_id == user.id``);
* active caretaker ``SpaceMembership`` (role in ``creator``/``moderator``);
* free published Pathway (any active space member);
* ``included`` Pathway + active ``SpaceMembership``;
* ``included_with_offer`` Pathway + active ``SpaceMembership`` AND
  EITHER an active, not-yet-expired ``AccessPass`` whose
  ``payment_option_id`` grants this Pathway via
  ``PaymentOptionGrant`` (the Option's ``status`` must be
  ``published`` (currently sold) or ``archived`` (historical
  buyers keep access); ``draft`` options never unlock anything),
  OR an active, not-yet-expired ``PathwayEntitlement`` for this
  Pathway.

  The entitlement arm is not a widening of the rule — it is the
  record ``services.purchase_fulfilment`` actually writes when a
  Payment Option carries a ``pathway`` grant (one
  ``EntitlementIntent`` per grant; ``AccessPass`` rows are written
  only for ``event_series`` grants). Accepting only the pass left
  a completed, fulfilled purchase locked out of the very Pathway it
  bought, while Creator Studio — which reads the entitlement —
  reported it as "Purchased". Manual Creator grants land in the
  same table, so they unlock these Pathways too;
* ``one_time`` / ``subscription`` Pathway + active
  ``PathwayEntitlement`` whose ``ends_at`` is NULL or in the future.

Explicitly not an access source:

* ``Enrollment`` — this is a progress-tracking record, created lazily
  when a member marks their first step complete. It is used by release
  scheduling and recognition; it is NOT a permanent entitlement.
  A revoked purchase whose owner had already completed a step must
  still lose access.
* ``PathwayUnlockRequirement`` — legacy join table (migration 051).
  As of migration 125 its rows have been backfilled into
  ``PaymentOptionGrant``; this predicate does not consult it. The
  table is left in place for rollback safety and is scheduled for
  drop in a later housekeeping migration.

Extraction rationale
--------------------
Kept in ``app.services`` (peer of ``channel_permissions``,
``event_permissions``) so both those modules and ``spaces.routes`` can
import it without creating a cycle. ``spaces.routes`` already imports
from ``channel_permissions``; if ``channel_permissions`` needed to
import from ``spaces.routes`` for this predicate, we'd have a loop —
this module dissolves that.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.payment_option import PaymentOption, PaymentOptionStatus
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.platform import (
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
)
from app.models.user import User


# ---------------------------------------------------------------------------
# Shared building blocks
#
# Three surfaces answer "who can reach this Pathway?":
# :func:`compute_pathway_access` (a bool, for member pages),
# ``spaces.routes._require_pathway_access`` (raises 403, for content
# endpoints) and ``channel_permissions.mention_candidate_user_ids`` (a
# set, for mention autocomplete). Each previously carried its own copy
# of the unlock query. Three copies are three chances to drift, and
# they had all drifted the same way — see the ``included_with_offer``
# note in the module docstring. The queries now live here once.
# ---------------------------------------------------------------------------


def unlock_option_ids_for_pathway(db: Session, pathway_id: str):
    """PaymentOptions that include this Pathway and may still unlock it.

    ``published`` = currently sold; ``archived`` = historical buyers
    keep what they paid for; ``draft`` never unlocks anything.
    Returned as a query so callers can use it as an ``IN`` subquery
    rather than materialising ids.
    """
    return (
        db.query(PaymentOptionGrant.payment_option_id)
        .join(
            PaymentOption,
            PaymentOption.id == PaymentOptionGrant.payment_option_id,
        )
        .filter(
            PaymentOptionGrant.grant_kind == "pathway",
            PaymentOptionGrant.pathway_id == pathway_id,
            PaymentOption.status.in_([
                PaymentOptionStatus.published,
                PaymentOptionStatus.archived,
            ]),
        )
    )


def has_active_pathway_entitlement(
    db: Session, *, user_id: str, pathway_id: str,
    now: datetime | None = None,
) -> bool:
    """An active, not-yet-expired ``PathwayEntitlement`` belonging to
    exactly this user and this Pathway.

    ``status`` must be ``active`` — a ``revoked``, ``expired`` or
    ``cancelled`` row never grants access — and ``ends_at`` must be
    NULL (perpetual) or still in the future. ``starts_at`` is
    deliberately not consulted: it never gated access, and beginning
    to honour it here would silently change behaviour for every
    existing entitlement.
    """
    at = now if now is not None else datetime.utcnow()
    return (
        db.query(PathwayEntitlement.id)
        .filter(
            PathwayEntitlement.user_id == user_id,
            PathwayEntitlement.pathway_id == pathway_id,
            PathwayEntitlement.status == EntitlementStatus.active,
            (PathwayEntitlement.ends_at.is_(None)
             | (PathwayEntitlement.ends_at > at)),
        )
        .first()
    ) is not None


def has_offer_access_pass(
    db: Session, *, user_id: str, space_id: str, pathway_id: str,
    now: datetime | None = None,
) -> bool:
    """An active, not-yet-expired ``AccessPass`` held by this user in
    this Collective, on an Option that includes this Pathway."""
    at = now if now is not None else datetime.utcnow()
    return (
        db.query(AccessPass.id)
        .filter(
            AccessPass.user_id == user_id,
            AccessPass.space_id == space_id,
            AccessPass.status == AccessPassStatus.active,
            AccessPass.payment_option_id.in_(
                unlock_option_ids_for_pathway(db, pathway_id)
            ),
            (AccessPass.valid_until.is_(None) | (AccessPass.valid_until > at)),
        )
        .first()
    ) is not None


def included_with_offer_unlocked(
    db: Session, *, user_id: str, space_id: str, pathway_id: str,
    now: datetime | None = None,
) -> bool:
    """Does this user hold something that unlocks an
    ``included_with_offer`` Pathway?

    Either durable access record counts: an ``AccessPass`` on an Option
    that includes the Pathway, or an active ``PathwayEntitlement`` for
    the Pathway itself.

    Callers MUST still require an active ``SpaceMembership``
    separately. This answers "do they hold an unlock?", not "may they
    enter?" — keeping the membership requirement at the call site means
    it cannot be lost by reaching for this helper.

    Neither arm is payment status. Both are records that expiry and
    revocation remove, so access ends when the grant ends.
    """
    return (
        has_offer_access_pass(
            db, user_id=user_id, space_id=space_id,
            pathway_id=pathway_id, now=now,
        )
        or has_active_pathway_entitlement(
            db, user_id=user_id, pathway_id=pathway_id, now=now,
        )
    )


def users_with_included_with_offer_access(
    db: Session, *, space_id: str, pathway_id: str,
    now: datetime | None = None,
) -> set[str]:
    """Set form of :func:`included_with_offer_unlocked`, for the
    mention-autocomplete path which needs every eligible user at once
    instead of one answer per user.

    Returns unlock-holders only. The caller intersects with the
    Collective's active membership, so a stray pass or entitlement held
    by a non-member cannot surface.
    """
    at = now if now is not None else datetime.utcnow()
    option_ids = unlock_option_ids_for_pathway(db, pathway_id)
    pass_holders = {
        r.user_id
        for r in db.query(AccessPass.user_id).filter(
            AccessPass.space_id == space_id,
            AccessPass.status == AccessPassStatus.active,
            AccessPass.payment_option_id.in_(option_ids),
            (AccessPass.valid_until.is_(None) | (AccessPass.valid_until > at)),
        ).all()
    }
    entitled = {
        r.user_id
        for r in db.query(PathwayEntitlement.user_id).filter(
            PathwayEntitlement.pathway_id == pathway_id,
            PathwayEntitlement.status == EntitlementStatus.active,
            (PathwayEntitlement.ends_at.is_(None)
             | (PathwayEntitlement.ends_at > at)),
        ).all()
    }
    return pass_holders | entitled


def compute_pathway_access(
    user: User | None,
    pathway: Pathway,
    space: Space,
    db: Session,
) -> bool:
    """Return True if ``user`` currently has access to ``pathway``.

    Accepts ``None`` for unauthenticated visitors — they never have
    access to paid or included Pathways.

    SEC-005-E note preserved from the original implementation:
    platform ``User.role == "creator"`` does NOT grant global Pathway
    access. Manager-level bypass (draft / archived / coming_soon /
    paid) requires platform admin, Space ownership, or an active
    creator/moderator ``SpaceMembership`` on this specific Collective.
    """
    if user is None:
        p_status = pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status)
        access_type = pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type or "free")
        if p_status in ("draft", "archived", "coming_soon"):
            return False
        return access_type == "free"
    if user.role == "admin":
        return True
    if space.creator_id == user.id:
        return True
    space_role = (
        db.query(SpaceMembership.role)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.role.in_(["creator", "moderator"]),
            SpaceMembership.status == "active",
        )
        .first()
    )
    if space_role:
        return True
    p_status = pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status)
    access_type = pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type or "free")
    if p_status in ("draft", "archived", "coming_soon"):
        return False
    if access_type == "free":
        return True
    if access_type == "included":
        mem = (
            db.query(SpaceMembership.id)
            .filter(
                SpaceMembership.user_id == user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == "active",
            )
            .first()
        )
        return mem is not None
    if access_type == "included_with_offer":
        # Ordinary members: require an active SpaceMembership on this
        # Collective. A stray AccessPass or PathwayEntitlement held by
        # a non-member cannot unlock the Pathway.
        member_row = (
            db.query(SpaceMembership.id)
            .filter(
                SpaceMembership.user_id == user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .first()
        )
        if member_row is None:
            return False
        return included_with_offer_unlocked(
            db, user_id=user.id, space_id=space.id, pathway_id=pathway.id,
        )

    # one_time or subscription — requires active PathwayEntitlement that hasn't expired.
    return has_active_pathway_entitlement(
        db, user_id=user.id, pathway_id=pathway.id,
    )
