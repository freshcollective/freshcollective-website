"""Public location, saved and read back.

The defect
----------
A creator changed **Public location** on a published Gathering, saved,
refreshed, and the previous value was still there. Three attempts.
Other venue fields in the same form saved correctly.

``_event_to_dict`` — the creator-side serialiser the editor loads
from — returned ``venue_name`` and ``venue_address`` and **not**
``venue_locality``. ``EventResponse`` declares the field, so FastAPI
filled in its ``None`` default and nothing errored: the row held a
Public location that the editor was never shown. Its box therefore
loaded blank however much was stored, and because the form sends
``venue_locality: venueLocality || null`` on every save, an untouched
box sent ``null`` — which the PATCH loop's ``if val is not None``
guard discarded. Write-only field, silent revert.

Nothing about the November Gathering made it special. The serialiser
omitted the field for every Gathering; creation worked because a new
form starts blank anyway, so there was nothing to read back.

What these tests pin
--------------------
The round trip, not the setter. ``test_the_editor_is_shown_the_stored
_value`` is the one that fails against the old code — asserting that
the PATCH writes the column passed throughout, which is why this
shipped. So the create/edit/publish/reload sequence is driven through
HTTP end to end, and the privacy split is re-asserted here because a
field becoming visible creator-side is exactly when somebody could
widen it by accident.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import (
    get_current_user,
    get_optional_user,
    get_verified_creator_user,
)
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    BookingStatus,
    Event,
    EventBooking,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)

# Kelly's value — a full street address she deliberately put in the
# public field. The product allows it; nothing may rewrite it to a
# suburb.
KELLY = "Arrabri Community House - 42 Allambanan Drive, Bayswater North"
OLD = "Bayswater, Victoria"
ADDRESS = "42 Allambanan Drive, Bayswater North VIC 3153"
ARRIVAL = "Side gate, code 1234. Park on the verge."


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def creator(make_user):
    return make_user(role="creator")


@pytest.fixture
def space(make_space, creator):
    return make_space(creator=creator, name="Nourish Connect Thrive")


@pytest.fixture
def client(db, creator):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: creator
    app.dependency_overrides[get_verified_creator_user] = lambda: creator
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_member(db, user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    return TestClient(app)


def creator_url(space, event_id: str) -> str:
    return f"/api/creator/spaces/{space.slug}/events/{event_id}"


def member_url(space, event_id: str) -> str:
    return f"/api/spaces/{space.slug}/events/{event_id}"


def _join(db, space, user, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=role, status=SpaceMembershipStatus.active,
        joined_at=datetime.utcnow(),
    ))
    db.flush()


def _create(client, space, **overrides) -> dict:
    body = {
        "title": "November Women's Circle",
        "starts_at": (datetime.utcnow() + timedelta(days=20)).isoformat(),
        "location_type": "in_person",
        "attendance_format": "in_person",
        "gathering_type": "circle",
        "venue_locality": OLD,
        "is_published": False,
    }
    body.update(overrides)
    r = client.post(f"/api/creator/spaces/{space.slug}/events", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ---------------------------------------------------------------------------
# 1 + 7 — the round trip that was broken
# ---------------------------------------------------------------------------


class TestTheEditorReadsBackWhatItWrote:
    def test_creating_with_a_public_location_stores_it(
        self, client, db, space,
    ):
        created = _create(client, space)
        row = db.get(Event, created["id"])
        assert row.venue_locality == OLD

    def test_the_create_response_carries_it(self, client, db, space):
        assert _create(client, space)["venue_locality"] == OLD

    def test_the_editor_is_shown_the_stored_value(
        self, client, db, space, make_event,
    ):
        """The regression test. The row held a Public location and the
        creator detail payload said ``None``, so the editor's box
        loaded blank and every save of an untouched box sent null."""
        event = make_event(
            space=space, is_published=True, venue_locality=OLD,
            attendance_format="in_person",
        )
        db.commit()
        body = client.get(creator_url(space, event.id)).json()
        assert body["venue_locality"] == OLD, (
            "the creator editor is not shown the stored Public location"
        )

    def test_it_sits_beside_the_fields_that_always_worked(
        self, client, db, space, make_event,
    ):
        """Venue name and address came back correctly, which is why the
        creator reported that *other* location details saved."""
        event = make_event(
            space=space, is_published=True, venue_locality=OLD,
            venue_name="Arrabri Community House", venue_address=ADDRESS,
            attendance_format="in_person",
        )
        db.commit()
        body = client.get(creator_url(space, event.id)).json()
        assert body["venue_name"] == "Arrabri Community House"
        assert body["venue_address"] == ADDRESS
        assert body["venue_locality"] == OLD

    def test_a_save_then_reload_shows_the_new_value(
        self, client, db, space, make_event,
    ):
        """The creator's actual sequence: edit, save, refresh."""
        event = make_event(
            space=space, is_published=True, venue_locality=OLD,
            attendance_format="in_person",
        )
        db.commit()
        url = creator_url(space, event.id)

        saved = client.patch(url, json={"venue_locality": KELLY})
        assert saved.status_code == 200, saved.text
        assert saved.json()["venue_locality"] == KELLY, (
            "the save response still reported the field as unset"
        )

        reloaded = client.get(url).json()
        assert reloaded["venue_locality"] == KELLY


