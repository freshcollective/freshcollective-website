"""One announcement per published experience, and none for a draft.

The rule: publicly live now, never announced before, and the creator
said yes. Each clause is asserted on its own, because each can regress
on its own.

The load-bearing test in this file is the Series one. A term of thirty
sessions must produce one email, not thirty — and the thing that
guarantees it is not the Series event but the refusal of an occurrence
to announce itself at all.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.comms.models import CommunicationEvent
from app.models.platform import Event, EventSeries, SpaceMembership, \
    SpaceMembershipStatus, SpaceRole
from app.services import publication_announcement as pub


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def kelly(make_user):
    return make_user(role="creator", name="Kelly")


@pytest.fixture
def space(make_space, kelly):
    return make_space(creator=kelly, name="Moonlit Circle")


@pytest.fixture
def join(db):
    def _join(space, user, role=SpaceRole.learner):
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=user.id, space_id=space.id,
            role=role, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()
    return _join


@pytest.fixture
def series(db, space):
    def _make(status="draft", notify=True, title="Autumn Term"):
        row = EventSeries(
            id=_uid("es"), space_id=space.id, title=title,
            slug=f"term-{uuid.uuid4().hex[:8]}",
            starts_at=datetime.utcnow() + timedelta(days=7),
            status=status, notify_members=notify,
        )
        db.add(row)
        db.flush()
        return row
    return _make


def _events(db, event_type):
    return (
        db.query(CommunicationEvent)
        .filter(CommunicationEvent.event_type == event_type)
        .all()
    )


# ---------------------------------------------------------------------------
# Standalone Gatherings
# ---------------------------------------------------------------------------


class TestDraftsAnnounceNothing:
    def test_an_unpublished_gathering(self, db, space, make_event, kelly):
        gathering = make_event(space=space, is_published=False)
        db.flush()
        assert pub.should_announce_gathering(db, gathering) is False
        assert pub.announce_gathering_if_newly_published(
            db, gathering, actor_user_id=kelly.id,
        ) is None

    def test_editing_a_draft_repeatedly(self, db, space, make_event, kelly):
        gathering = make_event(space=space, is_published=False)
        for title in ("First idea", "Second idea", "Third idea"):
            gathering.title = title
            db.flush()
            assert pub.announce_gathering_if_newly_published(
                db, gathering, actor_user_id=kelly.id,
            ) is None
        assert _events(db, pub.GATHERING_EVENT) == []

    def test_a_cancelled_gathering_is_not_an_invitation(
        self, db, space, make_event, kelly,
    ):
        gathering = make_event(space=space, is_published=True)
        gathering.status = "cancelled"
        db.flush()
        assert pub.should_announce_gathering(db, gathering) is False


class TestFirstPublication:
    def test_it_announces_once(self, db, space, make_event, kelly):
        gathering = make_event(space=space, is_published=True)
        db.flush()

        first = pub.announce_gathering_if_newly_published(
            db, gathering, actor_user_id=kelly.id,
        )
        assert first is not None
        assert first.event_type == pub.GATHERING_EVENT
        assert first.dedupe_key == pub.gathering_dedupe_key(
            gathering.id, space.id,
        )

    def test_republishing_does_not_announce_again(
        self, db, space, make_event, kelly,
    ):
        """Draft → publish → draft → publish is one announcement."""
        gathering = make_event(space=space, is_published=True)
        db.flush()
        pub.announce_gathering_if_newly_published(
            db, gathering, actor_user_id=kelly.id,
        )
        db.flush()

        gathering.is_published = False
        db.flush()
        gathering.is_published = True
        db.flush()

        assert pub.announce_gathering_if_newly_published(
            db, gathering, actor_user_id=kelly.id,
        ) is None
        assert len(_events(db, pub.GATHERING_EVENT)) == 1

    def test_later_edits_do_not_announce(
        self, db, space, make_event, kelly,
    ):
        gathering = make_event(space=space, is_published=True)
        db.flush()
        pub.announce_gathering_if_newly_published(
            db, gathering, actor_user_id=kelly.id,
        )
        db.flush()

        for title in ("Renamed", "Renamed again"):
            gathering.title = title
            db.flush()
            assert pub.announce_gathering_if_newly_published(
                db, gathering, actor_user_id=kelly.id,
            ) is None
        assert len(_events(db, pub.GATHERING_EVENT)) == 1

    def test_notify_disabled_publishes_quietly(
        self, db, space, make_event, kelly,
    ):
        gathering = make_event(space=space, is_published=True)
        gathering.notify_members = False
        db.flush()

        assert pub.should_announce_gathering(db, gathering) is False
        assert _events(db, pub.GATHERING_EVENT) == []

    def test_a_closed_collective_announces_nothing(
        self, db, space, make_event, kelly,
    ):
        gathering = make_event(space=space, is_published=True)
        space.status = "archived"
        db.flush()
        assert pub.should_announce_gathering(db, gathering) is False


class TestThePayloadIsMemberSafe:
    def test_it_carries_the_public_details(
        self, db, space, make_event, kelly,
    ):
        gathering = make_event(
            space=space, is_published=True, title="November Circle",
            venue_locality="South Croydon, VIC",
        )
        db.flush()
        event = pub.announce_gathering_if_newly_published(
            db, gathering, actor_user_id=kelly.id,
        )
        payload = event.payload
        assert payload["gathering_title"] == "November Circle"
        assert payload["venue_locality"] == "South Croydon, VIC"
        assert payload["gathering_when"], "no readable start time"

    def test_it_never_carries_the_street_address_or_join_link(
        self, db, space, make_event, kelly,
    ):
        """An announcement goes to people who have not booked."""
        gathering = make_event(
            space=space, is_published=True,
            venue_address="12 Example Street, South Croydon",
            location_url="https://zoom.example/j/123",
        )
        db.flush()
        event = pub.announce_gathering_if_newly_published(
            db, gathering, actor_user_id=kelly.id,
        )
        blob = str(event.payload)
        assert "12 Example Street" not in blob
        assert "zoom.example" not in blob


# ---------------------------------------------------------------------------
# Series, and the sessions inside them
# ---------------------------------------------------------------------------


class TestSeries:
    def test_a_draft_series_announces_nothing(self, db, series, kelly):
        row = series(status="draft")
        assert pub.should_announce_series(db, row) is False

    def test_publishing_announces_once(self, db, space, series, kelly):
        row = series(status="published")
        event = pub.announce_series_if_newly_published(
            db, row, actor_user_id=kelly.id,
        )
        assert event is not None
        assert event.dedupe_key == pub.series_dedupe_key(row.id, space.id)

    def test_editing_a_published_series_does_not_announce_again(
        self, db, series, kelly,
    ):
        row = series(status="published")
        pub.announce_series_if_newly_published(
            db, row, actor_user_id=kelly.id,
        )
        db.flush()
        row.title = "Autumn Term (revised)"
        db.flush()
        assert pub.announce_series_if_newly_published(
            db, row, actor_user_id=kelly.id,
        ) is None
        assert len(_events(db, pub.SERIES_EVENT)) == 1

    def test_notify_disabled_publishes_quietly(self, db, series, kelly):
        row = series(status="published", notify=False)
        assert pub.should_announce_series(db, row) is False

    def test_the_schedule_is_described_not_enumerated(
        self, db, space, series, make_event, kelly,
    ):
        row = series(status="published")
        for _ in range(12):
            occurrence = make_event(space=space, is_published=True)
            occurrence.series_id = row.id
        db.flush()

        event = pub.announce_series_if_newly_published(
            db, row, actor_user_id=kelly.id,
        )
        assert event.payload["session_count"] == 12


class TestOccurrencesNeverAnnounceThemselves:
    """The guarantee that a term of thirty sessions is one email."""

    def test_a_gathering_attached_to_a_series(
        self, db, space, series, make_event, kelly,
    ):
        row = series(status="published")
        occurrence = make_event(space=space, is_published=True)
        occurrence.series_id = row.id
        db.flush()
        assert pub.should_announce_gathering(db, occurrence) is False

    def test_a_bulk_recurrence_occurrence(
        self, db, space, make_event, kelly,
    ):
        """``recurrence_series_id`` is the low-level stamp on every row
        of a generated recurrence, independent of an EventSeries."""
        occurrence = make_event(space=space, is_published=True)
        occurrence.recurrence_series_id = str(uuid.uuid4())
        db.flush()
        assert pub.should_announce_gathering(db, occurrence) is False

    def test_generating_thirty_occurrences_announces_nothing(
        self, db, space, series, make_event, kelly,
    ):
        row = series(status="published")
        for _ in range(30):
            occurrence = make_event(space=space, is_published=True)
            occurrence.series_id = row.id
            db.flush()
            pub.announce_gathering_if_newly_published(
                db, occurrence, actor_user_id=kelly.id,
            )
        assert _events(db, pub.GATHERING_EVENT) == [], (
            "a generated occurrence announced itself"
        )

    def test_editing_an_occurrence_announces_nothing(
        self, db, space, series, make_event, kelly,
    ):
        row = series(status="published")
        occurrence = make_event(space=space, is_published=True)
        occurrence.series_id = row.id
        db.flush()
        for when in (3, 10, 17):
            occurrence.starts_at = datetime.utcnow() + timedelta(days=when)
            db.flush()
            assert pub.announce_gathering_if_newly_published(
                db, occurrence, actor_user_id=kelly.id,
            ) is None

    def test_the_series_still_announces_itself(
        self, db, space, series, make_event, kelly,
    ):
        """Occurrences silent, Series heard — both at once."""
        row = series(status="published")
        occurrence = make_event(space=space, is_published=True)
        occurrence.series_id = row.id
        db.flush()

        assert pub.announce_gathering_if_newly_published(
            db, occurrence, actor_user_id=kelly.id,
        ) is None
        assert pub.announce_series_if_newly_published(
            db, row, actor_user_id=kelly.id,
        ) is not None


class TestNothingIsRetroactive:
    """Migration 180's backfill, as a behaviour."""

    def test_a_backfilled_dedupe_row_silences_an_old_gathering(
        self, db, space, make_event, kelly,
    ):
        gathering = make_event(space=space, is_published=True)
        db.flush()
        db.add(CommunicationEvent(
            id=_uid("evt"), event_type=pub.GATHERING_EVENT,
            topic_key="gatherings", category_key="gatherings",
            source_type="fresh_collective", priority_hint="silent",
            subject_type="gathering", subject_id=gathering.id,
            context={"space_id": space.id, "backfilled": True},
            payload={},
            dedupe_key=pub.gathering_dedupe_key(gathering.id, space.id),
        ))
        db.flush()

        assert pub.should_announce_gathering(db, gathering) is False

    def test_without_it_an_old_gathering_would_announce(
        self, db, space, make_event, kelly,
    ):
        """Why the backfill is necessary rather than tidy."""
        gathering = make_event(space=space, is_published=True)
        db.flush()
        assert pub.should_announce_gathering(db, gathering) is True

    def test_the_migration_backfills_both_kinds_before_anything_emits(self):
        from pathlib import Path

        migration = (
            Path(__file__).resolve().parent.parent
            / "alembic" / "versions" / "180_publication_announcements.py"
        ).read_text()
        assert "'gathering.published'" in migration
        assert "'series.published'" in migration
        assert migration.count("ON CONFLICT DO NOTHING") == 2
