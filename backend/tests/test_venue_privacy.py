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
            # Was asserted as the *label* — the locality, because the
            # projection overwrote ``venue_name`` with it. That
            # collapsed the name of a place and its address into one
            # string, which the Gathering page then printed twice, and
            # hid the real name from every public surface. Both fields
            # now arrive as they are; the page composes them.
            assert body["venue_name"] == "Private residence, South Croydon, Vic"
            assert body["venue_address"] is None
            assert body["access_instructions"] is None
            assert "Example St" not in str(body)
            assert "code 1234" not in str(body)
        finally:
            self._teardown()

    def test_the_raw_venue_name_was_already_public_on_the_list(
        self, db, gathering,
    ):
        """Why returning it unchanged on the detail endpoint is a
        consistency fix rather than a widening: the events list has
        always handed the same anonymous viewer the same raw value, so
        the detail endpoint's override protected nothing that was not
        one call away."""
        space, event = gathering
        client = self._client(db, None)
        try:
            rows = client.get(f"/api/spaces/{space.slug}/events").json()
            mine = [r for r in rows if r["id"] == event.id]
            assert mine, rows
            assert mine[0]["venue_name"] == (
                "Private residence, South Croydon, Vic"
            )
            assert "Example St" not in str(rows)
            assert "code 1234" not in str(rows)
        finally:
            self._teardown()

    def test_the_two_public_surfaces_now_agree(self, db, gathering):
        """List and detail disagreed about ``venue_name`` — raw on one,
        the label on the other. Different pages showing different
        addresses for the same Gathering is the drift this closes."""
        space, event = gathering
        client = self._client(db, None)
        try:
            detail = client.get(
                f"/api/spaces/{space.slug}/events/{event.id}").json()
            rows = client.get(f"/api/spaces/{space.slug}/events").json()
            summary = [r for r in rows if r["id"] == event.id][0]
            for field in ("venue_name", "venue_locality"):
                assert detail[field] == summary[field], field
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


# ---------------------------------------------------------------------------
# The one-line public summary
# ---------------------------------------------------------------------------
#
# The same case table as ``frontend/src/lib/gatheringLocation.test.ts``.
# Two short implementations of one small rule, deliberately — the
# alternative is an endpoint whose only job is telling the calendar how
# to phrase a string. If one side is changed, this table fails.

SUMMARY_CASES = [
    # (venue_name, venue_locality, expected)
    ("Arrabri Community House", "42 Allambanan Drive, Bayswater North VIC 3153",
     "Arrabri Community House, 42 Allambanan Drive, Bayswater North VIC 3153"),
    # The reported Gathering: the venue typed into both fields.
    ("Arrabri Community House",
     "Arrabri Community House - 42 Allambanan Drive, Bayswater North",
     "Arrabri Community House, 42 Allambanan Drive, Bayswater North"),
    ("Arrabri Community House", "Arrabri Community House",
     "Arrabri Community House"),
    # A different place, not a repeat — nothing is stripped.
    ("The Studio", "The Studio Annexe, 14 King Street",
     "The Studio, The Studio Annexe, 14 King Street"),
    # Overlapping in the middle, not leading.
    ("King Street", "14 King Street, Richmond",
     "King Street, 14 King Street, Richmond"),
    ("Private residence", "South Croydon, Victoria",
     "Private residence, South Croydon, Victoria"),
    (None, "South Croydon, Victoria", "South Croydon, Victoria"),
    # The pre-migration-114 shape: everything in the name.
    ("Private residence, South Croydon, Vic", None,
     "Private residence, South Croydon, Vic"),
    (None, None, ""),
    ("The Studio", "The Studio, 14 King Street", "The Studio, 14 King Street"),
]


