"""Where a Gathering says it is, and who gets told exactly.

Two ideas share these columns. ``venue_locality`` is the public
answer — roughly where, so someone can tell if it is near them.
``venue_address``, ``access_instructions`` and ``location_url`` are
attendee detail. The rule separating them predates this file and is
preserved exactly: a **confirmed booking** (or being a caretaker)
reveals the private half. Holding an entitlement does not.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.spaces.venue_projection import public_venue_fields, public_venue_label


class _Event:
    def __init__(self, **kw):
        self.venue_locality = kw.get("venue_locality")
        self.venue_name = kw.get("venue_name")
        self.venue_address = kw.get("venue_address")
        self.access_instructions = kw.get("access_instructions")


class TestThePublicLabel:
    def test_locality_is_preferred(self):
        e = _Event(venue_locality="South Croydon, Victoria",
                   venue_name="Private residence, South Croydon, Vic")
        assert public_venue_label(e) == "South Croydon, Victoria"

    def test_venue_name_is_the_fallback_not_a_second_source(self):
        """Already public on every surface today. Dropping it would
        strip location from every Collective using it as intended, to
        fix one that used it for something else."""
        e = _Event(venue_name="The Studio, King Street")
        assert public_venue_label(e) == "The Studio, King Street"

    def test_the_address_is_never_the_fallback(self):
        """Omitting a location is a smaller harm than publishing a
        street address."""
        e = _Event(venue_address="14 Example St, South Croydon VIC 3136")
        assert public_venue_label(e) is None

    def test_access_instructions_are_never_the_fallback(self):
        e = _Event(access_instructions="Side gate, code 1234")
        assert public_venue_label(e) is None

    def test_blank_and_whitespace_are_not_a_locality(self):
        assert public_venue_label(_Event(venue_locality="   ",
                                         venue_name="The Studio")) == "The Studio"
        assert public_venue_label(_Event(venue_locality="", venue_name="")) is None

    def test_an_online_gathering_says_nothing_about_place(self):
        assert public_venue_label(_Event()) is None

    def test_the_field_pair_never_leaks_the_private_half(self):
        e = _Event(venue_locality="South Croydon, Victoria",
                   venue_address="14 Example St", access_instructions="Side gate")
        fields = public_venue_fields(e)
        assert set(fields) == {"venue_locality", "venue_name"}
        blob = " ".join(str(v) for v in fields.values())
        assert "Example St" not in blob
        assert "Side gate" not in blob


@pytest.fixture
def gathering(db, make_space, make_event):
    space = make_space(is_public=True,
                       area_policies={"areas": {"gatherings": "public"}})
    event = make_event(space=space)
    event.venue_locality = "South Croydon, Victoria"
    event.venue_name = "Private residence, South Croydon, Vic"
    event.venue_address = "14 Example St, South Croydon VIC 3136"
    event.access_instructions = "Side gate, code 1234"
    event.is_public = True
    event.starts_at = datetime.utcnow() + timedelta(days=3)
    db.flush()
    return space, event


class TestWhoSeesWhatOverTheApi:
    @staticmethod
    def _client(db, user=None):
        from fastapi.testclient import TestClient
        from app.auth.dependencies import get_current_user, get_optional_user
        from app.core.database import get_db
        from app.main import app
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: user
        if user is not None:
            app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    @staticmethod
    def _teardown():
        from app.main import app
        app.dependency_overrides.clear()

    def test_an_anonymous_viewer_gets_locality_and_nothing_private(
        self, db, gathering,
    ):
        space, event = gathering
        client = self._client(db, None)
        try:
            body = client.get(
                f"/api/spaces/{space.slug}/events/{event.id}").json()
            assert body["venue_locality"] == "South Croydon, Victoria"
            assert body["venue_name"] == "South Croydon, Victoria"
            assert body["venue_address"] is None
            assert body["access_instructions"] is None
            assert "Example St" not in str(body)
            assert "code 1234" not in str(body)
        finally:
            self._teardown()

    def test_a_member_who_has_not_booked_gets_the_same(
        self, db, gathering, make_user,
    ):
        """Membership is not attendance. The rule is a confirmed
        booking, and this preserves it."""
        from app.models.platform import SpaceMembership
        space, event = gathering
        member = make_user(role="user")
        db.add(SpaceMembership(
            id=str(uuid.uuid4()), user_id=member.id, space_id=space.id,
            role="learner", status="active",
        ))
        db.flush()
        client = self._client(db, member)
        try:
            body = client.get(
                f"/api/spaces/{space.slug}/events/{event.id}").json()
            assert body["venue_locality"] == "South Croydon, Victoria"
            assert body["venue_address"] is None
            assert body["access_instructions"] is None
        finally:
            self._teardown()

    def test_a_confirmed_attendee_gets_the_attendance_details(
        self, db, gathering, make_user,
    ):
        from app.models.platform import (
            BookingStatus, EventBooking, SpaceMembership,
        )
        space, event = gathering
        attendee = make_user(role="user")
        db.add(SpaceMembership(
            id=str(uuid.uuid4()), user_id=attendee.id, space_id=space.id,
            role="learner", status="active",
        ))
        db.add(EventBooking(
            id=str(uuid.uuid4()), event_id=event.id, user_id=attendee.id,
            status=BookingStatus.confirmed,
        ))
        db.flush()
        client = self._client(db, attendee)
        try:
            body = client.get(
                f"/api/spaces/{space.slug}/events/{event.id}").json()
            assert body["venue_address"] == "14 Example St, South Croydon VIC 3136"
            assert body["access_instructions"] == "Side gate, code 1234"
            assert body["venue_locality"] == "South Croydon, Victoria"
        finally:
            self._teardown()

    def test_the_owner_sees_everything(self, db, gathering, make_user):
        space, event = gathering
        owner = db.get(type(space), space.id).creator_id
        from app.models.user import User
        creator = db.query(User).filter(User.id == owner).first()
        client = self._client(db, creator)
        try:
            body = client.get(
                f"/api/spaces/{space.slug}/events/{event.id}").json()
            assert body["venue_address"] is not None
            assert body["access_instructions"] is not None
        finally:
            self._teardown()

    def test_a_gathering_with_no_locality_falls_back_safely(
        self, db, gathering,
    ):
        """Not to the address — to the already-public venue name, and
        if that is empty, to nothing."""
        space, event = gathering
        event.venue_locality = None
        event.venue_name = None
        db.flush()
        client = self._client(db, None)
        try:
            body = client.get(
                f"/api/spaces/{space.slug}/events/{event.id}").json()
            assert body["venue_name"] is None
            assert body["venue_locality"] is None
            assert body["venue_address"] is None
        finally:
            self._teardown()


class TestDiscoverPlacesUsesTheSameRule:
    def test_a_place_page_shows_locality_not_the_venue_line(
        self, db, make_space, make_event,
    ):
        from app.spaces.venue_projection import public_venue_label
        space = make_space(is_public=True,
                           area_policies={"areas": {"gatherings": "public"}})
        event = make_event(space=space)
        event.venue_locality = "South Croydon, Victoria"
        event.venue_name = "Private residence, South Croydon, Vic"
        db.flush()
        # The projection the Place page uses is the shared helper.
        assert public_venue_label(event) == "South Croydon, Victoria"


class TestEmailsCarryNoVenueDetail:
    def test_no_template_embeds_a_venue_field(self):
        """Audited rather than assumed: booking, reminder and
        cancellation mail render from the event title and time, so
        there is no venue detail in them to gate."""
        from pathlib import Path
        src = Path("app/services/email_templates.py").read_text()
        for private in ("venue_address", "access_instructions"):
            assert private not in src, private
