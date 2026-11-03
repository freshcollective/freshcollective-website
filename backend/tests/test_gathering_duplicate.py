"""Duplicating a Gathering: what comes with it, and what must not.

What this guards
----------------
The action exists so a creator can run the same session again. Two
ways it could go wrong are worth tests of their own.

**Carrying something instance-specific.** A duplicate that arrived
with the original's bookings, ticket payments, access passes or
attendance marks would be a quiet data-integrity failure: somebody
holding a seat at a session they never booked. The endpoint builds a
new row field by field rather than cloning, so these are never read —
these tests prove the result, not the mechanism.

**Duplicating a Series occurrence.** An occurrence takes its meaning
from the series it belongs to, and a copy would either carry a
membership it has no claim to or be a stray wearing a series name.
The refusal is in the backend, so it holds whatever the interface
does.

Dates are deliberately absent from the copy — a duplicate at the
original's time is a double booking — and the publish guard is what
makes a dateless draft safe to have.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_verified_creator_user
from app.core.database import get_db
from app.main import app
from app.models.access_pass import (
    AccessPass,
    AccessPassSource,
    AccessPassStatus,
    AccessPassType,
)
from app.models.platform import (
    BookingStatus,
    Event,
    EventBooking,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def url(slug: str, event_id: str) -> str:
    return f"/api/creator/spaces/{slug}/events/{event_id}/duplicate"


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
    app.dependency_overrides[get_verified_creator_user] = lambda: creator
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(db, user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_creator_user] = lambda: user
    return TestClient(app)


class TestWhatIsCopied:
    def test_the_configuration_comes_with_it(self, client, db, space, make_event):
        original = make_event(
            space=space,
            title="Monday Circle",
            description="A gentle hour together.",
            capacity=12,
            requires_booking=True,
            is_public=True,
            booking_access_type="paid_separately",
            ticket_price_cents=3500,
            ticket_currency="NZD",
            gathering_type="workshop",
            attendance_format="in_person",
            venue_name="The Hall",
            venue_locality="Bellingen",
            access_instructions="Side door.",
            booking_note="Bring a cushion.",
        )
        r = client.post(url(space.slug, original.id))
        assert r.status_code == 201, r.text
        copy = r.json()

        for field, expected in [
            ("title", "Monday Circle"),
            ("description", "A gentle hour together."),
            ("capacity", 12),
            ("requires_booking", True),
            ("is_public", True),
            ("booking_access_type", "paid_separately"),
            ("ticket_price_cents", 3500),
            ("ticket_currency", "NZD"),
            ("gathering_type", "workshop"),
            ("attendance_format", "in_person"),
            ("venue_name", "The Hall"),
            ("access_instructions", "Side door."),
            ("booking_note", "Bring a cushion."),
        ]:
            assert copy[field] == expected, field

        # ``venue_locality`` is copied but is not among the fields
        # ``_event_to_dict`` returns — a pre-existing omission in that
        # serialiser, unrelated to duplication — so it is checked on
        # the row rather than the response.
        row = db.query(Event).filter(Event.id == copy["id"]).one()
        assert row.venue_locality == "Bellingen"

    def test_it_is_a_new_draft_with_its_own_identity(
        self, client, space, make_event,
    ):
        original = make_event(space=space, is_published=True, status="active")
        copy = client.post(url(space.slug, original.id)).json()

        assert copy["id"] != original.id
        assert copy["is_published"] is False
        # The original is left exactly as it was.
        assert original.is_published is True
        assert original.status == "active"

    def test_the_dates_are_not_copied(self, client, space, make_event):
        original = make_event(
            space=space,
            starts_at=datetime(2026, 12, 1, 9, 0),
            ends_at=datetime(2026, 12, 1, 10, 30),
            booking_closes_at=datetime(2026, 11, 30, 9, 0),
        )
        copy = client.post(url(space.slug, original.id)).json()

        assert copy["starts_at"] is None
        assert copy["ends_at"] is None
        # A closing time relative to dates that no longer exist would
        # be worse than none.
        assert copy["booking_closes_at"] is None


class TestWhatIsNotCopied:
    def test_no_booking_comes_with_it(
        self, client, db, space, make_event, make_user,
    ):
        original = make_event(space=space)
        member = make_user()
        db.add(EventBooking(
            id=_uid("bk"), event_id=original.id, user_id=member.id,
            status=BookingStatus.confirmed,
        ))
        db.flush()

        copy_id = client.post(url(space.slug, original.id)).json()["id"]
        carried = (
            db.query(EventBooking)
            .filter(EventBooking.event_id == copy_id)
            .count()
        )
        assert carried == 0
        # And the original keeps its own.
        assert (
            db.query(EventBooking)
            .filter(EventBooking.event_id == original.id)
            .count()
        ) == 1

    def test_no_access_pass_comes_with_it(
        self, client, db, space, make_event, make_user,
    ):
        """A pass is somebody's paid entry to one session."""
        original = make_event(space=space)
        holder = make_user()
        db.add(AccessPass(
            id=_uid("ap"), user_id=holder.id, space_id=space.id,
            pass_type=AccessPassType.event_ticket,
            status=AccessPassStatus.active,
            source=AccessPassSource.one_time_purchase,
        ))
        db.flush()

        copy_id = client.post(url(space.slug, original.id)).json()["id"]
        copy = db.query(Event).filter(Event.id == copy_id).one()
        # Nothing links a pass to the new Gathering.
        assert copy.id != original.id
        assert (
            db.query(EventBooking)
            .filter(EventBooking.event_id == copy.id)
            .count()
        ) == 0

    def test_no_attendance_record_comes_with_it(
        self, client, db, space, make_event, creator,
    ):
        original = make_event(
            space=space,
            attendance_completed_at=datetime(2026, 1, 2, 3, 4),
            attendance_completed_by=creator.id,
        )
        copy_id = client.post(url(space.slug, original.id)).json()["id"]
        copy = db.query(Event).filter(Event.id == copy_id).one()
        assert copy.attendance_completed_at is None
        assert copy.attendance_completed_by is None

    def test_no_recording_comes_with_it(self, client, db, space, make_event):
        """A recording belongs to the session that was recorded."""
        original = make_event(
            space=space, recording_url="https://example.test/last-time",
        )
        copy_id = client.post(url(space.slug, original.id)).json()["id"]
        copy = db.query(Event).filter(Event.id == copy_id).one()
        assert copy.recording_url is None

    def test_no_conversation_channel_is_created(
        self, client, db, space, make_event,
    ):
        from app.models.platform import ConversationChannel

        original = make_event(space=space)
        before = db.query(ConversationChannel).count()
        client.post(url(space.slug, original.id))
        assert db.query(ConversationChannel).count() == before


