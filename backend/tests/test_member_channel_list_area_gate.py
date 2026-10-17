"""The member Channel list sits behind the Conversations doorway.

``list_member_channels`` returned a Collective's Channel names and
descriptions without asking whether the caller may reach the
Conversations Area at all — unlike the feed, the post detail and
search, which all open with ``require_area``. A member of a Collective
whose Conversations Area was shut could therefore enumerate what was
in there while being refused every post inside it.

The gate is the existing one, so these tests are mostly about blast
radius: a leader, an owner and a platform admin must still get the
list, because Creator Studio reads this same endpoint and none of them
holds an access pass to their own Collective.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.community.channels import list_member_channels
from app.models.platform import (
    ConversationChannel,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _member(db, user, space, *, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id, role=role,
        status=SpaceMembershipStatus.active, joined_at=datetime.utcnow(),
    ))
    db.flush()


def _channel(db, space):
    c = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="Common Room",
        slug=f"ch-{uuid.uuid4().hex[:8]}", channel_type="general",
        is_default=True, is_system=True,
    )
    db.add(c); db.flush()
    return c


def _call(db, user, space):
    return list_member_channels(slug=space.slug, db=db, current_user=user)


def _shut_conversations(space):
    """Conversations behind an access pass this member will not hold."""
    space.area_policies = {"areas": {"conversations": "active_access"}}


class TestTheDoorwayIsChecked:
    def test_a_learner_without_access_is_refused(self, db, make_space, make_user):
        space = make_space()
        _shut_conversations(space)
        learner = make_user()
        _member(db, learner, space)
        _channel(db, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            _call(db, learner, space)
        assert exc.value.status_code == 404, (
            "404 not 403 — a refusal must not confirm the Area exists"
        )

    def test_the_same_learner_gets_the_list_when_the_area_is_open(
        self, db, make_space, make_user,
    ):
        # The control. Without this, a gate that refused everyone would
        # pass the test above.
        space = make_space()
        space.area_policies = {"areas": {"conversations": "members"}}
        learner = make_user()
        _member(db, learner, space)
        _channel(db, space)
        db.commit()

        assert len(_call(db, learner, space)) == 1

    def test_the_default_policy_is_unaffected(self, db, make_space, make_user):
        # No ``area_policies`` at all — every Collective in production
        # today. The gate must be invisible here.
        space = make_space()
        learner = make_user()
        _member(db, learner, space)
        _channel(db, space)
        db.commit()

        assert len(_call(db, learner, space)) == 1


class TestCreatorStudioCallersAreUnaffected:
    """Creator Studio reads this endpoint too. A leader holds no access
    pass to their own Collective, so if the gate asked them the access
    question it would empty their Manage Channels list."""

    def test_a_moderator_still_gets_the_list(self, db, make_space, make_user):
        space = make_space()
        _shut_conversations(space)
        mod = make_user()
        _member(db, mod, space, role=SpaceRole.moderator)
        _channel(db, space)
        db.commit()

        assert len(_call(db, mod, space)) == 1

    def test_the_owner_still_gets_the_list(self, db, make_space, make_user):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        _shut_conversations(space)
        _channel(db, space)
        db.commit()

        # Deliberately no SpaceMembership row: ownership alone must
        # carry it, which is how legacy Collectives behave.
        assert len(_call(db, owner, space)) == 1

    def test_a_platform_admin_without_membership_still_gets_the_list(
        self, db, make_space, make_user,
    ):
        space = make_space()
        _shut_conversations(space)
        admin = make_user(role="admin")
        _channel(db, space)
        db.commit()

        assert len(_call(db, admin, space)) == 1

    def test_a_platform_creator_who_is_a_mere_learner_is_still_refused(
        self, db, make_space, make_user,
    ):
        # SEC-005-E: platform ``role == "creator"`` is Studio entry, not
        # authority over someone else's Collective. It must not act as
        # a leader bypass here either.
        space = make_space()
        _shut_conversations(space)
        outsider = make_user(role="creator")
        _member(db, outsider, space)
        _channel(db, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            _call(db, outsider, space)
        assert exc.value.status_code == 404
