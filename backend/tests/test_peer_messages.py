"""Member-to-member conversations — Ways to Connect 5c.

Peer messaging exists only because two people both said hello. The
authorisation anchor is therefore the persisted mutual hello, not
current Ways to Connect eligibility: eligibility governs discovery and
the first greeting, and recomputing it here would close a conversation
because a Gathering passed. That distinction is the thing most worth
pinning, so it gets its own class below.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.connections import MemberHello
from app.models.peer_messages import PeerMessage, PeerThread, canonical_pair
from app.models.platform import CreatorProfile
from app.peer_messages import service

URL = "/api/messages"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _named(db, user, name):
    db.add(CreatorProfile(user_id=user.id, display_name=name, is_public=True))
    db.flush()


def _hello(db, frm, to):
    db.add(MemberHello(id=_uid("h"), from_user_id=frm.id, to_user_id=to.id))
    db.flush()


@pytest.fixture
def connected(db, make_user):
    """Two named members with both hello rows — a mutual connection."""
    def _make(name_a="Alice", name_b="Bob"):
        a, b = make_user(), make_user()
        _named(db, a, name_a)
        _named(db, b, name_b)
        _hello(db, a, b)
        _hello(db, b, a)
        return a, b
    return _make


@pytest.fixture
def one_sided(db, make_user):
    def _make():
        a, b = make_user(), make_user()
        _named(db, a, "Alice")
        _named(db, b, "Bob")
        _hello(db, a, b)      # only one direction
        return a, b
    return _make


def _open(client, other_id):
    return client.post(f"{URL}/open", json={"user_id": other_id})


def _send(client, thread_id, body):
    return client.post(f"{URL}/{thread_id}/messages", json={"body": body})


# ---------------------------------------------------------------------------
# Authorisation — the mutual connection is the anchor
# ---------------------------------------------------------------------------


class TestMutualRequired:
    def test_a_connected_pair_can_open_a_conversation(
        self, client, db, connected,
    ):
        a, b = connected()
        as_user(a)
        res = _open(client, b.id)
        assert res.status_code == 200, res.text
        assert res.json()["other"]["id"] == b.id
        assert res.json()["messages"] == []

    def test_no_hellos_cannot_open_a_conversation(
        self, client, db, make_user,
    ):
        a, b = make_user(), make_user()
        _named(db, a, "Alice"); _named(db, b, "Bob")
        db.flush()
        as_user(a)
        assert _open(client, b.id).status_code == 404
        assert db.query(PeerThread).count() == 0

    def test_an_outgoing_only_hello_cannot_open_a_conversation(
        self, client, db, one_sided,
    ):
        a, b = one_sided()
        as_user(a)
        assert _open(client, b.id).status_code == 404
        assert db.query(PeerThread).count() == 0

    def test_an_incoming_only_hello_cannot_open_a_conversation(
        self, client, db, one_sided,
    ):
        """The recipient of a one-sided hello has no conversation either
        — saying hello back is what opens it."""
        a, b = one_sided()
        as_user(b)
        assert _open(client, a.id).status_code == 404
        assert db.query(PeerThread).count() == 0

    def test_an_arbitrary_member_id_cannot_open_a_conversation(
        self, client, db, connected, make_user,
    ):
        a, _ = connected()
        stranger = make_user()
        _named(db, stranger, "Stranger")
        db.flush()
        as_user(a)
        assert _open(client, stranger.id).status_code == 404

    def test_a_nonexistent_member_id_is_refused_identically(
        self, client, db, connected,
    ):
        """Same status, so this cannot be used to discover who exists."""
        a, _ = connected()
        as_user(a)
        assert _open(client, "u_nope").status_code == 404

    def test_a_self_conversation_is_impossible(self, client, db, connected):
        a, _ = connected()
        as_user(a)
        assert _open(client, a.id).status_code == 404
        assert db.query(PeerThread).count() == 0

    def test_the_service_refuses_a_self_conversation(self, db, connected):
        a, _ = connected()
        with pytest.raises(service.NotConnected):
            service.get_or_create_thread(db, a.id, a.id)

    def test_unauthenticated_cannot_reach_any_route(self, client, db, connected):
        a, b = connected()
        app.dependency_overrides.pop(get_current_user, None)
        assert client.get(URL).status_code in (401, 403)
        assert _open(client, b.id).status_code in (401, 403)


class TestConnectionPersistsNotEligibility:
    def test_a_conversation_survives_the_evidence_that_introduced_it(
        self, client, db, connected,
    ):
        """The product rule: eligibility governs discovery, not an
        existing connection. These two never had shared signals in this
        test at all — only the mutual hello — which is precisely the
        state a pair ends up in once a Gathering passes."""
        a, b = connected()
        as_user(a)
        thread_id = _open(client, b.id).json()["thread_id"]
        assert _send(client, thread_id, "Still here").status_code == 201

        as_user(b)
        assert client.get(f"{URL}/{thread_id}").status_code == 200

    def test_messaging_does_not_consult_ways_to_connect_eligibility(self):
        """Source contract: if the service ever imported the selection
        module, a lapsed Gathering could close a conversation."""
        src = (
            __import__("pathlib").Path("app/peer_messages/service.py").read_text()
        )
        code = __import__("re").sub(r'""".*?"""', "", src, flags=16 | 8)
        assert "ways_to_connect.selection" not in code
        assert "is_eligible_pair" not in code
        assert "RecognitionService" not in code


# ---------------------------------------------------------------------------
# One thread per pair
# ---------------------------------------------------------------------------


class TestThreadUniqueness:
    def test_opening_twice_returns_the_same_thread(self, client, db, connected):
        a, b = connected()
        as_user(a)
        first = _open(client, b.id).json()["thread_id"]
        second = _open(client, b.id).json()["thread_id"]
        assert first == second
        assert db.query(PeerThread).count() == 1

    def test_either_participant_opens_the_same_thread(self, client, db, connected):
        a, b = connected()
        as_user(a)
        from_a = _open(client, b.id).json()["thread_id"]
        as_user(b)
        from_b = _open(client, a.id).json()["thread_id"]
        assert from_a == from_b
        assert db.query(PeerThread).count() == 1

    def test_participant_order_cannot_duplicate_a_thread(self, db, connected):
        """A+B and B+A canonicalise to the same row."""
        a, b = connected()
        t1 = service.get_or_create_thread(db, a.id, b.id)
        t2 = service.get_or_create_thread(db, b.id, a.id)
        db.flush()
        assert t1.id == t2.id
        assert db.query(PeerThread).count() == 1

    def test_the_pair_is_stored_canonically(self, db, connected):
        a, b = connected()
        thread = service.get_or_create_thread(db, b.id, a.id)
        db.flush()
        low, high = canonical_pair(a.id, b.id)
        assert thread.participant_a_user_id == low
        assert thread.participant_b_user_id == high
        assert thread.participant_a_user_id < thread.participant_b_user_id

    def test_a_non_canonical_row_is_rejected_by_the_database(self, db, connected):
        """The ordering is an invariant of the row, not a convention."""
        from sqlalchemy.exc import IntegrityError

        a, b = connected()
        low, high = canonical_pair(a.id, b.id)
        db.add(PeerThread(
            id=_uid("pt"),
            participant_a_user_id=high,   # wrong way round
            participant_b_user_id=low,
        ))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_a_duplicate_pair_is_rejected_by_the_database(self, db, connected):
        from sqlalchemy.exc import IntegrityError

        a, b = connected()
        low, high = canonical_pair(a.id, b.id)
        for _ in range(2):
            db.add(PeerThread(
                id=_uid("pt"),
                participant_a_user_id=low,
                participant_b_user_id=high,
            ))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_simultaneous_opens_yield_one_thread(self, db, connected):
        """Neither caller reads before writing, so the conflict-tolerant
        insert is what makes this safe."""
        a, b = connected()
        t1 = service.get_or_create_thread(db, a.id, b.id)
        t2 = service.get_or_create_thread(db, b.id, a.id)
        t3 = service.get_or_create_thread(db, a.id, b.id)
        db.flush()
        assert t1.id == t2.id == t3.id
        assert db.query(PeerThread).count() == 1


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class TestMessages:
    @staticmethod
    def _thread(client, a, b):
        as_user(a)
        return _open(client, b.id).json()["thread_id"]

    def test_each_participant_can_send_and_the_other_sees_it(
        self, client, db, connected,
    ):
        a, b = connected()
        tid = self._thread(client, a, b)

        as_user(a)
        assert _send(client, tid, "Hello there").status_code == 201
        as_user(b)
        assert _send(client, tid, "Hello back").status_code == 201

        as_user(a)
        bodies = [m["body"] for m in client.get(f"{URL}/{tid}").json()["messages"]]
        assert bodies == ["Hello there", "Hello back"], "oldest first"

    def test_the_sender_comes_from_the_session_not_the_body(
        self, client, db, connected,
    ):
        """There is no sender field to spoof; this asserts the shape."""
        a, b = connected()
        tid = self._thread(client, a, b)
        as_user(a)
        res = client.post(
            f"{URL}/{tid}/messages",
            json={"body": "mine", "sender_user_id": b.id},
        )
        assert res.status_code == 201
        assert res.json()["sender_user_id"] == a.id

    def test_an_empty_message_is_rejected(self, client, db, connected):
        a, b = connected()
        tid = self._thread(client, a, b)
        as_user(a)
        assert _send(client, tid, "   ").status_code == 422
        assert db.query(PeerMessage).count() == 0

    def test_a_markup_only_message_is_rejected(self, client, db, connected):
        """Tags are stripped, so ``<b></b>`` is empty rather than a
        message containing markup."""
        a, b = connected()
        tid = self._thread(client, a, b)
        as_user(a)
        assert _send(client, tid, "<b></b>").status_code == 422

    def test_html_is_stripped_from_a_stored_message(self, client, db, connected):
        a, b = connected()
        tid = self._thread(client, a, b)
        as_user(a)
        res = _send(client, tid, "<script>alert(1)</script>hi <b>there</b>")
        assert res.status_code == 201
        assert res.json()["body"] == "alert(1)hi there"
        assert "<" not in res.json()["body"]

    def test_an_over_long_message_is_rejected(self, client, db, connected):
        a, b = connected()
        tid = self._thread(client, a, b)
        as_user(a)
        res = _send(client, tid, "x" * (service.MAX_BODY_CHARS + 1))
        assert res.status_code == 422
        assert db.query(PeerMessage).count() == 0

    def test_a_message_at_the_limit_is_accepted(self, client, db, connected):
        a, b = connected()
        tid = self._thread(client, a, b)
        as_user(a)
        assert _send(client, tid, "x" * service.MAX_BODY_CHARS).status_code == 201

    def test_surrounding_whitespace_is_trimmed(self, client, db, connected):
        a, b = connected()
        tid = self._thread(client, a, b)
        as_user(a)
        assert _send(client, tid, "  padded  ").json()["body"] == "padded"

    def test_the_thread_tracks_its_last_message_time(
        self, client, db, connected,
    ):
        a, b = connected()
        tid = self._thread(client, a, b)
        thread = db.query(PeerThread).filter(PeerThread.id == tid).one()
        assert thread.last_message_at is None, "lazy: opening sends nothing"

        as_user(a)
        _send(client, tid, "first")
        db.expire_all()
        thread = db.query(PeerThread).filter(PeerThread.id == tid).one()
        assert thread.last_message_at is not None


# ---------------------------------------------------------------------------
# Access control on an existing thread
# ---------------------------------------------------------------------------


class TestThreadAccess:
    def test_an_unrelated_member_cannot_read_a_thread(
        self, client, db, connected, make_user,
    ):
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "private")

        outsider = make_user()
        _named(db, outsider, "Nosy")
        db.flush()
        as_user(outsider)
        assert client.get(f"{URL}/{tid}").status_code == 404

    def test_an_unrelated_member_cannot_post_to_a_thread(
        self, client, db, connected, make_user,
    ):
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]

        outsider = make_user()
        _named(db, outsider, "Nosy")
        db.flush()
        as_user(outsider)
        assert _send(client, tid, "let me in").status_code == 404
        assert db.query(PeerMessage).count() == 0

    def test_a_nonexistent_thread_id_is_refused_identically(
        self, client, db, connected,
    ):
        """Same 404 as somebody else's thread, so ids are not probeable."""
        a, _ = connected()
        as_user(a)
        assert client.get(f"{URL}/pt_nope").status_code == 404

    def test_the_thread_list_contains_only_my_conversations(
        self, client, db, connected, make_user,
    ):
        a, b = connected()
        as_user(a)
        mine = _open(client, b.id).json()["thread_id"]

        c, d = connected("Cara", "Dev")
        as_user(c)
        theirs = _open(client, d.id).json()["thread_id"]

        as_user(a)
        ids = {t["thread_id"] for t in client.get(URL).json()}
        assert mine in ids
        assert theirs not in ids


