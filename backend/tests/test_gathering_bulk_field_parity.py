"""FC-201 — a recurring Gathering keeps the settings a single one keeps.

The defect
----------
``POST /events/bulk`` built each occurrence with a hand-written
argument list that had drifted from ``create_event``'s. Three fields
were missing:

* ``venue_locality`` — so every recurring Gathering lost its Public
  location while the creator's form showed it saved;
* ``ticket_price_cents`` and ``ticket_currency`` — so a recurring paid
  Gathering saved as a draft lost its price, and one published
  immediately violated ``ck_events_ticket_price_valid_when_published``
  and surfaced as a 500 rather than a field-scoped 400.

The bulk path also skipped ``_ensure_creator_write_allowed``, so a
restricted creator or a frozen Collective could generate a run of
Gatherings through a route that refused them a single one.

How these tests are built
-------------------------
Two layers, because either alone would rot.

**Behavioural parity.** ``TestStandaloneAndBulkAgree`` posts the *same*
payload to both endpoints and compares every column in the shared
mapping, value by value. It does not name the three fields from the
bug: it compares the whole set, so a field added to
``SHARED_EVENT_FIELDS`` is covered the day it is added, without anybody
remembering to extend this file.

**Structural partition.** ``TestEveryColumnIsAccountedFor`` asserts the
three buckets in ``services/gathering_fields`` partition ``Event``'s
columns exactly. A new column on the model fails here until somebody
decides whether it is a setting both paths copy or something an
occurrence owns — which is the decision that was never made for
``venue_locality``.

Neither reads source text, so a doc comment mentioning a field name
cannot satisfy or break them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Cross-file model registration for the SAVEPOINT test session.
import app.models.community_care  # noqa: F401

from app.auth.dependencies import get_verified_creator_user
from app.comms.models import CommunicationEvent
from app.core.database import get_db
from app.main import app
from app.models.platform import Event, EventSeries, SpaceMembership
from app.services.gathering_fields import (
    PER_ROW_EVENT_FIELDS,
    SHARED_EVENT_FIELDS,
    TICKET_FIELDS,
)


MELBOURNE = ZoneInfo("Australia/Melbourne")

#: Mon 5 Oct 2026, 6 pm Australia/Melbourne (AEDT, +11) = 07:00 UTC.
#: The same anchor ``test_recurrence_timezone`` uses, so a failure here
#: and a failure there point at the same instant.
ANCHOR_MON_6PM = datetime(2026, 10, 5, 7, 0, 0, tzinfo=timezone.utc)
ANCHOR_MON_7PM = datetime(2026, 10, 5, 8, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def client_as(db: Session):
    """TestClient authenticated as the passed-in user, pinned to the
    SAVEPOINT-scoped session."""
    def _install(user):
        app.dependency_overrides[get_verified_creator_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app, follow_redirects=False)

    yield _install

    app.dependency_overrides.pop(get_verified_creator_user, None)
    app.dependency_overrides.pop(get_db, None)


def _full_payload(**overrides) -> dict:
    """One Gathering with every shared setting populated.

    Deliberately not minimal. The point of these tests is that nothing
    is dropped in transit, so every field the editor can send carries a
    value distinguishable from its default — a null that should have
    been a string is then a failure rather than a coincidence.
    """
    payload = {
        "title": "  Monday Circle  ",  # untrimmed on purpose
        "description": "<p>A <strong>weekly</strong> circle.</p>",
        "starts_at": ANCHOR_MON_6PM.isoformat(),
        "ends_at": ANCHOR_MON_7PM.isoformat(),
        "location_type": "in_person",
        "location_url": "https://example.test/join/monday",
        "recording_url": None,
        "is_published": False,
        "is_public": True,
        "requires_booking": True,
        "capacity": 12,
        "show_remaining_publicly": False,
        "notify_members": False,
        "booking_closes_at": (
            ANCHOR_MON_6PM - timedelta(hours=2)
        ).isoformat(),
        "booking_note": "Bring a cushion.",
        "thumbnail_url": "https://example.test/thumb.png",
        "gathering_type": "workshop",
        "attendance_format": "hybrid",
        "venue_name": "The Old Hall",
        "venue_address": "12 Private Lane, Fitzroy VIC 3065",
        "venue_locality": "Fitzroy, Melbourne",
        "access_instructions": "Side door, ring the bell twice.",
        "booking_access_type": "included_with_collective",
        "booking_required_pathway_id": None,
        "ticket_price_cents": None,
        "ticket_currency": None,
    }
    payload.update(overrides)
    return payload


def _weekly(days: list[int], count: int) -> dict:
    return {
        "pattern": "weekly",
        "days_of_week": days,
        "end_after_n": count,
        "series_label": "Monday Circle",
    }


def _occurrences(db: Session, space_id: str) -> list[Event]:
    return (
        db.query(Event)
        .filter(Event.space_id == space_id)
        .order_by(Event.starts_at)
        .all()
    )


def _local(utc_naive: datetime) -> datetime:
    """Read a naive-UTC column back as a Melbourne wall-clock time."""
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(MELBOURNE)


def _make_series(db: Session, space) -> EventSeries:
    series = EventSeries(
        id=f"es_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title="Spring Term",
        starts_at=datetime(2026, 10, 1),
        ends_at=datetime(2026, 12, 20),
        status="draft",
    )
    db.add(series)
    db.flush()
    return series


# ---------------------------------------------------------------------------
# 1. The headline claim: both paths produce the same settings
# ---------------------------------------------------------------------------


class TestStandaloneAndBulkAgree:
    """Post one payload to each endpoint; compare every shared column.

    This is the regression guard the task asked for. It is written
    against the field list rather than against a list of field names
    repeated here, so it cannot fall behind the mapping.
    """

    COMPARED = SHARED_EVENT_FIELDS + TICKET_FIELDS

    def _run(self, client, space, payload, recurrence):
        single = client.post(
            f"/api/creator/spaces/{space.slug}/events", json=payload,
        )
        assert single.status_code == 201, single.text
        bulk = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={**payload, "recurrence": recurrence},
        )
        assert bulk.status_code == 201, bulk.text
        return single, bulk

    def test_every_shared_field_matches_on_a_free_gathering(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)

        payload = _full_payload()
        self._run(client, space, payload, _weekly([0], 3))

        rows = _occurrences(db, space.id)
        # One standalone + three occurrences.
        assert len(rows) == 4
        standalone = next(r for r in rows if r.recurrence_series_id is None)
        generated = [r for r in rows if r.recurrence_series_id is not None]
        assert len(generated) == 3

        for row in generated:
            for field in self.COMPARED:
                assert getattr(row, field) == getattr(standalone, field), (
                    f"{field} differs between a standalone Gathering and a "
                    f"generated occurrence: standalone="
                    f"{getattr(standalone, field)!r} "
                    f"occurrence={getattr(row, field)!r}"
                )

    def test_every_shared_field_matches_on_a_paid_gathering(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)

        payload = _full_payload(
            booking_access_type="paid_separately",
            ticket_price_cents=4500,
            ticket_currency="aud",  # lower case on purpose
        )
        self._run(client, space, payload, _weekly([0], 3))

        rows = _occurrences(db, space.id)
        standalone = next(r for r in rows if r.recurrence_series_id is None)
        generated = [r for r in rows if r.recurrence_series_id is not None]

        for row in generated:
            for field in self.COMPARED:
                assert getattr(row, field) == getattr(standalone, field), (
                    f"{field} differs on the paid path"
                )
        # And state the absolute values too, so a bug that broke BOTH
        # paths identically could not pass this class.
        assert standalone.ticket_price_cents == 4500
        assert {r.ticket_price_cents for r in generated} == {4500}
        assert {r.ticket_currency for r in generated} == {"AUD"}


# ---------------------------------------------------------------------------
# 2. The three fields the defect dropped, named explicitly
# ---------------------------------------------------------------------------


class TestTheDroppedFields:
    """Named one by one, because a regression in any of them is a
    distinct creator-visible failure and should read as its own line in
    a test report."""

    @pytest.fixture
    def generated(self, client_as, make_user, make_space, db):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(
                    booking_access_type="paid_separately",
                    ticket_price_cents=3300,
                    ticket_currency="AUD",
                ),
                "recurrence": _weekly([0], 4),
            },
        )
        assert r.status_code == 201, r.text
        rows = _occurrences(db, space.id)
        assert len(rows) == 4
        return rows

    def test_public_location_is_on_every_occurrence(self, generated):
        assert [r.venue_locality for r in generated] == [
            "Fitzroy, Melbourne"
        ] * 4

    def test_ticket_price_is_on_every_occurrence(self, generated):
        assert [r.ticket_price_cents for r in generated] == [3300] * 4

    def test_currency_is_on_every_occurrence(self, generated):
        assert [r.ticket_currency for r in generated] == ["AUD"] * 4

    def test_venue_name_is_on_every_occurrence(self, generated):
        assert [r.venue_name for r in generated] == ["The Old Hall"] * 4

    def test_private_address_is_on_every_occurrence(self, generated):
        assert [r.venue_address for r in generated] == [
            "12 Private Lane, Fitzroy VIC 3065"
        ] * 4

    def test_arrival_instructions_are_on_every_occurrence(self, generated):
        assert [r.access_instructions for r in generated] == [
            "Side door, ring the bell twice."
        ] * 4

    def test_joining_link_is_on_every_occurrence(self, generated):
        assert [r.location_url for r in generated] == [
            "https://example.test/join/monday"
        ] * 4

    def test_capacity_is_on_every_occurrence(self, generated):
        assert [r.capacity for r in generated] == [12] * 4

    def test_access_type_is_on_every_occurrence(self, generated):
        assert [r.booking_access_type for r in generated] == [
            "paid_separately"
        ] * 4

    def test_visibility_is_on_every_occurrence(self, generated):
        assert all(r.is_public is True for r in generated)
        assert all(r.show_remaining_publicly is False for r in generated)

    def test_title_is_stripped_like_the_standalone_path(self, generated):
        assert [r.title for r in generated] == ["Monday Circle"] * 4

    def test_rich_description_survives_sanitisation_identically(
        self, generated,
    ):
        for row in generated:
            assert row.description is not None
            assert "<strong>" in row.description


# ---------------------------------------------------------------------------
# 3. Ticket validation now runs on the bulk path
# ---------------------------------------------------------------------------


class TestPaidTicketValidation:
    """A paid recurrence must be validated the way a paid single
    Gathering is — before any row is written, and with the same
    field-scoped 400."""

    def test_published_paid_without_a_price_is_a_400_not_a_500(
        self, client_as, make_user, make_space, db,
    ):
        """The headline of Problem B. The DB CHECK constraint used to
        decide this, which meant an IntegrityError and a 500."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(
                    is_published=True,
                    booking_access_type="paid_separately",
                    ticket_price_cents=None,
                    ticket_currency=None,
                ),
                "recurrence": _weekly([0], 3),
            },
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "invalid_ticket_config"
        assert detail["field"] == "ticket_price_cents"
        # Nothing was written. A validation failure must not leave a
        # partial batch behind.
        assert _occurrences(db, space.id) == []

    def test_published_paid_with_a_valid_price_succeeds(
        self, client_as, make_user, make_space, db,
    ):
        """The other half: a correctly configured published paid
        recurrence now satisfies the CHECK constraint, because the price
        actually reaches the row."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(
                    is_published=True,
                    booking_access_type="paid_separately",
                    ticket_price_cents=5000,
                    ticket_currency="AUD",
                ),
                "recurrence": _weekly([0], 3),
            },
        )
        assert r.status_code == 201, r.text
        rows = _occurrences(db, space.id)
        assert len(rows) == 3
        assert all(r_.is_published is True for r_ in rows)
        assert {r_.ticket_price_cents for r_ in rows} == {5000}
        assert {r_.ticket_currency for r_ in rows} == {"AUD"}

    def test_draft_paid_keeps_its_price_without_requiring_one(
        self, client_as, make_user, make_space, db,
    ):
        """Draft-safe, exactly as the standalone path is: a work-in-
        progress price is preserved rather than demanded."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(
                    is_published=False,
                    booking_access_type="paid_separately",
                    ticket_price_cents=2500,
                    ticket_currency="AUD",
                ),
                "recurrence": _weekly([0], 2),
            },
        )
        assert r.status_code == 201, r.text
        rows = _occurrences(db, space.id)
        assert {r_.ticket_price_cents for r_ in rows} == {2500}

    def test_an_unsupported_currency_is_a_field_scoped_400(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(
                    booking_access_type="paid_separately",
                    ticket_price_cents=2500,
                    ticket_currency="JPY",  # zero-minor-unit, excluded
                ),
                "recurrence": _weekly([0], 2),
            },
        )
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["field"] == "ticket_currency"
        assert _occurrences(db, space.id) == []

    def test_a_free_recurrence_stores_no_ticket_data(
        self, client_as, make_user, make_space, db,
    ):
        """Free Gatherings unaffected — and stale ticket values sent by
        a confused client are nulled, as on the standalone path."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(
                    booking_access_type="included_with_collective",
                    ticket_price_cents=9999,
                    ticket_currency="AUD",
                ),
                "recurrence": _weekly([0], 2),
            },
        )
        assert r.status_code == 201, r.text
        rows = _occurrences(db, space.id)
        assert all(r_.ticket_price_cents is None for r_ in rows)
        assert all(r_.ticket_currency is None for r_ in rows)

    def test_series_pass_access_without_a_series_is_still_refused(
        self, client_as, make_user, make_space, db,
    ):
        """The pre-existing access-type invariant is untouched."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(booking_access_type="included_with_series"),
                "recurrence": _weekly([0], 2),
            },
        )
        assert r.status_code == 400, r.text
        assert _occurrences(db, space.id) == []


