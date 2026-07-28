"""
Tests for ``RecognitionService`` — the Discovery, Connection & Belonging
pillar's derivation of what two people share at read time.

The service reads current platform state; there is no stored graph. So
the tests build the substrate (memberships, enrolments, bookings) with
small inline helpers and assert what recognitions come out.

Every privacy / eligibility rule the service enforces has at least one
dedicated test — the whole point of the service existing is that
callers can trust these guards without re-implementing them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

# Ensure community_care is registered so User's FKs resolve when this
# file runs in isolation.
import app.models.community_care  # noqa: F401
from app.models.platform import (
    BookingStatus,
    Enrollment,
    EnrollmentStatus,
    EventBooking,
    Pathway,
    PathwayStatus,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.recognition_service import (
    Recognition,
    RecognitionService,
    SharedCollective,
    SharedGathering,
    SharedPathway,
)


# ---------------------------------------------------------------------------
# Inline substrate helpers (kept in the test file rather than conftest —
# only Recognition tests need them right now)
# ---------------------------------------------------------------------------

def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _visible_space(make_space, **overrides):
    """make_space that defaults to ``show_member_directory=True`` — the
    Recognition-visible baseline. Individual tests flip it back off to
    prove the guard."""
    overrides.setdefault("show_member_directory", True)
    return make_space(**overrides)


def _add_membership(db, user, space, *, status=SpaceMembershipStatus.active, role=SpaceRole.learner):
    row = SpaceMembership(
        id=_uid("sm"),
        user_id=user.id,
        space_id=space.id,
        role=role,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def _add_pathway(db, space, *, title="A Pathway", slug=None, status=PathwayStatus.active):
    row = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=slug or f"pathway-{uuid.uuid4().hex[:8]}",
        title=title,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def _add_enrolment(db, user, pathway, *, status=EnrollmentStatus.active):
    row = Enrollment(
        id=_uid("en"),
        user_id=user.id,
        pathway_id=pathway.id,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def _add_booking(db, user, event, *, status=BookingStatus.confirmed):
    row = EventBooking(
        id=_uid("bk"),
        event_id=event.id,
        user_id=user.id,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Recognition dataclass
# ---------------------------------------------------------------------------

class TestRecognitionShape:
    def test_empty_recognition_is_empty(self):
        r = Recognition(other_user_id="u1")
        assert r.is_empty is True

    def test_recognition_with_a_collective_is_not_empty(self):
        r = Recognition(
            other_user_id="u1",
            collectives=(SharedCollective(collective_id="s1", slug="s", name="S"),),
        )
        assert r.is_empty is False

    def test_recognition_is_immutable(self):
        r = Recognition(other_user_id="u1")
        with pytest.raises(Exception):
            r.other_user_id = "u2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RecognitionService.between — happy paths
# ---------------------------------------------------------------------------

class TestBetweenHappyPaths:
    def test_two_users_share_one_collective(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)

        r = RecognitionService.between(db, alice.id, bob.id)

        assert r.other_user_id == bob.id
        assert len(r.collectives) == 1
        assert r.collectives[0].collective_id == space.id
        assert r.collectives[0].slug == space.slug
        assert r.collectives[0].name == space.name
        assert r.pathways == ()
        assert r.gatherings == ()

    def test_shared_pathway_is_surfaced(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space, title="REAL Journey")
        _add_enrolment(db, alice, pw)
        _add_enrolment(db, bob, pw)

        r = RecognitionService.between(db, alice.id, bob.id)

        assert len(r.pathways) == 1
        assert r.pathways[0].pathway_id == pw.id
        assert r.pathways[0].title == "REAL Journey"
        assert r.pathways[0].collective_id == space.id

    def test_shared_gathering_is_surfaced(self, db, make_user, make_space, make_event):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = make_event(space=space, title="Thursday circle")
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        r = RecognitionService.between(db, alice.id, bob.id)

        assert len(r.gatherings) == 1
        assert r.gatherings[0].gathering_id == ev.id
        assert r.gatherings[0].title == "Thursday circle"

    def test_multiple_collectives_are_sorted_by_name(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        s_b = _visible_space(make_space, name="B Space")
        s_a = _visible_space(make_space, name="A Space")
        for s in (s_a, s_b):
            _add_membership(db, alice, s)
            _add_membership(db, bob, s)

        r = RecognitionService.between(db, alice.id, bob.id)

        assert [c.name for c in r.collectives] == ["A Space", "B Space"]


# ---------------------------------------------------------------------------
# RecognitionService.between — privacy guards
# ---------------------------------------------------------------------------

class TestBetweenPrivacyGuards:
    def test_same_user_returns_empty(self, db, make_user, make_space):
        alice = make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)

        r = RecognitionService.between(db, alice.id, alice.id)
        assert r.is_empty

    def test_suspended_viewer_returns_empty(self, db, make_user, make_space):
        alice = make_user(suspended_at=datetime.utcnow())
        bob = make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)

        assert RecognitionService.between(db, alice.id, bob.id).is_empty

    def test_suspended_other_returns_empty(self, db, make_user, make_space):
        alice = make_user()
        bob = make_user(suspended_at=datetime.utcnow())
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)

        assert RecognitionService.between(db, alice.id, bob.id).is_empty

    def test_cancelled_account_returns_empty(self, db, make_user, make_space):
        alice = make_user()
        bob = make_user(cancelled_at=datetime.utcnow())
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)

        assert RecognitionService.between(db, alice.id, bob.id).is_empty

    def test_suspended_until_in_past_does_not_exclude(self, db, make_user, make_space):
        # Auto-lift already fired.
        alice = make_user(
            suspended_at=datetime.utcnow() - timedelta(days=10),
            suspended_until=datetime.utcnow() - timedelta(days=1),
        )
        bob = make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)

        r = RecognitionService.between(db, alice.id, bob.id)
        assert len(r.collectives) == 1

    def test_missing_user_returns_empty(self, db, make_user):
        alice = make_user()
        assert RecognitionService.between(db, alice.id, "nonexistent").is_empty


class TestBetweenSubstrateGuards:
    def test_paused_membership_excluded(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space, status=SpaceMembershipStatus.paused)

        assert RecognitionService.between(db, alice.id, bob.id).is_empty

    def test_removed_membership_excluded(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space, status=SpaceMembershipStatus.removed)

        assert RecognitionService.between(db, alice.id, bob.id).is_empty

    def test_directory_hidden_collective_excluded(self, db, make_user, make_space):
        # show_member_directory=False is the creator saying "learners
        # can't see each other" — Recognition must honour that.
        alice, bob = make_user(), make_user()
        space = make_space(show_member_directory=False)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)

        assert RecognitionService.between(db, alice.id, bob.id).is_empty

    def test_directory_hidden_collective_also_hides_its_pathways(
        self, db, make_user, make_space
    ):
        alice, bob = make_user(), make_user()
        space = make_space(show_member_directory=False)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        _add_enrolment(db, alice, pw)
        _add_enrolment(db, bob, pw)

        r = RecognitionService.between(db, alice.id, bob.id)
        assert r.pathways == ()

    def test_archived_collective_excluded(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space, status="archived")
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)

        assert RecognitionService.between(db, alice.id, bob.id).is_empty

    def test_closed_collective_excluded(self, db, make_user, make_space):
        # Community Care Stage 2D terminal outcome. The Collective is over.
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space, closed_at=datetime.utcnow())
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)

        assert RecognitionService.between(db, alice.id, bob.id).is_empty

    def test_paused_enrolment_excluded(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        _add_enrolment(db, alice, pw)
        _add_enrolment(db, bob, pw, status=EnrollmentStatus.paused)

        r = RecognitionService.between(db, alice.id, bob.id)
        assert r.pathways == ()
        # Underlying collective still shared, so the collective row survives.
        assert len(r.collectives) == 1

    def test_cancelled_booking_excluded(self, db, make_user, make_space, make_event):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = make_event(space=space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev, status=BookingStatus.cancelled)

        r = RecognitionService.between(db, alice.id, bob.id)
        assert r.gatherings == ()

    def test_pending_payment_booking_excluded(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = make_event(space=space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev, status=BookingStatus.pending_payment)

        r = RecognitionService.between(db, alice.id, bob.id)
        assert r.gatherings == ()


# ---------------------------------------------------------------------------
# RecognitionService.for_user
# ---------------------------------------------------------------------------

class TestForUser:
    def test_returns_empty_when_no_co_members(self, db, make_user, make_space):
        alice = make_user()
        _add_membership(db, alice, _visible_space(make_space))
        assert RecognitionService.for_user(db, alice.id) == []

    def test_returns_one_recognition_per_other_user(
        self, db, make_user, make_space
    ):
        alice = make_user()
        bob, carol = make_user(), make_user()
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)
        _add_membership(db, carol, s)

        results = RecognitionService.for_user(db, alice.id)

        others = {r.other_user_id for r in results}
        assert others == {bob.id, carol.id}
        assert all(not r.is_empty for r in results)

    def test_excludes_suspended_other_from_results(
        self, db, make_user, make_space
    ):
        alice = make_user()
        bob = make_user()
        carol = make_user(suspended_at=datetime.utcnow())
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)
        _add_membership(db, carol, s)

        results = RecognitionService.for_user(db, alice.id)
        assert {r.other_user_id for r in results} == {bob.id}

    def test_suspended_viewer_returns_empty_list(self, db, make_user, make_space):
        alice = make_user(suspended_at=datetime.utcnow())
        bob = make_user()
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)

        assert RecognitionService.for_user(db, alice.id) == []

    def test_directory_hidden_collective_yields_no_candidates(
        self, db, make_user, make_space
    ):
        alice, bob = make_user(), make_user()
        s = make_space(show_member_directory=False)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)

        assert RecognitionService.for_user(db, alice.id) == []

    def test_results_are_sorted_by_other_user_id(
        self, db, make_user, make_space
    ):
        alice = make_user()
        # Force a predictable order regardless of insertion order.
        others = [make_user(id=f"u_{c}") for c in ("cccc", "aaaa", "bbbb")]
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        for u in others:
            _add_membership(db, u, s)

        result_ids = [r.other_user_id for r in RecognitionService.for_user(db, alice.id)]
        assert result_ids == sorted(result_ids)


# ---------------------------------------------------------------------------
# Result shape — focused objects, not ORM rows
# ---------------------------------------------------------------------------

class TestResultShape:
    def test_collectives_are_shared_collective_dataclass(
        self, db, make_user, make_space
    ):
        alice, bob = make_user(), make_user()
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)

        r = RecognitionService.between(db, alice.id, bob.id)
        assert isinstance(r.collectives[0], SharedCollective)
        # No ORM leakage — Space is not a SharedCollective.
        assert not hasattr(r.collectives[0], "creator_id")

    def test_pathways_are_shared_pathway_dataclass(
        self, db, make_user, make_space
    ):
        alice, bob = make_user(), make_user()
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)
        pw = _add_pathway(db, s)
        _add_enrolment(db, alice, pw)
        _add_enrolment(db, bob, pw)

        r = RecognitionService.between(db, alice.id, bob.id)
        assert isinstance(r.pathways[0], SharedPathway)

    def test_gatherings_are_shared_gathering_dataclass(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)
        ev = make_event(space=s)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        r = RecognitionService.between(db, alice.id, bob.id)
        assert isinstance(r.gatherings[0], SharedGathering)
