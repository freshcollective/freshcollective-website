"""Mutual "Say hello" — Ways to Connect 5b.

A hello is a directed row, and the four product states are read off
which of the two possible rows exist. There is no status column to get
out of step, which is what makes a double click, a retried request and
two people greeting each other simultaneously all converge without any
of them knowing about the others.

Authorisation reuses the canonical 5a rule rather than restating it:
``RecognitionService.for_user`` then ``is_eligible_pair``. The tests
below therefore double as a guard that the two cannot drift — if the
eligibility threshold ever changed, the hello endpoint would move with
it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.connections import MemberHello
from app.models.notification import Notification
from app.models.platform import (
    BookingStatus,
    CreatorProfile,
    EventBooking,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.ways_to_connect.hello_service import HelloState, hello_state, say_hello

URL = "/api/ways-to-connect"
NOW = datetime.utcnow()


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ways_to_connect_enabled", True)


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _named(db, user, name):
    db.add(CreatorProfile(
        user_id=user.id, display_name=name, is_public=True,
    ))
    db.flush()


def _join(db, user, space):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
    ))
    db.flush()


def _book(db, user, event, *, attendance=None):
    db.add(EventBooking(
        id=_uid("bk"), event_id=event.id, user_id=user.id,
        status=BookingStatus.confirmed, attendance_status=attendance,
    ))
    db.flush()


def _attended(make_event, space, *, days, title):
    ev = make_event(
        space=space,
        starts_at=NOW - timedelta(days=days),
        ends_at=NOW - timedelta(days=days) + timedelta(hours=1),
        title=title,
    )
    ev.attendance_completed_at = NOW - timedelta(days=days)
    return ev


@pytest.fixture
def eligible_pair(db, make_user, make_space, make_event):
    """Two named members sharing two attended Gatherings.

    Two realised signals — comfortably over the threshold, so these
    tests exercise the hello rather than the eligibility edge.
    """
    def _make(name_a="Alice", name_b="Bob"):
        a, b = make_user(), make_user()
        _named(db, a, name_a)
        _named(db, b, name_b)
        space = make_space(show_member_directory=True)
        for u in (a, b):
            _join(db, u, space)
        for n, days in enumerate((14, 45)):
            ev = _attended(make_event, space, days=days, title=f"Shared {n + 1}")
            for u in (a, b):
                _book(db, u, ev, attendance="attended")
        db.flush()
        return a, b
    return _make


def _post(client, target_id):
    return client.post(f"{URL}/{target_id}/hello")


def _hellos(db):
    return db.query(MemberHello).all()


def _notifs(db, user, kind=None):
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if kind:
        q = q.filter(Notification.notification_type == kind)
    return q.all()


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


class TestSayHello:
    def test_an_eligible_pair_can_say_hello(self, client, db, flag_on, eligible_pair):
        a, b = eligible_pair()
        as_user(a)

        res = _post(client, b.id)
        assert res.status_code == 200, res.text
        assert res.json() == {"relationship": "outgoing", "became_mutual": False}

    def test_the_state_is_outgoing_for_the_sender(
        self, client, db, flag_on, eligible_pair,
    ):
        a, b = eligible_pair()
        as_user(a)
        _post(client, b.id)
        db.expire_all()
        assert hello_state(db, a.id, b.id) is HelloState.OUTGOING

    def test_the_state_is_incoming_for_the_recipient(
        self, client, db, flag_on, eligible_pair,
    ):
        a, b = eligible_pair()
        as_user(a)
        _post(client, b.id)
        db.expire_all()
        assert hello_state(db, b.id, a.id) is HelloState.INCOMING

    def test_the_card_payload_reports_the_state(
        self, client, db, flag_on, eligible_pair,
    ):
        a, b = eligible_pair()
        as_user(a)
        _post(client, b.id)
        db.expire_all()

        person = next(
            p for p in client.get(URL).json()["people"] if p["id"] == b.id
        )
        assert person["relationship"] == "outgoing"

    def test_the_recipient_sees_incoming_on_their_own_page(
        self, client, db, flag_on, eligible_pair,
    ):
        a, b = eligible_pair()
        as_user(a)
        _post(client, b.id)
        db.expire_all()

        as_user(b)
        person = next(
            p for p in client.get(URL).json()["people"] if p["id"] == a.id
        )
        assert person["relationship"] == "incoming"


# ---------------------------------------------------------------------------
# Idempotency and races
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_clicking_twice_persists_one_hello(
        self, client, db, flag_on, eligible_pair,
    ):
        a, b = eligible_pair()
        as_user(a)

        first = _post(client, b.id)
        second = _post(client, b.id)
        db.expire_all()

        assert first.status_code == 200
        assert second.status_code == 200, "a repeat click is not a conflict"
        assert first.json() == second.json()
        assert len(_hellos(db)) == 1

    def test_clicking_twice_notifies_once(
        self, client, db, flag_on, eligible_pair,
    ):
        a, b = eligible_pair()
        as_user(a)
        _post(client, b.id)
        _post(client, b.id)
        _post(client, b.id)
        db.expire_all()

        assert len(_notifs(db, b, "ways_to_connect_hello_received")) == 1

    def test_the_unique_constraint_is_what_enforces_it(
        self, db, flag_on, eligible_pair,
    ):
        """Not a prior read: two concurrent requests would both see "no
        row" and both insert. ``say_hello`` survives the loser."""
        a, b = eligible_pair()
        say_hello(db, a.id, b.id)
        db.flush()
        # Simulate the racing request arriving after the row exists.
        state, created = say_hello(db, a.id, b.id)
        db.flush()

        assert state is HelloState.OUTGOING
        assert created is False, "the second caller must not announce"
        assert len(_hellos(db)) == 1

    def test_a_direct_duplicate_insert_is_rejected_by_the_database(
        self, db, eligible_pair,
    ):
        from sqlalchemy.exc import IntegrityError

        a, b = eligible_pair()
        db.add(MemberHello(id=_uid("h"), from_user_id=a.id, to_user_id=b.id))
        db.flush()
        db.add(MemberHello(id=_uid("h"), from_user_id=a.id, to_user_id=b.id))
        with pytest.raises(IntegrityError):
            db.flush()