# ---------------------------------------------------------------------------
# 2 + 3 + 4 — draft, published, and a legacy-shaped row
# ---------------------------------------------------------------------------


class TestEditingAtEveryStage:
    def test_editing_a_draft(self, client, db, space):
        created = _create(client, space, is_published=False)
        url = creator_url(space, created["id"])
        client.patch(url, json={"venue_locality": KELLY})
        assert client.get(url).json()["venue_locality"] == KELLY

    def test_publishing_leaves_it_alone(self, client, db, space):
        created = _create(client, space, is_published=False)
        url = creator_url(space, created["id"])
        client.patch(url, json={"venue_locality": KELLY})
        published = client.patch(url, json={"is_published": True})
        assert published.status_code == 200, published.text
        assert published.json()["venue_locality"] == KELLY
        assert client.get(url).json()["venue_locality"] == KELLY

    def test_editing_after_publication(self, client, db, space):
        """The reported case. Nothing about publication gates this
        field, and these assert that rather than assuming it."""
        created = _create(client, space, is_published=True)
        url = creator_url(space, created["id"])
        r = client.patch(url, json={"venue_locality": KELLY})
        assert r.status_code == 200, r.text
        assert client.get(url).json()["venue_locality"] == KELLY

    def test_a_legacy_row_with_the_locality_in_venue_name(
        self, client, db, space, make_event,
    ):
        """Shaped like Gatherings created before the field existed:
        ``venue_locality`` null, the locality typed into
        ``venue_name`` because that was the only box there was."""
        event = make_event(
            space=space, is_published=True,
            venue_locality=None, venue_name=OLD,
            attendance_format="in_person",
        )
        db.commit()
        url = creator_url(space, event.id)
        assert client.get(url).json()["venue_locality"] is None

        client.patch(url, json={"venue_locality": KELLY})
        body = client.get(url).json()
        assert body["venue_locality"] == KELLY
        assert body["venue_name"] == OLD, "the legacy venue name was altered"

    def test_a_row_shaped_by_the_migration_114_backfill(
        self, client, db, space, make_event,
    ):
        """The likeliest shape of the reported Gathering. Migration 114
        copied ``venue_address`` into the new ``venue_locality`` where it
        was unquestionably safe — letter-led, at most two segments, no
        digits — so a pre-114 Gathering reading "Bayswater, Victoria"
        ends up with that string in *both* columns.

        Editing the public half must not disturb the private one, even
        though they started out identical."""
        event = make_event(
            space=space, is_published=True,
            venue_locality=OLD, venue_address=OLD,
            attendance_format="in_person",
        )
        db.commit()
        url = creator_url(space, event.id)
        assert client.get(url).json()["venue_locality"] == OLD

        client.patch(url, json={"venue_locality": KELLY})
        db.expire_all()
        row = db.get(Event, event.id)
        assert row.venue_locality == KELLY
        assert row.venue_address == OLD, (
            "editing the public half moved the private one"
        )

    def test_the_locality_survives_the_default_attendance_format(
        self, client, db, space, make_event,
    ):
        """``attendance_format`` is NOT NULL with a server default of
        ``online``, so a Gathering predating the field reads as online
        whatever it really was. The editor only offers the Public
        location box for in-person and hybrid — but the API must still
        round-trip a stored value, or correcting the format and the
        location in one save would lose one of them."""
        event = make_event(
            space=space, is_published=True, venue_locality=OLD,
            attendance_format="online",
        )
        db.commit()
        url = creator_url(space, event.id)
        assert client.get(url).json()["venue_locality"] == OLD

        r = client.patch(url, json={
            "attendance_format": "in_person", "venue_locality": KELLY,
        })
        assert r.status_code == 200, r.text
        body = client.get(url).json()
        assert body["attendance_format"] == "in_person"
        assert body["venue_locality"] == KELLY


