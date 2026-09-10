"""Canonical Pathway-access rule for Fresh Collective.

One predicate. One place. Every surface that needs to answer
"can this user access this Pathway right now?" — the Pathway page,
Pathway-linked Conversation Channels, the @mention autocomplete for
those Channels, and any future feature scoped to Pathway access —
routes through :func:`compute_pathway_access`.

Recognised access sources (matches the historical behaviour of
``spaces.routes._compute_pathway_access``, from which this module
was extracted verbatim):

* platform admin (``User.role == "admin"``);
* Space owner (``Space.creator_id == user.id``);
* active caretaker ``SpaceMembership`` (role in ``creator``/``moderator``);
* free published Pathway (any active space member);
* ``included`` Pathway + active ``SpaceMembership``;
* ``included_with_offer`` Pathway + active ``AccessPass`` tied to one
  of the Pathway's ``PathwayUnlockRequirement.payment_option_id``s;
* ``one_time`` / ``subscription`` Pathway + active
  ``PathwayEntitlement`` whose ``ends_at`` is NULL or in the future.

Explicitly not an access source:

* ``Enrollment`` — this is a progress-tracking record, created lazily
  when a member marks their first step complete. It is used by release
  scheduling and recognition; it is NOT a permanent entitlement.
  A revoked purchase whose owner had already completed a step must
  still lose access.

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
from app.models.platform import (
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
    PathwayUnlockRequirement,
    Space,
    SpaceMembership,
)
from app.models.user import User


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
        unlock_option_ids = [
            row.payment_option_id
            for row in db.query(PathwayUnlockRequirement.payment_option_id)
            .filter(PathwayUnlockRequirement.pathway_id == pathway.id)
            .all()
        ]
        if not unlock_option_ids:
            return False
        pass_row = (
            db.query(AccessPass.id)
            .filter(
                AccessPass.user_id == user.id,
                AccessPass.space_id == space.id,
                AccessPass.status == AccessPassStatus.active,
                AccessPass.payment_option_id.in_(unlock_option_ids),
            )
            .first()
        )
        return pass_row is not None

    # one_time or subscription — requires active PathwayEntitlement that hasn't expired.
    now = datetime.utcnow()
    ent = (
        db.query(PathwayEntitlement.id)
        .filter(
            PathwayEntitlement.user_id == user.id,
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
            (PathwayEntitlement.ends_at.is_(None) | (PathwayEntitlement.ends_at > now)),
        )
        .first()
    )
    return ent is not None
