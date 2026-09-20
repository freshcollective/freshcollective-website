"""The one authority on which areas of a Collective a viewer may reach.

Every surface that needs the answer asks this and nothing else: the
list APIs, the server-rendered routes, the navigation tabs, the
Collective Home tiles, and the public discovery pages that must not
become a back door into a members-only area.

The failure this exists to prevent has already happened twice on this
platform at smaller scale — the Members tab and the Members Home tile
disagreeing, and the Explore card and the dashboard disagreeing about
membership. Both times the cause was two places deciding the same
thing. So: resolved once per request, threaded down, never
recalculated in a component and never recomputed per card.

Cost
----

* one membership lookup — ``services.space_viewer``, which the members
  directory already pays for;
* one EXISTS over the access tables, **only** when this Collective
  actually uses the ``active_access`` policy. A Collective using only
  ``public`` and ``members`` — every Collective today — adds no query
  at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.platform import Space
from app.models.user import User
from app.services.active_access import has_active_access
from app.services.space_viewer import SpaceViewer, resolve_space_viewer
from app.spaces import area_policies as ap


@dataclass(frozen=True)
class AreaAccess:
    """What this viewer may reach in this Collective."""

    viewer: SpaceViewer
    #: Every area's effective policy, defaults filled in.
    policies: dict[str, str]
    #: Areas whose doorway is open to this viewer.
    reachable: frozenset[str]
    #: Whether the viewer holds active access. ``False`` when nothing
    #: needed to know — do not read it as "has no access".
    has_active_access: bool
    #: Whether the question was actually asked.
    active_access_evaluated: bool

    def can_reach(self, area: str) -> bool:
        return area in self.reachable

    def policy_for(self, area: str) -> str:
        return self.policies.get(area, ap.AREA_DEFAULTS.get(area, ap.POLICY_MEMBERS))


def resolve_area_access(
    db: Session,
    space: Space,
    user: User | None,
    *,
    now: datetime | None = None,
) -> AreaAccess:
    """Resolve every area for this viewer, in one pass."""
    viewer = resolve_space_viewer(db, user, space)
    policies = ap.resolve_policies(space.area_policies)

    # Leaders and platform admins reach everything a member reaches and
    # everything an entitled member reaches. They administer the place;
    # requiring them to hold a pass to see their own Pathways list
    # would be absurd, and they can already see all of it in Creator
    # Studio. Asking the access question for them is therefore also
    # pointless, so it is skipped.
    is_leader = viewer.is_leader
    is_member = viewer.qualifies

    needs_access_check = (
        not is_leader
        and is_member
        and ap.POLICY_ACTIVE_ACCESS in policies.values()
    )
    active = False
    if needs_access_check and user is not None:
        active = has_active_access(
            db, user_id=user.id, space_id=space.id, now=now,
        )

    reachable = set()
    for area, policy in policies.items():
        if policy == ap.POLICY_PUBLIC:
            reachable.add(area)
        elif policy == ap.POLICY_MEMBERS:
            if is_member:
                reachable.add(area)
        elif policy == ap.POLICY_ACTIVE_ACCESS:
            if is_leader or (is_member and active):
                reachable.add(area)

    # ``show_member_directory`` is deliberately NOT applied here.
    #
    # It is a rule about *who appears in the list*, not about whether
    # the list answers: with the directory closed, a learner still
    # opens the Members page and sees the Collective's leaders, which
    # is long-standing behaviour and the only way to find the people
    # running the place. Folding it in here 404'd that page for every
    # learner in every Collective with the directory off.
    #
    # The two rules compose where they belong instead — the doorway
    # here, the row filter in ``members.routes.list_members``, and the
    # tile and tab in ``home_config.resolve`` and ``SpaceNav``, both of
    # which already take ``show_member_directory`` and drop Members
    # when it is off. An area policy therefore still cannot open a
    # directory the Collective has closed; it just cannot shut the
    # door on the leaders either.

    return AreaAccess(
        viewer=viewer,
        policies=policies,
        reachable=frozenset(reachable),
        has_active_access=active,
        active_access_evaluated=needs_access_check,
    )


def require_area(
    db: Session,
    space: Space,
    user: User | None,
    area: str,
    *,
    now: datetime | None = None,
) -> AreaAccess:
    """Resolve, and refuse with 404 when the doorway is shut.

    404 rather than 403, matching ``_get_member_space`` and
    ``_get_space_visible_to``: a refusal must not confirm that an area
    exists to someone who may not see it, or the shape of a private
    Collective leaks through its error codes.

    Returns the resolution so the caller can keep using it — the point
    of the guard is that a request resolves once.
    """
    from fastapi import HTTPException, status as http_status

    access = resolve_area_access(db, space, user, now=now)
    if not access.can_reach(area):
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Not found.",
        )
    return access