# ---------------------------------------------------------------------------
# 5 + 6 — partial updates in both directions
# ---------------------------------------------------------------------------


class TestPartialUpdates:
    def test_sending_only_the_locality_changes_only_the_locality(
        self, client, db, space, make_event,
    ):
        event = make_event(
            space=space, is_published=True, title="November Women's Circle",
            venue_locality=OLD, venue_name="Arrabri Community House",
            venue_address=ADDRESS, access_instructions=ARRIVAL,
            attendance_format="in_person", capacity=12,
        )
        db.commit()
        before = {
            "title": event.title, "venue_name": event.venue_name,
            "venue_address": event.venue_address,
            "access_instructions": event.access_instructions,
            "capacity": event.capacity,
        }
        client.patch(creator_url(space, event.id),
                     json={"venue_locality": KELLY})
        db.expire_all()
        row = db.get(Event, event.id)
        assert row.venue_locality == KELLY
        for field, was in before.items():
            assert getattr(row, field) == was, field

    def test_an_unrelated_save_preserves_the_locality(
        self, client, db, space, make_event,
    ):
        """Omitting the field must leave it exactly as it was — the
        guarantee the ``model_fields_set`` check has to keep."""
        event = make_event(
            space=space, is_published=True, venue_locality=KELLY,
            attendance_format="in_person",
        )
        db.commit()
        client.patch(creator_url(space, event.id),
                     json={"title": "December Women's Circle"})
        db.expire_all()
        row = db.get(Event, event.id)
        assert row.title == "December Women's Circle"
        assert row.venue_locality == KELLY

    def test_the_detach_patch_from_the_series_editor_preserves_it(
        self, client, db, space, make_event,
    ):
        """That caller sends ``{"series_id": null}`` and nothing else.
        A narrow PATCH must never be read as "clear the locality"."""
        event = make_event(
            space=space, is_published=True, venue_locality=KELLY,
            attendance_format="in_person",
        )
        db.commit()
        r = client.patch(creator_url(space, event.id),
                         json={"series_id": None})
        assert r.status_code == 200, r.text
        db.expire_all()
        assert db.get(Event, event.id).venue_locality == KELLY

    def test_an_explicit_null_clears_it(
        self, client, db, space, make_event,
    ):
        """A creator who empties the box means it. Before this, the
        field was a one-way door: the old value came back."""
        event = make_event(
            space=space, is_published=True, venue_locality=KELLY,
            attendance_format="in_person",
        )
        db.commit()
        url = creator_url(space, event.id)
        client.patch(url, json={"venue_locality": None})
        db.expire_all()
        assert db.get(Event, event.id).venue_locality is None
        assert client.get(url).json()["venue_locality"] is None

    def test_whitespace_counts_as_empty(
        self, client, db, space, make_event,
    ):
        event = make_event(
            space=space, is_published=True, venue_locality=KELLY,
            attendance_format="in_person",
        )
        db.commit()
        client.patch(creator_url(space, event.id),
                     json={"venue_locality": "   "})
        db.expire_all()
        assert db.get(Event, event.id).venue_locality is None

    def test_the_creator_may_put_a_street_address_in_the_public_field(
        self, client, db, space, make_event,
    ):
        """Deliberate, and the product allows it. Nothing may rewrite
        it to a suburb or refuse it for containing a number."""
        event = make_event(space=space, is_published=True,
                           attendance_format="in_person")
        db.commit()
        client.patch(creator_url(space, event.id),
                     json={"venue_locality": KELLY})
        db.expire_all()
        stored = db.get(Event, event.id).venue_locality
        assert stored == KELLY
        assert "42 Allambanan Drive" in stored


