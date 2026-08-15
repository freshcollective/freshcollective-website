"""Regression: /api/spaces/{slug} must expose authoritative learner_count
and leader_count aggregates independent of the /members privacy filter.

Previously the shared member Collective sidebar derived its member /
leader counts from ``members.filter(...).length`` where ``members``
came from ``/api/spaces/{slug}/members`` — an endpoint that hides
learner rows from learner-role callers when
``show_member_directory=False``. Ordinary members therefore saw
"0 members" in every sidebar even though the collective had many.

The fix: ``SpaceResponse`` now carries ``learner_count`` and
``leader_count`` as DB aggregates. The frontend consumes these fields
directly. This test locks in that behaviour so a future refactor
cannot silently regress the counts back to filter-derived.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.spaces.routes import get_space


def _membership(db, space, user, role: SpaceRole) -> SpaceMembership:
    m = SpaceMembership(
        id=f"sm_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        user_id=user.id,
        role=role,
        status=SpaceMembershipStatus.active,
    )
    db.add(m)
    db.flush()
    return m


@pytest.mark.parametrize(
    "show_directory,scenario",
    [
        (True,  "grove-style-3-members-directory-visible"),
        (False, "embody-style-2-members-directory-hidden"),
    ],
)
def test_learner_role_viewer_sees_authoritative_counts(
    db, make_space, make_user, show_directory, scenario,
):
    """A learner-role viewer must see the true learner_count / leader_count
    aggregates on ``GET /api/spaces/{slug}`` regardless of whether the
    member directory is publicly visible. The privacy filter only hides
    learner *identities* from the /members endpoint — it must never leak
    into the sidebar aggregate counts."""
    creator = make_user(role="creator")
    space = make_space(
        creator=creator,
        show_member_directory=show_directory,
    )
    _membership(db, space, creator, SpaceRole.creator)
    moderator = make_user()
    _membership(db, space, moderator, SpaceRole.moderator)

    learners = [make_user() for _ in range(3)]
    for u in learners:
        _membership(db, space, u, SpaceRole.learner)

    viewer = learners[0]
    resp = get_space(slug=space.slug, db=db, current_user=viewer)

    assert resp.learner_count == 3, (
        f"[{scenario}] learner_count should be authoritative (3), got "
        f"{resp.learner_count}. This means the sidebar will render "
        f"'0 members' for ordinary members again."
    )
    assert resp.leader_count == 2, (
        f"[{scenario}] leader_count should be authoritative (2 = creator + "
        f"moderator), got {resp.leader_count}."
    )


def test_anonymous_viewer_sees_authoritative_counts_on_public_space(
    db, make_space, make_user,
):
    """Public-Collective anonymous callers get the same authoritative
    aggregates. Prevents the sidebar showing 0 on marketing pages."""
    creator = make_user(role="creator")
    space = make_space(
        creator=creator,
        is_public=True,
        show_member_directory=False,
    )
    _membership(db, space, creator, SpaceRole.creator)
    for _ in range(4):
        _membership(db, space, make_user(), SpaceRole.learner)

    resp = get_space(slug=space.slug, db=db, current_user=None)
    assert resp.learner_count == 4
    assert resp.leader_count == 1


def test_counts_exclude_inactive_memberships(db, make_space, make_user):
    """Only ``status=active`` memberships count. Left / removed / pending
    members must not inflate the sidebar."""
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    _membership(db, space, creator, SpaceRole.creator)

    for _ in range(2):
        _membership(db, space, make_user(), SpaceRole.learner)

    inactive_user = make_user()
    m = _membership(db, space, inactive_user, SpaceRole.learner)
    m.status = SpaceMembershipStatus.removed
    db.flush()

    resp = get_space(slug=space.slug, db=db, current_user=creator)
    assert resp.learner_count == 2
    assert resp.leader_count == 1
