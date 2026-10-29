"""Collective-wide creator messages.

A Collective-wide message is not an announcement and not a new kind of
object: it is N ordinary direct messages, each in the member's own
one-to-one thread with the creator. Once sent it is indistinguishable
from N messages typed by hand, which is what gives it the properties
worth testing — a member can reply privately, and no member can learn
who else received it, because there is nothing shared to look at.

The tests that matter here are the ones that would let something
escape: eligibility (who is in the set), authorisation (who may send),
isolation (what one recipient can see of another), and the loop's
behaviour when one member fails.

No email leaves the process: ``_notify_direct_message`` is replaced in
every test that exercises delivery, and asserted on instead.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
import app.messages.routes as messages_routes
from app.auth.dependencies import get_current_user, get_verified_current_user
from app.core.database import get_db
from app.main import app
from app.models.messages import DirectMessage, MessageThread
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)

BROADCAST = "/api/creator/spaces/{slug}/messages/broadcast"
RECIPIENTS = "/api/creator/spaces/{slug}/messages/broadcast/recipients"


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


def _join(db, user, space, role=SpaceRole.learner,
          status=SpaceMembershipStatus.active):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=role, status=status,
    ))
    db.flush()


@pytest.fixture
def notices(monkeypatch):
    """Capture every notification the send asks for, and send nothing."""
    captured: list[dict] = []

    def _record(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(messages_routes, "_notify_direct_message", _record)
    return captured


@pytest.fixture
def collective(db, make_user, make_space):
    """A creator and three active members, plus people who must not be
    in the set: a member of another Collective, and a lapsed member."""
    creator = make_user(role="creator", name="Ada Leader")
    space = make_space(creator=creator)
    _join(db, creator, space, role=SpaceRole.creator)

    members = [make_user(name=f"Member {i}") for i in range(3)]
    for m in members:
        _join(db, m, space)

    lapsed = make_user(name="Gone Away")
    _join(db, lapsed, space, status=SpaceMembershipStatus.removed)

    other_space = make_space(creator=make_user(role="creator"))
    outsider = make_user(name="Else Where")
    _join(db, outsider, other_space)

    db.commit()
    return space, creator, members, lapsed, outsider


# ---------------------------------------------------------------------------
# Who receives it
# ---------------------------------------------------------------------------

class TestWhoIsInTheSet:
    def test_every_active_member_gets_their_own_thread(self, client, db, collective, notices):
        space, creator, members, _lapsed, _outsider = collective
        as_user(creator)

        res = client.post(BROADCAST.format(slug=space.slug), json={"body": "Hello everyone."})
        assert res.status_code == 201
        assert res.json() == {
            "recipients": 3, "sent": 3, "failed": 0, "failures": [],
        }

        threads = db.query(MessageThread).filter(
            MessageThread.space_id == space.id,
        ).all()
        assert {t.member_id for t in threads} == {m.id for m in members}
        for t in threads:
            bodies = [m.body for m in db.query(DirectMessage).filter(
                DirectMessage.thread_id == t.id).all()]
            assert bodies == ["Hello everyone."]

    def test_the_sender_is_excluded(self, client, db, collective, notices):
        space, creator, _members, _lapsed, _outsider = collective
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hi."})
        assert db.query(MessageThread).filter(
            MessageThread.member_id == creator.id).count() == 0

    def test_a_lapsed_member_is_excluded(self, client, db, collective, notices):
        space, creator, _members, lapsed, _outsider = collective
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hi."})
        assert db.query(MessageThread).filter(
            MessageThread.member_id == lapsed.id).count() == 0

    def test_a_member_of_another_collective_is_excluded(self, client, db, collective, notices):
        space, creator, _members, _lapsed, outsider = collective
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hi."})
        assert db.query(MessageThread).filter(
            MessageThread.member_id == outsider.id).count() == 0

    def test_the_count_endpoint_agrees_with_what_is_sent(self, client, collective, notices):
        space, creator, _members, _lapsed, _outsider = collective
        as_user(creator)

        preview = client.get(RECIPIENTS.format(slug=space.slug))
        assert preview.status_code == 200
        promised = preview.json()["count"]

        res = client.post(BROADCAST.format(slug=space.slug), json={"body": "Hi."})
        assert promised == res.json()["recipients"] == res.json()["sent"] == 3

    def test_a_collective_with_nobody_else_refuses(self, client, db, make_user, make_space, notices):
        lone = make_user(role="creator")
        space = make_space(creator=lone)
        _join(db, lone, space, role=SpaceRole.creator)
        db.commit()
        as_user(lone)

        res = client.post(BROADCAST.format(slug=space.slug), json={"body": "Anyone?"})
        assert res.status_code == 422
        assert "no other active members" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Threads: reused, never duplicated
# ---------------------------------------------------------------------------

class TestItReusesTheConversationYouAlreadyHave:
    def test_an_existing_thread_is_reused(self, client, db, collective, notices):
        space, creator, members, _lapsed, _outsider = collective
        existing = MessageThread(
            id=_uid("mt"), space_id=space.id,
            creator_id=creator.id, member_id=members[0].id,
        )
        db.add(existing)
        db.add(DirectMessage(id=_uid("dm"), thread_id=existing.id,
                             sender_id=creator.id, body="Earlier note."))
        db.commit()

        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hello everyone."})

        threads = db.query(MessageThread).filter(
            MessageThread.space_id == space.id,
            MessageThread.member_id == members[0].id,
        ).all()
        assert len(threads) == 1 and threads[0].id == existing.id
        bodies = [m.body for m in db.query(DirectMessage).filter(
            DirectMessage.thread_id == existing.id
        ).order_by(DirectMessage.created_at).all()]
        assert bodies == ["Earlier note.", "Hello everyone."]

    def test_sending_twice_adds_two_messages_not_two_threads(self, client, db, collective, notices):
        space, creator, _members, _lapsed, _outsider = collective
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "First."})
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Second."})

        assert db.query(MessageThread).filter(MessageThread.space_id == space.id).count() == 3
        assert db.query(DirectMessage).count() == 6


# ---------------------------------------------------------------------------
# Privacy — the property the whole design rests on
# ---------------------------------------------------------------------------

class TestRecipientsCannotSeeEachOther:
    def test_a_member_sees_only_their_own_thread(self, client, db, collective, notices):
        space, creator, members, _lapsed, _outsider = collective
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hello everyone."})

        as_user(members[0])
        res = client.get(f"/api/spaces/{space.slug}/messages")
        assert res.status_code == 200
        threads = res.json()
        assert len(threads) == 1

        other_ids = {m.id for m in members[1:]}
        blob = res.text
        for other in other_ids:
            assert other not in blob

    def test_a_member_cannot_open_another_members_thread(self, client, db, collective, notices):
        space, creator, members, _lapsed, _outsider = collective
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hello everyone."})

        theirs = db.query(MessageThread).filter(
            MessageThread.member_id == members[1].id).one()
        as_user(members[0])
        assert client.get(
            f"/api/spaces/{space.slug}/messages/{theirs.id}"
        ).status_code == 404

    def test_the_response_names_no_recipient_on_success(self, client, collective, notices):
        space, creator, members, _lapsed, _outsider = collective
        as_user(creator)
        res = client.post(BROADCAST.format(slug=space.slug), json={"body": "Hi."})
        blob = res.text
        for m in members:
            assert m.id not in blob

    def test_a_member_can_reply_privately(self, client, db, collective, notices):
        space, creator, members, _lapsed, _outsider = collective
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hello everyone."})

        thread = db.query(MessageThread).filter(
            MessageThread.member_id == members[0].id).one()
        as_user(members[0])
        res = client.post(
            f"/api/spaces/{space.slug}/messages/{thread.id}/reply",
            json={"body": "Just to you."},
        )
        assert res.status_code in (200, 201)

        as_user(members[1])
        assert client.get(
            f"/api/spaces/{space.slug}/messages/{thread.id}"
        ).status_code == 404


# ---------------------------------------------------------------------------
# Authorisation — the same gate the individual send uses
# ---------------------------------------------------------------------------

class TestOnlyPeopleWhoManageTheCollective:
    def test_an_ordinary_member_cannot_broadcast(self, client, collective, notices):
        space, _creator, members, _lapsed, _outsider = collective
        as_user(members[0])
        assert client.post(
            BROADCAST.format(slug=space.slug), json={"body": "Hi."}
        ).status_code == 403

    def test_a_moderator_can(self, client, db, collective, make_user, notices):
        space, _creator, _members, _lapsed, _outsider = collective
        mod = make_user(name="Mod Erator")
        _join(db, mod, space, role=SpaceRole.moderator)
        db.commit()
        as_user(mod)
        res = client.post(BROADCAST.format(slug=space.slug), json={"body": "Hi."})
        assert res.status_code == 201

    def test_a_creator_of_a_different_collective_cannot(self, client, collective, make_user, notices):
        space, _creator, _members, _lapsed, _outsider = collective
        stranger = make_user(role="creator", name="Other Creator")
        as_user(stranger)
        assert client.post(
            BROADCAST.format(slug=space.slug), json={"body": "Hi."}
        ).status_code == 403

    def test_a_platform_admin_without_membership_cannot(self, client, collective, make_user, notices):
        # SEC-005-E: DM authority is not inherited from a platform role.
        space, _creator, _members, _lapsed, _outsider = collective
        admin = make_user(role="admin", name="Platform Admin")
        as_user(admin)
        assert client.post(
            BROADCAST.format(slug=space.slug), json={"body": "Hi."}
        ).status_code == 403

    def test_the_count_endpoint_is_gated_too(self, client, collective, notices):
        space, _creator, members, _lapsed, _outsider = collective
        as_user(members[0])
        assert client.get(RECIPIENTS.format(slug=space.slug)).status_code == 403

    def test_an_empty_body_is_refused(self, client, collective, notices):
        space, creator, _members, _lapsed, _outsider = collective
        as_user(creator)
        assert client.post(
            BROADCAST.format(slug=space.slug), json={"body": "   "}
        ).status_code == 422


# ---------------------------------------------------------------------------
# Notifications — identical to an individual send
# ---------------------------------------------------------------------------

class TestEveryoneIsTold:
    def test_one_notification_per_member_linking_to_their_own_thread(
        self, client, db, collective, notices,
    ):
        space, creator, members, _lapsed, _outsider = collective
        as_user(creator)
        client.post(BROADCAST.format(slug=space.slug), json={"body": "Hello everyone."})

        assert len(notices) == 3
        assert {n["recipient_id"] for n in notices} == {m.id for m in members}

        for n in notices:
            thread = db.query(MessageThread).filter(
                MessageThread.member_id == n["recipient_id"]).one()
            assert n["thread_url"] == f"/spaces/{space.slug}/messages/{thread.id}"
            assert n["space_id"] == space.id
            assert n["preview"] == "Hello everyone."

    def test_it_uses_the_same_notification_path_as_an_individual_send(
        self, client, db, collective, notices,
    ):
        """One send to one member, then a broadcast: same shape."""
        space, creator, members, _lapsed, _outsider = collective
        as_user(creator)
        client.post(
            f"/api/creator/spaces/{space.slug}/messages",
            json={"member_id": members[0].id, "body": "Just you."},
        )
        individual = dict(notices[-1])
        notices.clear()

        client.post(BROADCAST.format(slug=space.slug), json={"body": "Everyone."})
        assert set(notices[0]) == set(individual)


# ---------------------------------------------------------------------------
# When one member fails
# ---------------------------------------------------------------------------

class TestAPartialFailure:
    def test_the_others_still_receive_it_and_nobody_is_sent_twice(
        self, client, db, collective, monkeypatch, notices,
    ):
        space, creator, members, _lapsed, _outsider = collective
        doomed = members[1].id
        real = messages_routes._deliver_to_member

        def _flaky(db_, *, member_id, **kwargs):
            if member_id == doomed:
                raise RuntimeError("delivery exploded")
            return real(db_, member_id=member_id, **kwargs)

        monkeypatch.setattr(messages_routes, "_deliver_to_member", _flaky)

        as_user(creator)
        res = client.post(BROADCAST.format(slug=space.slug), json={"body": "Hello."})
        assert res.status_code == 201
        payload = res.json()
        assert payload["recipients"] == 3
        assert payload["sent"] == 2
        assert payload["failed"] == 1
        assert payload["failures"] == [
            {"member_id": doomed, "reason": "RuntimeError"},
        ]

        # The two that worked have exactly one message each; the one
        # that failed has none. No duplicates anywhere.
        for m in members:
            threads = db.query(MessageThread).filter(
                MessageThread.member_id == m.id).all()
            count = sum(
                db.query(DirectMessage).filter(
                    DirectMessage.thread_id == t.id).count()
                for t in threads
            )
            assert count == (0 if m.id == doomed else 1)