# ---------------------------------------------------------------------------
# Unread / read
# ---------------------------------------------------------------------------


class TestUnread:
    def test_a_received_message_is_unread_until_the_thread_is_opened(
        self, client, db, connected,
    ):
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "knock knock")

        as_user(b)
        summary = next(t for t in client.get(URL).json() if t["thread_id"] == tid)
        assert summary["unread_count"] == 1

        client.get(f"{URL}/{tid}")
        db.expire_all()
        summary = next(t for t in client.get(URL).json() if t["thread_id"] == tid)
        assert summary["unread_count"] == 0

    def test_a_sender_never_sees_their_own_message_as_unread(
        self, client, db, connected,
    ):
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "mine")
        db.expire_all()

        summary = next(t for t in client.get(URL).json() if t["thread_id"] == tid)
        assert summary["unread_count"] == 0

    def test_opening_does_not_mark_my_own_messages_read(
        self, client, db, connected,
    ):
        """Read state belongs to the recipient; the sender opening their
        own thread must not resolve it on the other person's behalf."""
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "mine")
        client.get(f"{URL}/{tid}")
        db.expire_all()

        message = db.query(PeerMessage).one()
        assert message.is_read is False

    def test_marking_read_twice_changes_nothing_the_second_time(
        self, client, db, connected,
    ):
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "hi")
        thread = db.query(PeerThread).filter(PeerThread.id == tid).one()

        assert service.mark_read(db, thread, b.id) == 1
        assert service.mark_read(db, thread, b.id) == 0


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class TestNotifications:
    """What we ask the notification layer to send.

    ``send_notification`` deliberately opens its own session — the
    established pattern for the creator↔member threads, so a slow or
    failing notification cannot block or roll back a send. That also
    means it cannot see this test's uncommitted rows, so these assert
    the call we make rather than re-testing notification_service: the
    recipient, the absence of the body, and the link.
    """

    @staticmethod
    def _capture(monkeypatch):
        calls: list[dict] = []

        def fake(**kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(
            "app.services.notification_service.send_notification", fake,
        )
        return calls

    def test_only_the_recipient_is_notified(
        self, client, db, connected, monkeypatch,
    ):
        calls = self._capture(monkeypatch)
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "hello")

        assert len(calls) == 1
        assert calls[0]["recipient_id"] == b.id
        assert calls[0]["notification_type"] == "peer_message"

    def test_one_notification_per_persisted_message(
        self, client, db, connected, monkeypatch,
    ):
        calls = self._capture(monkeypatch)
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "one")
        _send(client, tid, "two")
        assert len(calls) == 2

    def test_a_rejected_message_notifies_nobody(
        self, client, db, connected, monkeypatch,
    ):
        calls = self._capture(monkeypatch)
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "   ")
        _send(client, tid, "x" * (service.MAX_BODY_CHARS + 1))
        assert calls == []

    def test_an_unauthorised_send_notifies_nobody(
        self, client, db, connected, make_user, monkeypatch,
    ):
        calls = self._capture(monkeypatch)
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        outsider = make_user()
        _named(db, outsider, "Nosy")
        db.flush()
        as_user(outsider)
        _send(client, tid, "let me in")
        assert calls == []

    def test_the_notification_carries_no_message_body(
        self, client, db, connected, monkeypatch,
    ):
        """A peer conversation is private between two people; a
        notification is the one place its content could surface outside
        the thread. The creator↔member notification carries an
        80-character preview — this one deliberately does not."""
        calls = self._capture(monkeypatch)
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "a secret worth keeping")

        sent = calls[0]
        # Pin the exact body, not merely the absence of one word: a
        # mutation that swapped in some *other* fragment of the
        # conversation would otherwise pass.
        assert sent["message"] == "Open your messages to read it."
        assert sent["title"] == "Alice sent you a message"
        assert "secret" not in sent["message"]
        assert "secret" not in sent["title"]
        assert sent["url"] == f"/messages/{tid}"

    def test_the_notification_is_in_app_only(
        self, client, db, connected, monkeypatch,
    ):
        """No ``space_id``/``pref_key``: a peer conversation has no
        Collective, and v1 does not email."""
        calls = self._capture(monkeypatch)
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "hi")

        assert "space_id" not in calls[0]
        assert "pref_key" not in calls[0]

    def test_the_notification_names_the_sender_not_their_email(
        self, client, db, connected, monkeypatch,
    ):
        calls = self._capture(monkeypatch)
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "hi")

        sent = calls[0]
        assert a.email not in sent["title"]
        assert a.email not in sent["message"]