# ---------------------------------------------------------------------------
# 4. Recurrence behaviour is unchanged
# ---------------------------------------------------------------------------


class TestRecurrenceIsUnchanged:
    """FC-201 repairs the field mapping and must not touch generation.

    ``test_recurrence_timezone`` is the primary guard for the generator;
    these assert the same properties hold now that the settings travel
    with it — i.e. that nothing in the repair reordered the loop or the
    date maths.
    """

    def test_weekly_count_and_dates(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={**_full_payload(), "recurrence": _weekly([0], 4)},
        )
        assert r.status_code == 201
        assert r.json()["created_count"] == 4
        rows = _occurrences(db, space.id)
        assert len(rows) == 4
        for row in rows:
            local = _local(row.starts_at)
            assert local.weekday() == 0
            assert (local.hour, local.minute) == (18, 0)
            assert (_local(row.ends_at).hour, _local(row.ends_at).minute) == (19, 0)
        # Consecutive Mondays.
        dates = [_local(r_.starts_at).date() for r_ in rows]
        assert [(dates[i + 1] - dates[i]).days for i in range(3)] == [7, 7, 7]

    def test_multiple_weekdays(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={**_full_payload(), "recurrence": _weekly([0, 3], 6)},
        )
        assert r.status_code == 201
        rows = _occurrences(db, space.id)
        assert len(rows) == 6
        weekdays = [_local(r_.starts_at).weekday() for r_ in rows]
        assert weekdays == [0, 3, 0, 3, 0, 3]
        # Every occurrence still carries the full settings.
        assert all(r_.venue_locality == "Fitzroy, Melbourne" for r_ in rows)

    def test_wall_clock_survives_the_dst_transition(
        self, client_as, make_user, make_space, db,
    ):
        """Australia/Melbourne moves to AEDT on Sun 4 Oct 2026. An
        anchor in September and a count that crosses it must keep 6 pm
        at 6 pm — and must keep its Public location on both sides."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        # Mon 28 Sep 2026 6 pm AEST (+10) = 08:00 UTC.
        anchor = datetime(2026, 9, 28, 8, 0, 0, tzinfo=timezone.utc)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(
                    starts_at=anchor.isoformat(),
                    ends_at=(anchor + timedelta(hours=1)).isoformat(),
                    booking_closes_at=None,
                ),
                "recurrence": _weekly([0], 3),
            },
        )
        assert r.status_code == 201, r.text
        rows = _occurrences(db, space.id)
        assert len(rows) == 3
        offsets = set()
        for row in rows:
            local = _local(row.starts_at)
            assert (local.hour, local.minute) == (18, 0)
            assert row.venue_locality == "Fitzroy, Melbourne"
            offsets.add(local.utcoffset())
        # The batch genuinely straddles the transition, so the test is
        # exercising what it claims to.
        assert len(offsets) == 2, (
            "expected the batch to cross the AEST/AEDT boundary"
        )

    def test_recurrence_identifiers(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={**_full_payload(), "recurrence": _weekly([0], 3)},
        )
        assert r.status_code == 201
        tag = r.json()["recurrence_series_id"]
        assert r.json()["series_id"] == tag  # deprecated alias, same value
        rows = _occurrences(db, space.id)
        assert {r_.recurrence_series_id for r_ in rows} == {tag}
        assert [r_.recurrence_index for r_ in rows] == [1, 2, 3]
        assert {r_.recurrence_total for r_ in rows} == {3}
        assert {r_.recurrence_label for r_ in rows} == {"Monday Circle"}
        # A bulk batch with no formal Series stays outside one.
        assert {r_.series_id for r_ in rows} == {None}

    def test_repeat_until_still_bounds_the_batch(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(),
                "recurrence": {
                    "pattern": "weekly",
                    "days_of_week": [0],
                    # Mon 5, 12, 19 Oct — then stop.
                    "repeat_until": datetime(
                        2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc,
                    ).isoformat(),
                },
            },
        )
        assert r.status_code == 201, r.text
        rows = _occurrences(db, space.id)
        assert [_local(r_.starts_at).day for r_ in rows] == [5, 12, 19]

    def test_optional_formal_series_association(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        series = _make_series(db, space)
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(series_id=series.id),
                "recurrence": _weekly([0], 3),
            },
        )
        assert r.status_code == 201, r.text
        rows = _occurrences(db, space.id)
        assert {r_.series_id for r_ in rows} == {series.id}
        # Both kinds of series membership coexist, as documented.
        assert all(r_.recurrence_series_id is not None for r_ in rows)

    def test_a_series_from_another_collective_is_refused(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        other = make_space(timezone="Australia/Melbourne")
        foreign_series = _make_series(db, other)
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(series_id=foreign_series.id),
                "recurrence": _weekly([0], 3),
            },
        )
        assert r.status_code == 400, r.text
        assert _occurrences(db, space.id) == []


# ---------------------------------------------------------------------------
# 5. Notifications stay exactly as they were (FC-209 is separate)
# ---------------------------------------------------------------------------


class TestNotificationBehaviourUnchanged:
    """FC-201 repairs data creation and must not start announcing.

    The silent-publication gap is real and is FC-209's; these tests pin
    the current behaviour so that fixing the fields does not
    accidentally fix — or worsen — the announcements.
    """

    def _comms_events(self, db: Session) -> list[CommunicationEvent]:
        return (
            db.query(CommunicationEvent)
            .filter(
                CommunicationEvent.event_type.in_(
                    ["gathering.published", "series.published"]
                )
            )
            .all()
        )

    def test_a_published_recurrence_announces_nothing(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        before = len(self._comms_events(db))
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                **_full_payload(is_published=True, notify_members=True),
                "recurrence": _weekly([0], 5),
            },
        )
        assert r.status_code == 201, r.text
        # Unchanged: no per-occurrence announcement, and no Series
        # announcement either, because no EventSeries was published.
        assert len(self._comms_events(db)) == before

    def test_a_standalone_publication_still_announces_once(
        self, client_as, make_user, make_space, db,
    ):
        """The control. If this ever fails, the repair broke the single
        Gathering path rather than leaving it alone."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events",
            json=_full_payload(is_published=True, notify_members=True),
        )
        assert r.status_code == 201, r.text
        rows = [
            e for e in self._comms_events(db)
            if (e.context or {}).get("space_id") == space.id
        ]
        assert len(rows) == 1
        assert rows[0].event_type == "gathering.published"