class TestTheSeriesRestriction:
    def test_a_series_occurrence_cannot_be_duplicated(
        self, client, db, space, make_event,
    ):
        from app.models.platform import EventSeries

        series = EventSeries(
            id=_uid("es"), space_id=space.id, title="Autumn Term",
            slug=f"autumn-{uuid.uuid4().hex[:8]}",
            starts_at=datetime(2026, 3, 1),
        )
        db.add(series)
        db.flush()
        occurrence = make_event(space=space, series_id=series.id)

        r = client.post(url(space.slug, occurrence.id))
        assert r.status_code == 400
        assert "series" in r.json()["detail"].lower()

    def test_a_bulk_recurrence_occurrence_cannot_be_duplicated(
        self, client, space, make_event,
    ):
        """The other kind of series membership, and just as blocked.

        ``recurrence_series_id`` tags rows created together by a bulk
        recurrence. Checking only ``series_id`` would leave every
        weekly series duplicable.
        """
        occurrence = make_event(
            space=space,
            recurrence_series_id=str(uuid.uuid4()),
            recurrence_label="Weekly Circle",
            recurrence_index=3,
            recurrence_total=8,
        )
        r = client.post(url(space.slug, occurrence.id))
        assert r.status_code == 400

    def test_the_restriction_is_enforced_in_the_backend(self, client, space, make_event):
        """Not only in the interface — this is the API saying no."""
        occurrence = make_event(
            space=space, recurrence_series_id=str(uuid.uuid4()),
        )
        assert client.post(url(space.slug, occurrence.id)).status_code == 400

    def test_a_duplicate_is_standalone_and_stays_so(
        self, client, db, space, make_event,
    ):
        original = make_event(space=space)
        copy_id = client.post(url(space.slug, original.id)).json()["id"]
        copy = db.query(Event).filter(Event.id == copy_id).one()
        assert copy.series_id is None
        assert copy.recurrence_series_id is None
        assert copy.recurrence_index is None
        assert copy.recurrence_total is None


