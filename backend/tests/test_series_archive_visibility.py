"""Finding a Gathering Series after its term has finished.

EMBODY runs in terms. Once a term ends, its Series still has to be
findable — its sessions, bookings and attendance are the record of what
happened.

What was wrong
--------------
Two things, both presentation, neither a missing row.

The Archives page fetched events and nothing else, so a Series had
nowhere to appear there and every Series — finished, archived, running,
draft — sat together in the band on Upcoming. And the archive listed
every past occurrence individually, so a thirty-session term read as
thirty unrelated Gatherings.

What a Series' life looks like
------------------------------
Stored status is ``draft`` / ``published`` / ``archived``. There is no
``completed``: a term that finished last month is still ``published``
until somebody archives it. So "finished" is a question about dates and
"put away" is a question about status, and ``services/series_lifecycle``
answers both at **read time** — nothing here writes, and opening a list
changes no row.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_series_archive_visibility.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import (
    get_creator_user,
    get_current_user,
    get_verified_creator_user,
)
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    BookingStatus,
    Event,
    EventBooking,
    EventSeries,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.series_lifecycle import (
    ARCHIVE_LIFECYCLES,
    UPCOMING_LIFECYCLES,
    classify_series,
)

NOW = datetime(2026, 11, 3, 12, 0, 0)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def creator(make_user):
    return make_user(role="creator")


@pytest.fixture
def space(make_space, creator):
    return make_space(creator=creator)


@pytest.fixture
def client(db, creator):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: creator
    app.dependency_overrides[get_creator_user] = lambda: creator
    app.dependency_overrides[get_verified_creator_user] = lambda: creator
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(db, user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_creator_user] = lambda: user
    app.dependency_overrides[get_verified_creator_user] = lambda: user
    return TestClient(app)


def make_series(db, space, title, *, status="published",
                starts_days=-90, ends_days=-10, **kw) -> EventSeries:
    now = datetime.utcnow()
    row = EventSeries(
        id=_uid("es"), space_id=space.id, title=title,
        slug=f"s-{uuid.uuid4().hex[:8]}",
        starts_at=now + timedelta(days=starts_days),
        ends_at=None if ends_days is None else now + timedelta(days=ends_days),
        status=status,
        **kw,
    )
    db.add(row)
    db.flush()
    return row


def series_url(space, scope: str | None = None) -> str:
    base = f"/api/creator/spaces/{space.slug}/gathering-series"
    return f"{base}?scope={scope}" if scope else base


def listed(client, space, scope: str | None = None) -> list[dict]:
    r = client.get(series_url(space, scope))
    assert r.status_code == 200, r.text
    return r.json()


def titles(rows: list[dict]) -> list[str]:
    return [row["title"] for row in rows]


# ---------------------------------------------------------------------------
# The classifier
# ---------------------------------------------------------------------------


class TestTheLifecycleRules:
    @pytest.mark.parametrize("status,starts,ends,expected", [
        # A term still to come.
        ("published", NOW + timedelta(days=10), NOW + timedelta(days=80), "scheduled"),
        # A term running now.
        ("published", NOW - timedelta(days=10), NOW + timedelta(days=80), "running"),
        # Every session has passed, but nobody archived it.
        ("published", NOW - timedelta(days=90), NOW - timedelta(days=10), "completed"),
        # An ongoing circle with no end date — never completes on its own.
        ("published", NOW - timedelta(days=400), None, "running"),
        # Put away explicitly, before its scheduled end.
        ("archived", NOW - timedelta(days=10), NOW + timedelta(days=80), "archived"),
        # Put away after it finished.
        ("archived", NOW - timedelta(days=90), NOW - timedelta(days=10), "archived"),
        # A draft with past dates is still a draft.
        ("draft", NOW - timedelta(days=90), NOW - timedelta(days=10), "draft"),
        # A draft with future dates.
        ("draft", NOW + timedelta(days=10), NOW + timedelta(days=80), "draft"),
    ])
    def test_each_state(self, status, starts, ends, expected):
        assert classify_series(
            status=status, starts_at=starts, ends_at=ends, now=NOW,
        ) == expected

    def test_status_wins_over_dates_in_both_directions(self):
        """Archiving early archives it; a draft that has 'finished' is
        not completed."""
        future = {"starts_at": NOW + timedelta(days=5),
                  "ends_at": NOW + timedelta(days=50)}
        past = {"starts_at": NOW - timedelta(days=50),
                "ends_at": NOW - timedelta(days=5)}
        assert classify_series(status="archived", now=NOW, **future) == "archived"
        assert classify_series(status="draft", now=NOW, **past) == "draft"

    def test_an_unknown_stored_status_is_still_reachable(self):
        """A row carrying a value this module has not met must be
        classified, not hidden."""
        out = classify_series(
            status="something_new", starts_at=NOW - timedelta(days=5),
            ends_at=None, now=NOW,
        )
        assert out in UPCOMING_LIFECYCLES | ARCHIVE_LIFECYCLES

    def test_a_series_with_no_dates_at_all_does_not_vanish(self):
        out = classify_series(
            status="published", starts_at=None, ends_at=None, now=NOW,
        )
        assert out in UPCOMING_LIFECYCLES

    def test_the_two_scopes_cover_every_lifecycle(self):
        """No state can fall between the two views, which is how a
        Series became unreachable in the first place."""
        from app.services.series_lifecycle import LIFECYCLES

        assert set(LIFECYCLES) == UPCOMING_LIFECYCLES | ARCHIVE_LIFECYCLES
        assert not (UPCOMING_LIFECYCLES & ARCHIVE_LIFECYCLES)


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


class TestWhatTheArchiveScopeReturns:
    @pytest.fixture
    def every_state(self, db, space):
        rows = {
            "future": make_series(db, space, "Term 1 2027",
                                  starts_days=30, ends_days=120),
            "running": make_series(db, space, "Term 4 2026",
                                   starts_days=-10, ends_days=40),
            "completed": make_series(db, space, "Term 3 2026",
                                     starts_days=-120, ends_days=-20),
            "archived": make_series(db, space, "Term 2 2026",
                                    status="archived",
                                    starts_days=-240, ends_days=-140),
            "archived_early": make_series(db, space, "Cancelled Pilot",
                                          status="archived",
                                          starts_days=-5, ends_days=60),
            "draft": make_series(db, space, "Term 1 2027 Draft",
                                 status="draft",
                                 starts_days=200, ends_days=260),
            "ongoing": make_series(db, space, "Open Circle",
                                   starts_days=-400, ends_days=None),
        }
        db.commit()
        return rows

    def test_a_completed_term_is_in_the_archive(
        self, client, db, space, every_state,
    ):
        """The reported bug. EMBODY Term 3 finished and was nowhere."""
        assert "Term 3 2026" in titles(listed(client, space, "archive"))

    def test_an_explicitly_archived_series_is_in_the_archive(
        self, client, db, space, every_state,
    ):
        assert "Term 2 2026" in titles(listed(client, space, "archive"))

    def test_one_archived_before_its_end_date_is_too(
        self, client, db, space, every_state,
    ):
        assert "Cancelled Pilot" in titles(listed(client, space, "archive"))

    def test_current_and_future_series_stay_out_of_the_archive(
        self, client, db, space, every_state,
    ):
        archive = titles(listed(client, space, "archive"))
        for title in ("Term 1 2027", "Term 4 2026", "Open Circle"):
            assert title not in archive, title

    def test_a_draft_stays_out_of_the_archive(
        self, client, db, space, every_state,
    ):
        assert "Term 1 2027 Draft" not in titles(listed(client, space, "archive"))

    def test_upcoming_holds_the_rest(self, client, db, space, every_state):
        upcoming = titles(listed(client, space, "upcoming"))
        assert "Term 1 2027" in upcoming
        assert "Term 4 2026" in upcoming
        assert "Open Circle" in upcoming
        # Drafts stay where a creator creates them — there is no
        # separate Drafts view and this change does not invent one.
        assert "Term 1 2027 Draft" in upcoming
        assert "Term 3 2026" not in upcoming
        assert "Term 2 2026" not in upcoming

    def test_every_series_is_in_exactly_one_scope(
        self, client, db, space, every_state,
    ):
        upcoming = set(titles(listed(client, space, "upcoming")))
        archive = set(titles(listed(client, space, "archive")))
        everything = set(titles(listed(client, space)))
        assert upcoming | archive == everything
        assert not (upcoming & archive)

    def test_omitting_the_scope_returns_everything_as_before(
        self, client, db, space, every_state,
    ):
        """Other callers of this endpoint pass no scope."""
        assert len(listed(client, space)) == 7

    def test_an_unrecognised_scope_shows_everything(
        self, client, db, space, every_state,
    ):
        """A typo in a query string should show too much, not nothing."""
        assert len(listed(client, space, "nonsense")) == 7

    def test_the_lifecycle_is_reported(self, client, db, space, every_state):
        by_title = {r["title"]: r for r in listed(client, space)}
        assert by_title["Term 3 2026"]["lifecycle"] == "completed"
        assert by_title["Term 2 2026"]["lifecycle"] == "archived"
        assert by_title["Term 4 2026"]["lifecycle"] == "running"
        assert by_title["Term 1 2027"]["lifecycle"] == "scheduled"
        assert by_title["Term 1 2027 Draft"]["lifecycle"] == "draft"
        assert by_title["Open Circle"]["lifecycle"] == "running"

    def test_the_stored_status_is_reported_unchanged_beside_it(
        self, client, db, space, every_state,
    ):
        """A completed term is still ``published`` in the database, and
        the payload says so — the derived value does not overwrite it."""
        row = [r for r in listed(client, space)
               if r["title"] == "Term 3 2026"][0]
        assert row["status"] == "published"
        assert row["lifecycle"] == "completed"


class TestNothingIsWrittenByReading:
    def test_listing_the_archive_changes_no_stored_status(
        self, client, db, space,
    ):
        """A term that finishes while its creator is on holiday must
        not quietly become ``archived``."""
        completed = make_series(db, space, "Term 3 2026")
        archived = make_series(db, space, "Term 2 2026", status="archived")
        db.commit()
        before = {
            s.id: (s.status, s.starts_at, s.ends_at, s.updated_at)
            for s in (completed, archived)
        }

        listed(client, space, "archive")
        listed(client, space, "upcoming")
        listed(client, space)

        db.expire_all()
        for sid, was in before.items():
            row = db.get(EventSeries, sid)
            assert (row.status, row.starts_at, row.ends_at, row.updated_at) == was

    def test_no_announcement_is_emitted(self, client, db, space):
        from app.comms.models import CommunicationEvent

        make_series(db, space, "Term 3 2026")
        db.commit()
        before = db.query(CommunicationEvent).count()
        listed(client, space, "archive")
        assert db.query(CommunicationEvent).count() == before


class TestSortingAndEdgeCases:
    def test_the_archive_is_most_recently_finished_first(
        self, client, db, space,
    ):
        make_series(db, space, "Oldest", starts_days=-400, ends_days=-300)
        make_series(db, space, "Middle", starts_days=-200, ends_days=-100)
        make_series(db, space, "Newest", starts_days=-60, ends_days=-10)
        db.commit()
        assert titles(listed(client, space, "archive")) == [
            "Newest", "Middle", "Oldest",
        ]

    def test_sorting_is_stable_across_requests(self, client, db, space):
        """Two terms sharing an end date must not swap places between
        page loads."""
        same = -30
        for n in range(5):
            make_series(db, space, f"Term {n}", starts_days=-120, ends_days=same)
        db.commit()
        first = titles(listed(client, space, "archive"))
        for _ in range(4):
            assert titles(listed(client, space, "archive")) == first

    def test_an_archived_series_with_no_end_date_still_appears(
        self, client, db, space,
    ):
        """It is archived by status, so dates cannot hide it."""
        make_series(db, space, "Open Circle, retired",
                    status="archived", starts_days=-300, ends_days=None)
        db.commit()
        assert "Open Circle, retired" in titles(listed(client, space, "archive"))

    def test_a_series_with_no_occurrences_still_appears(
        self, client, db, space,
    ):
        make_series(db, space, "Empty Term")
        db.commit()
        row = [r for r in listed(client, space, "archive")
               if r["title"] == "Empty Term"][0]
        assert row["gathering_count"] == 0

    def test_cancelled_occurrences_do_not_remove_the_series(
        self, client, db, space, make_event,
    ):
        series = make_series(db, space, "Term with cancellations")
        for _ in range(3):
            occurrence = make_event(space=space, is_published=True)
            occurrence.series_id = series.id
            occurrence.status = "cancelled"
        db.commit()
        assert "Term with cancellations" in titles(listed(client, space, "archive"))

    def test_a_legacy_series_with_no_published_at_appears(
        self, client, db, space,
    ):
        """Rows predating ``published_at`` must classify on status and
        dates alone, which is all the rule reads."""
        series = make_series(db, space, "Legacy Term")
        series.published_at = None
        db.commit()
        assert "Legacy Term" in titles(listed(client, space, "archive"))


# ---------------------------------------------------------------------------
# Occurrences
# ---------------------------------------------------------------------------


class TestOccurrencesAreNotAlsoStandaloneGatherings:
    def test_the_events_archive_still_contains_them(
        self, client, db, space, make_event,
    ):
        """The backend is unchanged here deliberately: the occurrences
        are real archived Gatherings and other callers want them. Which
        of them Creator Studio *lists* is the frontend's filter — see
        ``lib/seriesArchive``."""
        series = make_series(db, space, "Term 3 2026")
        for _ in range(3):
            occurrence = make_event(
                space=space, is_published=True,
                starts_at=datetime.utcnow() - timedelta(days=30),
                ends_at=datetime.utcnow() - timedelta(days=30, hours=-1),
            )
            occurrence.series_id = series.id
        db.commit()
        rows = client.get(
            f"/api/creator/spaces/{space.slug}/events?scope=archive").json()
        assert len([r for r in rows if r["series_id"] == series.id]) == 3

    def test_every_occurrence_reports_its_series(
        self, client, db, space, make_event,
    ):
        """What the frontend filter reads. Both relationships are on the
        payload so it can tell a Series occurrence from a bulk-created
        one with no Series."""
        series = make_series(db, space, "Term 3 2026")
        occurrence = make_event(
            space=space, is_published=True,
            starts_at=datetime.utcnow() - timedelta(days=30),
            ends_at=datetime.utcnow() - timedelta(days=30, hours=-1),
        )
        occurrence.series_id = series.id
        bulk = make_event(
            space=space, is_published=True,
            starts_at=datetime.utcnow() - timedelta(days=30),
            ends_at=datetime.utcnow() - timedelta(days=30, hours=-1),
        )
        bulk.recurrence_series_id = _uid("rs")
        db.commit()

        rows = {
            r["id"]: r for r in client.get(
                f"/api/creator/spaces/{space.slug}/events?scope=archive").json()
        }
        assert rows[occurrence.id]["series_id"] == series.id
        assert rows[bulk.id]["series_id"] is None
        assert rows[bulk.id]["recurrence_series_id"] == bulk.recurrence_series_id

    def test_the_series_count_matches_its_active_occurrences(
        self, client, db, space, make_event,
    ):
        series = make_series(db, space, "Term 3 2026")
        for _ in range(4):
            occurrence = make_event(space=space, is_published=True)
            occurrence.series_id = series.id
        cancelled = make_event(space=space, is_published=True)
        cancelled.series_id = series.id
        cancelled.status = "cancelled"
        db.commit()
        row = [r for r in listed(client, space, "archive")
               if r["title"] == "Term 3 2026"][0]
        assert row["gathering_count"] == 4


class TestHistoricalRecordsAreIntact:
    def test_bookings_attendance_and_links_survive_a_listing(
        self, client, db, space, make_event, make_user,
    ):
        """Reading a list touches nothing. Asserted over the records a
        creator opens an archived term to review."""
        series = make_series(db, space, "Term 3 2026")
        occurrence = make_event(space=space, is_published=True)
        occurrence.series_id = series.id
        attendee = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=attendee.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        booking = EventBooking(
            id=_uid("bk"), event_id=occurrence.id, user_id=attendee.id,
            status=BookingStatus.confirmed, source="manual",
            attendance_status="attended",
        )
        db.add(booking)
        db.commit()

        listed(client, space, "archive")
        listed(client, space, "upcoming")
        db.expire_all()

        still = db.get(EventBooking, booking.id)
        assert still is not None
        assert still.status == BookingStatus.confirmed
        assert still.attendance_status == "attended"
        assert still.event_id == occurrence.id
        assert db.get(Event, occurrence.id).series_id == series.id

    def test_the_occurrence_count_is_unchanged(
        self, client, db, space, make_event,
    ):
        """No replacement occurrences are generated by a read."""
        series = make_series(db, space, "Term 3 2026")
        for _ in range(3):
            occurrence = make_event(space=space, is_published=True)
            occurrence.series_id = series.id
        db.commit()
        before = db.query(Event).filter(Event.series_id == series.id).count()
        listed(client, space, "archive")
        db.expire_all()
        assert db.query(Event).filter(Event.series_id == series.id).count() == before


class TestPermissions:
    def test_a_stranger_sees_nothing(self, db, space, make_user):
        make_series(db, space, "Term 3 2026")
        db.commit()
        outsider = make_user(role="creator")
        try:
            r = as_user(db, outsider).get(series_url(space, "archive"))
            assert r.status_code in (403, 404), r.status_code
        finally:
            app.dependency_overrides.clear()

    def test_an_ordinary_member_cannot_reach_the_archive(
        self, db, space, make_user,
    ):
        make_series(db, space, "Term 3 2026")
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.commit()
        try:
            r = as_user(db, member).get(series_url(space, "archive"))
            assert r.status_code in (403, 404), r.status_code
        finally:
            app.dependency_overrides.clear()

    def test_a_moderator_may(self, db, space, make_user):
        make_series(db, space, "Term 3 2026")
        moderator = make_user(role="creator")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=moderator.id, space_id=space.id,
            role=SpaceRole.moderator, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.commit()
        try:
            r = as_user(db, moderator).get(series_url(space, "archive"))
            assert r.status_code == 200, r.text
            assert "Term 3 2026" in titles(r.json())
        finally:
            app.dependency_overrides.clear()

    def test_another_collectives_archive_is_not_visible(
        self, client, db, space, make_space,
    ):
        other = make_space()
        make_series(db, other, "Not Yours")
        make_series(db, space, "Term 3 2026")
        db.commit()
        rows = titles(listed(client, space, "archive"))
        assert "Not Yours" not in rows
        assert "Term 3 2026" in rows

    def test_an_archived_series_does_not_become_publicly_visible(
        self, db, make_space, make_event, make_user,
    ):
        """Creator archive management and member-facing visibility stay
        separate concerns."""
        from app.auth.dependencies import get_optional_user

        public_space = make_space(
            is_public=True, area_policies={"areas": {"gatherings": "public"}},
        )
        series = make_series(db, public_space, "Term 3 2026", status="archived")
        db.commit()

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: None
        try:
            r = TestClient(app).get(
                f"/api/spaces/{public_space.slug}/gathering-series/{series.slug}")
            assert r.status_code in (403, 404), r.status_code
        finally:
            app.dependency_overrides.clear()