# ---------------------------------------------------------------------------
# 6. Existing Gatherings are never touched
# ---------------------------------------------------------------------------


class TestExistingGatheringsAreLeftAlone:
    def test_a_bulk_create_does_not_modify_prior_gatherings(
        self, client_as, make_user, make_space, make_event, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        existing = make_event(space=space, title="Already here")
        existing.venue_locality = None
        existing.ticket_price_cents = 111
        db.flush()
        snapshot = {
            f: getattr(existing, f)
            for f in SHARED_EVENT_FIELDS + TICKET_FIELDS
        }
        existing_id = existing.id

        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={**_full_payload(), "recurrence": _weekly([0], 3)},
        )
        assert r.status_code == 201, r.text

        db.expire_all()
        after = db.get(Event, existing_id)
        assert after is not None
        for field, value in snapshot.items():
            assert getattr(after, field) == value, (
                f"bulk creation altered {field} on an existing Gathering"
            )


# ---------------------------------------------------------------------------
# 7. Permissions, scoping and the write gate
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_a_non_caretaker_cannot_bulk_create(
        self, client_as, make_user, make_space, db,
    ):
        space = make_space(timezone="Australia/Melbourne")
        outsider = make_user(role="creator")
        client = client_as(outsider)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={**_full_payload(), "recurrence": _weekly([0], 3)},
        )
        assert r.status_code == 403, r.text
        assert _occurrences(db, space.id) == []

    def test_a_moderator_may_bulk_create(
        self, client_as, make_user, make_space, db,
    ):
        space = make_space(timezone="Australia/Melbourne")
        moderator = make_user(role="creator")
        db.add(SpaceMembership(
            id=f"sm_{uuid.uuid4().hex[:12]}",
            space_id=space.id,
            user_id=moderator.id,
            role="moderator",
            status="active",
        ))
        db.flush()
        client = client_as(moderator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={**_full_payload(), "recurrence": _weekly([0], 2)},
        )
        assert r.status_code == 201, r.text
        assert len(_occurrences(db, space.id)) == 2

    def test_occurrences_land_only_in_the_target_collective(
        self, client_as, make_user, make_space, db,
    ):
        """Cross-Collective isolation: a creator who owns two
        Collectives writes into exactly the one they named."""
        creator = make_user(role="creator")
        target = make_space(creator=creator, timezone="Australia/Melbourne")
        other = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{target.slug}/events/bulk",
            json={**_full_payload(), "recurrence": _weekly([0], 3)},
        )
        assert r.status_code == 201, r.text
        assert len(_occurrences(db, target.id)) == 3
        assert _occurrences(db, other.id) == []

    def test_a_closed_collective_refuses_bulk_creation(
        self, client_as, make_user, make_space, db,
    ):
        """The write gate ``create_event`` has always applied, now
        applied here too."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        space.closed_at = datetime.utcnow()
        db.flush()
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={**_full_payload(), "recurrence": _weekly([0], 3)},
        )
        assert r.status_code == 403, r.text
        assert _occurrences(db, space.id) == []

    def test_a_frozen_collective_refuses_bulk_creation(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        space.frozen_at = datetime.utcnow()
        space.frozen_until = None
        db.flush()
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={**_full_payload(), "recurrence": _weekly([0], 3)},
        )
        assert r.status_code == 403, r.text
        assert _occurrences(db, space.id) == []

    def test_the_same_gate_still_refuses_a_single_gathering(
        self, client_as, make_user, make_space, db,
    ):
        """Parity in the other direction — the gate was never missing
        here, and must stay."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        space.closed_at = datetime.utcnow()
        db.flush()
        client = client_as(creator)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events", json=_full_payload(),
        )
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 8. The structural guard — no column can be forgotten again
# ---------------------------------------------------------------------------