# ---------------------------------------------------------------------------
# Privacy of the payload
# ---------------------------------------------------------------------------


class TestPrivacy:
    def test_the_participant_payload_is_name_and_picture_only(
        self, client, db, connected,
    ):
        a, b = connected()
        as_user(a)
        other = _open(client, b.id).json()["other"]
        assert set(other.keys()) == {"id", "display_name", "image"}
        # ``fallback_url`` is the card this picture degrades to. Platform
        # artwork, shared by everybody with the same initial, so it says
        # nothing about this participant — and it is the same set of keys
        # Ways to Connect sends, which is the point of one resolver.
        assert set(other["image"].keys()) == {
            "kind", "url", "initial", "fallback_url",
        }
        if other["image"]["fallback_url"] is not None:
            assert other["image"]["fallback_url"].startswith(
                "/api/uploads/platform-artwork/"
            )

    def test_no_email_anywhere_in_the_payloads(self, client, db, connected):
        a, b = connected()
        as_user(a)
        tid = _open(client, b.id).json()["thread_id"]
        _send(client, tid, "hi")

        for text in (
            client.get(URL).text,
            client.get(f"{URL}/{tid}").text,
        ):
            assert b.email not in text
            assert a.email not in text

    def test_no_recognition_evidence_appears_in_a_conversation(
        self, client, db, connected,
    ):
        a, b = connected()
        as_user(a)
        body = client.get(f"{URL}/{_open(client, b.id).json()['thread_id']}").text
        for leaked in ("shared", "gathering", "pathway", "collective"):
            assert leaked not in body.lower(), (
                "the conversation is not a place to restate what they share"
            )


