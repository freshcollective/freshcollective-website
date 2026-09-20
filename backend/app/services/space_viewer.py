"""Who is this person, relative to this Collective?

One predicate, shared by every endpoint that returns Collective-scoped
data a stranger has no business seeing. Extracted from
``spaces.routes._get_member_space`` (SEC-004) so the members directory
can ask the same question rather than carry a second, subtly different
answer — which is exactly how the directory came to leak: it asked
"is the caller a learner?" and an anonymous caller is not, so the
privacy branch never ran.

Qualifying relationships, unchanged from the original:

  * ``User.role == "admin"`` — platform admin keeps cross-Collective
    oversight;
  * the caller owns the Space (``space.creator_id``), which covers
    legacy Collectives whose owner has no membership row;
  * an active ``SpaceMembership`` of any role.

Callers who do not qualify get **404, not 403** — refusing to confirm
a Collective exists to someone who cannot see it. Matches
``_get_space_visible_to`` and matters for private / link-only
Collectives.

Kept in ``app.services`` beside ``series_access`` and
``channel_permissions`` for the same reason those live there: routers
import it without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.platform import Space, SpaceMembership
from app.models.user import User

# Roles that see a Collective from the inside — they administer it, so
# member-directory privacy (which exists to stop learners browsing each
# other) does not apply to them.
LEADER_MEMBERSHIP_ROLES = frozenset({"creator", "moderator"})


@dataclass(frozen=True)
class SpaceViewer:
    """The caller's standing in one Collective."""

    is_admin: bool
    is_owner: bool
    #: ``learner`` / ``moderator`` / ``creator``, or ``None`` when the
    #: caller holds no active membership row (an owner or admin may
    #: legitimately have none).
    membership_role: str | None

    @property
    def qualifies(self) -> bool:
        """May this caller read Collective-scoped member data at all?"""
        return self.is_admin or self.is_owner or self.membership_role is not None

    @property
    def is_leader(self) -> bool:
        """Does this caller see the Collective from the inside?

        Deliberately expressed as "is a leader", not "is a learner".
        The old directory check asked the negative question and so
        exempted everyone who was not a learner — anonymous callers
        included. Asking the positive question means any future role,
        and any caller with no role at all, is treated as an outsider
        by default.
        """
        return (
            self.is_admin
            or self.is_owner
            or (self.membership_role in LEADER_MEMBERSHIP_ROLES)
        )


def resolve_space_viewer(
    db: Session, user: User | None, space: Space,
) -> SpaceViewer:
    """Describe ``user``'s standing in ``space``. Never raises."""
    if user is None:
        return SpaceViewer(is_admin=False, is_owner=False, membership_role=None)

    membership = (
        db.query(SpaceMembership.role)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == "active",
        )
        .first()
    )
    role: str | None = None
    if membership is not None:
        raw = membership[0]
        role = raw.value if hasattr(raw, "value") else str(raw)

    return SpaceViewer(
        is_admin=(user.role == "admin"),
        is_owner=(space.creator_id == user.id),
        membership_role=role,
    )


def require_space_viewer(
    db: Session, user: User | None, space: Space,
) -> SpaceViewer:
    """``resolve_space_viewer``, refusing outsiders with 404."""
    viewer = resolve_space_viewer(db, user, space)
    if not viewer.qualifies:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.",
        )
    return viewer
