"""Block and report for peer connections — Ways to Connect 5d.

Mutual consent at the start is not a sufficient long-term safety
mechanism: a connection persists, and private messaging comes with it.
These two controls are what make that acceptable.

The governing rule is that **block outranks mutual connection**. A
mutual hello says two people agreed to talk; a block says one of them
has withdrawn that, and withdrawal wins. Every test here is ultimately
about that precedence holding everywhere — Ways to Connect, thread
creation, and every send — rather than in one place and not another.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_verified_current_user
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.community_care import CommunityCareCase, CommunityCareReport
from app.models.connections import MemberHello
from app.models.member_blocks import MemberBlock
from app.models.peer_messages import PeerMessage, PeerThread
from app.models.platform import CreatorProfile
from app.peer_messages import service
from app.services import member_block_service as blocks

MSG = "/api/messages"
WTC = "/api/ways-to-connect"


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


def _named(db, user, name):
    db.add(CreatorProfile(user_id=user.id, display_name=name, is_public=True))
    db.flush()


@pytest.fixture
def connected(db, make_user):
    def _make(name_a="Alice", name_b="Bob"):
        a, b = make_user(), make_user()
        _named(db, a, name_a)
        _named(db, b, name_b)
        for frm, to in ((a, b), (b, a)):
            db.add(MemberHello(id=_uid("h"), from_user_id=frm.id, to_user_id=to.id))
        db.flush()
        return a, b
    return _make


def _thread(client, a, b):
    as_user(a)
    return client.post(f"{MSG}/open", json={"user_id": b.id}).json()["thread_id"]


def _send(client, tid, body="hello"):
    return client.post(f"{MSG}/{tid}/messages", json={"body": body})


# ---------------------------------------------------------------------------
# Baseline — without a block, everything works
# ---------------------------------------------------------------------------


class TestWithoutABlock:
    def test_connected_members_can_message(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        assert _send(client, tid).status_code == 201
        as_user(b)
        assert _send(client, tid, "and back").status_code == 201

    def test_the_thread_reports_that_sending_is_available(
        self, client, db, connected,
    ):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        detail = client.get(f"{MSG}/{tid}").json()
        assert detail["can_send"] is True
        assert detail["blocked_by_me"] is False


# ---------------------------------------------------------------------------
# Block outranks the connection
# ---------------------------------------------------------------------------


class TestBlockStopsMessaging:
    def test_the_blocker_cannot_send(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()

        assert _send(client, tid, "after blocking").status_code == 404
        assert db.query(PeerMessage).count() == 0

    def test_the_blocked_person_cannot_send(self, client, db, connected):
        """The consequence is mutual even though the act was one-sided."""
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()

        as_user(b)
        assert _send(client, tid, "hello?").status_code == 404
        assert db.query(PeerMessage).count() == 0

    def test_a_block_set_mid_conversation_stops_it(self, client, db, connected):
        """Checked on every send, not only at thread creation."""
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        assert _send(client, tid, "before").status_code == 201
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()
        assert _send(client, tid, "after").status_code == 404
        assert db.query(PeerMessage).count() == 1

    def test_the_service_refuses_regardless_of_direction(self, db, connected):
        a, b = connected()
        thread = service.get_or_create_thread(db, a.id, b.id)
        db.flush()
        blocks.block(db, b.id, a.id)      # b blocked a
        db.flush()

        for sender in (a.id, b.id):
            with pytest.raises(service.Blocked):
                service.send_message(db, thread, sender, "hi")

    def test_may_interact_is_the_single_rule(self, db, connected):
        a, b = connected()
        assert service.may_interact(db, a.id, b.id) is True
        blocks.block(db, a.id, b.id)
        db.flush()
        assert service.may_interact(db, a.id, b.id) is False
        # The connection itself is untouched — block outranks it.
        assert service.are_mutually_connected(db, a.id, b.id) is True


class TestBlockStopsNewThreads:
    def test_a_blocked_pair_cannot_open_a_new_conversation(
        self, client, db, connected,
    ):
        a, b = connected()
        blocks.block(db, a.id, b.id)
        db.flush()
        as_user(a)
        res = client.post(f"{MSG}/open", json={"user_id": b.id})
        assert res.status_code == 404
        assert db.query(PeerThread).count() == 0

    def test_an_existing_conversation_stays_readable(self, client, db, connected):
        """History is kept deliberately: it is the blocker's record of
        what happened, and a reviewer may need it."""
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        _send(client, tid, "evidence")
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()

        for viewer in (a, b):
            as_user(viewer)
            detail = client.get(f"{MSG}/{tid}").json()
            assert detail["can_send"] is False
            assert [m["body"] for m in detail["messages"]] == ["evidence"]

    def test_the_blocked_person_is_not_told_who_blocked_them(
        self, client, db, connected,
    ):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()

        as_user(b)
        detail = client.get(f"{MSG}/{tid}").json()
        assert detail["blocked_by_me"] is False, (
            "the person who was blocked must not be shown an unblock control"
        )
        assert detail["can_send"] is False

    def test_the_blocker_sees_their_own_block(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()
        assert client.get(f"{MSG}/{tid}").json()["blocked_by_me"] is True

    def test_nothing_is_deleted_by_a_block(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        _send(client, tid, "kept")
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()

        assert db.query(PeerMessage).count() == 1
        assert db.query(PeerThread).count() == 1
        assert db.query(MemberHello).count() == 2, "hellos survive a block"


# ---------------------------------------------------------------------------
# Ways to Connect
# ---------------------------------------------------------------------------


class TestBlockHidesFromWaysToConnect:
    @pytest.fixture
    def flag_on(self, monkeypatch):
        monkeypatch.setattr(settings, "ways_to_connect_enabled", True)

    def test_a_blocked_pair_cannot_say_hello(
        self, client, db, connected, flag_on,
    ):
        """Even with an existing mutual connection, and even by direct
        API — the canonical candidate set excludes them."""
        a, b = connected()
        blocks.block(db, a.id, b.id)
        db.flush()

        for viewer, target in ((a, b), (b, a)):
            as_user(viewer)
            assert client.post(f"{WTC}/{target.id}/hello").status_code == 404

    def test_the_filter_lives_in_the_canonical_service(
        self, db, make_user, make_space, make_event,
    ):
        """Not in the route, and not in the frontend: both the listing
        and the hello authorisation draw from ``for_user``.

        Needs a pair with genuinely shared signals. An earlier version
        used the hello-only fixture, for which Recognition returns
        nothing anyway — so the assertion passed whether or not the
        filter existed. Mutation testing caught that.
        """
        from datetime import timedelta

        from app.models.platform import (
            BookingStatus,
            EventBooking,
            SpaceMembership,
            SpaceMembershipStatus,
            SpaceRole,
        )
        from app.services.recognition_service import RecognitionService

        now = __import__("datetime").datetime.utcnow()
        a, b = make_user(), make_user()
        _named(db, a, "Alice")
        _named(db, b, "Bob")
        space = make_space(show_member_directory=True)
        for u in (a, b):
            db.add(SpaceMembership(
                id=_uid("sm"), user_id=u.id, space_id=space.id,
                role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            ))
        ev = make_event(
            space=space,
            starts_at=now - timedelta(days=10),
            ends_at=now - timedelta(days=10) + timedelta(hours=1),
            title="Shared",
        )
        ev.attendance_completed_at = now - timedelta(days=10)
        for u in (a, b):
            db.add(EventBooking(
                id=_uid("bk"), event_id=ev.id, user_id=u.id,
                status=BookingStatus.confirmed, attendance_status="attended",
            ))
        db.flush()

        # Without a block they recognise each other — otherwise the
        # negative below would prove nothing.
        assert b.id in {
            r.other_user_id for r in RecognitionService.for_user(db, a.id)
        }

        blocks.block(db, b.id, a.id)
        db.flush()

        for viewer, other in ((a, b), (b, a)):
            ids = {
                r.other_user_id
                for r in RecognitionService.for_user(db, viewer.id)
            }
            assert other.id not in ids, "a block removes the pair both ways"

    def test_recognition_excludes_the_pair_in_either_direction(
        self, db, connected,
    ):
        from app.services.member_block_service import blocked_user_ids

        a, b = connected()
        blocks.block(db, a.id, b.id)
        db.flush()
        assert blocked_user_ids(db, a.id) == {b.id}
        assert blocked_user_ids(db, b.id) == {a.id}


# ---------------------------------------------------------------------------
# Idempotency, asymmetry, unblock
# ---------------------------------------------------------------------------


class TestBlockBookkeeping:
    def test_blocking_twice_keeps_one_row(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/block")
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()
        assert db.query(MemberBlock).count() == 1

    def test_the_service_reports_whether_it_created_a_row(self, db, connected):
        a, b = connected()
        assert blocks.block(db, a.id, b.id) is True
        db.flush()
        assert blocks.block(db, a.id, b.id) is False

    def test_both_directions_can_exist_independently(self, db, connected):
        a, b = connected()
        blocks.block(db, a.id, b.id)
        blocks.block(db, b.id, a.id)
        db.flush()
        assert db.query(MemberBlock).count() == 2

    def test_a_self_block_is_impossible(self, db, connected):
        a, _ = connected()
        with pytest.raises(ValueError):
            blocks.block(db, a.id, a.id)

    def test_the_database_refuses_a_self_block(self, db, connected):
        from sqlalchemy.exc import IntegrityError

        a, _ = connected()
        db.add(MemberBlock(
            id=_uid("mb"), blocker_user_id=a.id, blocked_user_id=a.id,
        ))
        with pytest.raises(IntegrityError):
            db.flush()


class TestUnblock:
    def test_unblocking_restores_messaging(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()
        assert _send(client, tid, "nope").status_code == 404

        client.delete(f"{MSG}/{tid}/block")
        db.expire_all()
        assert _send(client, tid, "back on").status_code == 201

    def test_nobody_has_to_say_hello_again(self, client, db, connected):
        """The hello rows were never removed, so the connection is
        simply uncovered rather than rebuilt."""
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/block")
        client.delete(f"{MSG}/{tid}/block")
        db.expire_all()
        assert db.query(MemberHello).count() == 2
        assert service.may_interact(db, a.id, b.id) is True

    def test_a_remaining_opposite_block_keeps_messaging_closed(
        self, client, db, connected,
    ):
        """The case asymmetric state exists for: A clearing their own
        boundary must not override B's."""
        a, b = connected()
        tid = _thread(client, a, b)
        blocks.block(db, a.id, b.id)
        blocks.block(db, b.id, a.id)
        db.flush()

        as_user(a)
        client.delete(f"{MSG}/{tid}/block")
        db.expire_all()

        assert db.query(MemberBlock).count() == 1
        assert _send(client, tid, "still no").status_code == 404
        as_user(b)
        assert _send(client, tid, "also no").status_code == 404

    def test_unblock_only_clears_the_callers_own_row(self, db, connected):
        a, b = connected()
        blocks.block(db, b.id, a.id)
        db.flush()
        # a tries to clear b's block by unblocking b
        assert blocks.unblock(db, a.id, b.id) is False
        db.flush()
        assert db.query(MemberBlock).count() == 1
        assert blocks.is_blocked_between(db, a.id, b.id) is True

    def test_unblocking_when_nothing_is_blocked_is_not_an_error(
        self, client, db, connected,
    ):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        res = client.delete(f"{MSG}/{tid}/block")
        assert res.status_code == 200
        assert res.json()["blocked_by_me"] is False

    def test_has_blocked_is_directional(self, db, connected):
        a, b = connected()
        blocks.block(db, a.id, b.id)
        db.flush()
        assert blocks.has_blocked(db, a.id, b.id) is True
        assert blocks.has_blocked(db, b.id, a.id) is False