class TestAnOverLongValueIsRefusedCleanly:
    """``venue_locality`` is ``String(160)``. Over that, Postgres raised
    a DataError that surfaced as a 500 and lost the whole save — which
    only became reachable now the field is genuinely in play. Not the
    reported defect (that value is 61 characters), but adjacent enough
    to close while here."""

    def test_the_api_refuses_rather_than_erroring(
        self, client, db, space, make_event,
    ):
        from app.creator.schemas import VENUE_LOCALITY_MAX

        event = make_event(space=space, is_published=True,
                           venue_locality=OLD, attendance_format="in_person")
        db.commit()
        r = client.patch(creator_url(space, event.id),
                         json={"venue_locality": "x" * (VENUE_LOCALITY_MAX + 1)})
        assert r.status_code == 422, r.status_code
        db.expire_all()
        assert db.get(Event, event.id).venue_locality == OLD, (
            "a refused save still moved the stored value"
        )

    def test_the_limit_itself_is_accepted(
        self, client, db, space, make_event,
    ):
        from app.creator.schemas import VENUE_LOCALITY_MAX

        event = make_event(space=space, is_published=True,
                           attendance_format="in_person")
        db.commit()
        exact = "x" * VENUE_LOCALITY_MAX
        r = client.patch(creator_url(space, event.id),
                         json={"venue_locality": exact})
        assert r.status_code == 200, r.text
        assert client.get(creator_url(space, event.id)).json()[
            "venue_locality"] == exact

    def test_the_bound_matches_the_column(self):
        """Three places agree on 160: the column, the schema and the
        editor's input. Asserted because a drift reintroduces the 500."""
        from app.creator.schemas import VENUE_LOCALITY_MAX
        from app.models.platform import Event as EventModel

        column = EventModel.__table__.columns["venue_locality"]
        assert column.type.length == VENUE_LOCALITY_MAX

        form = (
            __import__("pathlib").Path(__file__).resolve().parent.parent.parent
            / "frontend" / "src" / "app" / "creator" / "spaces" / "[slug]"
            / "events" / "EventForm.tsx"
        ).read_text()
        assert f"maxLength={{{VENUE_LOCALITY_MAX}}}" in form, (
            "the editor's Public location input no longer caps at "
            f"{VENUE_LOCALITY_MAX}"
        )

    def test_the_response_schema_is_not_bounded(self):
        """A stored value must always be returnable. Bounding the Out
        schema would make an existing row un-loadable instead of
        un-savable, which is the worse failure."""
        from app.creator.schemas import EventResponse

        field = EventResponse.model_fields["venue_locality"]
        assert not [
            m for m in field.metadata if getattr(m, "max_length", None)
        ], "EventResponse.venue_locality has acquired a length bound"


# ---------------------------------------------------------------------------
# 8 — the public page
# ---------------------------------------------------------------------------


class TestThePublicPage:
    def test_a_visitor_reads_the_updated_location(
        self, client, db, space, make_event, make_user,
    ):
        event = make_event(
            space=space, is_published=True, is_public=True,
            venue_locality=OLD, attendance_format="in_person",
        )
        db.commit()
        client.patch(creator_url(space, event.id),
                     json={"venue_locality": KELLY})
        db.commit()
        app.dependency_overrides.clear()

        viewer = make_user()
        member = as_member(db, viewer)
        _join(db, space, viewer)
        db.commit()
        body = member.get(member_url(space, event.id)).json()
        assert body["venue_locality"] == KELLY

    def test_the_public_label_follows_the_locality(
        self, db, space, make_event,
    ):
        from app.spaces.venue_projection import public_venue_label

        event = make_event(
            space=space, is_published=True, venue_locality=KELLY,
            venue_name=OLD, attendance_format="in_person",
        )
        db.flush()
        assert public_venue_label(event) == KELLY


# ---------------------------------------------------------------------------
# 9 — the privacy split is unchanged
# ---------------------------------------------------------------------------


