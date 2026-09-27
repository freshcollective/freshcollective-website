"""``GET /api/ways-to-connect`` — the member's own Recognition.

Two things these tests exist to hold. First, that the endpoint is a
thin read over ``RecognitionService`` and inherits every rule the
service enforces — reach past it and the member's own setting, the
account guards, the Collective gate and the evidence rules all fall
away at once. Second, that the person-first shape stays bounded: at
most three featured, chosen by the server, with no search, no paging
and no way to ask for someone who was not offered. The shape is not
what makes a directory; the absence of those limits would.
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
from app.models.platform import (
    BookingStatus,
    CreatorProfile,
    Enrollment,
    EnrollmentStatus,
    EventBooking,
    Pathway,
    PathwayStatus,
    PathwayStep,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    StepProgress,
)

URL = "/api/ways-to-connect"
NOW = datetime.utcnow()


# ---------------------------------------------------------------------------
# Fixtures / substrate helpers
# ---------------------------------------------------------------------------

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


def _join(db, user, space):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
    ))
    db.flush()


def _visible_space(make_space, **kw):
    kw.setdefault("show_member_directory", True)
    return make_space(**kw)


def _upcoming(make_event, space, *, days=7, **kw):
    return make_event(
        space=space,
        starts_at=NOW + timedelta(days=days),
        ends_at=NOW + timedelta(days=days, hours=1),
        **kw,
    )


def _past_attended_event(make_event, space, *, days=10, **kw):
    ev = make_event(
        space=space,
        starts_at=NOW - timedelta(days=days),
        ends_at=NOW - timedelta(days=days) + timedelta(hours=1),
        **kw,
    )
    ev.attendance_completed_at = NOW - timedelta(days=days)
    return ev


def _book(db, user, event, *, status=BookingStatus.confirmed, attendance=None):
    db.add(EventBooking(
        id=_uid("bk"), event_id=event.id, user_id=user.id,
        status=status, attendance_status=attendance,
    ))
    db.flush()


def _two_attended(db, make_event, users, space, *, label="Shared"):
    """Two attended Gatherings shared by everyone in ``users``.

    Two signals is the threshold for a person card, so any test that
    wants somebody *featured* needs at least this much. Tests that only
    need a recognisable person — the minimisation and in-payload ones —
    still use a single Gathering on purpose.
    """
    for n, days in enumerate((14, 45)):
        ev = _past_attended_event(make_event, space, days=days, title=f"{label} {n + 1}")
        for u in users:
            _book(db, u, ev, attendance="attended")


def _walk_pathway(db, users, space, *, title="Life in Alignment"):
    pw = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}", title=title,
        status=PathwayStatus.active,
    )
    db.add(pw); db.flush()
    step = PathwayStep(
        id=_uid("pst"), pathway_id=pw.id, slug="s1",
        title="Step one", position=0, content_type="text",
    )
    db.add(step); db.flush()
    for u in users:
        db.add(Enrollment(
            id=_uid("en"), user_id=u.id, pathway_id=pw.id,
            status=EnrollmentStatus.active,
        ))
        db.add(StepProgress(
            id=_uid("sp"), user_id=u.id, step_id=step.id,
            completed_at=NOW - timedelta(days=1),
        ))
    db.flush()
    return pw


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

class TestTheGate:
    def test_anonymous_is_rejected(self, client, db, flag_on):
        app.dependency_overrides.pop(get_current_user, None)
        assert client.get(URL).status_code in (401, 403)

    def test_flag_off_returns_503(self, client, db, make_user, monkeypatch):
        monkeypatch.setattr(settings, "ways_to_connect_enabled", False)
        as_user(make_user())

        res = client.get(URL)

        assert res.status_code == 503
        assert "not yet enabled" in res.json()["detail"]

    def test_flag_off_wins_even_with_real_evidence(
        self, client, db, make_user, make_space, make_event, monkeypatch
    ):
        monkeypatch.setattr(settings, "ways_to_connect_enabled", False)
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        assert client.get(URL).status_code == 503

    def test_flag_on_returns_the_members_own_data(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(name="Alice"), make_user(name="Bob")
        space = _visible_space(make_space)
        for u in (alice, bob):
            _join(db, u, space)
        _two_attended(db, make_event, (alice, bob), space, label="Circle")
        as_user(alice)

        body = client.get(URL).json()

        assert len(body["people"]) == 1
        assert body["people"][0]["display_name"] == "Bob"
        assert body["featured_count"] == 1


# ---------------------------------------------------------------------------
# Whose data it is
# ---------------------------------------------------------------------------

class TestWhoseDataItIs:
    def test_the_route_accepts_no_user_id(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """Structural: the subject comes from the auth dependency, so
        'someone else's Ways to Connect' has no request to express."""
        alice, bob, carol = make_user(), make_user(name="Bob"), make_user(name="Carol")
        space = _visible_space(make_space)
        # Bob and Carol share a Gathering; Alice shares nothing.
        ev = _upcoming(make_event, space)
        for u in (alice, bob, carol):
            _join(db, u, space)
        _book(db, bob, ev); _book(db, carol, ev)
        as_user(alice)

        for params in ({}, {"user_id": bob.id}, {"id": bob.id}, {"as": bob.id}):
            body = client.get(URL, params=params).json()
            assert body["people"] == [], params

    def test_each_member_sees_only_their_own(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob, carol = (
            make_user(name="Alice"), make_user(name="Bob"), make_user(name="Carol")
        )
        space = _visible_space(make_space)
        for u in (alice, bob, carol):
            _join(db, u, space)
        shared = _upcoming(make_event, space, title="Bob and Carol only")
        _book(db, bob, shared); _book(db, carol, shared)

        as_user(alice)
        assert client.get(URL).json()["people"] == []

        as_user(bob)
        bob_body = client.get(URL).json()
        assert [p["display_name"] for p in bob_body["people"]] == ["Carol"]
        assert bob_body["people"][0]["shared"][0]["title"] == "Bob and Carol only"


# ---------------------------------------------------------------------------
# The service remains the authority
# ---------------------------------------------------------------------------

class TestServiceRulesAreInherited:
    def _pair(self, db, make_user, make_space, make_event, **bob_kw):
        alice = make_user(name="Alice")
        bob = make_user(name="Bob", **bob_kw)
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        return alice, bob, space

    def test_opted_out_viewer_gets_nothing(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _, _ = self._pair(db, make_user, make_space, make_event)
        alice.ways_to_connect_enabled = False
        db.flush()
        as_user(alice)

        res = client.get(URL)

        assert res.status_code == 200
        assert res.json()["people"] == []

    def test_opted_out_peer_is_absent(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _, _ = self._pair(
            db, make_user, make_space, make_event, ways_to_connect_enabled=False
        )
        as_user(alice)

        assert client.get(URL).json()["people"] == []

    def test_suspended_peer_is_absent(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _, _ = self._pair(
            db, make_user, make_space, make_event, suspended_at=datetime.utcnow()
        )
        as_user(alice)

        assert client.get(URL).json()["people"] == []

    def test_cancelled_peer_is_absent(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _, _ = self._pair(
            db, make_user, make_space, make_event, cancelled_at=datetime.utcnow()
        )
        as_user(alice)

        assert client.get(URL).json()["people"] == []

    def test_collective_only_peer_is_absent(
        self, client, db, flag_on, make_user, make_space
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _join(db, alice, space); _join(db, bob, space)
        as_user(alice)

        assert client.get(URL).json()["people"] == []

    def test_hidden_directory_collective_is_absent(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = make_space(show_member_directory=False)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        assert client.get(URL).json()["people"] == []

    def test_a_no_show_is_absent(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        ev = _past_attended_event(make_event, space)
        for u in (alice, bob):
            _join(db, u, space)
        _book(db, alice, ev, attendance="attended")
        _book(db, bob, ev, attendance="no_show")
        as_user(alice)

        assert client.get(URL).json()["people"] == []


# ---------------------------------------------------------------------------
# Shape — person first, bounded
# ---------------------------------------------------------------------------

def _person(body, name):
    return next(p for p in body["people"] if p["display_name"] == name)


class TestResponseShape:
    def test_the_top_level_is_people(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        for u in (alice, bob):
            _join(db, u, space)
        _two_attended(db, make_event, (alice, bob), space)
        as_user(alice)

        body = client.get(URL).json()

        assert set(body.keys()) == {"people", "featured_count", "truncated"}
        assert [p["display_name"] for p in body["people"]] == ["Bob"]
        assert body["featured_count"] == 1

    def test_a_person_carries_the_shared_gathering_that_explains_them(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space, name="EMBODY")
        for u in (alice, bob):
            _join(db, u, space)
        # An upcoming Gathering is only ever a supporting signal, so it
        # rides alongside real history rather than standing alone.
        _two_attended(db, make_event, (alice, bob), space)
        ev = _upcoming(make_event, space, title="Thursday EMBODY")
        for u in (alice, bob):
            _book(db, u, ev)
        as_user(alice)

        person = client.get(URL).json()["people"][0]

        assert person["display_name"] == "Bob"
        assert [c["name"] for c in person["collectives"]] == ["EMBODY"]
        upcoming = [s for s in person["shared"] if s["basis"] == "upcoming"]
        assert len(upcoming) == 1
        assert upcoming[0]["title"] == "Thursday EMBODY"
        assert upcoming[0]["kind"] == "gathering"

    def test_a_person_carries_the_shared_pathway_that_explains_them(
        self, client, db, flag_on, make_user, make_space
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space, name="The Grove")
        for u in (alice, bob):
            _join(db, u, space)
        # Two Pathways: one alone is not enough for a card.
        _walk_pathway(db, [alice, bob], space, title="Life in Alignment")
        _walk_pathway(db, [alice, bob], space, title="Coming Home")
        as_user(alice)

        person = client.get(URL).json()["people"][0]

        pathways = [s for s in person["shared"] if s["kind"] == "pathway"]
        assert {p["title"] for p in pathways} == {"Life in Alignment", "Coming Home"}
        assert all(p["crossing_at"] is not None for p in pathways)

    def test_one_person_carries_every_thing_they_share(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """The inverse of the old context-first shape: two shared
        things are two entries on one person, not one person listed
        twice."""
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        for u in (alice, bob):
            _join(db, u, space)
        ev = _upcoming(make_event, space, title="Thursday circle")
        for u in (alice, bob):
            _book(db, u, ev)
        _walk_pathway(db, [alice, bob], space, title="Life in Alignment")
        as_user(alice)

        body = client.get(URL).json()

        assert len(body["people"]) == 1
        titles = {s["title"] for s in body["people"][0]["shared"]}
        assert titles == {"Thursday circle", "Life in Alignment"}

    def test_attended_basis_survives(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        ev = _past_attended_event(make_event, space, title="Last Tuesday")
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev, attendance="attended")
        as_user(alice)

        shared = client.get(URL).json()["people"][0]["shared"][0]

        assert shared["basis"] == "attended"
        assert shared["title"] == "Last Tuesday"

    def test_the_collectives_timezone_is_carried(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """``starts_at`` is stored naive. Without the Collective's zone
        a client would render the day from its own clock and be wrong
        for half the world."""
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space, timezone="Pacific/Auckland")
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        person = client.get(URL).json()["people"][0]

        assert person["collectives"][0]["timezone"] == "Pacific/Auckland"

    def test_attended_gatherings_list_most_recent_first(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """Nearest to now, not oldest first — the list should read as
        "you were just in a room together", not as a history."""
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        for u in (alice, bob):
            _join(db, u, space)
        for title, days in (("Older", 120), ("Newer", 20)):
            ev = _past_attended_event(make_event, space, days=days, title=title)
            for u in (alice, bob):
                _book(db, u, ev, attendance="attended")
        as_user(alice)

        shared = client.get(URL).json()["people"][0]["shared"]

        assert [s["title"] for s in shared] == ["Newer", "Older"]

    def test_upcoming_gatherings_list_soonest_first(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        for u in (alice, bob):
            _join(db, u, space)
        for title, days in (("Later", 30), ("Sooner", 3)):
            ev = _upcoming(make_event, space, days=days, title=title)
            for u in (alice, bob):
                _book(db, u, ev)
        as_user(alice)

        shared = client.get(URL).json()["people"][0]["shared"]

        assert [s["title"] for s in shared] == ["Sooner", "Later"]

    def test_upcoming_shared_things_precede_past_ones(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        for u in (alice, bob):
            _join(db, u, space)
        past = _past_attended_event(make_event, space, title="Past")
        for u in (alice, bob):
            _book(db, u, past, attendance="attended")
        soon = _upcoming(make_event, space, title="Soon")
        for u in (alice, bob):
            _book(db, u, soon)
        as_user(alice)

        shared = client.get(URL).json()["people"][0]["shared"]

        assert [s["title"] for s in shared] == ["Soon", "Past"]


# ---------------------------------------------------------------------------
# Featuring — at most three, named only
# ---------------------------------------------------------------------------

class TestFeaturing:
    def _crowd(self, db, make_user, make_space, make_event, n, *, named=True):
        """``n`` peers, each *eligible* — two attended Gatherings with
        the viewer, on their own pair of dates so nobody is coupled to
        anybody else's evidence."""
        alice = make_user()
        space = _visible_space(make_space)
        _join(db, alice, space)
        peers = []
        for i in range(n):
            u = make_user(name=f"Peer {i:02d}" if named else None)
            _join(db, u, space)
            for days in (i * 3 + 5, i * 3 + 60):
                ev = _past_attended_event(
                    make_event, space, days=days, title=f"Sitting {i}-{days}",
                )
                for who in (alice, u):
                    _book(db, who, ev, attendance="attended")
            peers.append(u)
        return alice, peers

    def _thin_crowd(self, db, make_user, make_space, make_event, n):
        """``n`` peers with exactly one shared signal each — recognisable,
        never featured."""
        alice = make_user()
        space = _visible_space(make_space)
        _join(db, alice, space)
        peers = []
        for i in range(n):
            u = make_user(name=f"Thin {i:02d}")
            _join(db, u, space)
            ev = _upcoming(make_event, space, days=i + 2, title=f"Once {i}")
            for who in (alice, u):
                _book(db, who, ev)
            peers.append(u)
        return alice, peers

    def test_at_most_three_are_featured(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, peers = self._crowd(db, make_user, make_space, make_event, 9)
        as_user(alice)

        body = client.get(URL).json()

        assert body["featured_count"] == 3
        assert len(body["people"]) == 9, "the tail feeds the in-context lines"

    def test_two_eligible_people_means_two_featured(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _ = self._crowd(db, make_user, make_space, make_event, 2)
        as_user(alice)

        assert client.get(URL).json()["featured_count"] == 2

    def test_one_eligible_person_means_one_featured(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _ = self._crowd(db, make_user, make_space, make_event, 1)
        as_user(alice)

        assert client.get(URL).json()["featured_count"] == 1

    def test_nobody_is_manufactured_to_reach_three(
        self, client, db, flag_on, make_user, make_space
    ):
        alice = make_user()
        space = _visible_space(make_space)
        _join(db, alice, space)
        for _ in range(5):
            _join(db, make_user(name="Co-member"), space)
        as_user(alice)

        body = client.get(URL).json()

        assert body["featured_count"] == 0
        assert body["people"] == []

    def test_single_signal_people_are_recognisable_but_never_featured(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """The rule the visual review produced. One shared Gathering is
        a coincidence — it still names them on the Gathering's own page,
        and it does not earn a card."""
        alice, peers = self._thin_crowd(db, make_user, make_space, make_event, 4)
        as_user(alice)

        body = client.get(URL).json()

        assert body["featured_count"] == 0
        assert len(body["people"]) == 4, "still in the payload for in-context lines"

    def test_a_pair_with_only_future_plans_is_never_featured(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """Two confirmed bookings for two future Gatherings. Two signals,
        nothing realised, no card — and still named on each Gathering's
        own page."""
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        for u in (alice, bob):
            _join(db, u, space)
        for days, title in ((5, "Soon"), (20, "Later")):
            ev = _upcoming(make_event, space, days=days, title=title)
            for u in (alice, bob):
                _book(db, u, ev)
        as_user(alice)

        body = client.get(URL).json()

        assert body["featured_count"] == 0
        assert len(body["people"]) == 1, "still recognisable, just not introduced"

    def test_one_attended_gathering_plus_a_plan_is_featured(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """The same two signals, one of them realised. That is the line."""
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        for u in (alice, bob):
            _join(db, u, space)
        past = _past_attended_event(make_event, space, days=20, title="Was there")
        for u in (alice, bob):
            _book(db, u, past, attendance="attended")
        soon = _upcoming(make_event, space, days=5, title="Will be there")
        for u in (alice, bob):
            _book(db, u, soon)
        as_user(alice)

        assert client.get(URL).json()["featured_count"] == 1

    def test_repeated_attendance_is_featured_ahead_of_one_room_plus_a_plan(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice = make_user()
        twice, once = make_user(name="Twice"), make_user(name="Once")
        space = _visible_space(make_space)
        for u in (alice, twice, once):
            _join(db, u, space)
        # Twice: two real rooms, both a long time ago.
        for days in (200, 240):
            ev = _past_attended_event(make_event, space, days=days, title=f"Old {days}")
            for u in (alice, twice):
                _book(db, u, ev, attendance="attended")
        # Once: one recent room plus an imminent booking.
        recent = _past_attended_event(make_event, space, days=3, title="Recent")
        for u in (alice, once):
            _book(db, u, recent, attendance="attended")
        soon = _upcoming(make_event, space, days=2, title="Imminent")
        for u in (alice, once):
            _book(db, u, soon)
        as_user(alice)

        body = client.get(URL).json()

        assert [p["display_name"] for p in body["people"][:2]] == ["Twice", "Once"]

    def test_the_threshold_does_not_drop_to_fill_the_page(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """One eligible person plus four thin ones is one card, not
        three."""
        alice, peers = self._crowd(db, make_user, make_space, make_event, 1)
        space = db.query(SpaceMembership).filter(
            SpaceMembership.user_id == peers[0].id
        ).first()
        space = db.get(Space, space.space_id)
        for i in range(4):
            u = make_user(name=f"Thin {i}")
            _join(db, u, space)
            ev = _upcoming(make_event, space, days=i + 2, title=f"Once {i}")
            for who in (alice, u):
                _book(db, who, ev)
        as_user(alice)

        assert client.get(URL).json()["featured_count"] == 1

    def test_unnamed_members_are_never_featured(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """Eligible on the evidence, and still not a card — we will not
        introduce someone we cannot name."""
        alice, _ = self._crowd(db, make_user, make_space, make_event, 4, named=False)
        as_user(alice)

        body = client.get(URL).json()

        assert body["featured_count"] == 0
        assert len(body["people"]) == 4
        assert all(p["display_name"] is None for p in body["people"])

    def test_featured_people_come_first_in_the_payload(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _ = self._crowd(db, make_user, make_space, make_event, 6)
        as_user(alice)

        body = client.get(URL).json()
        featured = body["people"][: body["featured_count"]]

        assert len(featured) == 3
        assert all(p["display_name"] for p in featured)

    def test_named_people_are_featured_ahead_of_unnamed_ones(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice = make_user()
        space = _visible_space(make_space)
        _join(db, alice, space)
        named = make_user(name="Sarah")
        everyone = (named, make_user(name=None), make_user(name=None))
        for u in everyone:
            _join(db, u, space)
        # All three are equally eligible; only one can be introduced.
        for days in (10, 50):
            ev = _past_attended_event(make_event, space, days=days, title=f"S{days}")
            for u in (alice, *everyone):
                _book(db, u, ev, attendance="attended")
        as_user(alice)

        body = client.get(URL).json()

        assert body["featured_count"] == 1
        assert body["people"][0]["display_name"] == "Sarah"

    def test_the_selection_is_stable_across_calls(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """Not a shuffle. The same state yields the same page."""
        alice, _ = self._crowd(db, make_user, make_space, make_event, 8)
        as_user(alice)

        first = client.get(URL).json()
        second = client.get(URL).json()

        assert first == second


# ---------------------------------------------------------------------------
# Member data minimisation
# ---------------------------------------------------------------------------

class TestNoPrivateFields:
    def _pair(self, db, make_user, make_space, make_event, **bob_kw):
        alice = make_user()
        bob = make_user(**bob_kw)
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        return alice, bob

    def test_a_person_carries_only_the_fields_it_needs(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _ = self._pair(
            db, make_user, make_space, make_event,
            name="Bob", email="bob-private@example.test",
        )
        as_user(alice)

        person = client.get(URL).json()["people"][0]

        assert set(person.keys()) == {
            "id", "display_name", "avatar_url", "collectives", "shared",
        }

    def test_nothing_private_appears_anywhere_in_the_payload(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _ = self._pair(
            db, make_user, make_space, make_event,
            name="Bob", email="bob-private@example.test",
        )
        as_user(alice)

        raw = client.get(URL).text.lower()

        for leaked in (
            "bob-private", "@example.test", "password", "reflection",
            "score", "rank", "match", "strength", "suspended", "cancelled",
            "joined", "created_at", "email",
        ):
            assert leaked not in raw, leaked

    def test_an_unnamed_member_has_a_null_name_not_a_placeholder(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _ = self._pair(
            db, make_user, make_space, make_event,
            name=None, email="quietperson@example.test",
        )
        as_user(alice)

        person = client.get(URL).json()["people"][0]

        assert person["display_name"] is None

    def test_an_unnamed_member_is_never_labelled_with_their_email(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _ = self._pair(
            db, make_user, make_space, make_event,
            name=None, email="quietperson@example.test",
        )
        as_user(alice)

        raw = client.get(URL).text

        assert "quietperson" not in raw
        assert "Member" not in raw

    def test_an_unnamed_member_still_takes_part(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """No public profile required. Having no name costs a member
        their card, and nothing else."""
        alice, bob = self._pair(db, make_user, make_space, make_event, name=None)
        as_user(alice)

        body = client.get(URL).json()

        assert len(body["people"]) == 1
        assert body["people"][0]["id"] == bob.id
        assert body["people"][0]["shared"][0]["kind"] == "gathering"
        assert body["featured_count"] == 0

    def test_an_ordinary_member_has_no_avatar_and_that_is_fine(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _ = self._pair(db, make_user, make_space, make_event, name="Bob")
        as_user(alice)

        assert client.get(URL).json()["people"][0]["avatar_url"] is None

    def test_a_public_creator_profile_supplies_the_avatar(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = self._pair(
            db, make_user, make_space, make_event, name="Bob", role="creator",
        )
        db.add(CreatorProfile(
            user_id=bob.id, display_name="Bobbie",
            avatar_url="/uploads/avatars/bob.png", is_public=True,
        ))
        db.flush()
        as_user(alice)

        person = client.get(URL).json()["people"][0]

        assert person["display_name"] == "Bobbie"
        assert person["avatar_url"] == "/uploads/avatars/bob.png"

    def test_a_private_creator_profile_does_not(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = self._pair(
            db, make_user, make_space, make_event, name="Bob", role="creator",
        )
        db.add(CreatorProfile(
            user_id=bob.id, display_name="Hidden",
            avatar_url="/uploads/avatars/bob.png", is_public=False,
        ))
        db.flush()
        as_user(alice)

        person = client.get(URL).json()["people"][0]

        assert person["avatar_url"] is None
        assert person["display_name"] == "Bob"


# ---------------------------------------------------------------------------
# Finite
# ---------------------------------------------------------------------------

class TestFinite:
    def _pair(self, db, make_user, make_space, make_event):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        return alice, bob

    def test_there_is_no_paging_or_search_mechanism(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _ = self._pair(db, make_user, make_space, make_event)
        as_user(alice)

        body = client.get(URL).json()

        for browsing in ("cursor", "next", "page", "total", "offset", "query"):
            assert browsing not in body

    def test_unknown_query_parameters_change_nothing(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _ = self._pair(db, make_user, make_space, make_event)
        as_user(alice)

        plain = client.get(URL).json()
        poked = client.get(
            URL, params={"sort": "score", "limit": "1000", "q": "bob", "user_id": "x"},
        ).json()

        assert plain == poked

    def test_a_person_cannot_be_requested_by_id(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """The featured few are chosen by the server. There is no
        parameter that asks for somebody in particular — which is what
        keeps 'no browsing' true rather than merely unimplemented."""
        alice, _ = self._pair(db, make_user, make_space, make_event)
        carol = make_user(name="Carol")
        as_user(alice)

        body = client.get(URL, params={"person": carol.id, "id": carol.id}).json()

        assert [p["display_name"] for p in body["people"]] == ["Bob"]

    def test_truncated_is_false_in_the_ordinary_case(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _ = self._pair(db, make_user, make_space, make_event)
        as_user(alice)

        assert client.get(URL).json()["truncated"] is False
