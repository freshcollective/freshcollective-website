"""Cancelled and archived Gatherings stay out of active Creator lists.

``Event.status`` (active | cancelled | archived) and ``Event.is_published``
are separate axes. The Series occurrence list read publication state
alone, so a cancelled EMBODY session sat among its siblings wearing a
PUBLISHED badge while its own page said it had been cancelled. The member
Series page has always applied both.

Everything here also pins the other half of the contract: nothing is
deleted, detached or rewritten to achieve the hiding. The rows keep their
``series_id``, their bookings, their attendance and their cancellation
history, and they remain reachable through the creator archive scope.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

import app.models.community_care  # noqa: F401
from app.creator._gathering_series_routes import (
    list_series_gatherings,
    list_gathering_series,
)
from app.creator.routes import list_events
from app.models.platform import (
    Event,
    EventBooking,
    EventSeries,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def series_setup(db, make_user, make_space, make_event):
    """A Collective with a Series holding one occurrence of each status."""
    creator = make_user(role="creator", name="Ada Leader")
    space = make_space(creator=creator)
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=creator.id, space_id=space.id,
        role=SpaceRole.creator, status=SpaceMembershipStatus.active,
    ))
    series = EventSeries(
        id=_uid("es"), space_id=space.id, slug="term-4-2026",
        title="Term 4 2026", status="published",
        starts_at=datetime.utcnow(), ends_at=datetime.utcnow() + timedelta(days=90),
    )
    db.add(series)
    db.flush()

    future = datetime.utcnow() + timedelta(days=10)
    active = make_event(space=space, title="Active session", series_id=series.id,
                        starts_at=future, ends_at=future + timedelta(hours=1))
    cancelled = make_event(space=space, title="Cancelled session", series_id=series.id,
                           starts_at=future + timedelta(days=1),
                           ends_at=future + timedelta(days=1, hours=1),
                           status="cancelled")
    archived = make_event(space=space, title="Archived session", series_id=series.id,
                          starts_at=future + timedelta(days=2),
                          ends_at=future + timedelta(days=2, hours=1),
                          status="archived")
    past = datetime.utcnow() - timedelta(days=5)
    past_active = make_event(space=space, title="Past session", series_id=series.id,
                            starts_at=past, ends_at=past + timedelta(hours=1))
    db.commit()
    return space, creator, series, active, cancelled, archived, past_active


def _titles(rows) -> set[str]:
    return {r["title"] for r in rows}


# ---------------------------------------------------------------------------
# Gatherings in this Series
# ---------------------------------------------------------------------------

class TestTheSeriesOccurrenceList:
    def test_a_cancelled_occurrence_is_not_listed(self, db, series_setup):
        """The reported bug: it appeared here, badged PUBLISHED."""
        space, creator, series, *_ = series_setup

        rows = list_series_gatherings(space.slug, series.slug, db=db, current_user=creator)

        assert "Cancelled session" not in _titles(rows)

    def test_an_archived_occurrence_is_not_listed(self, db, series_setup):
        space, creator, series, *_ = series_setup

        rows = list_series_gatherings(space.slug, series.slug, db=db, current_user=creator)

        assert "Archived session" not in _titles(rows)

    def test_active_occurrences_are_listed(self, db, series_setup):
        space, creator, series, *_ = series_setup

        rows = list_series_gatherings(space.slug, series.slug, db=db, current_user=creator)

        assert "Active session" in _titles(rows)

    def test_a_past_but_active_occurrence_is_still_listed(self, db, series_setup):
        """No time fence, deliberately. A Series is a term, and a Creator
        mid-term must still see the sessions that have already run."""
        space, creator, series, *_ = series_setup

        rows = list_series_gatherings(space.slug, series.slug, db=db, current_user=creator)

        assert "Past session" in _titles(rows)

    def test_the_list_is_exactly_the_active_ones(self, db, series_setup):
        space, creator, series, *_ = series_setup

        rows = list_series_gatherings(space.slug, series.slug, db=db, current_user=creator)

        assert _titles(rows) == {"Active session", "Past session"}

    def test_a_cancelled_occurrence_is_still_published(self, db, series_setup):
        """Pins WHY filtering was needed rather than reading a flag: the
        two axes are independent and publication state does not change."""
        *_, cancelled, _archived, _past = series_setup

        db.refresh(cancelled)
        assert cancelled.is_published is True
        assert cancelled.status == "cancelled"


# ---------------------------------------------------------------------------
# The count that labels the list
# ---------------------------------------------------------------------------

class TestTheSeriesOccurrenceCount:
    def test_the_count_matches_the_list(self, db, series_setup):
        space, creator, series, *_ = series_setup

        rows = list_gathering_series(space.slug, db=db, current_user=creator)
        listed = list_series_gatherings(space.slug, series.slug, db=db, current_user=creator)

        row = next(r for r in rows if r["id"] == series.id)
        assert row["gathering_count"] == len(listed) == 2, (
            "the count told the Creator a different number than the list showed"
        )


# ---------------------------------------------------------------------------
# Nothing is destroyed to achieve the hiding
# ---------------------------------------------------------------------------

class TestTheRecordsSurvive:
    def test_the_rows_remain_with_their_series_relationship(self, db, series_setup):
        space, creator, series, _active, cancelled, archived, _past = series_setup

        list_series_gatherings(space.slug, series.slug, db=db, current_user=creator)

        for ev in (cancelled, archived):
            db.refresh(ev)
            assert ev.series_id == series.id, "series_id must never be rewritten to hide a row"
        assert db.query(Event).filter(Event.series_id == series.id).count() == 4

    def test_bookings_and_attendance_on_a_cancelled_occurrence_survive(
        self, db, make_user, series_setup
    ):
        space, creator, series, _active, cancelled, *_ = series_setup
        member = make_user(name="Attendee")
        db.add(EventBooking(
            id=_uid("eb"), event_id=cancelled.id, user_id=member.id,
            status="confirmed", attendance_status="attended",
        ))
        db.commit()

        list_series_gatherings(space.slug, series.slug, db=db, current_user=creator)

        booking = db.query(EventBooking).filter(EventBooking.event_id == cancelled.id).one()
        assert booking.status == "confirmed"
        assert booking.attendance_status == "attended"


# ---------------------------------------------------------------------------
# They remain reachable where history lives
# ---------------------------------------------------------------------------

class TestTheCreatorArchiveStillHoldsThem:
    def test_a_future_cancelled_occurrence_is_in_the_archive(self, db, series_setup):
        space, creator, *_ = series_setup

        rows = list_events(space.slug, scope="archive", db=db, current_user=creator)

        assert "Cancelled session" in _titles(rows)

    def test_a_future_archived_occurrence_is_in_the_archive(self, db, series_setup):
        """The hole this closes. ``upcoming`` excludes non-active rows and
        ``archive`` only took past-or-cancelled, so a Gathering archived
        while still in the future was unreachable in Creator Studio."""
        space, creator, *_ = series_setup

        rows = list_events(space.slug, scope="archive", db=db, current_user=creator)

        assert "Archived session" in _titles(rows)

    def test_every_occurrence_is_reachable_through_one_scope_or_the_other(
        self, db, series_setup
    ):
        space, creator, *_ = series_setup

        upcoming = _titles(list_events(space.slug, scope="upcoming", db=db, current_user=creator))
        archive = _titles(list_events(space.slug, scope="archive", db=db, current_user=creator))

        assert upcoming | archive == {
            "Active session", "Cancelled session", "Archived session", "Past session",
        }
        assert upcoming.isdisjoint(archive), "a Gathering should sit in one scope, not both"


# ---------------------------------------------------------------------------
# The Collective Overview snapshot
# ---------------------------------------------------------------------------

class TestTheUpcomingScope:
    def test_upcoming_excludes_cancelled_and_archived(self, db, series_setup):
        """What made the EMBODY Overview read "31 upcoming gatherings": the
        card counted an unscoped fetch, which returns every status."""
        space, creator, *_ = series_setup

        rows = list_events(space.slug, scope="upcoming", db=db, current_user=creator)

        assert _titles(rows) == {"Active session"}

    def test_unscoped_still_returns_everything(self, db, series_setup):
        """Pinned because the Overview's bug was the *default*: omitting
        the scope returns all statuses, and callers must ask."""
        space, creator, *_ = series_setup

        rows = list_events(space.slug, db=db, current_user=creator)

        assert len(_titles(rows)) == 4

    def test_a_live_in_progress_gathering_counts_as_upcoming(
        self, db, make_space, make_user, make_event
    ):
        """``end_marker > now``, not ``starts_at > now`` — the platform's
        definition, and the small difference from the old client-side count."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=creator.id, space_id=space.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
        ))
        now = datetime.utcnow()
        make_event(space=space, title="Happening now",
                   starts_at=now - timedelta(minutes=30),
                   ends_at=now + timedelta(minutes=30))
        db.commit()

        rows = list_events(space.slug, scope="upcoming", db=db, current_user=creator)

        assert "Happening now" in _titles(rows)


# ---------------------------------------------------------------------------
# The member archive is deliberately narrower
# ---------------------------------------------------------------------------

class TestMemberVisibilityIsUnchanged:
    def test_a_future_archived_gathering_does_not_appear_to_members(
        self, db, make_user, series_setup
    ):
        """Archiving is how a Creator takes something off the member-facing
        schedule. Widening the creator archive must not hand members
        something they could not see before."""
        from app.spaces.routes import list_events as member_list_events

        space, _creator, *_ = series_setup
        member = make_user(name="Member")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        ))
        db.commit()

        rows = member_list_events(space.slug, scope="archive", db=db, current_user=member)
        titles = {getattr(r, "title", None) or r["title"] for r in rows}

        assert "Archived session" not in titles
        # A future cancelled one still does — long-standing behaviour.
        assert "Cancelled session" in titles