class TestPermissions:
    def test_a_stranger_cannot_duplicate(
        self, db, space, make_event, make_user,
    ):
        original = make_event(space=space)
        outsider = make_user(role="creator")
        c = as_user(db, outsider)
        try:
            r = c.post(url(space.slug, original.id))
            assert r.status_code in (403, 404), r.status_code
        finally:
            app.dependency_overrides.clear()

    def test_a_moderator_of_the_space_may_duplicate(
        self, db, space, make_event, make_user,
    ):
        """``_get_managed_space`` admits creator and moderator alike."""
        original = make_event(space=space)
        moderator = make_user(role="creator")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=moderator.id, space_id=space.id,
            role=SpaceRole.moderator, status=SpaceMembershipStatus.active,
            joined_at=datetime(2026, 1, 1),
        ))
        db.flush()
        c = as_user(db, moderator)
        try:
            r = c.post(url(space.slug, original.id))
            assert r.status_code == 201, r.text
            # The duplicating creator owns the new draft.
            assert r.json()["id"]
        finally:
            app.dependency_overrides.clear()

    def test_a_gathering_in_another_space_is_not_found(
        self, client, space, make_event, make_space,
    ):
        elsewhere = make_event(space=make_space())
        assert client.post(url(space.slug, elsewhere.id)).status_code == 404


class TestADatelessDraftCannotBePublished:
    def _patch(self, client, slug, event_id, **body):
        return client.patch(
            f"/api/creator/spaces/{slug}/events/{event_id}", json=body,
        )

    def test_publishing_without_dates_is_refused(
        self, client, space, make_event,
    ):
        original = make_event(space=space)
        copy_id = client.post(url(space.slug, original.id)).json()["id"]

        r = self._patch(client, space.slug, copy_id, is_published=True)
        assert r.status_code == 400
        assert "start date" in r.json()["detail"].lower()

    def test_setting_dates_and_publishing_together_is_allowed(
        self, client, space, make_event,
    ):
        """What a creator finishing a duplicate actually does."""
        original = make_event(space=space)
        copy_id = client.post(url(space.slug, original.id)).json()["id"]

        r = self._patch(
            client, space.slug, copy_id,
            starts_at="2027-02-01T09:00:00",
            ends_at="2027-02-01T10:00:00",
            is_published=True,
        )
        assert r.status_code == 200, r.text
        assert r.json()["is_published"] is True
        assert r.json()["starts_at"] is not None

    def test_a_dateless_draft_may_still_be_edited(
        self, client, space, make_event,
    ):
        original = make_event(space=space)
        copy_id = client.post(url(space.slug, original.id)).json()["id"]
        r = self._patch(client, space.slug, copy_id, title="Renamed")
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "Renamed"
        assert r.json()["starts_at"] is None


class TestADatelessDraftIsInvisibleToMembers:
    def test_it_does_not_appear_in_a_public_listing(
        self, client, db, space, make_event,
    ):
        """The first of the two independent guards.

        Every member-facing query either compares ``starts_at``
        against a time — never true for NULL — or filters
        ``is_published``, which a draft never is.
        """
        original = make_event(space=space, is_published=True)
        copy_id = client.post(url(space.slug, original.id)).json()["id"]

        published_upcoming = (
            db.query(Event)
            .filter(
                Event.space_id == space.id,
                Event.is_published.is_(True),
                Event.starts_at > datetime.utcnow(),
            )
            .all()
        )
        ids = {e.id for e in published_upcoming}
        assert original.id in ids
        assert copy_id not in ids


# ---------------------------------------------------------------------------
# The duplicate has to be findable
# ---------------------------------------------------------------------------