class TestEveryColumnIsAccountedFor:
    """The buckets in ``services/gathering_fields`` must partition
    ``Event``'s columns exactly.

    This is the test that would have caught FC-201 at the moment
    ``venue_locality`` and the ticket columns were added to the model,
    rather than months later from a creator's report. It reads the
    mapped table, not the source text, so a comment naming a column
    neither satisfies nor breaks it.
    """

    def test_the_three_buckets_cover_every_column(self):
        columns = set(Event.__table__.columns.keys())
        buckets = set(SHARED_EVENT_FIELDS + TICKET_FIELDS + PER_ROW_EVENT_FIELDS)
        missing = columns - buckets
        assert not missing, (
            "These Event columns are in neither bucket in "
            "services/gathering_fields. Decide for each whether it is a "
            "setting both creation paths copy (SHARED_EVENT_FIELDS) or "
            "something an occurrence owns (PER_ROW_EVENT_FIELDS), or a "
            "recurring Gathering will silently lose it: "
            f"{sorted(missing)}"
        )

    def test_the_buckets_name_no_column_that_does_not_exist(self):
        columns = set(Event.__table__.columns.keys())
        buckets = set(SHARED_EVENT_FIELDS + TICKET_FIELDS + PER_ROW_EVENT_FIELDS)
        stale = buckets - columns
        assert not stale, (
            f"services/gathering_fields names columns Event no longer has: "
            f"{sorted(stale)}"
        )

    def test_the_buckets_do_not_overlap(self):
        all_three = (
            list(SHARED_EVENT_FIELDS)
            + list(TICKET_FIELDS)
            + list(PER_ROW_EVENT_FIELDS)
        )
        duplicates = {f for f in all_three if all_three.count(f) > 1}
        assert not duplicates, f"field in more than one bucket: {duplicates}"

    def test_every_shared_field_is_settable_from_the_request(self):
        """A shared field has to be something the editor can actually
        send, or the mapping would read an attribute that is not
        there."""
        from app.creator.schemas import EventCreateRequest

        request_fields = set(EventCreateRequest.model_fields)
        unsettable = set(SHARED_EVENT_FIELDS) - request_fields
        assert not unsettable, (
            "SHARED_EVENT_FIELDS names fields EventCreateRequest does not "
            f"carry: {sorted(unsettable)}"
        )

    def test_ticket_fields_are_not_read_straight_off_the_request(self):
        """The validator's return values are the only ones that may
        reach a row, so the ticket columns must not be in the verbatim
        bucket."""
        assert not set(TICKET_FIELDS) & set(SHARED_EVENT_FIELDS)