class TestThePublicOneLineSummary:
    @pytest.mark.parametrize("name,locality,expected", SUMMARY_CASES)
    def test_it_matches_the_shared_case_table(self, name, locality, expected):
        from app.spaces.venue_projection import public_location_summary

        assert public_location_summary(
            _Event(venue_name=name, venue_locality=locality),
        ) == expected

    def test_it_never_reads_the_private_half(self):
        from app.spaces.venue_projection import public_location_summary

        out = public_location_summary(_Event(
            venue_name="Private residence",
            venue_locality="South Croydon, Victoria",
            venue_address="62 Longview Road, South Croydon",
            access_instructions="Park in the driveway.",
        ))
        assert "Longview" not in out
        assert "driveway" not in out
        assert out == "Private residence, South Croydon, Victoria"

    def test_the_frontend_table_carries_the_same_cases(self):
        """A drift guard on the duplication, not on the output: if the
        TypeScript side loses a case this table keeps, they have
        stopped being two implementations of one rule."""
        import pathlib

        ts = (
            pathlib.Path(__file__).resolve().parent.parent.parent
            / "frontend" / "src" / "lib" / "gatheringLocation.test.ts"
        ).read_text()
        for probe in (
            "The Studio Annexe",          # whitespace is not a separator
            "14 King Street, Richmond",   # a mid-string overlap survives
            "Private residence, South Croydon, Vic",  # the legacy shape
            "42 Allambanan Drive",        # the reported Gathering
        ):
            assert probe in ts, probe


class TestTheCalendarFile:
    """``.ics`` is downloadable by any member, and by anyone at all for
    a public Gathering. Its ``LOCATION`` used to be ``location_url`` —
    the joining link the detail endpoint gates on a confirmed booking."""

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

    def _ics(self, db, gathering, user=None) -> str:
        space, event = gathering
        event.location_url = "https://zoom.example/j/privatelink"
        db.flush()
        client = self._client(db, user)
        try:
            r = client.get(
                f"/api/spaces/{space.slug}/events/{event.id}/calendar.ics")
            assert r.status_code == 200, r.text
            return r.text
        finally:
            from app.main import app
            app.dependency_overrides.clear()

    def test_the_joining_link_is_gone_from_an_anonymous_download(
        self, db, gathering,
    ):
        body = self._ics(db, gathering)
        assert "zoom.example" not in body, (
            "the attendee-only joining link is in the calendar file"
        )
        assert "privatelink" not in body

    def test_the_private_address_is_not_there_either(self, db, gathering):
        body = self._ics(db, gathering)
        assert "Example St" not in body
        assert "code 1234" not in body

    def test_it_carries_the_public_location(self, db, gathering):
        body = self._ics(db, gathering)
        line = [ln for ln in body.split("\r\n") if ln.startswith("LOCATION:")]
        assert line, body
        assert line[0] == (
            "LOCATION:Private residence, South Croydon, Vic, "
            "South Croydon, Victoria"
        ), line[0]

    def test_a_confirmed_attendee_gets_the_same_file(
        self, db, gathering, make_user,
    ):
        """No per-viewer branching here. A calendar file is saved,
        forwarded and synced to third-party services; the place to give
        somebody an address is the Gathering page and their booking
        confirmation."""
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
        assert self._ics(db, gathering, attendee) == self._ics(db, gathering)

    def test_the_event_url_is_a_real_fresh_collective_link(
        self, db, gathering, monkeypatch,
    ):
        """Was a hardcoded ``fresh.community``, which is not a Fresh
        Collective domain — every calendar entry carried a dead link."""
        from app.core.config import settings

        monkeypatch.setattr(
            settings, "public_app_url", "https://freshcollective.au",
            raising=False,
        )
        space, event = gathering
        body = self._ics(db, gathering)
        assert (
            f"URL:https://freshcollective.au/spaces/{space.slug}"
            f"/events/{event.id}" in body
        )
        url_lines = [ln for ln in body.split("\r\n") if ln.startswith("URL:")]
        assert url_lines and "fresh.community" not in url_lines[0]

    def test_the_uid_domain_is_deliberately_left_alone(self, db, gathering):
        """``UID`` is an opaque identifier, not a link. Changing it
        would make every calendar entry already synced to somebody's
        phone duplicate rather than update, so the stale domain stays
        there — it is never resolved."""
        body = self._ics(db, gathering)
        uid = [ln for ln in body.split("\r\n") if ln.startswith("UID:")]
        assert uid and uid[0].endswith("@fresh.community")
