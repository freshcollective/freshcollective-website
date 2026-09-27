"""Who may read a member's profile, and what it tells them.

Every test here is a regression: each one describes something
``GET /api/profile/{user_id}`` used to answer for any signed-in caller,
with no shared context of any kind. The bypasses were probed on a live
local database before this work — a learner could read the profile of
someone the member directory had deliberately hidden from them, and an
unnamed member's email local part came back as their display name.

The access rule is deliberately the directory's own rule, reached
through ``member_visibility``, so these tests and
``test_member_image``'s directory tests cannot drift apart.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_optional_user
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    CreatorProfile,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.member_identity import NEUTRAL_DISPLAY_NAME


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    # Both, because the directory resolves its viewer through
    # ``get_optional_user`` so it can 404 an outsider, while the profile
    # route requires a signed-in caller.
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user


def _join(db, user, space, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=role, status=SpaceMembershipStatus.active,
    ))
    db.flush()


def _open_directory(make_space, **kw):
    """A Collective whose member directory is switched on.

    The platform default is ``False`` — learners see a count, not each
    other — so a test that means "the directory is open" has to say so.
    """
    kw.setdefault("show_member_directory", True)
    return make_space(**kw)


def _profile(db, user, **kw):
    kw.setdefault("is_public", True)
    cp = CreatorProfile(user_id=user.id, **kw)
    db.add(cp)
    db.flush()
    return cp


# ---------------------------------------------------------------------------
# Rule 3 — a shared Collective is required
# ---------------------------------------------------------------------------

class TestASharedCollectiveIsRequired:
    def test_strangers_cannot_read_each_other(self, client, db, make_user, make_space):
        """The original bypass: signed in was the whole rule."""
        here, elsewhere = make_space(), make_space()
        viewer, target = make_user(name="Viewer"), make_user(name="Target")
        _join(db, viewer, here)
        _join(db, target, elsewhere)
        db.commit()
        as_user(viewer)

        assert client.get(f"/api/profile/{target.id}").status_code == 404

    def test_sharing_a_collective_is_enough(self, client, db, make_user, make_space):
        space = _open_directory(make_space)
        viewer, target = make_user(name="Viewer"), make_user(name="Target")
        _join(db, viewer, space)
        _join(db, target, space)
        db.commit()
        as_user(viewer)

        res = client.get(f"/api/profile/{target.id}")
        assert res.status_code == 200
        assert res.json()["display_name"] == "Target"

    def test_belonging_to_no_collective_at_all_reads_nobody(
        self, client, db, make_user, make_space
    ):
        space = make_space()
        target = make_user(name="Target")
        _join(db, target, space)
        db.commit()
        as_user(make_user(name="Drifter"))

        assert client.get(f"/api/profile/{target.id}").status_code == 404

    def test_your_own_profile_needs_no_collective(self, client, db, make_user):
        me = make_user(name="Me")
        db.commit()
        as_user(me)

        res = client.get(f"/api/profile/{me.id}")
        assert res.status_code == 200
        assert res.json()["display_name"] == "Me"

    def test_a_refusal_does_not_confirm_the_account_exists(
        self, client, db, make_user, make_space
    ):
        """404 not 403, and the same 404 as a wholly unknown id."""
        space = make_space()
        viewer = make_user(name="Viewer")
        _join(db, viewer, space)
        stranger = make_user(name="Stranger")
        db.commit()
        as_user(viewer)

        hidden = client.get(f"/api/profile/{stranger.id}")
        absent = client.get("/api/profile/u_does_not_exist")
        assert hidden.status_code == absent.status_code == 404
        assert hidden.json() == absent.json()


# ---------------------------------------------------------------------------
# The directory bypass
# ---------------------------------------------------------------------------

class TestTheProfileNeverOutrunsTheDirectory:
    def test_a_hidden_learner_stays_hidden(self, client, db, make_user, make_space):
        """The sharpest bypass. With the directory off, a learner cannot
        *list* fellow learners — but could fetch each one directly, and
        ids are handed out by post authors and mention search."""
        space = make_space(show_member_directory=False)
        viewer, target = make_user(name="Viewer"), make_user(name="Hidden Learner")
        _join(db, viewer, space)
        _join(db, target, space)
        db.commit()
        as_user(viewer)

        listed = [m["id"] for m in client.get(f"/api/spaces/{space.slug}/members").json()]
        assert target.id not in listed, "fixture no longer exercises the hidden case"

        assert client.get(f"/api/profile/{target.id}").status_code == 404

    def test_the_platform_default_already_hides_learners(
        self, client, db, make_user, make_space
    ):
        """``show_member_directory`` defaults to False, so this is the
        ordinary case rather than an unusual one: two learners in the same
        Collective cannot read each other until the Creator opens the
        directory."""
        space = make_space()
        assert space.show_member_directory is False, "platform default changed"
        viewer, target = make_user(name="Viewer"), make_user(name="Target")
        _join(db, viewer, space)
        _join(db, target, space)
        db.commit()
        as_user(viewer)

        assert client.get(f"/api/profile/{target.id}").status_code == 404

    def test_leaders_are_still_visible_when_learners_are_hidden(
        self, client, db, make_user, make_space
    ):
        """The directory keeps showing who runs the place, so the profile
        must too — the rule is the same rule, not a stricter one."""
        space = make_space(show_member_directory=False)
        viewer, leader = make_user(name="Viewer"), make_user(name="The Moderator")
        _join(db, viewer, space)
        _join(db, leader, space, role=SpaceRole.moderator)
        db.commit()
        as_user(viewer)

        res = client.get(f"/api/profile/{leader.id}")
        assert res.status_code == 200
        assert res.json()["display_name"] == "The Moderator"

    def test_a_leader_may_still_read_a_hidden_learner(
        self, client, db, make_user, make_space
    ):
        """The setting exists to stop learners browsing each other; it was
        never meant to blind the people administering the Collective."""
        space = make_space(show_member_directory=False)
        leader, target = make_user(name="Mod"), make_user(name="Hidden Learner")
        _join(db, leader, space, role=SpaceRole.moderator)
        _join(db, target, space)
        db.commit()
        as_user(leader)

        assert client.get(f"/api/profile/{target.id}").status_code == 200


# ---------------------------------------------------------------------------
# Rule 2 — a deliberately public Creator profile
# ---------------------------------------------------------------------------

class TestAPublicCreatorProfile:
    def test_is_readable_without_a_shared_collective(
        self, client, db, make_user, make_space
    ):
        creator = make_user(name="Public Creator", role="creator")
        _profile(db, creator, bio="Hello", is_public=True)
        db.commit()
        as_user(make_user(name="Curious"))

        res = client.get(f"/api/profile/{creator.id}")
        assert res.status_code == 200
        assert res.json()["bio"] == "Hello"

    def test_a_private_creator_profile_is_not(self, client, db, make_user):
        """``is_public`` is how a Creator says the profile is their public
        face. Holding a row is not saying it — every member who uploads a
        photo gets one, created private."""
        creator = make_user(name="Shy Creator", role="creator")
        _profile(db, creator, bio="Hello", is_public=False)
        db.commit()
        as_user(make_user(name="Curious"))

        assert client.get(f"/api/profile/{creator.id}").status_code == 404

    def test_an_ordinary_member_with_a_public_profile_is_not_a_public_creator(
        self, client, db, make_user
    ):
        """The carve-out is for Creators, not for anyone holding a public
        profile row — otherwise it would swallow the rule it sits beside."""
        member = make_user(name="Ordinary", role="user")
        _profile(db, member, is_public=True)
        db.commit()
        as_user(make_user(name="Curious"))

        assert client.get(f"/api/profile/{member.id}").status_code == 404

    def test_a_cancelled_creator_loses_the_carve_out(self, client, db, make_user):
        from datetime import datetime

        creator = make_user(name="Was A Creator", role="creator",
                            creator_cancelled_at=datetime.utcnow())
        _profile(db, creator, is_public=True)
        db.commit()
        as_user(make_user(name="Curious"))

        assert client.get(f"/api/profile/{creator.id}").status_code == 404


# ---------------------------------------------------------------------------
# What the payload says
# ---------------------------------------------------------------------------

class TestWhatTheProfileDiscloses:
    def test_an_unnamed_member_is_not_named_after_their_email(
        self, client, db, make_user, make_space
    ):
        """It used to answer ``private.person.1985`` for
        ``private.person.1985@example.test``, to anyone signed in."""
        space = _open_directory(make_space)
        viewer = make_user(name="Viewer")
        target = make_user(name=None, email="private.person.1985@example.test")
        _join(db, viewer, space)
        _join(db, target, space)
        db.commit()
        as_user(viewer)

        body = client.get(f"/api/profile/{target.id}").json()
        assert body["display_name"] == NEUTRAL_DISPLAY_NAME
        assert "private.person" not in str(body)
        # And the image derived from that name reveals nothing either.
        assert body["image"]["initial"] in (None, NEUTRAL_DISPLAY_NAME[0])

    def test_account_age_is_not_another_members_business(
        self, client, db, make_user, make_space
    ):
        space = _open_directory(make_space)
        viewer, target = make_user(name="Viewer"), make_user(name="Target")
        _join(db, viewer, space)
        _join(db, target, space)
        db.commit()
        as_user(viewer)

        assert client.get(f"/api/profile/{target.id}").json()["joined_platform"] is None

    def test_your_own_account_age_is_your_own_fact(self, client, db, make_user):
        me = make_user(name="Me")
        db.commit()
        as_user(me)

        assert client.get(f"/api/profile/{me.id}").json()["joined_platform"] is not None

    def test_a_private_collective_is_never_named(
        self, client, db, make_user, make_space
    ):
        """``spaces_led`` filtered only on status, so the name of a
        link-only or private Collective reached any caller who could read
        the Creator's profile."""
        creator = make_user(name="Creator", role="creator")
        _profile(db, creator, is_public=True)
        make_space(creator_id=creator.id, name="Open House", visibility="public")
        make_space(creator_id=creator.id, name="Secret Circle", visibility="private")
        make_space(creator_id=creator.id, name="By Invitation", visibility="link")
        db.commit()
        as_user(make_user(name="Curious"))

        led = client.get(f"/api/profile/{creator.id}").json()["spaces_led"]
        assert led == ["Open House"]

    def test_a_private_collective_is_named_to_someone_already_inside_it(
        self, client, db, make_user, make_space
    ):
        creator = make_user(name="Creator", role="creator")
        _profile(db, creator, is_public=True)
        secret = make_space(creator_id=creator.id, name="Secret Circle",
                            visibility="private")
        viewer = make_user(name="Insider")
        _join(db, viewer, secret)
        db.commit()
        as_user(viewer)

        led = client.get(f"/api/profile/{creator.id}").json()["spaces_led"]
        assert led == ["Secret Circle"]

    def test_a_private_profile_still_withholds_bio_and_photo(
        self, client, db, make_user, make_space
    ):
        """Long-standing behaviour, pinned here because the access rule
        moved around it: sharing a Collective earns you a name, not
        somebody's private profile contents."""
        space = _open_directory(make_space)
        viewer, target = make_user(name="Viewer"), make_user(name="Target")
        _join(db, viewer, space)
        _join(db, target, space)
        _profile(db, target, bio="private words",
                 avatar_url="/api/uploads/avatars/x.png", is_public=False)
        db.commit()
        as_user(viewer)

        body = client.get(f"/api/profile/{target.id}").json()
        assert body["bio"] is None
        assert body["avatar_url"] is None
        assert "private words" not in str(body)

    def test_the_exact_field_set(self, client, db, make_user):
        """Pinned so a field cannot be added to a member-facing payload
        without this test being read."""
        me = make_user(name="Me")
        db.commit()
        as_user(me)

        assert set(client.get(f"/api/profile/{me.id}").json()) == {
            "id", "display_name", "avatar_url", "bio", "profile_tagline",
            "is_creator", "joined_platform", "spaces_led", "image",
        }

    def test_no_email_address_anywhere_in_the_payload(
        self, client, db, make_user, make_space
    ):
        space = _open_directory(make_space)
        viewer = make_user(name="Viewer")
        target = make_user(name="Target", email="target@example.test")
        _join(db, viewer, space)
        _join(db, target, space)
        db.commit()
        as_user(viewer)

        res = client.get(f"/api/profile/{target.id}")
        assert res.status_code == 200, "a 404 body would pass the assertion below"
        assert "@" not in str(res.json())