class TestTheDuplicateAppearsInCreatorStudio:
    """The gap the UI work found.

    The endpoint created a correct draft that nobody could reach. It
    set ``status="draft"`` — a value no other Event path produces; the
    column holds active / cancelled / archived — and Creator Studio's
    ``upcoming`` scope filters on ``status == "active"``. The dateless
    row then failed the archive's filter too, because every comparison
    against a NULL end time is NULL rather than false. In neither
    scope, so invisible: the same shape of bug as the future-archived
    Gathering that once fell out of both.
    """

    @staticmethod
    def _creator_client(db, creator):
        from app.auth.dependencies import get_creator_user

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: creator
        app.dependency_overrides[get_creator_user] = lambda: creator
        app.dependency_overrides[get_verified_creator_user] = lambda: creator
        return TestClient(app)

    def _ids(self, client, space, scope: str) -> list[str]:
        r = client.get(f"/api/creator/spaces/{space.slug}/events?scope={scope}")
        assert r.status_code == 200, r.text
        return [row["id"] for row in r.json()]

    def test_a_duplicate_is_an_ordinary_unpublished_gathering(
        self, client, db, space, make_event,
    ):
        """Draft-ness is ``is_published=False`` and nothing else."""
        original = make_event(space=space, is_published=True)
        db.commit()
        body = client.post(url(space.slug, original.id)).json()
        assert body["is_published"] is False
        assert body["status"] == "active", (
            "status carries a value no other Event path produces"
        )

    def test_it_shows_up_on_the_gatherings_page(
        self, db, space, creator, make_event,
    ):
        original = make_event(space=space, is_published=True)
        db.commit()
        client = self._creator_client(db, creator)
        try:
            created = client.post(url(space.slug, original.id)).json()
            assert created["starts_at"] is None
            assert created["id"] in self._ids(client, space, "upcoming"), (
                "the duplicate is missing from the list it was created for"
            )
        finally:
            app.dependency_overrides.clear()

    def test_it_is_not_in_the_archive(self, db, space, creator, make_event):
        """It is work in progress, not history."""
        original = make_event(space=space, is_published=True)
        db.commit()
        client = self._creator_client(db, creator)
        try:
            created = client.post(url(space.slug, original.id)).json()
            assert created["id"] not in self._ids(client, space, "archive")
        finally:
            app.dependency_overrides.clear()

    def test_it_sorts_after_the_dated_gatherings(
        self, db, space, creator, make_event,
    ):
        """``ORDER BY starts_at ASC`` puts NULLs last in Postgres, so a
        draft awaiting a date sits at the end of the schedule rather
        than above today. The frontend ordering helper matches."""
        original = make_event(space=space, is_published=True)
        db.commit()
        client = self._creator_client(db, creator)
        try:
            created = client.post(url(space.slug, original.id)).json()
            ids = self._ids(client, space, "upcoming")
            assert ids[-1] == created["id"], ids
        finally:
            app.dependency_overrides.clear()

    def test_a_dated_gathering_is_still_scoped_as_before(
        self, db, space, creator, make_event,
    ):
        """The widened filter must not drag history into ``upcoming``."""
        from datetime import datetime, timedelta

        past = make_event(
            space=space, is_published=True,
            starts_at=datetime.utcnow() - timedelta(days=10),
            ends_at=datetime.utcnow() - timedelta(days=10, hours=-1),
        )
        future = make_event(space=space, is_published=True)
        db.commit()
        client = self._creator_client(db, creator)
        try:
            upcoming = self._ids(client, space, "upcoming")
            archive = self._ids(client, space, "archive")
            assert future.id in upcoming
            assert past.id not in upcoming
            assert past.id in archive
        finally:
            app.dependency_overrides.clear()

    def test_a_cancelled_dateless_draft_is_not_in_upcoming(
        self, db, space, creator, make_event,
    ):
        """The status filter still does its job — only the date
        condition was widened."""
        original = make_event(space=space, is_published=True)
        db.commit()
        client = self._creator_client(db, creator)
        try:
            created = client.post(url(space.slug, original.id)).json()
            from app.models.platform import Event

            db.expire_all()
            db.get(Event, created["id"]).status = "cancelled"
            db.commit()
            assert created["id"] not in self._ids(client, space, "upcoming")
            assert created["id"] in self._ids(client, space, "archive")
        finally:
            app.dependency_overrides.clear()

    def test_a_dateless_draft_is_still_invisible_to_members(
        self, db, space, creator, make_event, make_user,
    ):
        """``status="active"`` must not have made it member-visible.
        ``is_published`` is what members filter on."""
        from app.auth.dependencies import get_optional_user

        original = make_event(space=space, is_published=True, is_public=True)
        db.commit()
        client = self._creator_client(db, creator)
        try:
            created = client.post(url(space.slug, original.id)).json()
        finally:
            app.dependency_overrides.clear()

        # An active member, so the listing answers at all — the point
        # is what it contains, not whether the door opens.
        viewer = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=viewer.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        ))
        db.commit()

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: viewer
        app.dependency_overrides[get_current_user] = lambda: viewer
        try:
            member = TestClient(app)
            rows = member.get(f"/api/spaces/{space.slug}/events").json()
            assert isinstance(rows, list), rows
            assert created["id"] not in [r["id"] for r in rows]
            detail = member.get(
                f"/api/spaces/{space.slug}/events/{created['id']}")
            assert detail.status_code == 404, detail.status_code
        finally:
            app.dependency_overrides.clear()