class TestServiceLevelDefences:
    """The service's own checks, exercised directly.

    The routes load a thread through ``thread_for_participant`` first,
    which already rejects a non-participant — so the checks inside
    ``send_message`` are defence in depth that no request can reach.
    That is exactly how a second line of defence rots: mutation testing
    showed both could be deleted with the suite still green. These call
    the service directly so they are load-bearing.
    """

    def test_send_refuses_a_non_participant(self, db, connected, make_user):
        a, b = connected()
        thread = service.get_or_create_thread(db, a.id, b.id)
        db.flush()
        outsider = make_user()
        db.flush()

        with pytest.raises(service.NotAParticipant):
            service.send_message(db, thread, outsider.id, "let me in")
        assert db.query(PeerMessage).count() == 0

    def test_send_refuses_once_the_connection_is_gone(self, db, connected):
        """Why the re-check exists: if a connection is ever revoked, the
        thread row still exists, and sending must stop without anybody
        having to hunt down and delete threads."""
        a, b = connected()
        thread = service.get_or_create_thread(db, a.id, b.id)
        db.flush()

        # Remove one direction — no longer mutual.
        db.query(MemberHello).filter(
            MemberHello.from_user_id == b.id,
            MemberHello.to_user_id == a.id,
        ).delete()
        db.flush()

        with pytest.raises(service.NotConnected):
            service.send_message(db, thread, a.id, "still there?")
        assert db.query(PeerMessage).count() == 0

    def test_a_still_connected_pair_can_still_send(self, db, connected):
        """The negative above is only meaningful beside this."""
        a, b = connected()
        thread = service.get_or_create_thread(db, a.id, b.id)
        db.flush()
        message = service.send_message(db, thread, a.id, "hello")
        assert message.sender_user_id == a.id

    def test_mark_read_refuses_a_non_participant(
        self, db, connected, make_user,
    ):
        a, b = connected()
        thread = service.get_or_create_thread(db, a.id, b.id)
        db.flush()
        outsider = make_user()
        db.flush()

        with pytest.raises(service.NotAParticipant):
            service.mark_read(db, thread, outsider.id)

    def test_other_participant_rejects_a_stranger(self, db, connected, make_user):
        a, b = connected()
        thread = service.get_or_create_thread(db, a.id, b.id)
        db.flush()
        outsider = make_user()
        with pytest.raises(ValueError):
            thread.other_participant(outsider.id)


class TestSenderCannotBeSpoofed:
    def test_the_request_schema_has_no_sender_field(self):
        """Structural, not behavioural: there is no field to spoof.

        A test that posts a ``sender_user_id`` proves little, because
        Pydantic simply ignores it — which is why this asserts the shape
        of the contract instead.
        """
        from app.peer_messages.routes import SendPeerMessageRequest

        assert set(SendPeerMessageRequest.model_fields) == {"body"}

    def test_the_route_passes_the_authenticated_user(self):
        import pathlib
        import re

        src = pathlib.Path("app/peer_messages/routes.py").read_text()
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        assert "db, thread, current_user.id, body.body," in code