# ---------------------------------------------------------------------------
# Mutual
# ---------------------------------------------------------------------------


class TestMutual:
    def test_saying_hello_back_connects_both(
        self, client, db, flag_on, eligible_pair,
    ):
        a, b = eligible_pair()
        as_user(a)
        _post(client, b.id)
        db.expire_all()

        as_user(b)
        res = _post(client, a.id)
        db.expire_all()

        assert res.json() == {"relationship": "mutual", "became_mutual": True}
        assert hello_state(db, a.id, b.id) is HelloState.MUTUAL
        assert hello_state(db, b.id, a.id) is HelloState.MUTUAL

    def test_both_cards_report_connected(
        self, client, db, flag_on, eligible_pair,
    ):
        a, b = eligible_pair()
        as_user(a); _post(client, b.id)
        as_user(b); _post(client, a.id)
        db.expire_all()

        for viewer, other in ((a, b), (b, a)):
            as_user(viewer)
            person = next(
                p for p in client.get(URL).json()["people"] if p["id"] == other.id
            )
            assert person["relationship"] == "mutual"

    def test_the_mutual_transition_is_idempotent(
        self, client, db, flag_on, eligible_pair,
    ):
        a, b = eligible_pair()
        as_user(a); _post(client, b.id)
        as_user(b)
        first = _post(client, a.id)
        second = _post(client, a.id)
        db.expire_all()

        assert first.json()["became_mutual"] is True
        # The transition already happened; a repeat is still mutual but
        # is no longer the moment it became so.
        assert second.json()["relationship"] == "mutual"
        assert second.json()["became_mutual"] is False
        assert len(_hellos(db)) == 2

    def test_both_people_are_told_once(self, client, db, flag_on, eligible_pair):
        a, b = eligible_pair()
        as_user(a); _post(client, b.id)
        as_user(b); _post(client, a.id); _post(client, a.id)
        db.expire_all()

        assert len(_notifs(db, a, "ways_to_connect_connected")) == 1
        assert len(_notifs(db, b, "ways_to_connect_connected")) == 1

    def test_simultaneous_hellos_converge_on_one_mutual_connection(
        self, db, flag_on, eligible_pair,
    ):
        """Both sides greet before either sees the other's row."""
        a, b = eligible_pair()
        state_a, created_a = say_hello(db, a.id, b.id)
        state_b, created_b = say_hello(db, b.id, a.id)
        db.flush()

        assert created_a and created_b
        assert state_a is HelloState.OUTGOING   # b's row did not exist yet
        assert state_b is HelloState.MUTUAL
        assert hello_state(db, a.id, b.id) is HelloState.MUTUAL
        assert len(_hellos(db)) == 2, "one row each, no duplicates"