class TestBlockAuthorisation:
    def test_an_unrelated_member_cannot_block_through_a_thread(
        self, client, db, connected, make_user,
    ):
        a, b = connected()
        tid = _thread(client, a, b)
        outsider = make_user()
        _named(db, outsider, "Nosy")
        db.flush()
        as_user(outsider)
        assert client.post(f"{MSG}/{tid}/block").status_code == 404
        assert db.query(MemberBlock).count() == 0

    def test_unauthenticated_cannot_block(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_verified_current_user, None)
        assert client.post(f"{MSG}/{tid}/block").status_code in (401, 403)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestReport:
    def test_a_participant_can_report_the_other(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        _send(client, tid, "something upsetting")

        res = client.post(
            f"{MSG}/{tid}/report",
            json={"category": "harassment_or_bullying"},
        )
        assert res.status_code == 201, res.text
        assert res.json()["case_number"]

    def test_the_case_names_the_reported_member_and_no_collective(
        self, client, db, connected,
    ):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/report", json={"category": "unsafe_behaviour"})
        db.expire_all()

        case = db.query(CommunityCareCase).one()
        assert case.content_type == "member_behaviour"
        assert case.subject_member_user_id == b.id
        assert case.subject_space_id is None, "a conversation has no Collective"
        assert case.status == "new"

    def test_the_report_records_the_reporter(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/report", json={"category": "spam_or_scam"})
        db.expire_all()

        report = db.query(CommunityCareReport).one()
        assert report.reporter_user_id == a.id
        assert report.target_member_user_id == b.id
        assert report.reporter_kind == "member"
        assert report.content_type == "peer_conversation"

    def test_the_conversation_is_snapshotted_as_evidence(
        self, client, db, connected,
    ):
        """The live thread is not a safe source of truth for a review —
        either party may send more afterwards."""
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        _send(client, tid, "first")
        as_user(b)
        _send(client, tid, "second")
        as_user(a)
        client.post(f"{MSG}/{tid}/report", json={"category": "unsafe_behaviour"})
        db.expire_all()

        snap = db.query(CommunityCareCase).one().content_snapshot
        assert snap["kind"] == "peer_conversation"
        assert snap["peer_thread_id"] == tid
        assert [m["body"] for m in snap["messages"]] == ["first", "second"]

    def test_a_specific_message_can_be_referenced(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(b)
        mid = _send(client, tid, "the one").json()["id"]
        as_user(a)
        client.post(
            f"{MSG}/{tid}/report",
            json={"category": "harassment_or_bullying", "message_id": mid},
        )
        db.expire_all()
        assert db.query(CommunityCareCase).one().content_snapshot[
            "reported_message_id"
        ] == mid

    def test_a_message_from_another_conversation_cannot_be_attached(
        self, client, db, connected,
    ):
        a, b = connected()
        tid = _thread(client, a, b)
        c, d = connected("Cara", "Dev")
        other_tid = _thread(client, c, d)
        as_user(c)
        foreign = _send(client, other_tid, "not yours").json()["id"]

        as_user(a)
        res = client.post(
            f"{MSG}/{tid}/report",
            json={"category": "unsafe_behaviour", "message_id": foreign},
        )
        assert res.status_code == 404
        assert db.query(CommunityCareCase).count() == 0

    def test_an_unrelated_member_cannot_report_a_thread(
        self, client, db, connected, make_user,
    ):
        a, b = connected()
        tid = _thread(client, a, b)
        outsider = make_user()
        _named(db, outsider, "Nosy")
        db.flush()
        as_user(outsider)
        res = client.post(f"{MSG}/{tid}/report", json={"category": "spam_or_scam"})
        assert res.status_code == 404
        assert db.query(CommunityCareCase).count() == 0

    def test_an_unknown_category_is_refused(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        res = client.post(f"{MSG}/{tid}/report", json={"category": "nonsense"})
        assert res.status_code == 422

    def test_something_else_requires_an_explanation(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        assert client.post(
            f"{MSG}/{tid}/report", json={"category": "something_else"},
        ).status_code == 422
        assert client.post(
            f"{MSG}/{tid}/report",
            json={"category": "something_else", "reporter_note": "what happened"},
        ).status_code == 201

    def test_two_reports_about_the_same_member_share_one_case(
        self, client, db, connected, make_user,
    ):
        """Dedupe, exactly as the Collective report path does."""
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/report", json={"category": "spam_or_scam"})
        client.post(f"{MSG}/{tid}/report", json={"category": "unsafe_behaviour"})
        db.expire_all()

        assert db.query(CommunityCareCase).count() == 1
        assert db.query(CommunityCareReport).count() == 2
        assert db.query(CommunityCareCase).one().report_count == 2

    def test_reporting_does_not_block(self, client, db, connected):
        """The two are independent actions, offered together but never
        coupled."""
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/report", json={"category": "spam_or_scam"})
        db.expire_all()

        assert db.query(MemberBlock).count() == 0
        assert service.may_interact(db, a.id, b.id) is True

    def test_blocking_does_not_report(self, client, db, connected):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()
        assert db.query(CommunityCareCase).count() == 0

    def test_a_report_can_be_filed_while_blocked(self, client, db, connected):
        """Blocking first must not close the path to telling somebody."""
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        _send(client, tid, "context")
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()

        res = client.post(
            f"{MSG}/{tid}/report", json={"category": "harassment_or_bullying"},
        )
        assert res.status_code == 201


class TestReportPrivacy:
    def test_the_reported_person_is_not_notified(self, client, db, connected):
        from app.models.notification import Notification

        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/report", json={"category": "spam_or_scam"})
        db.expire_all()

        assert (
            db.query(Notification)
            .filter(Notification.user_id == b.id)
            .count()
        ) == 0

    def test_the_response_exposes_only_a_case_number(
        self, client, db, connected,
    ):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        body = client.post(
            f"{MSG}/{tid}/report", json={"category": "spam_or_scam"},
        ).json()
        assert set(body.keys()) == {"case_number"}

    def test_no_block_or_report_state_leaks_to_an_unrelated_member(
        self, client, db, connected, make_user,
    ):
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/block")
        outsider = make_user()
        _named(db, outsider, "Nosy")
        db.flush()

        as_user(outsider)
        assert client.get(f"{MSG}/{tid}").status_code == 404
        assert client.get(MSG).json() == []