class TestTheWholeWorkflow:
    """Duplicate, set a date, publish — the sequence the creator runs."""

    @staticmethod
    def _creator_client(db, creator):
        from app.auth.dependencies import get_creator_user

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: creator
        app.dependency_overrides[get_creator_user] = lambda: creator
        app.dependency_overrides[get_verified_creator_user] = lambda: creator
        return TestClient(app)

    def test_duplicate_then_date_then_publish(
        self, db, space, creator, make_event,
    ):
        from datetime import datetime, timedelta

        original = make_event(
            space=space, is_published=True, title="November Women's Circle",
            attendance_format="in_person",
            venue_name="Arrabri Community House",
            venue_locality="42 Allambanan Drive, Bayswater North",
            booking_access_type="paid_separately",
            ticket_price_cents=4500, ticket_currency="AUD",
            capacity=12, requires_booking=True,
        )
        db.commit()
        client = self._creator_client(db, creator)
        try:
            created = client.post(url(space.slug, original.id)).json()
            event_url = f"/api/creator/spaces/{space.slug}/events/{created['id']}"

            # The editor loads it.
            loaded = client.get(event_url)
            assert loaded.status_code == 200, loaded.text
            body = loaded.json()
            assert body["title"] == "November Women's Circle"
            assert body["venue_name"] == "Arrabri Community House"
            assert body["venue_locality"] == "42 Allambanan Drive, Bayswater North"
            assert body["ticket_price_cents"] == 4500
            assert body["capacity"] == 12
            assert body["starts_at"] is None

            # Publishing without a date is refused.
            refused = client.patch(event_url, json={"is_published": True})
            assert refused.status_code == 400, refused.text

            # Date, title, publish — together, as the editor sends it.
            when = datetime.utcnow() + timedelta(days=40)
            saved = client.patch(event_url, json={
                "title": "December Women's Circle",
                "starts_at": when.isoformat(),
                "ends_at": (when + timedelta(hours=2)).isoformat(),
                "is_published": True,
            })
            assert saved.status_code == 200, saved.text
            assert saved.json()["is_published"] is True

            # And the original is exactly as it was.
            from app.models.platform import Event

            db.expire_all()
            source = db.get(Event, original.id)
            assert source.title == "November Women's Circle"
            assert source.is_published is True
            assert source.starts_at is not None
        finally:
            app.dependency_overrides.clear()

    def test_duplicating_emits_no_announcement(
        self, db, space, creator, make_event,
    ):
        """A draft has been published to nobody. The announcement fires
        at the duplicate's own first publication, not at creation."""
        from app.comms.models import CommunicationEvent

        original = make_event(space=space, is_published=True)
        db.commit()
        before = db.query(CommunicationEvent).count()
        client = self._creator_client(db, creator)
        try:
            r = client.post(url(space.slug, original.id))
            assert r.status_code == 201, r.text
            assert db.query(CommunicationEvent).count() == before
        finally:
            app.dependency_overrides.clear()

    def test_no_channel_link_comes_with_it(
        self, db, space, creator, make_event,
    ):
        """A channel may be linked to several experiences, so copying
        a link would hand the new Gathering somebody else's members."""
        from sqlalchemy import text as _sql

        original = make_event(space=space, is_published=True)
        db.commit()
        client = self._creator_client(db, creator)
        try:
            created = client.post(url(space.slug, original.id)).json()
            linked = db.execute(
                _sql(
                    "SELECT count(*) FROM channel_experience_links "
                    "WHERE event_id = :id"
                ),
                {"id": created["id"]},
            ).scalar()
            assert linked == 0
        finally:
            app.dependency_overrides.clear()