# ---------------------------------------------------------------------------
# Authorisation
# ---------------------------------------------------------------------------


class TestAuthorisation:
    def test_an_arbitrary_user_id_is_refused(
        self, client, db, flag_on, eligible_pair, make_user,
    ):
        a, _ = eligible_pair()
        stranger = make_user()
        _named(db, stranger, "Stranger")
        db.flush()
        as_user(a)

        res = _post(client, stranger.id)
        assert res.status_code == 404
        assert _hellos(db) == []

    def test_a_nonexistent_user_id_is_refused_the_same_way(
        self, client, db, flag_on, eligible_pair,
    ):
        """Same status as an ineligible one, so the endpoint cannot be
        used to discover who exists or who shares what."""
        a, _ = eligible_pair()
        as_user(a)

        ineligible = _post(client, "u_does_not_exist").status_code
        assert ineligible == 404

    def test_an_ineligible_pair_is_refused(
        self, client, db, flag_on, make_user, make_space, make_event,
    ):
        """One shared attended Gathering is one signal. The threshold is
        two, so this pair is recognisable but not introducible — and not
        greetable either."""
        a, b = make_user(), make_user()
        _named(db, a, "Alice"); _named(db, b, "Bob")
        space = make_space(show_member_directory=True)
        for u in (a, b):
            _join(db, u, space)
        ev = _attended(make_event, space, days=14, title="Only one")
        for u in (a, b):
            _book(db, u, ev, attendance="attended")
        db.flush()
        as_user(a)

        assert _post(client, b.id).status_code == 404
        assert _hellos(db) == []

    def test_self_hello_is_refused(self, client, db, flag_on, eligible_pair):
        a, _ = eligible_pair()
        as_user(a)
        assert _post(client, a.id).status_code == 400
        assert _hellos(db) == []

    def test_the_service_refuses_a_self_hello_too(self, db, eligible_pair):
        """Defence in depth: the route checks, and so does the service,
        so no future caller can reintroduce it."""
        a, _ = eligible_pair()
        with pytest.raises(ValueError):
            say_hello(db, a.id, a.id)

    def test_an_opted_out_member_cannot_be_greeted(
        self, client, db, flag_on, eligible_pair,
    ):
        """Their own participation setting removes them from Recognition
        entirely, so eligibility — and therefore the hello — fails."""
        a, b = eligible_pair()
        b.ways_to_connect_enabled = False
        db.flush()
        as_user(a)

        assert _post(client, b.id).status_code == 404

    def test_the_flag_gates_the_endpoint(self, client, db, eligible_pair):
        """No ``flag_on`` fixture: the surface does not exist yet."""
        a, b = eligible_pair()
        as_user(a)
        assert _post(client, b.id).status_code == 503
        assert _hellos(db) == []

    def test_unauthenticated_is_refused(self, client, db, flag_on, eligible_pair):
        a, b = eligible_pair()
        app.dependency_overrides.pop(get_current_user, None)
        res = _post(client, b.id)
        assert res.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Persistence and discoverability
# ---------------------------------------------------------------------------


class TestConnectionPersists:
    def test_a_mutual_connection_outlives_its_evidence(
        self, client, db, flag_on, eligible_pair,
    ):
        """Eligibility governs discovery and the first hello. It does not
        govern a connection two people already made."""
        a, b = eligible_pair()
        as_user(a); _post(client, b.id)
        as_user(b); _post(client, a.id)
        db.expire_all()

        # Remove the shared history entirely.
        db.query(EventBooking).filter(EventBooking.user_id == b.id).delete()
        db.flush()
        db.expire_all()

        assert hello_state(db, a.id, b.id) is HelloState.MUTUAL


