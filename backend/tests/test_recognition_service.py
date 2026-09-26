"""
Tests for ``RecognitionService`` — the Discovery, Connection & Belonging
pillar's derivation of what two people share at read time.

The service reads current platform state; there is no stored graph. So
the tests build the substrate (memberships, enrolments, bookings,
attendance, step progress) with small inline helpers and assert what
recognitions come out.

Every privacy / eligibility rule the service enforces has at least one
dedicated test — the whole point of the service existing is that
callers can trust these guards without re-implementing them.

Time is injected rather than mocked. ``NOW`` below is the clock every
test derives its fixtures and assertions from, so window behaviour is
deterministic and readable on the page.
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
    PathwayStep,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    StepProgress,
)
from app.services.recognition_service import (
    RECENT_ATTENDANCE_DAYS,
    REPEATED_ATTENDANCE_DAYS,
    Recognition,
    RecognitionService,
    SharedCollective,
    SharedGathering,
    SharedGatheringBasis,
    SharedPathway,
)


#: The clock every test in this file reasons against.
NOW = datetime(2026, 6, 1, 12, 0, 0)


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


def _add_step(db, pathway, *, position=0, title="A Step"):
    row = PathwayStep(
        id=_uid("pst"),
        pathway_id=pathway.id,
        slug=f"step-{uuid.uuid4().hex[:8]}",
        title=title,
        position=position,
        content_type="text",
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


def _complete_step(db, user, step, *, completed_at=None):
    """A genuinely completed step — what 'started the Pathway' means."""
    row = StepProgress(
        id=_uid("sp"),
        user_id=user.id,
        step_id=step.id,
        completed_at=completed_at or NOW - timedelta(days=1),
    )
    db.add(row)
    db.flush()
    return row


def _draft_reflection(db, user, step):
    """A StepProgress row written by saving a *draft* reflection:
    ``completed_at`` stays NULL. Private journalling — must never make
    someone recognisable."""
    row = StepProgress(
        id=_uid("sp"),
        user_id=user.id,
        step_id=step.id,
        completed_at=None,
        reflection_text="a private draft",
    )
    db.add(row)
    db.flush()
    return row


def _start_pathway(db, user, pathway, step):
    """Enrol a user and have them genuinely begin the Pathway."""
    _add_enrolment(db, user, pathway)
    _complete_step(db, user, step)


def _add_booking(db, user, event, *, status=BookingStatus.confirmed, attendance=None):
    row = EventBooking(
        id=_uid("bk"),
        event_id=event.id,
        user_id=user.id,
        status=status,
        attendance_status=attendance,
    )
    db.add(row)
    db.flush()
    return row


def _upcoming_event(make_event, space, *, days_ahead=7, **overrides):
    return make_event(
        space=space,
        starts_at=NOW + timedelta(days=days_ahead),
        ends_at=NOW + timedelta(days=days_ahead, hours=1),
        **overrides,
    )


def _past_event(make_event, space, *, days_ago, finalised=True, **overrides):
    ev = make_event(
        space=space,
        starts_at=NOW - timedelta(days=days_ago),
        ends_at=NOW - timedelta(days=days_ago) + timedelta(hours=1),
        **overrides,
    )
    if finalised:
        ev.attendance_completed_at = NOW - timedelta(days=days_ago) + timedelta(hours=2)
    return ev


def _both_attended(db, a, b, event):
    _add_booking(db, a, event, attendance="attended")
    _add_booking(db, b, event, attendance="attended")


def _between(db, a, b, *, now=NOW):
    return RecognitionService.between(db, a.id, b.id, now=now)


# ---------------------------------------------------------------------------
# Recognition dataclass
# ---------------------------------------------------------------------------

class TestRecognitionShape:
    def test_empty_recognition_is_empty(self):
        r = Recognition(other_user_id="u1")
        assert r.is_empty is True

    def test_a_collective_alone_does_not_make_a_recognition_non_empty(self):
        """Co-membership is the boundary that makes Recognition
        permissible, not evidence worth surfacing."""
        r = Recognition(
            other_user_id="u1",
            collectives=(
                SharedCollective(
                    collective_id="s1", slug="s", name="S",
                    timezone="Australia/Melbourne",
                ),
            ),
        )
        assert r.is_empty is True

    def test_a_pathway_makes_a_recognition_non_empty(self):
        r = Recognition(
            other_user_id="u1",
            pathways=(
                SharedPathway(
                    pathway_id="p1", slug="p", title="P", collective_id="s1"
                ),
            ),
        )
        assert r.is_empty is False

    def test_a_gathering_makes_a_recognition_non_empty(self):
        r = Recognition(
            other_user_id="u1",
            gatherings=(
                SharedGathering(
                    gathering_id="e1",
                    title="E",
                    starts_at=NOW,
                    collective_id="s1",
                    basis=SharedGatheringBasis.UPCOMING,
                ),
            ),
        )
        assert r.is_empty is False

    def test_recognition_is_immutable(self):
        r = Recognition(other_user_id="u1")
        with pytest.raises(Exception):
            r.other_user_id = "u2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Shared Collective is the boundary, never the evidence
# ---------------------------------------------------------------------------

class TestCollectiveIsBoundaryNotEvidence:
    def test_shared_collective_alone_yields_no_recognition(
        self, db, make_user, make_space
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)

        r = _between(db, alice, bob)

        assert r.is_empty is True
        assert r.pathways == ()
        assert r.gatherings == ()

    def test_collective_size_is_irrelevant(self, db, make_user, make_space):
        """No threshold exists. A two-person Collective is as
        insufficient as a two-hundred-person one."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)

        assert _between(db, alice, bob).is_empty is True

    def test_collective_rides_along_as_context_when_evidence_exists(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space, name="The Grove")
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        r = _between(db, alice, bob)

        assert r.is_empty is False
        assert [c.name for c in r.collectives] == ["The Grove"]
        assert r.gatherings[0].collective_id == space.id

    def test_multiple_collectives_are_sorted_by_name(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        s_b = _visible_space(make_space, name="B Space")
        s_a = _visible_space(make_space, name="A Space")
        for s in (s_a, s_b):
            _add_membership(db, alice, s)
            _add_membership(db, bob, s)
        ev = _upcoming_event(make_event, s_a)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        r = _between(db, alice, bob)

        assert [c.name for c in r.collectives] == ["A Space", "B Space"]


# ---------------------------------------------------------------------------
# Upcoming Gatherings — a shared confirmed booking, until it starts
# ---------------------------------------------------------------------------

class TestUpcomingGatherings:
    def test_both_confirmed_on_an_upcoming_gathering(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space, title="Thursday circle")
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        r = _between(db, alice, bob)

        assert len(r.gatherings) == 1
        assert r.gatherings[0].gathering_id == ev.id
        assert r.gatherings[0].title == "Thursday circle"
        assert r.gatherings[0].basis is SharedGatheringBasis.UPCOMING

    def test_one_confirmed_one_cancelled_yields_nothing(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev, status=BookingStatus.cancelled)

        assert _between(db, alice, bob).gatherings == ()

    def test_one_confirmed_one_pending_payment_yields_nothing(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev, status=BookingStatus.pending_payment)

        assert _between(db, alice, bob).gatherings == ()

    def test_only_one_person_booked_yields_nothing(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)

        assert _between(db, alice, bob).gatherings == ()

    def test_booking_stops_being_evidence_once_the_gathering_starts(
        self, db, make_user, make_space, make_event
    ):
        """The same substrate, read from two different clocks. Before it
        starts, a shared booking is a shared intention. Afterwards, only
        attendance can say whether anything was shared — and attendance
        was never finalised here."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space, days_ahead=3)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        before = _between(db, alice, bob, now=NOW)
        after = _between(db, alice, bob, now=NOW + timedelta(days=4))

        assert len(before.gatherings) == 1
        assert after.gatherings == ()
        assert after.is_empty is True

    def test_a_cancelled_upcoming_gathering_yields_nothing(
        self, db, make_user, make_space, make_event
    ):
        """Two people holding bookings for something that is not
        happening are not about to share anything."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space, status="cancelled")
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        r = _between(db, alice, bob)

        assert r.gatherings == ()
        assert r.is_empty is True

    def test_an_archived_upcoming_gathering_yields_nothing(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space, status="archived")
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert _between(db, alice, bob).gatherings == ()

    def test_cancelling_the_gathering_withdraws_the_recognition(
        self, db, make_user, make_space, make_event
    ):
        """Derived, not stored: the recognition is there while the
        Gathering is on and gone on the next read once it is not."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert len(_between(db, alice, bob).gatherings) == 1

        ev.status = "cancelled"
        db.flush()

        assert _between(db, alice, bob).gatherings == ()

    def test_upcoming_gatherings_are_soonest_first(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        far = _upcoming_event(make_event, space, days_ahead=30, title="Far")
        near = _upcoming_event(make_event, space, days_ahead=2, title="Near")
        for ev in (far, near):
            _add_booking(db, alice, ev)
            _add_booking(db, bob, ev)

        r = _between(db, alice, bob)

        assert [g.title for g in r.gatherings] == ["Near", "Far"]


# ---------------------------------------------------------------------------
# Past Gatherings — attendance, finalised, never inferred
# ---------------------------------------------------------------------------

class TestPastAttendedGatherings:
    def test_finalised_and_both_attended_yields_recognition(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _past_event(make_event, space, days_ago=10, title="Last Tuesday")
        _both_attended(db, alice, bob, ev)

        r = _between(db, alice, bob)

        assert len(r.gatherings) == 1
        assert r.gatherings[0].gathering_id == ev.id
        assert r.gatherings[0].basis is SharedGatheringBasis.ATTENDED

    def test_attended_plus_no_show_yields_nothing(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _past_event(make_event, space, days_ago=10)
        _add_booking(db, alice, ev, attendance="attended")
        _add_booking(db, bob, ev, attendance="no_show")

        assert _between(db, alice, bob).gatherings == ()

    def test_both_no_show_yields_nothing(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _past_event(make_event, space, days_ago=10)
        _add_booking(db, alice, ev, attendance="no_show")
        _add_booking(db, bob, ev, attendance="no_show")

        assert _between(db, alice, bob).gatherings == ()

    def test_unfinalised_attendance_is_never_inferred(
        self, db, make_user, make_space, make_event
    ):
        """Both booked, both even marked attended — but the creator
        never finished the roster, so the marks are provisional and we
        do not claim a shared experience from them."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _past_event(make_event, space, days_ago=10, finalised=False)
        _both_attended(db, alice, bob, ev)

        assert _between(db, alice, bob).gatherings == ()

    def test_unfinalised_booking_only_is_not_evidence(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _past_event(make_event, space, days_ago=10, finalised=False)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert _between(db, alice, bob).is_empty is True

    def test_pending_attendance_is_not_attendance(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _past_event(make_event, space, days_ago=10)
        _add_booking(db, alice, ev, attendance="attended")
        _add_booking(db, bob, ev, attendance="pending")

        assert _between(db, alice, bob).gatherings == ()

    def test_a_later_cancelled_booking_does_not_erase_real_attendance(
        self, db, make_user, make_space, make_event
    ):
        """Refunds, credits and administrative cancellations happen
        after the fact. None of them mean the person was not there."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _past_event(make_event, space, days_ago=10, title="The one they came to")
        _add_booking(db, alice, ev, attendance="attended")
        _add_booking(
            db, bob, ev,
            status=BookingStatus.cancelled,
            attendance="attended",
        )

        r = _between(db, alice, bob)

        assert len(r.gatherings) == 1
        assert r.gatherings[0].title == "The one they came to"
        assert r.gatherings[0].basis is SharedGatheringBasis.ATTENDED

    def test_attendance_outranks_booking_status_on_both_sides(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _past_event(make_event, space, days_ago=10)
        for user in (alice, bob):
            _add_booking(
                db, user, ev,
                status=BookingStatus.cancelled,
                attendance="attended",
            )

        assert len(_between(db, alice, bob).gatherings) == 1

    def test_a_cancelled_booking_without_attendance_still_yields_nothing(
        self, db, make_user, make_space, make_event
    ):
        """The relaxation is about the attendance mark outranking the
        booking — not about dropping the requirement for a mark."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _past_event(make_event, space, days_ago=10)
        _add_booking(db, alice, ev, attendance="attended")
        _add_booking(db, bob, ev, status=BookingStatus.cancelled)

        assert _between(db, alice, bob).gatherings == ()

    def test_recurrence_linkage_is_preserved_for_later_phrasing(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        series = _uid("rs")
        ev = _past_event(
            make_event, space, days_ago=10, recurrence_series_id=series
        )
        _both_attended(db, alice, bob, ev)

        r = _between(db, alice, bob)

        assert r.gatherings[0].recurrence_series_id == series


# ---------------------------------------------------------------------------
# Past co-attendance decay
# ---------------------------------------------------------------------------

class TestAttendanceRecency:
    def test_single_attendance_inside_the_recent_window_survives(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _past_event(make_event, space, days_ago=RECENT_ATTENDANCE_DAYS - 5)
        _both_attended(db, alice, bob, ev)

        assert len(_between(db, alice, bob).gatherings) == 1

    def test_single_attendance_outside_the_recent_window_drops(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _past_event(make_event, space, days_ago=RECENT_ATTENDANCE_DAYS + 5)
        _both_attended(db, alice, bob, ev)

        r = _between(db, alice, bob)

        assert r.gatherings == ()
        assert r.is_empty is True

    def test_repeated_attendance_survives_the_single_attendance_window(
        self, db, make_user, make_space, make_event
    ):
        """Two shared attendances, both older than the single-occurrence
        window. A pattern, not a coincidence — so both stand."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        for days in (RECENT_ATTENDANCE_DAYS + 10, RECENT_ATTENDANCE_DAYS + 40):
            _both_attended(
                db, alice, bob, _past_event(make_event, space, days_ago=days)
            )

        r = _between(db, alice, bob)

        assert len(r.gatherings) == 2
        assert all(g.basis is SharedGatheringBasis.ATTENDED for g in r.gatherings)

    def test_repeated_attendance_drops_outside_the_extended_window(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        for days in (REPEATED_ATTENDANCE_DAYS + 10, REPEATED_ATTENDANCE_DAYS + 40):
            _both_attended(
                db, alice, bob, _past_event(make_event, space, days_ago=days)
            )

        r = _between(db, alice, bob)

        assert r.gatherings == ()
        assert r.is_empty is True

    def test_one_inside_extended_window_alone_still_needs_recency(
        self, db, make_user, make_space, make_event
    ):
        """One attendance inside the extended window but outside the
        recent one, plus one that has already aged out entirely. Only
        one qualifies as repeated evidence, so the recent-window rule
        applies to it and nothing survives."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        _both_attended(
            db, alice, bob,
            _past_event(make_event, space, days_ago=RECENT_ATTENDANCE_DAYS + 30),
        )
        _both_attended(
            db, alice, bob,
            _past_event(make_event, space, days_ago=REPEATED_ATTENDANCE_DAYS + 30),
        )

        assert _between(db, alice, bob).gatherings == ()

    def test_attended_gatherings_are_most_recent_first(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        _both_attended(
            db, alice, bob,
            _past_event(make_event, space, days_ago=60, title="Older"),
        )
        _both_attended(
            db, alice, bob,
            _past_event(make_event, space, days_ago=5, title="Newer"),
        )

        r = _between(db, alice, bob)

        assert [g.title for g in r.gatherings] == ["Newer", "Older"]

    def test_upcoming_precede_attended(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        soon = _upcoming_event(make_event, space, days_ahead=3, title="Soon")
        _add_booking(db, alice, soon)
        _add_booking(db, bob, soon)
        _both_attended(
            db, alice, bob,
            _past_event(make_event, space, days_ago=5, title="Recent"),
        )

        r = _between(db, alice, bob)

        assert [g.title for g in r.gatherings] == ["Soon", "Recent"]
        assert r.gatherings[0].basis is SharedGatheringBasis.UPCOMING
        assert r.gatherings[1].basis is SharedGatheringBasis.ATTENDED


# ---------------------------------------------------------------------------
# Pathways — a deliberate shared commitment, once both have begun
# ---------------------------------------------------------------------------

class TestSharedPathways:
    def test_both_enrolled_and_both_started(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space, title="REAL Journey")
        step = _add_step(db, pw)
        _start_pathway(db, alice, pw, step)
        _start_pathway(db, bob, pw, step)

        r = _between(db, alice, bob)

        assert len(r.pathways) == 1
        assert r.pathways[0].pathway_id == pw.id
        assert r.pathways[0].title == "REAL Journey"
        assert r.pathways[0].collective_id == space.id

    def test_enrolled_but_neither_started_yields_nothing(
        self, db, make_user, make_space
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        _add_step(db, pw)
        _add_enrolment(db, alice, pw)
        _add_enrolment(db, bob, pw)

        r = _between(db, alice, bob)

        assert r.pathways == ()
        assert r.is_empty is True

    def test_only_one_started_yields_nothing(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        step = _add_step(db, pw)
        _start_pathway(db, alice, pw, step)
        _add_enrolment(db, bob, pw)

        assert _between(db, alice, bob).pathways == ()

    def test_each_may_have_started_a_different_step(
        self, db, make_user, make_space
    ):
        """'Started' is about the Pathway, not about walking in step."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        first = _add_step(db, pw, position=0)
        second = _add_step(db, pw, position=1)
        _add_enrolment(db, alice, pw)
        _complete_step(db, alice, first)
        _add_enrolment(db, bob, pw)
        _complete_step(db, bob, second)

        assert len(_between(db, alice, bob).pathways) == 1

    def test_progress_in_a_different_pathway_does_not_count(
        self, db, make_user, make_space
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        shared = _add_pathway(db, space, title="Shared")
        _add_step(db, shared)
        other = _add_pathway(db, space, title="Other")
        other_step = _add_step(db, other)
        _add_enrolment(db, alice, shared)
        _add_enrolment(db, bob, shared)
        # Both have completed a step — but in the wrong Pathway.
        _complete_step(db, alice, other_step)
        _complete_step(db, bob, other_step)

        assert _between(db, alice, bob).pathways == ()

    def test_a_draft_reflection_is_not_a_start(self, db, make_user, make_space):
        """Saving a private draft writes a StepProgress row with
        ``completed_at`` NULL. Private journalling must never be the
        thing that makes a member visible to someone else."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        step = _add_step(db, pw)
        _add_enrolment(db, alice, pw)
        _complete_step(db, alice, step)
        _add_enrolment(db, bob, pw)
        _draft_reflection(db, bob, step)

        assert _between(db, alice, bob).pathways == ()

    def test_paused_enrolment_excluded(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        step = _add_step(db, pw)
        _start_pathway(db, alice, pw, step)
        _add_enrolment(db, bob, pw, status=EnrollmentStatus.paused)
        _complete_step(db, bob, step)

        assert _between(db, alice, bob).pathways == ()

    def test_completed_enrolment_excluded(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        step = _add_step(db, pw)
        _start_pathway(db, alice, pw, step)
        _add_enrolment(db, bob, pw, status=EnrollmentStatus.completed)
        _complete_step(db, bob, step)

        assert _between(db, alice, bob).pathways == ()

    def test_a_started_pathway_does_not_expire_with_inactivity(
        self, db, make_user, make_space
    ):
        """No 90-day activity window. Both began it long ago, neither
        has touched it since, both enrolments are still active — the
        shared Pathway stands."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        step = _add_step(db, pw)
        long_ago = NOW - timedelta(days=400)
        _add_enrolment(db, alice, pw)
        _complete_step(db, alice, step, completed_at=long_ago)
        _add_enrolment(db, bob, pw)
        _complete_step(db, bob, step, completed_at=long_ago)

        r = _between(db, alice, bob, now=NOW)

        assert len(r.pathways) == 1


# ---------------------------------------------------------------------------
# Privacy guards — account state
# ---------------------------------------------------------------------------

class TestAccountGuards:
    def test_same_user_returns_empty(self, db, make_user, make_space):
        alice = make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)

        r = RecognitionService.between(db, alice.id, alice.id, now=NOW)
        assert r.is_empty is True

    def test_suspended_viewer_returns_empty(
        self, db, make_user, make_space, make_event
    ):
        alice = make_user(suspended_at=datetime.utcnow())
        bob = make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert _between(db, alice, bob).is_empty is True

    def test_suspended_other_returns_empty(
        self, db, make_user, make_space, make_event
    ):
        alice = make_user()
        bob = make_user(suspended_at=datetime.utcnow())
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert _between(db, alice, bob).is_empty is True

    def test_cancelled_account_returns_empty(
        self, db, make_user, make_space, make_event
    ):
        alice = make_user()
        bob = make_user(cancelled_at=datetime.utcnow())
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert _between(db, alice, bob).is_empty is True

    def test_suspended_until_in_past_does_not_exclude(
        self, db, make_user, make_space, make_event
    ):
        alice = make_user()
        bob = make_user(
            suspended_at=datetime.utcnow() - timedelta(days=10),
            suspended_until=datetime.utcnow() - timedelta(days=1),
        )
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert _between(db, alice, bob).is_empty is False

    def test_missing_user_returns_empty(self, db, make_user):
        alice = make_user()
        r = RecognitionService.between(db, alice.id, "nobody", now=NOW)
        assert r.is_empty is True


# ---------------------------------------------------------------------------
# Privacy guards — the Collective gate suppresses everything under it
# ---------------------------------------------------------------------------

class TestCollectiveGate:
    def _pair_with_everything(self, db, make_user, make_space, make_event, space):
        """Two members of ``space`` sharing a Pathway and both an
        upcoming and an attended Gathering — the maximal substrate, so a
        guard that suppresses it is suppressing everything."""
        alice, bob = make_user(), make_user()
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        step = _add_step(db, pw)
        _start_pathway(db, alice, pw, step)
        _start_pathway(db, bob, pw, step)
        soon = _upcoming_event(make_event, space)
        _add_booking(db, alice, soon)
        _add_booking(db, bob, soon)
        _both_attended(
            db, alice, bob, _past_event(make_event, space, days_ago=5)
        )
        return alice, bob

    def test_baseline_is_rich(self, db, make_user, make_space, make_event):
        """Guards the guards: if this ever stops producing evidence, the
        suppression tests below would pass for the wrong reason."""
        space = _visible_space(make_space)
        alice, bob = self._pair_with_everything(
            db, make_user, make_space, make_event, space
        )

        r = _between(db, alice, bob)

        assert len(r.pathways) == 1
        assert len(r.gatherings) == 2

    def test_directory_hidden_collective_suppresses_everything(
        self, db, make_user, make_space, make_event
    ):
        space = make_space(show_member_directory=False)
        alice, bob = self._pair_with_everything(
            db, make_user, make_space, make_event, space
        )

        r = _between(db, alice, bob)

        assert r.is_empty is True
        assert r.collectives == ()
        assert r.pathways == ()
        assert r.gatherings == ()

    def test_archived_collective_suppresses_everything(
        self, db, make_user, make_space, make_event
    ):
        space = _visible_space(make_space, status="archived")
        alice, bob = self._pair_with_everything(
            db, make_user, make_space, make_event, space
        )

        assert _between(db, alice, bob).is_empty is True

    def test_closed_collective_suppresses_everything(
        self, db, make_user, make_space, make_event
    ):
        space = _visible_space(make_space, closed_at=datetime.utcnow())
        alice, bob = self._pair_with_everything(
            db, make_user, make_space, make_event, space
        )

        assert _between(db, alice, bob).is_empty is True

    def test_paused_membership_suppresses_everything(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space, status=SpaceMembershipStatus.paused)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert _between(db, alice, bob).is_empty is True

    def test_removed_membership_suppresses_everything(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space, status=SpaceMembershipStatus.removed)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert _between(db, alice, bob).is_empty is True


# ---------------------------------------------------------------------------
# The member's own switch — "Include me in Ways to Connect"
# ---------------------------------------------------------------------------

def _pair_sharing_a_gathering(db, make_user, make_space, make_event, **user_kw):
    """Two members of a visible Collective booked onto the same
    upcoming Gathering — the simplest thing that is a Recognition."""
    alice = make_user(**user_kw.pop("alice", {}))
    bob = make_user(**user_kw.pop("bob", {}))
    space = _visible_space(make_space)
    _add_membership(db, alice, space)
    _add_membership(db, bob, space)
    ev = _upcoming_event(make_event, space)
    _add_booking(db, alice, ev)
    _add_booking(db, bob, ev)
    return alice, bob


def _pair_sharing_a_pathway(db, make_user, make_space, **user_kw):
    alice = make_user(**user_kw.pop("alice", {}))
    bob = make_user(**user_kw.pop("bob", {}))
    space = _visible_space(make_space)
    _add_membership(db, alice, space)
    _add_membership(db, bob, space)
    pw = _add_pathway(db, space)
    step = _add_step(db, pw)
    _start_pathway(db, alice, pw, step)
    _start_pathway(db, bob, pw, step)
    return alice, bob


class TestWaysToConnectOptOut:
    def test_both_opted_in_behaves_normally(
        self, db, make_user, make_space, make_event
    ):
        """The baseline the rest of this class is measured against."""
        alice, bob = _pair_sharing_a_gathering(db, make_user, make_space, make_event)

        assert _between(db, alice, bob).is_empty is False

    def test_viewer_opted_out_sees_nothing(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = _pair_sharing_a_gathering(
            db, make_user, make_space, make_event,
            alice={"ways_to_connect_enabled": False},
        )

        assert _between(db, alice, bob).is_empty is True

    def test_other_opted_out_is_not_surfaced(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = _pair_sharing_a_gathering(
            db, make_user, make_space, make_event,
            bob={"ways_to_connect_enabled": False},
        )

        assert _between(db, alice, bob).is_empty is True

    def test_opting_out_is_symmetric(
        self, db, make_user, make_space, make_event
    ):
        """One person switching off empties the result for both of
        them. Recognition is a shared fact, so there is no direction in
        which it survives."""
        alice, bob = _pair_sharing_a_gathering(
            db, make_user, make_space, make_event,
            bob={"ways_to_connect_enabled": False},
        )

        assert _between(db, alice, bob).is_empty is True
        assert _between(db, bob, alice).is_empty is True

    def test_it_applies_to_pathway_evidence_too(self, db, make_user, make_space):
        """Not a Gathering-specific guard — it is checked before any
        derivation runs."""
        alice, bob = _pair_sharing_a_pathway(
            db, make_user, make_space,
            bob={"ways_to_connect_enabled": False},
        )

        assert _between(db, alice, bob).is_empty is True
        assert _between(db, bob, alice).is_empty is True

    def test_switching_off_removes_recognition_on_the_next_read(
        self, db, make_user, make_space, make_event
    ):
        """Derived, not stored: nothing to clean up, and the change is
        visible the moment anyone looks again."""
        alice, bob = _pair_sharing_a_gathering(db, make_user, make_space, make_event)
        assert _between(db, alice, bob).is_empty is False

        bob.ways_to_connect_enabled = False
        db.flush()

        assert _between(db, alice, bob).is_empty is True

    def test_switching_back_on_restores_it(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = _pair_sharing_a_gathering(
            db, make_user, make_space, make_event,
            bob={"ways_to_connect_enabled": False},
        )
        assert _between(db, alice, bob).is_empty is True

        bob.ways_to_connect_enabled = True
        db.flush()

        assert _between(db, alice, bob).is_empty is False

    def test_for_user_is_empty_for_an_opted_out_viewer(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = _pair_sharing_a_gathering(
            db, make_user, make_space, make_event,
            alice={"ways_to_connect_enabled": False},
        )

        assert RecognitionService.for_user(db, alice.id, now=NOW) == []

    def test_for_user_drops_an_opted_out_candidate(
        self, db, make_user, make_space, make_event
    ):
        """Bob and Carol both share the Gathering with Alice. Only
        Carol still takes part."""
        alice, bob, carol = make_user(), make_user(
            ways_to_connect_enabled=False
        ), make_user()
        space = _visible_space(make_space)
        ev = _upcoming_event(make_event, space)
        for user in (alice, bob, carol):
            _add_membership(db, user, space)
            _add_booking(db, user, ev)

        results = RecognitionService.for_user(db, alice.id, now=NOW)

        assert {r.other_user_id for r in results} == {carol.id}

    def test_an_opted_out_member_sees_nobody_and_is_seen_by_nobody(
        self, db, make_user, make_space, make_event
    ):
        """Both halves of the symmetry through the list entry point."""
        alice, bob = _pair_sharing_a_gathering(
            db, make_user, make_space, make_event,
            bob={"ways_to_connect_enabled": False},
        )

        assert RecognitionService.for_user(db, bob.id, now=NOW) == []
        assert RecognitionService.for_user(db, alice.id, now=NOW) == []


# ---------------------------------------------------------------------------
# Symmetry — structural, but pinned rather than trusted
# ---------------------------------------------------------------------------

def _evidence_fingerprint(r: Recognition):
    """Everything about a Recognition except whose point of view it is."""
    return (
        sorted(c.collective_id for c in r.collectives),
        sorted(p.pathway_id for p in r.pathways),
        sorted((g.gathering_id, g.basis) for g in r.gatherings),
    )


class TestSymmetry:
    def test_upcoming_gathering_is_symmetric(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        forward = _between(db, alice, bob)
        backward = _between(db, bob, alice)

        assert forward.other_user_id == bob.id
        assert backward.other_user_id == alice.id
        assert _evidence_fingerprint(forward) == _evidence_fingerprint(backward)

    def test_attended_gathering_is_symmetric(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        _both_attended(
            db, alice, bob, _past_event(make_event, space, days_ago=10)
        )

        assert _evidence_fingerprint(_between(db, alice, bob)) == (
            _evidence_fingerprint(_between(db, bob, alice))
        )

    def test_repeated_attendance_is_symmetric(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        for days in (RECENT_ATTENDANCE_DAYS + 10, RECENT_ATTENDANCE_DAYS + 40):
            _both_attended(
                db, alice, bob, _past_event(make_event, space, days_ago=days)
            )

        assert _evidence_fingerprint(_between(db, alice, bob)) == (
            _evidence_fingerprint(_between(db, bob, alice))
        )

    def test_pathway_is_symmetric(self, db, make_user, make_space):
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        step = _add_step(db, pw)
        _start_pathway(db, alice, pw, step)
        _start_pathway(db, bob, pw, step)

        assert _evidence_fingerprint(_between(db, alice, bob)) == (
            _evidence_fingerprint(_between(db, bob, alice))
        )

    def test_asymmetric_substrate_is_symmetrically_empty(
        self, db, make_user, make_space
    ):
        """Only one side has started. Neither direction may surface it."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        pw = _add_pathway(db, space)
        step = _add_step(db, pw)
        _start_pathway(db, alice, pw, step)
        _add_enrolment(db, bob, pw)

        assert _between(db, alice, bob).is_empty is True
        assert _between(db, bob, alice).is_empty is True

    def test_collective_gate_is_symmetric(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        space = make_space(show_member_directory=False)
        _add_membership(db, alice, space)
        _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert _between(db, alice, bob).is_empty is True
        assert _between(db, bob, alice).is_empty is True


# ---------------------------------------------------------------------------
# RecognitionService.for_user
# ---------------------------------------------------------------------------

class TestForUser:
    def test_returns_empty_when_no_co_members(self, db, make_user, make_space):
        alice = make_user()
        _add_membership(db, alice, _visible_space(make_space))
        assert RecognitionService.for_user(db, alice.id, now=NOW) == []

    def test_co_membership_alone_yields_no_results(
        self, db, make_user, make_space
    ):
        """Co-members are candidates, not recognitions."""
        alice, bob = make_user(), make_user()
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)

        assert RecognitionService.for_user(db, alice.id, now=NOW) == []

    def test_returns_one_recognition_per_other_user_with_evidence(
        self, db, make_user, make_space, make_event
    ):
        alice = make_user()
        bob, carol, dave = make_user(), make_user(), make_user()
        s = _visible_space(make_space)
        for u in (alice, bob, carol, dave):
            _add_membership(db, u, s)
        ev = _upcoming_event(make_event, s)
        for u in (alice, bob, carol):
            _add_booking(db, u, ev)
        # dave is a co-member with no shared evidence.

        results = RecognitionService.for_user(db, alice.id, now=NOW)

        assert {r.other_user_id for r in results} == {bob.id, carol.id}
        assert all(not r.is_empty for r in results)

    def test_excludes_suspended_other_from_results(
        self, db, make_user, make_space, make_event
    ):
        alice = make_user()
        bob = make_user()
        carol = make_user(suspended_at=datetime.utcnow())
        s = _visible_space(make_space)
        for u in (alice, bob, carol):
            _add_membership(db, u, s)
        ev = _upcoming_event(make_event, s)
        for u in (alice, bob, carol):
            _add_booking(db, u, ev)

        results = RecognitionService.for_user(db, alice.id, now=NOW)
        assert {r.other_user_id for r in results} == {bob.id}

    def test_suspended_viewer_returns_empty_list(
        self, db, make_user, make_space, make_event
    ):
        alice = make_user(suspended_at=datetime.utcnow())
        bob = make_user()
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)
        ev = _upcoming_event(make_event, s)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert RecognitionService.for_user(db, alice.id, now=NOW) == []

    def test_directory_hidden_collective_yields_no_candidates(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        s = make_space(show_member_directory=False)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)
        ev = _upcoming_event(make_event, s)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert RecognitionService.for_user(db, alice.id, now=NOW) == []

    def test_results_are_sorted_by_other_user_id(
        self, db, make_user, make_space, make_event
    ):
        alice = make_user()
        # Force a predictable order regardless of insertion order.
        others = [make_user(id=f"u_{c}") for c in ("cccc", "aaaa", "bbbb")]
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        ev = _upcoming_event(make_event, s)
        _add_booking(db, alice, ev)
        for u in others:
            _add_membership(db, u, s)
            _add_booking(db, u, ev)

        result_ids = [
            r.other_user_id
            for r in RecognitionService.for_user(db, alice.id, now=NOW)
        ]
        assert result_ids == sorted(result_ids)
        assert len(result_ids) == 3

    def test_now_is_threaded_through_to_the_windows(
        self, db, make_user, make_space, make_event
    ):
        """The same substrate read from a later clock loses the
        upcoming Gathering — proof ``for_user`` does not quietly fall
        back to the wall clock."""
        alice, bob = make_user(), make_user()
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)
        ev = _upcoming_event(make_event, s, days_ahead=3)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        assert len(RecognitionService.for_user(db, alice.id, now=NOW)) == 1
        assert RecognitionService.for_user(
            db, alice.id, now=NOW + timedelta(days=4)
        ) == []


# ---------------------------------------------------------------------------
# Batched for_user — parity with the pairwise derivation, and a query
# count that does not follow the size of the Collective
# ---------------------------------------------------------------------------

def _count_statements(db):
    """Context manager counting SQL statements on the session's bind.

    Counts what is actually sent to the database, so a lazy load
    inside the derivation is caught the same as a deliberate query.
    """
    from contextlib import contextmanager
    from sqlalchemy import event

    @contextmanager
    def _counter():
        bind = db.get_bind()
        seen: list[str] = []

        def _on_execute(conn, cursor, statement, params, context, executemany):
            seen.append(statement)

        event.listen(bind, "before_cursor_execute", _on_execute)
        try:
            yield seen
        finally:
            event.remove(bind, "before_cursor_execute", _on_execute)

    return _counter()


def _rich_fixture(db, make_user, make_space, make_event):
    """One viewer and one peer of every kind the rules distinguish.

    Everything hangs off a single visible Collective so the privacy
    boundary is constant and the only variable is the evidence.
    """
    space = _visible_space(make_space, name="The Grove")
    viewer = make_user()
    _add_membership(db, viewer, space)

    peers = {}

    def _peer(key, **user_kw):
        u = make_user(**user_kw)
        _add_membership(db, u, space)
        peers[key] = u
        return u

    # Upcoming Gathering together.
    upcoming_peer = _peer("upcoming")
    soon = _upcoming_event(make_event, space, days_ahead=5, title="Next Tuesday")
    _add_booking(db, viewer, soon)
    _add_booking(db, upcoming_peer, soon)

    # One attended past Gathering, inside the recent window.
    attended_peer = _peer("attended")
    recent = _past_event(make_event, space, days_ago=10, title="Ten days ago")
    _both_attended(db, viewer, attended_peer, recent)

    # Repeated co-attendance, both older than the single-occurrence
    # window — kept because there are two of them.
    repeat_peer = _peer("repeated")
    for days in (RECENT_ATTENDANCE_DAYS + 20, RECENT_ATTENDANCE_DAYS + 60):
        _both_attended(
            db, viewer, repeat_peer,
            _past_event(make_event, space, days_ago=days, title=f"Circle {days}"),
        )

    # Shared Pathway, both genuinely started.
    pathway_peer = _peer("pathway")
    pw = _add_pathway(db, space, title="Life in Alignment")
    step = _add_step(db, pw)
    _start_pathway(db, viewer, pw, step)
    _start_pathway(db, pathway_peer, pw, step)

    # Collective-only — a candidate, never a recognition.
    _peer("collective_only")

    # Opted out of Ways to Connect.
    opted_out = _peer("opted_out", ways_to_connect_enabled=False)
    oo_ev = _upcoming_event(make_event, space, days_ahead=6)
    _add_booking(db, viewer, oo_ev)
    _add_booking(db, opted_out, oo_ev)

    # Suspended, and cancelled.
    for key, kw in (
        ("suspended", {"suspended_at": datetime.utcnow()}),
        ("cancelled", {"cancelled_at": datetime.utcnow()}),
    ):
        u = _peer(key, **kw)
        ev = _upcoming_event(make_event, space, days_ahead=6)
        _add_booking(db, viewer, ev)
        _add_booking(db, u, ev)

    # Marked absent at a finalised Gathering.
    no_show = _peer("no_show")
    ns = _past_event(make_event, space, days_ago=8)
    _add_booking(db, viewer, ns, attendance="attended")
    _add_booking(db, no_show, ns, attendance="no_show")

    # Both present, but the creator never finished the roster.
    unfinalised = _peer("unfinalised")
    uf = _past_event(make_event, space, days_ago=8, finalised=False)
    _both_attended(db, viewer, unfinalised, uf)

    # Booked together on a Gathering that has been cancelled.
    inactive = _peer("inactive_event")
    dead = _upcoming_event(make_event, space, days_ahead=9, status="cancelled")
    _add_booking(db, viewer, dead)
    _add_booking(db, inactive, dead)

    # A single co-attendance that has aged out.
    expired = _peer("expired")
    _both_attended(
        db, viewer, expired,
        _past_event(make_event, space, days_ago=RECENT_ATTENDANCE_DAYS + 30),
    )

    db.flush()
    return viewer, peers


class TestBatchedParity:
    """``for_user`` must be ``between`` for everyone, not a second
    opinion about what counts."""

    def test_matches_pairwise_derivation_across_a_mixed_fixture(
        self, db, make_user, make_space, make_event
    ):
        viewer, peers = _rich_fixture(db, make_user, make_space, make_event)

        batched = RecognitionService.for_user(db, viewer.id, now=NOW)

        pairwise = []
        for peer in peers.values():
            r = RecognitionService.between(db, viewer.id, peer.id, now=NOW)
            if not r.is_empty:
                pairwise.append(r)
        pairwise.sort(key=lambda r: r.other_user_id)

        assert [r.other_user_id for r in batched] == [
            r.other_user_id for r in pairwise
        ]
        for got, want in zip(batched, pairwise):
            assert _evidence_fingerprint(got) == _evidence_fingerprint(want)

    def test_only_the_peers_with_real_evidence_survive(
        self, db, make_user, make_space, make_event
    ):
        viewer, peers = _rich_fixture(db, make_user, make_space, make_event)

        got = {r.other_user_id for r in RecognitionService.for_user(db, viewer.id, now=NOW)}

        assert got == {
            peers["upcoming"].id,
            peers["attended"].id,
            peers["repeated"].id,
            peers["pathway"].id,
        }
        for excluded in (
            "collective_only", "opted_out", "suspended", "cancelled",
            "no_show", "unfinalised", "inactive_event", "expired",
        ):
            assert peers[excluded].id not in got, excluded

    def test_evidence_detail_survives_batching(
        self, db, make_user, make_space, make_event
    ):
        viewer, peers = _rich_fixture(db, make_user, make_space, make_event)
        by_peer = {
            r.other_user_id: r
            for r in RecognitionService.for_user(db, viewer.id, now=NOW)
        }

        up = by_peer[peers["upcoming"].id]
        assert [g.title for g in up.gatherings] == ["Next Tuesday"]
        assert up.gatherings[0].basis is SharedGatheringBasis.UPCOMING

        at = by_peer[peers["attended"].id]
        assert at.gatherings[0].basis is SharedGatheringBasis.ATTENDED

        assert len(by_peer[peers["repeated"].id].gatherings) == 2

        pw = by_peer[peers["pathway"].id]
        assert [p.title for p in pw.pathways] == ["Life in Alignment"]

    def test_collective_context_rides_along(
        self, db, make_user, make_space, make_event
    ):
        viewer, peers = _rich_fixture(db, make_user, make_space, make_event)
        by_peer = {
            r.other_user_id: r
            for r in RecognitionService.for_user(db, viewer.id, now=NOW)
        }

        assert [c.name for c in by_peer[peers["pathway"].id].collectives] == [
            "The Grove"
        ]

    def test_results_stay_sorted_by_peer(
        self, db, make_user, make_space, make_event
    ):
        viewer, _ = _rich_fixture(db, make_user, make_space, make_event)
        ids = [r.other_user_id for r in RecognitionService.for_user(db, viewer.id, now=NOW)]
        assert ids == sorted(ids)

    def test_a_peer_who_left_the_collective_is_not_recognised(
        self, db, make_user, make_space, make_event
    ):
        """The visible-space set belongs to the viewer. A peer holding
        a booking in a Collective they have since left must not be
        surfaced through it — the batched joins check their membership
        rather than inheriting the viewer's."""
        alice, bob = make_user(), make_user()
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        membership = _add_membership(db, bob, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)
        assert len(RecognitionService.for_user(db, alice.id, now=NOW)) == 1

        membership.status = SpaceMembershipStatus.removed
        db.flush()

        assert RecognitionService.for_user(db, alice.id, now=NOW) == []
        assert _between(db, alice, bob).is_empty is True


class TestBatchedQueryCount:
    """The reason this path exists at all."""

    def _collective_of(self, db, make_user, make_space, make_event, *, peers):
        space = _visible_space(make_space)
        viewer = make_user()
        _add_membership(db, viewer, space)
        ev = _upcoming_event(make_event, space)
        _add_booking(db, viewer, ev)
        for _ in range(peers):
            u = make_user()
            _add_membership(db, u, space)
            _add_booking(db, u, ev)
        db.flush()
        return viewer

    def test_query_count_does_not_follow_member_count(
        self, db, make_user, make_space, make_event
    ):
        small = self._collective_of(db, make_user, make_space, make_event, peers=3)
        large = self._collective_of(db, make_user, make_space, make_event, peers=60)

        with _count_statements(db) as small_sql:
            small_results = RecognitionService.for_user(db, small.id, now=NOW)
        with _count_statements(db) as large_sql:
            large_results = RecognitionService.for_user(db, large.id, now=NOW)

        assert len(small_results) == 3
        assert len(large_results) == 60

        # Twenty times the people. The statement count must not move
        # with them — a small constant difference would still be a
        # per-candidate query in disguise.
        assert len(large_sql) == len(small_sql), (
            f"query count grew with membership: "
            f"{len(small_sql)} for 3 peers, {len(large_sql)} for 60"
        )
        # Bounded well below the candidate count either way. The exact
        # number is deliberately not pinned — this guards against N+1
        # returning, not against a future sixth or seventh statement.
        assert len(large_sql) < 20, f"unexpectedly many statements: {len(large_sql)}"

    def test_an_empty_result_is_cheap(
        self, db, make_user, make_space, make_event
    ):
        """An opted-out viewer must not pay for a derivation."""
        alice = make_user(ways_to_connect_enabled=False)
        space = _visible_space(make_space)
        _add_membership(db, alice, space)
        for _ in range(10):
            _add_membership(db, make_user(), space)
        db.flush()

        with _count_statements(db) as sql:
            assert RecognitionService.for_user(db, alice.id, now=NOW) == []

        assert len(sql) <= 2, f"expected an early exit, saw {len(sql)} statements"


# ---------------------------------------------------------------------------
# Result shape — focused objects, not ORM rows
# ---------------------------------------------------------------------------

class TestResultShape:
    def test_collectives_are_shared_collective_dataclass(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)
        ev = _upcoming_event(make_event, s)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        r = _between(db, alice, bob)
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
        step = _add_step(db, pw)
        _start_pathway(db, alice, pw, step)
        _start_pathway(db, bob, pw, step)

        r = _between(db, alice, bob)
        assert isinstance(r.pathways[0], SharedPathway)

    def test_gatherings_are_shared_gathering_dataclass(
        self, db, make_user, make_space, make_event
    ):
        alice, bob = make_user(), make_user()
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)
        ev = _upcoming_event(make_event, s)
        _add_booking(db, alice, ev)
        _add_booking(db, bob, ev)

        r = _between(db, alice, bob)
        assert isinstance(r.gatherings[0], SharedGathering)
        assert not hasattr(r.gatherings[0], "capacity")

    def test_reflection_text_never_reaches_the_result(
        self, db, make_user, make_space
    ):
        """Private journalling is not part of any Recognition."""
        alice, bob = make_user(), make_user()
        s = _visible_space(make_space)
        _add_membership(db, alice, s)
        _add_membership(db, bob, s)
        pw = _add_pathway(db, s)
        step = _add_step(db, pw)
        _add_enrolment(db, alice, pw)
        _add_enrolment(db, bob, pw)
        for u in (alice, bob):
            db.add(StepProgress(
                id=_uid("sp"), user_id=u.id, step_id=step.id,
                completed_at=NOW - timedelta(days=1),
                reflection_text="deeply private",
            ))
        db.flush()

        r = _between(db, alice, bob)

        assert len(r.pathways) == 1
        assert "deeply private" not in repr(r)
