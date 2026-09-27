"""The creator ↔ member messages routes, exercised through the API.

This router had no tests at all, which is how it came to be broken in a
way a passing suite could not see. ``_user_display`` read
``user.display_name`` — a column ``User`` does not have — so every
endpoint that serialises a thread or a message raised ``AttributeError``
and answered 500. The Messages tab is rendered for every member of every
Collective, ungated by any flag, and the member inbox and thread pages
call these endpoints directly.

So the coverage here is deliberately route-level rather than
unit-level: the defect was in what the endpoints returned, and only a
real request would have caught it.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_verified_current_user
from app.core.database import get_db
from app.main import app
from app.models.messages import DirectMessage, MessageThread
from app.models.platform import (
    CreatorProfile,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.member_identity import NEUTRAL_DISPLAY_NAME

MEMBER_EMAIL = "quiet.member.1985@her-own-domain.test"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_current_user] = lambda: user


def _join(db, user, space, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=role, status=SpaceMembershipStatus.active,
    ))
    db.flush()


@pytest.fixture
def conversation(db, make_user, make_space):
    """A Collective, a creator, a member, and a thread with two messages.

    The member is deliberately unnamed with a distinctive address: that
    is the case the broken name ladder was reaching for, and the one most
    likely to leak an email address into a label.
    """
    creator = make_user(role="creator", name="Ada Leader")
    space = make_space(creator=creator)
    member = make_user(name=None, email=MEMBER_EMAIL)
    _join(db, creator, space, role=SpaceRole.creator)
    _join(db, member, space)

    thread = MessageThread(
        id=_uid("mt"), space_id=space.id,
        creator_id=creator.id, member_id=member.id,
    )
    db.add(thread)
    db.flush()
    db.add(DirectMessage(id=_uid("dm"), thread_id=thread.id,
                         sender_id=creator.id, body="Welcome along."))
    db.add(DirectMessage(id=_uid("dm"), thread_id=thread.id,
                         sender_id=member.id, body="Thank you."))
    db.commit()
    return space, creator, member, thread


# ---------------------------------------------------------------------------
# The member side — what the Messages tab actually reaches
# ---------------------------------------------------------------------------

class TestTheMemberInbox:
    def test_listing_threads_answers(self, client, conversation):
        """The regression: this was a 500 for every member."""
        space, _creator, member, thread = conversation
        as_user(member)

        res = client.get(f"/api/spaces/{space.slug}/messages")

        assert res.status_code == 200, res.text
        assert [t["thread_id"] for t in res.json()] == [thread.id]

    def test_the_inbox_names_the_creator(self, client, conversation):
        space, _creator, member, _thread = conversation
        as_user(member)

        row = client.get(f"/api/spaces/{space.slug}/messages").json()[0]

        assert row["other_user_name"] == "Ada Leader"
        assert row["last_message"] == "Thank you."
        assert row["unread_count"] == 1  # the creator's message, unread

    def test_thread_detail_answers(self, client, conversation):
        space, creator, member, thread = conversation
        as_user(member)

        res = client.get(f"/api/spaces/{space.slug}/messages/{thread.id}")

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["creator_name"] == "Ada Leader"
        assert [m["body"] for m in body["messages"]] == [
            "Welcome along.", "Thank you.",
        ]

    def test_every_message_names_its_sender(self, client, conversation):
        space, _creator, member, thread = conversation
        as_user(member)

        body = client.get(f"/api/spaces/{space.slug}/messages/{thread.id}").json()

        assert [m["sender_name"] for m in body["messages"]] == [
            "Ada Leader", NEUTRAL_DISPLAY_NAME,
        ]

    def test_replying_returns_the_thread(self, client, conversation):
        space, _creator, member, thread = conversation
        as_user(member)

        res = client.post(
            f"/api/spaces/{space.slug}/messages/{thread.id}/reply",
            json={"body": "One more thing"},
        )

        assert res.status_code == 200, res.text
        assert res.json()["messages"][-1]["body"] == "One more thing"

    def test_an_outsider_is_refused(self, client, conversation, make_user, db):
        """403 rather than the 404 the Collective-scoped helpers use.

        Pinned as it stands rather than corrected: this is existing
        SEC-005-D behaviour and tightening the error code is a separate
        decision, not part of repairing a crash.
        """
        space, _creator, _member, _thread = conversation
        db.commit()
        as_user(make_user(name="Outsider"))

        assert client.get(f"/api/spaces/{space.slug}/messages").status_code == 403


    def test_the_navigation_path_a_member_actually_walks(
        self, client, conversation
    ):
        """Messages tab → inbox → open a thread, as the pages do it.

        ``SpaceNav`` renders the tab for every member, ungated. Both pages
        swallow a failed fetch — the inbox returns ``[]`` and the thread
        page calls ``notFound()`` — so while these endpoints were 500ing
        the feature looked like an empty inbox rather than an error. Worth
        walking the whole path rather than trusting either half.
        """
        space, _creator, member, _thread = conversation
        as_user(member)

        inbox = client.get(f"/api/spaces/{space.slug}/messages")
        assert inbox.status_code == 200, inbox.text
        assert inbox.json(), "an empty inbox is what the failure looked like"

        thread_id = inbox.json()[0]["thread_id"]
        detail = client.get(f"/api/spaces/{space.slug}/messages/{thread_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["messages"], "a thread with no messages reads as lost"

        read = client.post(f"/api/spaces/{space.slug}/messages/{thread_id}/read")
        assert read.status_code == 204, read.text

        after = client.get(f"/api/spaces/{space.slug}/messages").json()[0]
        assert after["unread_count"] == 0


# ---------------------------------------------------------------------------
# The creator side
# ---------------------------------------------------------------------------

class TestTheCreatorSide:
    def test_listing_threads_answers(self, client, conversation):
        space, creator, _member, thread = conversation
        as_user(creator)

        res = client.get(f"/api/creator/spaces/{space.slug}/messages")

        assert res.status_code == 200, res.text
        assert [t["thread_id"] for t in res.json()] == [thread.id]

    def test_thread_detail_answers(self, client, conversation):
        space, creator, _member, thread = conversation
        as_user(creator)

        res = client.get(f"/api/creator/spaces/{space.slug}/messages/{thread.id}")

        assert res.status_code == 200, res.text
        assert res.json()["member_name"] == NEUTRAL_DISPLAY_NAME


# ---------------------------------------------------------------------------
# Names come from the canonical ladder, not from an email address
# ---------------------------------------------------------------------------

class TestHowPeopleAreNamed:
    def test_an_unnamed_member_reads_as_the_neutral_label(
        self, client, conversation
    ):
        space, creator, _member, thread = conversation
        as_user(creator)

        body = client.get(
            f"/api/creator/spaces/{space.slug}/messages/{thread.id}"
        ).json()

        assert body["member_name"] == NEUTRAL_DISPLAY_NAME

    def test_no_email_address_is_exposed_merely_to_render_a_name(
        self, client, conversation
    ):
        """The broken ladder's last rung was the local part of the address,
        so repairing it must not restore that by another route."""
        space, creator, _member, thread = conversation

        for viewer, url in (
            (creator, f"/api/creator/spaces/{space.slug}/messages"),
            (creator, f"/api/creator/spaces/{space.slug}/messages/{thread.id}"),
        ):
            as_user(viewer)
            res = client.get(url)
            assert res.status_code == 200, res.text
            assert MEMBER_EMAIL not in res.text
            assert "quiet.member" not in res.text

    def test_a_named_member_is_named(self, client, db, make_user, make_space):
        creator = make_user(role="creator", name="Ada Leader")
        space = make_space(creator=creator)
        member = make_user(name="Rosalind Franklin")
        _join(db, creator, space, role=SpaceRole.creator)
        _join(db, member, space)
        thread = MessageThread(id=_uid("mt"), space_id=space.id,
                               creator_id=creator.id, member_id=member.id)
        db.add(thread)
        db.commit()
        as_user(creator)

        body = client.get(
            f"/api/creator/spaces/{space.slug}/messages/{thread.id}"
        ).json()

        assert body["member_name"] == "Rosalind Franklin"

    def test_a_public_profile_display_name_wins(
        self, client, db, make_user, make_space
    ):
        """What the broken line was reaching for: ``display_name`` lives on
        ``CreatorProfile``, not on ``User``."""
        creator = make_user(role="creator", name="Ada Leader")
        space = make_space(creator=creator)
        member = make_user(name="Rosalind Franklin")
        db.add(CreatorProfile(user_id=member.id, display_name="Ros",
                              is_public=True))
        _join(db, creator, space, role=SpaceRole.creator)
        _join(db, member, space)
        thread = MessageThread(id=_uid("mt"), space_id=space.id,
                               creator_id=creator.id, member_id=member.id)
        db.add(thread)
        db.commit()
        as_user(creator)

        body = client.get(
            f"/api/creator/spaces/{space.slug}/messages/{thread.id}"
        ).json()

        assert body["member_name"] == "Ros"

    def test_a_private_profile_display_name_does_not(
        self, client, db, make_user, make_space
    ):
        creator = make_user(role="creator", name="Ada Leader")
        space = make_space(creator=creator)
        member = make_user(name="Rosalind Franklin")
        db.add(CreatorProfile(user_id=member.id, display_name="Ros",
                              is_public=False))
        _join(db, creator, space, role=SpaceRole.creator)
        _join(db, member, space)
        thread = MessageThread(id=_uid("mt"), space_id=space.id,
                               creator_id=creator.id, member_id=member.id)
        db.add(thread)
        db.commit()
        as_user(creator)

        body = client.get(
            f"/api/creator/spaces/{space.slug}/messages/{thread.id}"
        ).json()

        assert body["member_name"] == "Rosalind Franklin"

    def test_the_thread_payload_field_set(self, client, conversation):
        space, creator, _member, thread = conversation
        as_user(creator)

        body = client.get(
            f"/api/creator/spaces/{space.slug}/messages/{thread.id}"
        ).json()

        assert set(body) == {
            "thread_id", "space_id", "creator_id", "creator_name",
            "member_id", "member_name", "messages", "unread_count",
        }
        assert set(body["messages"][0]) == {
            "id", "sender_id", "sender_name", "body", "is_read", "created_at",
        }

    def test_the_inbox_row_field_set(self, client, conversation):
        space, creator, _member, _thread = conversation
        as_user(creator)

        row = client.get(f"/api/creator/spaces/{space.slug}/messages").json()[0]

        assert set(row) == {
            "thread_id", "other_user_id", "other_user_name",
            "last_message", "last_message_at", "unread_count",
        }