class TestTheAttendeeOnlyFieldsStayGated:
    def _event(self, db, space, make_event):
        event = make_event(
            space=space, is_published=True, is_public=True,
            venue_locality=KELLY, venue_name="Arrabri Community House",
            venue_address=ADDRESS, access_instructions=ARRIVAL,
            location_url="https://zoom.example/j/1",
            attendance_format="hybrid",
        )
        db.commit()
        return event

    def test_a_member_without_a_booking_sees_the_locality_only(
        self, db, space, make_event, make_user,
    ):
        event = self._event(db, space, make_event)
        app.dependency_overrides.clear()
        viewer = make_user()
        member = as_member(db, viewer)
        _join(db, space, viewer)
        db.commit()
        body = member.get(member_url(space, event.id)).json()
        assert body["venue_locality"] == KELLY
        assert body["venue_address"] is None
        assert body["access_instructions"] is None
        app.dependency_overrides.clear()

    def test_the_address_is_not_smuggled_through_another_key(
        self, db, space, make_event, make_user,
    ):
        """Asserted over the whole payload rather than field by field:
        this field becoming visible creator-side is exactly when a
        sibling could be widened by accident."""
        event = self._event(db, space, make_event)
        app.dependency_overrides.clear()
        viewer = make_user()
        member = as_member(db, viewer)
        _join(db, space, viewer)
        db.commit()
        body = member.get(member_url(space, event.id)).json()
        whole = repr(body)
        assert "Allambanan Drive, Bayswater North VIC" not in whole, (
            "the attendee-only address reached a non-attendee"
        )
        assert "code 1234" not in whole
        assert "zoom.example" not in whole
        app.dependency_overrides.clear()

    def test_a_confirmed_attendee_still_gets_the_detail(
        self, db, space, make_event, make_user,
    ):
        event = self._event(db, space, make_event)
        app.dependency_overrides.clear()
        viewer = make_user()
        _join(db, space, viewer)
        db.add(EventBooking(
            id=_uid("bk"), event_id=event.id, user_id=viewer.id,
            status=BookingStatus.confirmed, source="manual",
        ))
        db.commit()
        member = as_member(db, viewer)
        body = member.get(member_url(space, event.id)).json()
        assert body["venue_address"] == ADDRESS
        assert body["access_instructions"] == ARRIVAL
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 10 + 12 — bookings, payments and notifications are untouched
# ---------------------------------------------------------------------------