class TestIncomingIsDiscoverable:
    def test_an_incoming_hello_is_carded_even_when_not_featured(
        self, client, db, flag_on, make_user, make_space, make_event,
    ):
        """Somebody greeting you must not be buried because that day's
        rotation put them outside the featured few — or because the
        evidence that introduced them has since lapsed."""
        a, b = make_user(), make_user()
        _named(db, a, "Alice"); _named(db, b, "Bob")
        space = make_space(show_member_directory=True)
        for u in (a, b):
            _join(db, u, space)
        # One signal only: recognisable, not featured.
        ev = _attended(make_event, space, days=14, title="One")
        for u in (a, b):
            _book(db, u, ev, attendance="attended")
        db.add(MemberHello(id=_uid("h"), from_user_id=b.id, to_user_id=a.id))
        db.flush()

        as_user(a)
        payload = client.get(URL).json()
        assert payload["featured_count"] >= 1
        # First card, not buried in the tail.
        assert payload["people"][0]["id"] == b.id
        assert payload["people"][0]["relationship"] == "incoming"

    def test_featured_count_covers_the_lifted_person(
        self, client, db, flag_on, eligible_pair, make_user, make_space, make_event,
    ):
        """The frontend slices the first ``featured_count`` people as
        cards; lifting someone to the front has to count them or the
        slice cuts a featured person off the end."""
        a, b = eligible_pair()
        waiting = make_user()
        _named(db, waiting, "Wanda")
        space = make_space(show_member_directory=True)
        for u in (a, waiting):
            _join(db, u, space)
        ev = _attended(make_event, space, days=20, title="One")
        for u in (a, waiting):
            _book(db, u, ev, attendance="attended")
        db.add(MemberHello(id=_uid("h"), from_user_id=waiting.id, to_user_id=a.id))
        db.flush()

        as_user(a)
        payload = client.get(URL).json()
        carded = payload["people"][: payload["featured_count"]]
        ids = {p["id"] for p in carded}
        assert waiting.id in ids, "the person waiting on you is a card"
        assert b.id in ids, "and the eligible person is not displaced"


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


class TestPrivacy:
    def test_the_hello_response_carries_no_personal_data(
        self, client, db, flag_on, eligible_pair,
    ):
        a, b = eligible_pair()
        as_user(a)
        body = _post(client, b.id).json()
        assert set(body.keys()) == {"relationship", "became_mutual"}

    def test_notifications_name_the_person_but_not_the_evidence(
        self, client, db, flag_on, eligible_pair,
    ):
        """"You were both at X" would publish a shared history into a
        surface the page already states in context."""
        a, b = eligible_pair(name_a="Alice Smith")
        as_user(a)
        _post(client, b.id)
        db.expire_all()

        note = _notifs(db, b, "ways_to_connect_hello_received")[0]
        assert "Alice" in note.title
        assert "Smith" not in note.message, "first name only"
        assert "Shared 1" not in note.message
        assert "Shared 2" not in note.message

    def test_no_email_appears_in_the_notification(
        self, client, db, flag_on, eligible_pair,
    ):
        a, b = eligible_pair()
        as_user(a)
        _post(client, b.id)
        db.expire_all()

        for note in _notifs(db, b):
            assert a.email not in (note.message or "")
            assert a.email not in (note.title or "")


class TestInsertIsConflictTolerant:
    """Direct coverage for ``ON CONFLICT DO NOTHING``.

    ``say_hello`` pre-checks for an existing row, so in a sequential
    double click the insert never runs twice and the conflict clause is
    never exercised — which is exactly how a concurrency safeguard rots
    unnoticed. These tests drive the statement itself, which is the only
    thing standing between two simultaneous requests and either an
    IntegrityError or a duplicate row.
    """

    @staticmethod
    def _insert(db, from_id, to_id):
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return db.execute(
            pg_insert(MemberHello.__table__)
            .values(id=_uid("h"), from_user_id=from_id, to_user_id=to_id)
            .on_conflict_do_nothing(constraint="uq_member_hellos_pair")
        )

    def test_a_second_identical_insert_does_not_raise(self, db, eligible_pair):
        a, b = eligible_pair()
        first = self._insert(db, a.id, b.id)
        second = self._insert(db, a.id, b.id)
        db.flush()

        assert first.rowcount == 1
        assert second.rowcount == 0, "the loser of the race inserts nothing"
        assert len(_hellos(db)) == 1

    def test_rowcount_is_what_decides_who_announces(self, db, eligible_pair):
        """``created`` comes from ``rowcount``, so the creator of the row
        is the one request that notifies."""
        a, b = eligible_pair()
        self._insert(db, a.id, b.id)
        db.flush()

        # A racing caller whose pre-check saw nothing still reaches the
        # insert, and must come away knowing it did not create the row.
        _, created = say_hello(db, a.id, b.id)
        db.flush()
        assert created is False

    def test_the_reciprocal_direction_is_not_a_conflict(self, db, eligible_pair):
        """The constraint is on the ordered pair, so B greeting A is a
        different row — which is what makes mutuality representable."""
        a, b = eligible_pair()
        self._insert(db, a.id, b.id)
        self._insert(db, b.id, a.id)
        db.flush()
        assert len(_hellos(db)) == 2
