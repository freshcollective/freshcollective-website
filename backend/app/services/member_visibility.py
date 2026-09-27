"""May this viewer see this member, and on whose terms?

Extracted from ``members.routes.list_members``. The directory already
carried the whole rule — a qualifying relationship with the Collective,
the members-area doorway, and the Collective's own
``show_member_directory`` switch — but it carried it inline, so
``GET /api/profile/{user_id}`` answered a different and much looser
question: any signed-in caller, any user id, no shared context at all.
A learner could read the profile of someone the directory would never
have listed to them, including a fellow learner in a Collective that had
deliberately switched the directory off.

The lesson is the one already recorded in ``space_viewer``: two
implementations of one privacy rule means one of them is wrong. So the
rule lives here once, and both callers ask it. Stated plainly:

    a member's profile must never reveal what the member directory
    would not have shown the same viewer.

Refusals stay 404 rather than 403, matching ``require_space_viewer``:
an error code must not confirm that a person, or a private Collective,
exists to someone who cannot see them.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.platform import Space, SpaceMembership, SpaceRole
from app.models.user import User
from app.services.space_viewer import SpaceViewer, resolve_space_viewer
from app.spaces.area_access import resolve_area_access
from app.spaces.area_policies import AREA_MEMBERS

#: Roles the directory still shows when it is hiding learners from each
#: other. Leaders run the place; the switch exists to stop learners
#: browsing one another, not to hide who is in charge.
DIRECTORY_LEADER_ROLES: Final = (SpaceRole.creator, SpaceRole.moderator)

#: The only ``Space.visibility`` level that anyone may be told about
#: without already having access. ``link`` and ``private`` Collectives
#: are not public knowledge — naming one in a profile would leak it.
PUBLIC_VISIBILITY: Final = "public"


def directory_hides_learners(space: Space, viewer: SpaceViewer) -> bool:
    """Is this viewer held to the Collective's directory restriction?

    Leaders administer the Collective, so the setting — which exists to
    stop learners browsing each other — does not apply to them. Phrased
    as "not a leader" rather than "is a learner" so that anyone without
    a recognised inside role is treated as an outsider by default.
    """
    return (
        not getattr(space, "show_member_directory", True)
        and not viewer.is_leader
    )


def directory_role_filter(
    space: Space, viewer: SpaceViewer
) -> tuple[SpaceRole, ...] | None:
    """Membership roles this viewer may see listed, or None for all."""
    return DIRECTORY_LEADER_ROLES if directory_hides_learners(space, viewer) else None


def _is_leader_role(role: object | None) -> bool:
    """Is this the role of someone who leads the Collective?

    ``None`` means the person holds no membership row, which reaches
    this function only for a Collective's own owner — a leader by
    definition, and the legacy case ``space_viewer`` documents.
    """
    if role is None:
        return True
    raw = role.value if hasattr(role, "value") else str(role)
    return raw in {r.value for r in DIRECTORY_LEADER_ROLES}


def _collectives_showing(db: Session, target: User) -> list[tuple[Space, object | None]]:
    """Every active Collective in which ``target`` might legitimately be seen.

    Their active memberships, plus any Collective they own outright —
    a Collective's owner may have no membership row at all, and being
    the person who runs the place a viewer belongs to is about as
    legitimate a shared context as exists.
    """
    rows = (
        db.query(Space, SpaceMembership.role)
        .join(
            SpaceMembership,
            and_(
                SpaceMembership.space_id == Space.id,
                SpaceMembership.user_id == target.id,
                SpaceMembership.status == "active",
            ),
        )
        .filter(Space.status == "active")
        .all()
    )
    found = {space.id: (space, role) for space, role in rows}

    for space in (
        db.query(Space)
        .filter(Space.creator_id == target.id, Space.status == "active")
        .all()
    ):
        found.setdefault(space.id, (space, None))

    return list(found.values())


def shared_visible_collective(
    db: Session, viewer: User | None, target: User
) -> Space | None:
    """The first Collective in which ``viewer`` may legitimately see ``target``.

    Applies the member directory's rule in full: the viewer needs a
    qualifying relationship with the Collective, the members area has to
    be reachable by them, and where the directory is restricted the
    target must be one of the people it still shows. Returns the
    Collective so a caller can say *why* access was granted; ``None``
    means there is no such place and the caller should refuse.
    """
    if viewer is None:
        return None

    for space, target_role in _collectives_showing(db, target):
        access = resolve_area_access(db, space, viewer)
        if not access.viewer.qualifies:
            continue
        if not access.can_reach(AREA_MEMBERS):
            continue
        if directory_hides_learners(space, access.viewer) and not _is_leader_role(
            target_role
        ):
            continue
        return space

    return None


def visible_collectives_led(
    db: Session, viewer: User | None, target: User
) -> list[str]:
    """Names of active Collectives ``target`` leads that ``viewer`` may know of.

    A public Collective is public knowledge, so naming it discloses
    nothing. A ``link`` or ``private`` one is named only to someone who
    could already reach it — otherwise a Creator's profile becomes a
    directory of their private Collectives, readable by anyone who can
    see the profile at all.
    """
    names: list[str] = []
    for space in (
        db.query(Space)
        .filter(Space.creator_id == target.id, Space.status == "active")
        .order_by(Space.name)
        .all()
    ):
        if space.visibility == PUBLIC_VISIBILITY:
            names.append(space.name)
        elif viewer is not None and resolve_space_viewer(db, viewer, space).qualifies:
            names.append(space.name)
    return names