class TestChangingTheLocationTouchesNothingElse:
    def test_a_confirmed_booking_survives(
        self, client, db, space, make_event, make_user,
    ):
        """Changing where a Gathering is must not invalidate the people
        coming to it."""
        event = make_event(
            space=space, is_published=True, venue_locality=OLD,
            attendance_format="in_person", capacity=12,
        )
        attendee = make_user()
        _join(db, space, attendee)
        booking = EventBooking(
            id=_uid("bk"), event_id=event.id, user_id=attendee.id,
            status=BookingStatus.confirmed, source="manual",
        )
        db.add(booking)
        db.commit()

        client.patch(creator_url(space, event.id),
                     json={"venue_locality": KELLY})
        db.expire_all()
        still = db.get(EventBooking, booking.id)
        assert still is not None
        assert still.status == BookingStatus.confirmed
        assert still.event_id == event.id

    def test_the_ticket_configuration_is_untouched(
        self, client, db, space, make_event, make_user,
    ):
        event = make_event(
            space=space, is_published=True, venue_locality=OLD,
            attendance_format="in_person",
            booking_access_type="paid_separately",
            ticket_price_cents=4500, ticket_currency="aud",
        )
        db.commit()
        r = client.patch(creator_url(space, event.id),
                         json={"venue_locality": KELLY})
        assert r.status_code == 200, r.text
        db.expire_all()
        row = db.get(Event, event.id)
        assert row.ticket_price_cents == 4500
        assert (row.ticket_currency or "").lower() == "aud"
        assert row.booking_access_type == "paid_separately"

    def test_no_announcement_is_emitted(
        self, client, db, space, make_event,
    ):
        """A location edit is not a publication. The publication
        announcement fires on the first publish only, and a dedupe row
        already exists for an already-published Gathering — asserted
        because this PATCH is the handler that emits it."""
        from app.comms.models import CommunicationEvent

        event = make_event(
            space=space, is_published=True, venue_locality=OLD,
            attendance_format="in_person",
        )
        # Already announced, as a Gathering published weeks ago is.
        # Doing it through the service rather than leaving the fixture
        # un-announced: a published row with no dedupe entry would be
        # announced by the next PATCH — correct behaviour, and it would
        # mask what this test is about.
        import app.services.publication_announcement as pub_svc
        assert pub_svc.announce_gathering_if_newly_published(
            db, event, actor_user_id=space.creator_id,
        ) is not None
        db.commit()

        before = db.query(CommunicationEvent).count()
        r = client.patch(creator_url(space, event.id),
                         json={"venue_locality": KELLY})
        assert r.status_code == 200, r.text
        assert db.query(CommunicationEvent).count() == before, (
            "editing the location emitted a communication event"
        )

    def test_attendees_are_not_told(self, client, db, space, make_event,
                                    make_user):
        """No location-change notification exists. Recorded as a test so
        that if one is added, it is added deliberately — see the report
        accompanying this change."""
        from app.comms.models import CommunicationIntent

        event = make_event(
            space=space, is_published=True, venue_locality=OLD,
            attendance_format="in_person",
        )
        attendee = make_user()
        _join(db, space, attendee)
        db.add(EventBooking(
            id=_uid("bk"), event_id=event.id, user_id=attendee.id,
            status=BookingStatus.confirmed, source="manual",
        ))
        import app.services.publication_announcement as pub_svc
        pub_svc.announce_gathering_if_newly_published(
            db, event, actor_user_id=space.creator_id,
        )
        db.commit()
        before = db.query(CommunicationIntent).count()
        r = client.patch(creator_url(space, event.id),
                         json={"venue_locality": KELLY})
        assert r.status_code == 200, r.text
        assert db.query(CommunicationIntent).count() == before


# ---------------------------------------------------------------------------
# 11 — the three attendance formats
# ---------------------------------------------------------------------------


class TestEveryAttendanceFormat:
    @pytest.mark.parametrize("fmt", ["in_person", "hybrid", "online"])
    def test_the_field_round_trips(
        self, client, db, space, make_event, fmt,
    ):
        """Stored and read back for all three. The editor only *offers*
        the box for in-person and hybrid, but the API must not quietly
        drop a value — an online Gathering that was in person last
        month still has one in the row."""
        event = make_event(
            space=space, is_published=True, attendance_format=fmt,
        )
        db.commit()
        url = creator_url(space, event.id)
        r = client.patch(url, json={"venue_locality": KELLY,
                                    "attendance_format": fmt})
        assert r.status_code == 200, r.text
        assert client.get(url).json()["venue_locality"] == KELLY

    def test_switching_format_does_not_discard_it(
        self, client, db, space, make_event,
    ):
        """in_person → hybrid keeps the location. Asserted because the
        editor hides the box for online, and a creator moving a
        Gathering online then back should not lose their text."""
        event = make_event(
            space=space, is_published=True, venue_locality=KELLY,
            attendance_format="in_person",
        )
        db.commit()
        url = creator_url(space, event.id)
        client.patch(url, json={"attendance_format": "hybrid"})
        assert client.get(url).json()["venue_locality"] == KELLY


# ---------------------------------------------------------------------------
# The serialiser contract
# ---------------------------------------------------------------------------


class TestTheSerialiserDeclaresWhatItSends:
    def test_every_declared_venue_field_is_actually_populated(
        self, db, space, make_event,
    ):
        """``EventResponse`` declares ``venue_locality`` with a ``None``
        default, so omitting the key from the dict produced a valid
        response carrying null. A declared field that the serialiser
        never fills is silent, so it is checked here rather than
        trusted."""
        from app.creator.routes import _event_to_dict

        event = make_event(
            space=space, venue_locality=OLD, venue_name="Arrabri",
            venue_address=ADDRESS, access_instructions=ARRIVAL,
            location_url="https://zoom.example/j/1",
            attendance_format="hybrid",
        )
        db.flush()
        payload = _event_to_dict(event)
        for field in ("venue_locality", "venue_name", "venue_address",
                      "access_instructions", "location_url"):
            assert field in payload, f"{field} is missing from the payload"
            assert payload[field] == getattr(event, field), field


