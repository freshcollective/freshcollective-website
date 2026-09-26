"""``GET /api/ways-to-connect`` — the member's own Recognition.

Two things these tests exist to hold. First, that the endpoint is a
thin read over ``RecognitionService`` and inherits every rule the
service enforces — reach past it and the member's own setting, the
account guards, the Collective gate and the evidence rules all fall
away at once. Second, that the response stays indexed by *shared
experience* rather than by person: the moment the top level becomes a
list of people, this is a directory.
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
        ev = _upcoming(make_event, space, title="Thursday circle")
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        body = client.get(URL).json()

        assert len(body["contexts"]) == 1
        assert body["contexts"][0]["title"] == "Thursday circle"


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
            assert body["contexts"] == [], params

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
        assert client.get(URL).json()["contexts"] == []

        as_user(bob)
        bob_body = client.get(URL).json()
        assert [c["title"] for c in bob_body["contexts"]] == ["Bob and Carol only"]
        assert [p["display_name"] for p in bob_body["contexts"][0]["people"]] == ["Carol"]


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
        assert res.json()["contexts"] == []

    def test_opted_out_peer_is_absent(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _, _ = self._pair(
            db, make_user, make_space, make_event, ways_to_connect_enabled=False
        )
        as_user(alice)

        assert client.get(URL).json()["contexts"] == []

    def test_suspended_peer_is_absent(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _, _ = self._pair(
            db, make_user, make_space, make_event, suspended_at=datetime.utcnow()
        )
        as_user(alice)

        assert client.get(URL).json()["contexts"] == []

    def test_cancelled_peer_is_absent(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, _, _ = self._pair(
            db, make_user, make_space, make_event, cancelled_at=datetime.utcnow()
        )
        as_user(alice)

        assert client.get(URL).json()["contexts"] == []

    def test_collective_only_peer_is_absent(
        self, client, db, flag_on, make_user, make_space
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _join(db, alice, space); _join(db, bob, space)
        as_user(alice)

        assert client.get(URL).json()["contexts"] == []

    def test_hidden_directory_collective_is_absent(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = make_space(show_member_directory=False)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        assert client.get(URL).json()["contexts"] == []

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

        assert client.get(URL).json()["contexts"] == []


# ---------------------------------------------------------------------------
# Shape — shared experience first
# ---------------------------------------------------------------------------

class TestResponseShape:
    def test_a_gathering_context_carries_its_people(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice = make_user(name="Alice")
        bob, carol = make_user(name="Bob"), make_user(name="Carol")
        space = _visible_space(make_space, name="EMBODY")
        ev = _upcoming(make_event, space, title="Thursday EMBODY")
        for u in (alice, bob, carol):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        ctx = client.get(URL).json()["contexts"][0]

        assert ctx["kind"] == "gathering"
        assert ctx["title"] == "Thursday EMBODY"
        assert ctx["basis"] == "upcoming"
        assert ctx["collective"]["name"] == "EMBODY"
        assert [p["display_name"] for p in ctx["people"]] == ["Bob", "Carol"]

    def test_a_pathway_context_carries_its_people(
        self, client, db, flag_on, make_user, make_space
    ):
        alice, bob = make_user(name="Alice"), make_user(name="Bob")
        space = _visible_space(make_space, name="The Grove")
        for u in (alice, bob):
            _join(db, u, space)
        _walk_pathway(db, [alice, bob], space, title="Life in Alignment")
        as_user(alice)

        ctx = client.get(URL).json()["contexts"][0]

        assert ctx["kind"] == "pathway"
        assert ctx["title"] == "Life in Alignment"
        assert ctx["collective"]["name"] == "The Grove"
        assert [p["display_name"] for p in ctx["people"]] == ["Bob"]

    def test_attended_basis_survives(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        ev = _past_attended_event(make_event, space, title="Last Tuesday")
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev, attendance="attended")
        as_user(alice)

        ctx = client.get(URL).json()["contexts"][0]

        assert ctx["basis"] == "attended"
        assert ctx["title"] == "Last Tuesday"

    def test_the_same_person_may_appear_in_two_contexts(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """The same people turn up at the same circle and on the same
        Pathway. Collapsing that to one row would lose the thing worth
        saying."""
        alice, bob = make_user(name="Alice"), make_user(name="Bob")
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space, title="Thursday circle")
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        _walk_pathway(db, [alice, bob], space, title="Life in Alignment")
        as_user(alice)

        contexts = client.get(URL).json()["contexts"]

        assert {c["title"] for c in contexts} == {
            "Thursday circle", "Life in Alignment"
        }
        for c in contexts:
            assert [p["display_name"] for p in c["people"]] == ["Bob"]

    def test_the_top_level_is_contexts_not_people(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        body = client.get(URL).json()

        assert set(body.keys()) == {"contexts", "truncated"}
        assert all("kind" in c and "people" in c for c in body["contexts"])

    def test_upcoming_precede_pathways_precede_attended(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        for u in (alice, bob):
            _join(db, u, space)
        soon = _upcoming(make_event, space, days=3, title="Soon")
        for u in (alice, bob):
            _book(db, u, soon)
        past = _past_attended_event(make_event, space, days=5, title="Past")
        for u in (alice, bob):
            _book(db, u, past, attendance="attended")
        _walk_pathway(db, [alice, bob], space, title="Walking")
        as_user(alice)

        kinds = [c["kind"] for c in client.get(URL).json()["contexts"]]

        assert kinds == ["gathering", "pathway", "gathering"]


# ---------------------------------------------------------------------------
# Member data minimisation
# ---------------------------------------------------------------------------

class TestNoPrivateFields:
    def test_a_person_carries_only_id_name_and_avatar(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice = make_user()
        bob = make_user(name="Bob", email="bob-private@example.test")
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        person = client.get(URL).json()["contexts"][0]["people"][0]

        assert set(person.keys()) == {"id", "display_name", "avatar_url"}

    def test_nothing_private_appears_anywhere_in_the_payload(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice = make_user()
        bob = make_user(name="Bob", email="bob-private@example.test")
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        raw = client.get(URL).text.lower()

        for leaked in (
            "bob-private", "@example.test", "password", "reflection",
            "score", "rank", "match", "suspended", "cancelled",
            "joined", "created_at", "email",
        ):
            assert leaked not in raw, leaked

    def test_a_member_without_a_name_is_not_labelled_with_their_email(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """The member directory's fallback uses the email local part.
        This surface does not."""
        alice = make_user()
        bob = make_user(name=None, email="quietperson@example.test")
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        person = client.get(URL).json()["contexts"][0]["people"][0]

        assert person["display_name"] == "Member"
        assert "quietperson" not in client.get(URL).text

    def test_an_ordinary_member_has_no_avatar_and_that_is_fine(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        person = client.get(URL).json()["contexts"][0]["people"][0]

        assert person["avatar_url"] is None

    def test_a_public_creator_profile_supplies_the_avatar(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice = make_user()
        bob = make_user(name="Bob", role="creator")
        db.add(CreatorProfile(
            user_id=bob.id, display_name="Bobbie",
            avatar_url="/uploads/avatars/bob.png", is_public=True,
        ))
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        db.flush()
        as_user(alice)

        person = client.get(URL).json()["contexts"][0]["people"][0]

        assert person["display_name"] == "Bobbie"
        assert person["avatar_url"] == "/uploads/avatars/bob.png"

    def test_a_private_creator_profile_does_not(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice = make_user()
        bob = make_user(name="Bob", role="creator")
        db.add(CreatorProfile(
            user_id=bob.id, display_name="Hidden",
            avatar_url="/uploads/avatars/bob.png", is_public=False,
        ))
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        db.flush()
        as_user(alice)

        person = client.get(URL).json()["contexts"][0]["people"][0]

        assert person["avatar_url"] is None
        assert person["display_name"] == "Bob"


# ---------------------------------------------------------------------------
# Finite
# ---------------------------------------------------------------------------

class TestFinite:
    def test_there_is_no_paging_or_search_mechanism(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        body = client.get(URL).json()

        for browsing in ("cursor", "next", "page", "total", "offset", "query"):
            assert browsing not in body

    def test_unknown_query_parameters_change_nothing(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        plain = client.get(URL).json()
        poked = client.get(
            URL, params={"sort": "score", "limit": "1000", "q": "bob"}
        ).json()

        assert plain == poked

    def test_truncated_is_false_in_the_ordinary_case(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        ev = _upcoming(make_event, space)
        for u in (alice, bob):
            _join(db, u, space); _book(db, u, ev)
        as_user(alice)

        assert client.get(URL).json()["truncated"] is False

    def test_the_context_bound_is_applied_deterministically(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        from app.ways_to_connect.routes import MAX_CONTEXTS

        alice, bob = make_user(), make_user(name="Bob")
        space = _visible_space(make_space)
        _join(db, alice, space); _join(db, bob, space)
        for i in range(MAX_CONTEXTS + 5):
            ev = _upcoming(make_event, space, days=i + 1, title=f"G{i:03d}")
            _book(db, alice, ev); _book(db, bob, ev)
        as_user(alice)

        first = client.get(URL).json()
        second = client.get(URL).json()

        assert len(first["contexts"]) == MAX_CONTEXTS
        assert first["truncated"] is True
        assert first == second, "the cut must be stable across calls"
