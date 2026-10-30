"""A conversation, all the way round: creator → member → creator → member.

The defect this file was written for
------------------------------------
A creator sent a Collective-wide message to three members. Two replied.
Your World showed the creator "2 unread messages"; Moonlit Circle →
Messages showed "No messages yet".

Both were right about their own query. The unread count matches either
side of a thread; ``member_list_threads`` matched ``member_id`` alone.
A creator's conversations sit in the ``creator_id`` column, so the
inbox returned nothing while the badge counted two. The replies were
never lost — they were unreachable.

The fix is one predicate, ``_i_am_a_participant``, and the tests that
matter are the ones that would let it over-reach: a participant sees
their own conversations and nobody else's, from either side.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.messages.routes as messages_routes
import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_verified_current_user
from app.core.database import get_db
from app.main import app
from app.models.messages import DirectMessage, MessageThread
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.message_counts import unread_message_counts

CREATOR_SEND = "/api/creator/spaces/{slug}/messages"
BROADCAST = "/api/creator/spaces/{slug}/messages/broadcast"
INBOX = "/api/spaces/{slug}/messages"
THREAD = "/api/spaces/{slug}/messages/{tid}"
REPLY = "/api/spaces/{slug}/messages/{tid}/reply"
READ = "/api/spaces/{slug}/messages/{tid}/read"


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


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
def notices(monkeypatch):
    """Every notification asked for, and nothing sent."""
    captured: list[dict] = []
    monkeypatch.setattr(
        messages_routes, "_notify_direct_message",
        lambda **kw: captured.append(kw),
    )
    return captured


@pytest.fixture
def circle(db, make_user, make_space):
    """A creator and three members, as in the production test."""
    creator = make_user(role="creator", name="Lindsey Hilliard")
    space = make_space(creator=creator)
    _join(db, creator, space, role=SpaceRole.creator)
    sophie = make_user(name="Sophie Bennett")
    tom = make_user(name="Tom Test")
    quiet = make_user(name="Quiet Member")
    for m in (sophie, tom, quiet):
        _join(db, m, space)
    db.commit()
    return space, creator, sophie, tom, quiet


# ---------------------------------------------------------------------------
# The reported scenario, end to end
# ---------------------------------------------------------------------------

class TestTheCreatorCanSeeTheReplies:
    def test_broadcast_then_two_replies_then_the_creator_reads_both(
        self, client, db, circle, notices,
    ):
        space, creator, sophie, tom, quiet = circle

        as_user(creator)
        assert client.post(
            BROADCAST.format(slug=space.slug), json={"body": "Hello everyone."},
        ).status_code == 201

        def thread_of(member):
            return db.query(MessageThread).filter(
                MessageThread.space_id == space.id,
                MessageThread.member_id == member.id,
            ).one()

        as_user(sophie)
        assert client.post(
            REPLY.format(slug=space.slug, tid=thread_of(sophie).id),
            json={"body": "I can see it"},
        ).status_code == 200

        as_user(tom)
        assert client.post(
            REPLY.format(slug=space.slug, tid=thread_of(tom).id),
            json={"body": "Got it, thanks"},
        ).status_code == 200

        # The creator's Collective inbox — this returned [] before.
        as_user(creator)
        res = client.get(INBOX.format(slug=space.slug))
        assert res.status_code == 200
        inbox = res.json()
        assert len(inbox) == 3, "the creator should see one thread per member"

        by_name = {t["other_user_name"]: t for t in inbox}
        assert by_name["Sophie Bennett"]["unread_count"] == 1
        assert by_name["Tom Test"]["unread_count"] == 1
        assert by_name["Quiet Member"]["unread_count"] == 0
        assert by_name["Sophie Bennett"]["last_message"] == "I can see it"

    def test_the_badge_and_the_inbox_agree(self, client, db, circle, notices):
        """The symptom: 2 unread, nothing to open."""
        space, creator, sophie, tom, _quiet = circle
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hello."})

        for member, text in ((sophie, "I can see it"), (tom, "Got it")):
            tid = db.query(MessageThread).filter(
                MessageThread.member_id == member.id).one().id
            as_user(member)
            client.post(REPLY.format(slug=space.slug, tid=tid), json={"body": text})

        counted = unread_message_counts(db, creator.id, [space.id]).get(space.id, 0)
        as_user(creator)
        inbox = client.get(INBOX.format(slug=space.slug)).json()
        from_inbox = sum(t["unread_count"] for t in inbox)

        assert counted == 2
        assert from_inbox == counted, "the badge and the inbox must count the same thing"

    def test_the_creator_can_open_and_answer_a_reply(self, client, db, circle, notices):
        """Creator → Member → Creator → Member, the whole way round."""
        space, creator, sophie, *_ = circle
        as_user(creator)
        client.post(CREATOR_SEND.format(slug=space.slug),
                    json={"member_id": sophie.id, "body": "Hello Sophie."})
        tid = db.query(MessageThread).filter(
            MessageThread.member_id == sophie.id).one().id

        as_user(sophie)
        client.post(REPLY.format(slug=space.slug, tid=tid), json={"body": "I can see it"})

        # The creator opens it from the Collective's Messages tab.
        as_user(creator)
        detail = client.get(THREAD.format(slug=space.slug, tid=tid))
        assert detail.status_code == 200
        # Compared as a set, not a sequence. The suite wraps each test
        # in one transaction, so Postgres ``now()`` — the default
        # behind ``created_at`` — returns the same instant for every
        # message, and the relationship's ``order_by`` has nothing to
        # separate them. Production commits each message in its own
        # transaction, where the timestamps differ and the order holds.
        # The same tie is why activities carry a sequence number
        # (migration 156). What matters here is that the creator can
        # see both halves of the conversation at all.
        assert {m["body"] for m in detail.json()["messages"]} == {
            "Hello Sophie.", "I can see it",
        }

        # …and answers from the same place.
        answered = client.post(REPLY.format(slug=space.slug, tid=tid),
                               json={"body": "Glad it arrived."})
        assert answered.status_code == 200

        as_user(sophie)
        back = client.get(THREAD.format(slug=space.slug, tid=tid)).json()
        assert {m["body"] for m in back["messages"]} == {
            "Hello Sophie.", "I can see it", "Glad it arrived.",
        }
        # Two, not one: replying is not reading. Sophie answered the
        # creator's first message without opening the thread, so it is
        # still unread for her alongside the new answer. The inbox has
        # always counted it this way; ``POST .../read`` is what clears
        # it, and it is exercised in its own test below.
        assert back["unread_count"] == 2

    def test_reading_clears_the_count(self, client, db, circle, notices):
        space, creator, sophie, *_ = circle
        as_user(creator)
        client.post(CREATOR_SEND.format(slug=space.slug),
                    json={"member_id": sophie.id, "body": "Hello."})
        tid = db.query(MessageThread).filter(
            MessageThread.member_id == sophie.id).one().id
        as_user(sophie)
        client.post(REPLY.format(slug=space.slug, tid=tid), json={"body": "Hi back"})

        as_user(creator)
        assert unread_message_counts(db, creator.id, [space.id]) == {space.id: 1}
        assert client.post(READ.format(slug=space.slug, tid=tid)).status_code == 204
        assert unread_message_counts(db, creator.id, [space.id]) == {}


# ---------------------------------------------------------------------------
# Privacy — what the widened query must not do
# ---------------------------------------------------------------------------

class TestNobodySeesSomebodyElsesConversation:
    def test_a_member_sees_only_their_own_thread(self, client, db, circle, notices):
        space, creator, sophie, tom, _q = circle
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hello."})

        as_user(sophie)
        inbox = client.get(INBOX.format(slug=space.slug)).json()
        assert len(inbox) == 1
        assert inbox[0]["other_user_name"] == "Lindsey Hilliard"
        assert tom.id not in client.get(INBOX.format(slug=space.slug)).text

    def test_a_member_cannot_open_another_members_thread(self, client, db, circle, notices):
        space, creator, sophie, tom, _q = circle
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hello."})
        toms = db.query(MessageThread).filter(MessageThread.member_id == tom.id).one()

        as_user(sophie)
        assert client.get(
            THREAD.format(slug=space.slug, tid=toms.id)).status_code == 404
        assert client.post(
            REPLY.format(slug=space.slug, tid=toms.id),
            json={"body": "sneaking in"}).status_code == 404

    def test_a_creator_of_another_collective_sees_nothing(
        self, client, db, circle, make_user, make_space, notices,
    ):
        space, creator, sophie, *_ = circle
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hello."})
        tid = db.query(MessageThread).filter(
            MessageThread.member_id == sophie.id).one().id

        stranger = make_user(role="creator", name="Other Creator")
        as_user(stranger)
        # Not a member here, so the gate refuses before any thread query.
        assert client.get(INBOX.format(slug=space.slug)).status_code == 403
        assert client.get(THREAD.format(slug=space.slug, tid=tid)).status_code == 403

    def test_a_member_of_the_collective_who_is_not_in_the_thread_is_refused(
        self, client, db, circle, notices,
    ):
        space, creator, sophie, _tom, quiet = circle
        as_user(creator)
        client.post(CREATOR_SEND.format(slug=space.slug),
                    json={"member_id": sophie.id, "body": "Hello Sophie."})
        tid = db.query(MessageThread).filter(
            MessageThread.member_id == sophie.id).one().id

        as_user(quiet)
        assert client.get(THREAD.format(slug=space.slug, tid=tid)).status_code == 404


# ---------------------------------------------------------------------------
# A creator with more than one Collective
# ---------------------------------------------------------------------------

class TestTwoCollectivesStaySeparate:
    def test_each_inbox_shows_only_its_own_collective(
        self, client, db, circle, make_user, make_space, notices,
    ):
        space_a, creator, sophie, *_ = circle
        space_b = make_space(creator=creator)
        _join(db, creator, space_b, role=SpaceRole.creator)
        beth = make_user(name="Beth Second")
        _join(db, beth, space_b)
        db.commit()

        as_user(creator)
        client.post(CREATOR_SEND.format(slug=space_a.slug),
                    json={"member_id": sophie.id, "body": "A."})
        client.post(CREATOR_SEND.format(slug=space_b.slug),
                    json={"member_id": beth.id, "body": "B."})

        a_inbox = client.get(INBOX.format(slug=space_a.slug)).json()
        b_inbox = client.get(INBOX.format(slug=space_b.slug)).json()
        assert [t["other_user_name"] for t in a_inbox] == ["Sophie Bennett"]
        assert [t["other_user_name"] for t in b_inbox] == ["Beth Second"]

    def test_unread_counts_are_reported_per_collective(
        self, client, db, circle, make_user, make_space, notices,
    ):
        space_a, creator, sophie, tom, _q = circle
        space_b = make_space(creator=creator)
        _join(db, creator, space_b, role=SpaceRole.creator)
        beth = make_user(name="Beth Second")
        _join(db, beth, space_b)
        db.commit()

        as_user(creator)
        client.post(BROADCAST.format(slug=space_a.slug), json={"body": "A."})
        client.post(CREATOR_SEND.format(slug=space_b.slug),
                    json={"member_id": beth.id, "body": "B."})

        for member, space in ((sophie, space_a), (tom, space_a), (beth, space_b)):
            tid = db.query(MessageThread).filter(
                MessageThread.space_id == space.id,
                MessageThread.member_id == member.id).one().id
            as_user(member)
            client.post(REPLY.format(slug=space.slug, tid=tid), json={"body": "ok"})

        assert unread_message_counts(db, creator.id, [space_a.id, space_b.id]) == {
            space_a.id: 2, space_b.id: 1,
        }


# ---------------------------------------------------------------------------
# What the reply tells the other person
# ---------------------------------------------------------------------------

class TestTheReplyNotification:
    def test_it_reaches_the_creator_with_the_collective_and_a_link(
        self, client, db, circle, notices,
    ):
        space, creator, sophie, *_ = circle
        as_user(creator)
        client.post(CREATOR_SEND.format(slug=space.slug),
                    json={"member_id": sophie.id, "body": "Hello."})
        tid = db.query(MessageThread).filter(
            MessageThread.member_id == sophie.id).one().id
        notices.clear()

        as_user(sophie)
        client.post(REPLY.format(slug=space.slug, tid=tid), json={"body": "I can see it"})

        assert len(notices) == 1
        n = notices[0]
        assert n["recipient_id"] == creator.id
        assert n["sender_name"] == "Sophie Bennett"
        assert n["space_name"] == space.name
        assert n["thread_url"] == f"/spaces/{space.slug}/messages/{tid}"
        assert n["preview"] == "I can see it"

    def test_the_link_opens_for_the_creator(self, client, db, circle, notices):
        """The URL in the email must resolve for whoever receives it."""
        space, creator, sophie, *_ = circle
        as_user(creator)
        client.post(CREATOR_SEND.format(slug=space.slug),
                    json={"member_id": sophie.id, "body": "Hello."})
        tid = db.query(MessageThread).filter(
            MessageThread.member_id == sophie.id).one().id
        as_user(sophie)
        client.post(REPLY.format(slug=space.slug, tid=tid), json={"body": "Hi"})
        notices.clear()
        as_user(sophie)
        client.post(REPLY.format(slug=space.slug, tid=tid), json={"body": "Again"})

        path = notices[-1]["thread_url"]          # /spaces/{slug}/messages/{tid}
        as_user(creator)
        assert client.get(f"/api{path}").status_code == 200

    def test_a_creator_replying_does_not_notify_themselves(
        self, client, db, circle, notices,
    ):
        space, creator, sophie, *_ = circle
        as_user(creator)
        client.post(CREATOR_SEND.format(slug=space.slug),
                    json={"member_id": sophie.id, "body": "Hello."})
        tid = db.query(MessageThread).filter(
            MessageThread.member_id == sophie.id).one().id
        notices.clear()

        # The creator answers through the Collective tab, not Studio.
        as_user(creator)
        client.post(REPLY.format(slug=space.slug, tid=tid), json={"body": "Answer."})

        assert len(notices) == 1
        assert notices[0]["recipient_id"] == sophie.id
        assert notices[0]["sender_name"] == "Lindsey Hilliard"