# ---------------------------------------------------------------------------
# The production diagnostic
# ---------------------------------------------------------------------------


class TestTheDiagnosticIsSafeToRunInProduction:
    """``scripts/inspect_gathering_location.py`` answers "what is in the
    row" for a reported Gathering. It runs against real creator records
    with real bookings, so read-only is a property worth a test rather
    than a convention."""

    SCRIPT = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "scripts" / "inspect_gathering_location.py"
    )

    def _load(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "inspect_gathering_location", self.SCRIPT,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_the_source_contains_no_write_statement(self):
        source = self.SCRIPT.read_text().lower()
        for forbidden in (
            "db.add(", "db.commit()", "db.delete(", "db.merge(",
            "insert into", "delete from", "update ", "op.execute",
        ):
            assert forbidden not in source, forbidden

    def test_it_reports_a_row_without_changing_it(
        self, db, space, make_event, capsys,
    ):
        event = make_event(
            space=space, is_published=True, venue_locality=OLD,
            venue_name="Arrabri Community House", venue_address=ADDRESS,
            access_instructions=ARRIVAL, attendance_format="in_person",
        )
        db.commit()
        before = (
            event.venue_locality, event.venue_name,
            event.venue_address, event.access_instructions,
        )
        module = self._load()
        module.report(db, event)
        out = capsys.readouterr().out

        assert OLD in out, "the Public location is not reported"
        assert "venue_locality" in out
        assert "public label" in out
        db.expire_all()
        row = db.get(Event, event.id)
        assert (
            row.venue_locality, row.venue_name,
            row.venue_address, row.access_instructions,
        ) == before

    def test_the_attendee_only_fields_are_described_not_printed(
        self, db, space, make_event, capsys,
    ):
        """It runs in a terminal and its output gets pasted into bug
        reports. The question it answers is "is the creator's text in
        the wrong column", which a shape answers."""
        event = make_event(
            space=space, is_published=True, venue_locality=OLD,
            venue_address=ADDRESS, access_instructions=ARRIVAL,
            location_url="https://zoom.example/j/1",
            attendance_format="hybrid",
        )
        db.commit()
        module = self._load()
        module.report(db, event)
        out = capsys.readouterr().out
        assert ADDRESS not in out, "the full venue address was printed"
        assert "code 1234" not in out, "arrival instructions were printed"
        assert "zoom.example/j/1" not in out, "the joining link was printed"
        # …but their presence is still visible.
        assert f"{len(ADDRESS)} chars" in out

    def test_it_names_the_mismatch_this_defect_produced(
        self, db, space, make_event, capsys, monkeypatch,
    ):
        """The line that would have identified the bug in one command.
        Simulated by making the serialiser omit the field again, so the
        check is proven to fire rather than assumed to."""
        from app.creator import routes as creator_routes

        event = make_event(
            space=space, is_published=True, venue_locality=OLD,
            attendance_format="in_person",
        )
        db.commit()

        real = creator_routes._event_to_dict

        def without_locality(ev, *a, **kw):
            payload = dict(real(ev, *a, **kw))
            payload.pop("venue_locality", None)
            return payload

        monkeypatch.setattr(
            creator_routes, "_event_to_dict", without_locality,
        )
        module = self._load()
        module.report(db, event)
        out = capsys.readouterr().out
        assert "MISMATCH" in out
        assert "loads blank" in out

    def test_it_distinguishes_the_fallback_from_a_real_locality(
        self, db, space, make_event, capsys,
    ):
        """A Gathering whose public line comes from ``venue_name``
        because nobody ever filled in the locality — the pre-114 shape —
        must not read as though the locality were set."""
        event = make_event(
            space=space, is_published=True,
            venue_locality=None, venue_name=OLD,
            attendance_format="in_person",
        )
        db.commit()
        module = self._load()
        module.report(db, event)
        out = capsys.readouterr().out
        assert "fallback: venue_name" in out
