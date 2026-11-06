"""FC-209 — a recurring schedule announces itself once.

The defect
----------
Publishing a run of Gatherings generated together, with no formal
``EventSeries``, announced nothing at all. The occurrence-level refusal
in ``publication_announcement._belongs_to_series`` was right — twelve
emails for one decision is a flood — and nothing picked the batch up
afterwards. The creator pressed a button labelled "Publish Series" and
members were never told.

The two concepts this file keeps apart
--------------------------------------
A **recurring schedule** is a set of *independent* Gatherings sharing a
``recurrence_series_id``: Kelly's Women's Circle on the first Friday of
each month, each date booked and paid for on its own.

A **formal Gathering Series** is a connected experience with its own
page, lifecycle and payment options, identified by ``series_id``.

Both can be true of the same rows. When they are, the Series announces
and the recurrence stays silent — so the two can never both fire for
the same Gatherings. That is the duplicate-prevention rule, and it is
asserted from both directions here.

What is deliberately NOT tested as changed
------------------------------------------
Recurrence generation, ticketing and the field mapping from FC-201.
Those have their own files and are run alongside this one; a failure
there is a regression in FC-201, not in this work.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Cross-file model registration for the SAVEPOINT test session.
import app.models.community_care  # noqa: F401

from app.auth.dependencies import get_creator_user, get_verified_creator_user
from app.comms.categories import (
    CHANNEL_EMAIL_TRANSACTIONAL,
    CHANNEL_IN_APP,
    PRIORITY_SILENT,
)
from app.comms.models import CommunicationEvent
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    Event,
    EventSeries,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import publication_announcement as pub


RECURRENCE = pub.RECURRENCE_EVENT
GATHERING = pub.GATHERING_EVENT
SERIES = pub.SERIES_EVENT

#: Mon 5 Oct 2026, 6 pm Australia/Melbourne (AEDT, +11) = 07:00 UTC.
ANCHOR = datetime(2026, 10, 5, 7, 0, 0, tzinfo=timezone.utc)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def kelly(make_user):
    return make_user(role="creator", name="Kelly")


@pytest.fixture
def space(make_space, kelly):
    return make_space(
        creator=kelly, name="Moonlit Circle", timezone="Australia/Melbourne",
    )


@pytest.fixture
def client_as(db: Session):
    """Both creator dependencies, because this file drives two routers.

    Gathering writes require the verified variant; the Gathering Series
    PATCH takes ``get_creator_user``. Overriding only one leaves the
    other answering 401, which reads as a permission bug rather than a
    missing override.
    """
    def _install(user):
        app.dependency_overrides[get_verified_creator_user] = lambda: user
        app.dependency_overrides[get_creator_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app, follow_redirects=False)

    yield _install

    app.dependency_overrides.pop(get_verified_creator_user, None)
    app.dependency_overrides.pop(get_creator_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def join(db):
    def _join(space, user, role=SpaceRole.learner):
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=user.id, space_id=space.id,
            role=role, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()
        return user
    return _join


def _payload(**overrides) -> dict:
    payload = {
        "title": "Women's Circle",
        "description": "<p>A monthly circle.</p>",
        "starts_at": ANCHOR.isoformat(),
        "ends_at": (ANCHOR + timedelta(hours=2)).isoformat(),
        "location_type": "in_person",
        "attendance_format": "in_person",
        "gathering_type": "circle",
        "venue_locality": "Fitzroy, Melbourne",
        "venue_address": "12 Private Lane, Fitzroy VIC 3065",
        "access_instructions": "Side door.",
        "booking_access_type": "included_with_collective",
        "requires_booking": True,
        "is_published": True,
        "notify_members": True,
    }
    payload.update(overrides)
    return payload


def _recurrence(days=(0,), count=12, label="Women's Circle") -> dict:
    return {
        "pattern": "weekly",
        "days_of_week": list(days),
        "end_after_n": count,
        "series_label": label,
    }


def _bulk(client, space, *, payload=None, recurrence=None):
    return client.post(
        f"/api/creator/spaces/{space.slug}/events/bulk",
        json={
            **(payload or _payload()),
            "recurrence": recurrence or _recurrence(),
        },
    )


def _events_of(db, space_id, event_type):
    return [
        e for e in db.query(CommunicationEvent)
        .filter(CommunicationEvent.event_type == event_type)
        .all()
        if (e.context or {}).get("space_id") == space_id
    ]


def _occurrences(db, space_id):
    return (
        db.query(Event)
        .filter(Event.space_id == space_id)
        .order_by(Event.starts_at)
        .all()
    )


def _make_series(db, space, status="draft", notify=True):
    row = EventSeries(
        id=_uid("es"), space_id=space.id, title="Autumn Term",
        slug=f"term-{uuid.uuid4().hex[:8]}",
        starts_at=datetime.utcnow() + timedelta(days=7),
        status=status, notify_members=notify,
        published_at=datetime.utcnow() if status == "published" else None,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Scenario A — a schedule with no formal Series
# ---------------------------------------------------------------------------


class TestScenarioA_StandaloneSchedule:
    def test_twelve_occurrences_produce_one_announcement(
        self, db, client_as, kelly, space,
    ):
        """The headline. Not twelve, and not zero."""
        r = _bulk(client_as(kelly), space)
        assert r.status_code == 201, r.text
        assert len(_occurrences(db, space.id)) == 12

        batch = _events_of(db, space.id, RECURRENCE)
        assert len(batch) == 1
        # And emphatically not the per-occurrence announcement.
        assert _events_of(db, space.id, GATHERING) == []
        assert _events_of(db, space.id, SERIES) == []

    def test_it_is_keyed_to_the_schedule_not_an_occurrence(
        self, db, client_as, kelly, space,
    ):
        r = _bulk(client_as(kelly), space)
        tag = r.json()["recurrence_series_id"]
        ev = _events_of(db, space.id, RECURRENCE)[0]
        assert ev.dedupe_key == pub.recurrence_dedupe_key(tag, space.id)
        assert ev.subject_type == "recurrence"
        assert ev.subject_id == tag
        assert ev.actor_user_id == kelly.id

    def test_the_payload_describes_the_schedule(
        self, db, client_as, kelly, space,
    ):
        _bulk(client_as(kelly), space)
        p = _events_of(db, space.id, RECURRENCE)[0].payload
        assert p["occurrence_count"] == 12
        assert p["schedule_name"] == "Women's Circle"
        assert p["first_starts_at"] < p["last_starts_at"]
        # The Collective's own zone, not UTC.
        assert "at 6:00pm" in (p["first_when"] or "")
        assert p["is_paid"] is False

    def test_a_schedule_with_no_name_falls_back_to_the_title(
        self, db, client_as, kelly, space,
    ):
        """``schedule_name`` is never empty — a heading cannot be."""
        _bulk(
            client_as(kelly), space,
            payload=_payload(title="Monday Sit"),
            recurrence=_recurrence(label=None),
        )
        p = _events_of(db, space.id, RECURRENCE)[0].payload
        assert p["schedule_name"] == "Monday Sit"

    def test_a_single_standalone_gathering_still_announces_itself(
        self, db, client_as, kelly, space,
    ):
        """The control: nothing about the non-recurring path moved."""
        r = client_as(kelly).post(
            f"/api/creator/spaces/{space.slug}/events", json=_payload(),
        )
        assert r.status_code == 201, r.text
        assert len(_events_of(db, space.id, GATHERING)) == 1
        assert _events_of(db, space.id, RECURRENCE) == []


# ---------------------------------------------------------------------------
# Scenario B — attached to a formal Series
# ---------------------------------------------------------------------------


class TestScenarioB_FormalSeries:
    def test_a_batch_in_a_series_announces_nothing_from_the_recurrence(
        self, db, client_as, kelly, space,
    ):
        """The duplicate-prevention rule, from the recurrence side."""
        series = _make_series(db, space, status="draft")
        r = _bulk(
            client_as(kelly), space, payload=_payload(series_id=series.id),
        )
        assert r.status_code == 201, r.text
        assert {e.series_id for e in _occurrences(db, space.id)} == {series.id}
        assert _events_of(db, space.id, RECURRENCE) == []
        assert _events_of(db, space.id, GATHERING) == []

    def test_publishing_the_series_still_announces_exactly_once(
        self, db, client_as, kelly, space,
    ):
        """And from the Series side: unchanged behaviour.

        Driven through the Series' own route rather than by calling the
        service after a commit — ``emit`` opens a SAVEPOINT, which this
        suite's session cannot do once an HTTP request has committed.
        Exercising the real path is the better test anyway.
        """
        series = _make_series(db, space, status="draft")
        slug = series.slug
        client = client_as(kelly)
        _bulk(client, space, payload=_payload(series_id=series.id))

        r = client.patch(
            f"/api/creator/spaces/{space.slug}/gathering-series/{slug}",
            json={"status": "published"},
        )
        assert r.status_code == 200, r.text
        assert len(_events_of(db, space.id, SERIES)) == 1
        # Still nothing from the recurrence — no duplicate.
        assert _events_of(db, space.id, RECURRENCE) == []

    def test_republishing_the_series_adds_no_second_announcement(
        self, db, client_as, kelly, space,
    ):
        series = _make_series(db, space, status="draft")
        slug = series.slug
        client = client_as(kelly)
        _bulk(client, space, payload=_payload(series_id=series.id))
        for status in ("published", "draft", "published"):
            r = client.patch(
                f"/api/creator/spaces/{space.slug}/gathering-series/{slug}",
                json={"status": status},
            )
            assert r.status_code == 200, r.text
        assert len(_events_of(db, space.id, SERIES)) == 1
        assert _events_of(db, space.id, RECURRENCE) == []

    def test_publishing_an_occurrence_of_a_series_batch_announces_nothing(
        self, db, client_as, kelly, space,
    ):
        """Editing a Series occurrence must not reach either batch
        announcement. The dispatcher checks ``series_id`` first."""
        series = _make_series(db, space, status="draft")
        _bulk(
            client_as(kelly), space,
            payload=_payload(series_id=series.id, is_published=False),
        )
        one = _occurrences(db, space.id)[0]
        r = client_as(kelly).patch(
            f"/api/creator/spaces/{space.slug}/events/{one.id}",
            json={"is_published": True},
        )
        assert r.status_code == 200, r.text
        assert _events_of(db, space.id, RECURRENCE) == []
        assert _events_of(db, space.id, GATHERING) == []

    def test_the_series_announcement_counts_the_generated_occurrences(
        self, db, client_as, kelly, space,
    ):
        """A recurring batch inside a Series is still that Series'
        sessions — the Series announcement reports them."""
        series = _make_series(db, space, status="draft")
        slug = series.slug
        client = client_as(kelly)
        _bulk(
            client, space,
            payload=_payload(series_id=series.id),
            recurrence=_recurrence(count=6),
        )
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/gathering-series/{slug}",
            json={"status": "published"},
        )
        assert r.status_code == 200, r.text
        ev = _events_of(db, space.id, SERIES)[0]
        assert ev.payload["session_count"] == 6


# ---------------------------------------------------------------------------
# Scenario C — drafts
# ---------------------------------------------------------------------------


class TestScenarioC_Drafts:
    def test_a_draft_schedule_announces_nothing(
        self, db, client_as, kelly, space,
    ):
        r = _bulk(
            client_as(kelly), space, payload=_payload(is_published=False),
        )
        assert r.status_code == 201, r.text
        assert len(_occurrences(db, space.id)) == 12
        assert _events_of(db, space.id, RECURRENCE) == []

    def test_publishing_one_occurrence_later_announces_the_schedule(
        self, db, client_as, kelly, space,
    ):
        """There is no batch-level publish action, so the first
        occurrence to become member-visible announces the schedule."""
        _bulk(client_as(kelly), space, payload=_payload(is_published=False))
        rows = _occurrences(db, space.id)

        r = client_as(kelly).patch(
            f"/api/creator/spaces/{space.slug}/events/{rows[0].id}",
            json={"is_published": True},
        )
        assert r.status_code == 200, r.text
        assert len(_events_of(db, space.id, RECURRENCE)) == 1

    def test_publishing_the_remaining_eleven_adds_nothing(
        self, db, client_as, kelly, space,
    ):
        _bulk(client_as(kelly), space, payload=_payload(is_published=False))
        client = client_as(kelly)
        for row in _occurrences(db, space.id):
            r = client.patch(
                f"/api/creator/spaces/{space.slug}/events/{row.id}",
                json={"is_published": True},
            )
            assert r.status_code == 200, r.text
        assert len(_events_of(db, space.id, RECURRENCE)) == 1

    def test_a_draft_schedule_is_not_member_visible(
        self, db, client_as, kelly, space,
    ):
        r = _bulk(
            client_as(kelly), space, payload=_payload(is_published=False),
        )
        tag = r.json()["recurrence_series_id"]
        assert pub.recurrence_is_member_visible(db, space.id, tag) is False
        assert pub.recurrence_facts(db, space.id, tag) is None

    def test_a_cancelled_schedule_is_not_an_invitation(
        self, db, client_as, kelly, space,
    ):
        """Every occurrence cancelled means nothing to announce."""
        r = _bulk(
            client_as(kelly), space, payload=_payload(is_published=False),
        )
        tag = r.json()["recurrence_series_id"]
        for row in _occurrences(db, space.id):
            row.is_published = True
            row.status = "cancelled"
        db.flush()
        assert pub.recurrence_is_member_visible(db, space.id, tag) is False

    def test_one_live_occurrence_is_enough(
        self, db, client_as, kelly, space,
    ):
        """A creator who published eleven of twelve has published the
        schedule."""
        r = _bulk(
            client_as(kelly), space, payload=_payload(is_published=False),
        )
        tag = r.json()["recurrence_series_id"]
        rows = _occurrences(db, space.id)
        rows[3].is_published = True
        db.flush()
        assert pub.recurrence_is_member_visible(db, space.id, tag) is True
        facts = pub.recurrence_facts(db, space.id, tag)
        assert facts is not None and facts.count == 1


# ---------------------------------------------------------------------------
# Scenario D — the creator said no
# ---------------------------------------------------------------------------


class TestScenarioD_NotifyDisabled:
    def test_notify_members_false_announces_nothing(
        self, db, client_as, kelly, space,
    ):
        r = _bulk(
            client_as(kelly), space, payload=_payload(notify_members=False),
        )
        assert r.status_code == 201, r.text
        assert len(_occurrences(db, space.id)) == 12
        assert _events_of(db, space.id, RECURRENCE) == []

    def test_the_choice_survives_a_draft_and_a_later_publication(
        self, db, client_as, kelly, space,
    ):
        """The creator's "no" is stored on every row, so publishing an
        occurrence weeks later still respects it."""
        _bulk(
            client_as(kelly), space,
            payload=_payload(is_published=False, notify_members=False),
        )
        one = _occurrences(db, space.id)[0]
        r = client_as(kelly).patch(
            f"/api/creator/spaces/{space.slug}/events/{one.id}",
            json={"is_published": True},
        )
        assert r.status_code == 200, r.text
        assert _events_of(db, space.id, RECURRENCE) == []

    def test_should_announce_refuses_on_the_flag_alone(
        self, db, client_as, kelly, space,
    ):
        r = _bulk(client_as(kelly), space)
        tag = r.json()["recurrence_series_id"]
        # Visible and already announced; the flag is asserted on its own.
        assert pub.should_announce_recurrence(
            db, space.id, tag, notify_members=False,
        ) is False


# ---------------------------------------------------------------------------
# Scenario E — repeated saves and later edits
# ---------------------------------------------------------------------------


class TestScenarioE_NoResend:
    @pytest.fixture
    def published(self, db, client_as, kelly, space):
        r = _bulk(client_as(kelly), space)
        assert r.status_code == 201, r.text
        assert len(_events_of(db, space.id, RECURRENCE)) == 1
        return r.json()["recurrence_series_id"]

    def test_a_repeated_bulk_request_creates_a_second_batch_not_a_resend(
        self, db, client_as, kelly, space, published,
    ):
        """A replayed POST is a new recurrence tag by design — it
        generates new Gatherings. What must not happen is the FIRST
        schedule announcing twice."""
        before = _events_of(db, space.id, RECURRENCE)
        r = _bulk(client_as(kelly), space)
        assert r.status_code == 201
        after = _events_of(db, space.id, RECURRENCE)
        keys = {e.dedupe_key for e in after}
        assert len(keys) == len(after), "a schedule announced twice"
        assert before[0].dedupe_key in keys

    @pytest.mark.parametrize("patch", [
        {"title": "Renamed Circle"},
        {"description": "<p>New words.</p>"},
        {"venue_locality": "Carlton, Melbourne"},
        {"venue_address": "9 Other Lane"},
        {"access_instructions": "Front door now."},
        {"booking_note": "Bring a cushion."},
        {"capacity": 20},
        {"is_public": True},
    ])
    def test_editing_an_occurrence_does_not_resend(
        self, db, client_as, kelly, space, published, patch,
    ):
        one = _occurrences(db, space.id)[0]
        r = client_as(kelly).patch(
            f"/api/creator/spaces/{space.slug}/events/{one.id}", json=patch,
        )
        assert r.status_code == 200, r.text
        assert len(_events_of(db, space.id, RECURRENCE)) == 1

    def test_moving_one_date_does_not_resend(
        self, db, client_as, kelly, space, published,
    ):
        """The dedupe key is the recurrence tag, which a date change
        never touches."""
        one = _occurrences(db, space.id)[0]
        moved = (ANCHOR + timedelta(days=3)).isoformat()
        r = client_as(kelly).patch(
            f"/api/creator/spaces/{space.slug}/events/{one.id}",
            json={"starts_at": moved},
        )
        assert r.status_code == 200, r.text
        assert len(_events_of(db, space.id, RECURRENCE)) == 1

    def test_returning_one_to_draft_and_publishing_it_again_does_not_resend(
        self, db, client_as, kelly, space, published,
    ):
        one = _occurrences(db, space.id)[0]
        client = client_as(kelly)
        for value in (False, True):
            r = client.patch(
                f"/api/creator/spaces/{space.slug}/events/{one.id}",
                json={"is_published": value},
            )
            assert r.status_code == 200, r.text
        assert len(_events_of(db, space.id, RECURRENCE)) == 1

    def test_cancelling_one_occurrence_does_not_resend(
        self, db, client_as, kelly, space, published,
    ):
        one = _occurrences(db, space.id)[0]
        r = client_as(kelly).post(
            f"/api/creator/spaces/{space.slug}/events/{one.id}/cancel",
        )
        assert r.status_code == 200, r.text
        assert len(_events_of(db, space.id, RECURRENCE)) == 1

    def test_the_service_is_idempotent_when_called_directly(
        self, db, kelly, space, published,
    ):
        assert pub.announce_recurrence_if_newly_published(
            db, space_id=space.id, recurrence_series_id=published,
            actor_user_id=kelly.id, notify_members=True,
        ) is None


# ---------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------


class TestRecipients:
    def _resolve(self, db, space_id):
        from app.comms.routing.resolver import get_resolver_for
        ev = _events_of(db, space_id, RECURRENCE)[0]
        return get_resolver_for(RECURRENCE).resolve(db, ev)

    def test_active_members_are_selected_and_the_creator_is_not(
        self, db, client_as, kelly, space, join, make_user,
    ):
        join(space, kelly, role=SpaceRole.creator)
        a = join(space, make_user())
        b = join(space, make_user())
        _bulk(client_as(kelly), space)

        ids = {r.user_id for r in self._resolve(db, space.id)}
        assert ids == {a.id, b.id}
        assert kelly.id not in ids

    def test_a_non_member_is_not_selected(
        self, db, client_as, kelly, space, join, make_user,
    ):
        member = join(space, make_user())
        outsider = make_user()
        _bulk(client_as(kelly), space)
        ids = {r.user_id for r in self._resolve(db, space.id)}
        assert ids == {member.id}
        assert outsider.id not in ids

    def test_an_inactive_membership_is_not_selected(
        self, db, client_as, kelly, space, join, make_user,
    ):
        gone = join(space, make_user())
        row = (
            db.query(SpaceMembership)
            .filter(SpaceMembership.user_id == gone.id)
            .one()
        )
        row.status = SpaceMembershipStatus.removed
        db.flush()
        _bulk(client_as(kelly), space)
        assert self._resolve(db, space.id) == []

    def test_a_member_of_another_collective_is_not_selected(
        self, db, client_as, kelly, space, make_space, join, make_user,
    ):
        """Cross-Collective isolation on the recipient list."""
        mine = join(space, make_user())
        other = make_space(timezone="Australia/Melbourne")
        theirs = join(other, make_user())
        _bulk(client_as(kelly), space)
        ids = {r.user_id for r in self._resolve(db, space.id)}
        assert ids == {mine.id}
        assert theirs.id not in ids

    def test_the_resolver_goes_silent_if_the_schedule_is_withdrawn(
        self, db, client_as, kelly, space, join, make_user,
    ):
        """Routing runs after the response, so every occurrence can be
        unpublished in the gap."""
        join(space, make_user())
        _bulk(client_as(kelly), space)
        for row in _occurrences(db, space.id):
            row.is_published = False
        db.flush()
        assert self._resolve(db, space.id) == []

    def test_the_destination_is_the_gatherings_page(
        self, db, client_as, kelly, space, join, make_user,
    ):
        join(space, make_user())
        _bulk(client_as(kelly), space)
        ctx = self._resolve(db, space.id)[0].template_context
        assert ctx["gatherings_url"] == f"/spaces/{space.slug}/events"
        # Not keyed to an occurrence, so no edit can break it.
        for row in _occurrences(db, space.id):
            assert row.id not in ctx["gatherings_url"]

    def test_private_attendance_details_never_reach_the_context(
        self, db, client_as, kelly, space, join, make_user,
    ):
        """An announcement goes to people who have not booked."""
        join(space, make_user())
        _bulk(
            client_as(kelly), space,
            payload=_payload(location_url="https://zoom.test/secret"),
        )
        ev = _events_of(db, space.id, RECURRENCE)[0]
        ctx = self._resolve(db, space.id)[0].template_context
        for blob in (ev.payload, ctx):
            flat = repr(blob)
            assert "12 Private Lane" not in flat
            assert "Side door" not in flat
            assert "zoom.test/secret" not in flat
        # The public locality is fine — the Gathering page shows it.
        assert ctx["venue_locality"] == "Fitzroy, Melbourne"


# ---------------------------------------------------------------------------
# Preferences and the delivery classification
# ---------------------------------------------------------------------------


class TestPreferences:
    def test_the_member_can_switch_it_off(self, db, space, make_user):
        """An announcement must stay opt-out-able. It is governed by the
        Gatherings category, like the reminder and the other two
        publication announcements."""
        from app.comms.preferences import get_effective_preference, set_preference

        who = make_user()
        set_preference(
            db, user_id=who.id, category_key="gatherings",
            channel=CHANNEL_EMAIL_TRANSACTIONAL, priority=PRIORITY_SILENT,
        )
        db.flush()
        priority, locked, origin = get_effective_preference(
            db, user_id=who.id, category_key="gatherings",
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
        )
        assert priority == PRIORITY_SILENT
        assert locked is False
        assert origin == "override"

    def test_it_is_not_delivery_locked(self):
        from app.comms.registry import is_transactional_event
        assert is_transactional_event(RECURRENCE) is False

    def test_it_sits_in_the_gatherings_category(self):
        from app.comms.registry import category_for_topic, get_event_definition
        d = get_event_definition(RECURRENCE)
        assert d is not None
        assert d.topic == "gatherings"
        assert category_for_topic(d.topic) == "gatherings"

    def test_the_topic_is_live_so_an_intent_can_reach_a_provider(self):
        from app.comms.rollout import is_event_live
        assert is_event_live(RECURRENCE) is True


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TestTemplates:
    CTX = {
        "collective_name": "Moonlit Circle",
        "schedule_name": "Women's Circle",
        "gathering_title": "Women's Circle",
        "occurrence_count": 12,
        "first_when": "Friday 7 November at 10:00am",
        "attendance_format": "in_person",
        "venue_locality": "Fitzroy, Melbourne",
        "location_type": "in_person",
        "description": "A monthly circle.",
        "is_paid": False,
        "gatherings_url": "/spaces/moonlit/events",
        "recurrence_series_id": "rec_1",
    }

    def _render(self, channel, **overrides):
        from app.comms.routing.resolver import ResolvedRecipient
        from app.comms.templates.registry import get_template_for
        t = get_template_for(RECURRENCE, channel)
        assert t is not None, f"no template for {channel}"
        return t.render(None, None, ResolvedRecipient(
            user_id="u", role_in_event="member_of_collective",
            human_reason="h", template_context={**self.CTX, **overrides},
        ))

    def test_both_channels_have_a_template(self):
        from app.comms.templates.registry import get_template_for
        assert get_template_for(RECURRENCE, CHANNEL_IN_APP) is not None
        assert get_template_for(
            RECURRENCE, CHANNEL_EMAIL_TRANSACTIONAL,
        ) is not None

    def test_the_email_names_the_collective_and_the_schedule(self):
        p = self._render(CHANNEL_EMAIL_TRANSACTIONAL)
        assert "Moonlit Circle" in p.subject
        assert "Women's Circle" in p.subject
        assert "Women&#x27;s Circle" in p.body_html or "Women's Circle" in p.body_html

    def test_the_email_says_there_are_several_dates(self):
        p = self._render(CHANNEL_EMAIL_TRANSACTIONAL)
        assert "12 gatherings" in p.body_text
        assert "Friday 7 November at 10:00am" in p.body_text

    def test_the_email_does_not_imply_a_package(self):
        """The line that keeps a schedule from reading as a paid
        Series, present whether the dates are free or ticketed."""
        for is_paid in (False, True):
            p = self._render(CHANNEL_EMAIL_TRANSACTIONAL, is_paid=is_paid)
            assert "booked separately" in p.body_text
            low = p.body_text.lower()
            assert "series" not in low
            assert "package" not in low

    def test_the_email_links_to_the_gatherings_page_absolutely(self):
        p = self._render(CHANNEL_EMAIL_TRANSACTIONAL)
        assert "/spaces/moonlit/events" in p.body_text
        assert "://" in p.body_text, "a bare path reached an inbox"

    def test_the_email_uses_the_shared_shell(self):
        p = self._render(CHANNEL_EMAIL_TRANSACTIONAL)
        assert p.body_html.lstrip().startswith("<!DOCTYPE html>")

    def test_the_email_carries_only_the_public_locality(self):
        p = self._render(
            CHANNEL_EMAIL_TRANSACTIONAL,
            venue_address="12 Private Lane", access_instructions="Side door",
        )
        assert "Fitzroy, Melbourne" in p.body_text
        assert "Private Lane" not in p.body_text
        assert "Side door" not in p.body_text

    def test_an_online_schedule_reads_as_online(self):
        p = self._render(
            CHANNEL_EMAIL_TRANSACTIONAL,
            attendance_format="online", location_type="zoom",
            venue_locality=None,
        )
        assert "Online" in p.body_text

    def test_the_in_app_notification_is_short_and_links_back(self):
        p = self._render(CHANNEL_IN_APP)
        assert p.subject == "New dates: Women's Circle"
        assert "12 gatherings" in p.body_text
        assert p.metadata["url"] == "/spaces/moonlit/events"
        assert p.metadata["notification_type"] == (
            "gathering_recurrence_published"
        )

    def test_a_one_date_schedule_does_not_say_dates(self):
        """Degenerate but reachable — ``end_after_n`` of 1, and also the
        creator who publishes one occurrence of a draft batch."""
        p = self._render(CHANNEL_IN_APP, occurrence_count=1)
        assert p.subject == "New gathering: Women's Circle"
        assert "1 gathering," in p.body_text

    def test_one_date_is_never_called_several_or_the_first(self):
        """The email must stay true at every count. The opening slot
        therefore carries no number, and the generated span says "on"
        rather than "the first on" when there is only one."""
        p = self._render(CHANNEL_EMAIL_TRANSACTIONAL, occurrence_count=1)
        assert "several" not in p.body_text.lower()
        assert "the first on" not in p.body_text
        assert "1 gathering, on Friday 7 November at 10:00am" in p.body_text
        # Nothing to choose between, so the choose-your-dates line goes.
        assert "booked separately" not in p.body_text

    def test_many_dates_do_say_the_first(self):
        p = self._render(CHANNEL_EMAIL_TRANSACTIONAL, occurrence_count=12)
        assert "12 gatherings, the first on" in p.body_text
        assert "booked separately" in p.body_text

    def test_nothing_renders_blank_without_a_name(self):
        p = self._render(
            CHANNEL_EMAIL_TRANSACTIONAL,
            schedule_name=None, gathering_title=None,
        )
        assert p.subject.strip()
        assert "{{" not in p.body_html


# ---------------------------------------------------------------------------
# Permissions and scoping on the announcing path
# ---------------------------------------------------------------------------


class TestPermissionsAndScoping:
    def test_a_non_caretaker_cannot_announce_anything(
        self, db, client_as, space, make_user,
    ):
        outsider = make_user(role="creator")
        r = _bulk(client_as(outsider), space)
        assert r.status_code == 403, r.text
        assert _events_of(db, space.id, RECURRENCE) == []

    def test_a_closed_collective_announces_nothing(
        self, db, client_as, kelly, space,
    ):
        space.closed_at = datetime.utcnow()
        db.flush()
        r = _bulk(client_as(kelly), space)
        assert r.status_code == 403, r.text
        assert _events_of(db, space.id, RECURRENCE) == []

    def test_a_draft_collective_is_not_announceable(
        self, db, client_as, kelly, space,
    ):
        """``_collective_is_live`` — an experience nobody can reach is
        not announced."""
        r = _bulk(client_as(kelly), space, payload=_payload(is_published=False))
        tag = r.json()["recurrence_series_id"]
        for row in _occurrences(db, space.id):
            row.is_published = True
        space.status = "draft"
        db.flush()
        assert pub.recurrence_is_member_visible(db, space.id, tag) is False

    def test_a_recurrence_tag_cannot_reach_across_collectives(
        self, db, client_as, kelly, space, make_space,
    ):
        """The facts query is scoped by ``space_id``, so the same tag
        asked of another Collective finds nothing."""
        r = _bulk(client_as(kelly), space)
        tag = r.json()["recurrence_series_id"]
        other = make_space(timezone="Australia/Melbourne")
        assert pub.recurrence_facts(db, other.id, tag) is None
        assert pub.recurrence_is_member_visible(db, other.id, tag) is False

    def test_occurrences_land_only_in_the_target_collective(
        self, db, client_as, kelly, space, make_space,
    ):
        other = make_space(creator=kelly, timezone="Australia/Melbourne")
        _bulk(client_as(kelly), space)
        assert len(_occurrences(db, space.id)) == 12
        assert _occurrences(db, other.id) == []
        assert _events_of(db, other.id, RECURRENCE) == []


# ---------------------------------------------------------------------------
# The three publication announcements, side by side
# ---------------------------------------------------------------------------


class TestTheDispatcher:
    """``announce_if_newly_published`` is the one entry point, and its
    ordering is the rule. Asserted directly so a route refactor cannot
    quietly change which announcement a Gathering gets."""

    def test_a_series_occurrence_gets_nothing(
        self, db, space, make_event, kelly,
    ):
        series = _make_series(db, space)
        g = make_event(space=space, is_published=True)
        g.series_id = series.id
        g.recurrence_series_id = "rec_x"
        db.flush()
        assert pub.announce_if_newly_published(
            db, g, actor_user_id=kelly.id,
        ) is None

    def test_a_recurrence_occurrence_gets_the_schedule_announcement(
        self, db, space, make_event, kelly,
    ):
        g = make_event(space=space, is_published=True)
        g.series_id = None
        g.recurrence_series_id = "rec_y"
        g.notify_members = True
        db.flush()
        a = pub.announce_if_newly_published(db, g, actor_user_id=kelly.id)
        assert a is not None
        assert a.event_type == RECURRENCE
        assert a.event.event_type == RECURRENCE

    def test_a_standalone_gathering_gets_its_own_announcement(
        self, db, space, make_event, kelly,
    ):
        g = make_event(space=space, is_published=True)
        g.series_id = None
        g.recurrence_series_id = None
        db.flush()
        a = pub.announce_if_newly_published(db, g, actor_user_id=kelly.id)
        assert a is not None
        assert a.event_type == GATHERING

    def test_the_occurrence_level_refusal_is_unchanged(
        self, db, space, make_event,
    ):
        """FC-209 did not relax ``should_announce_gathering``. A
        recurrence row still may not announce *itself* — that is what
        stops twelve emails."""
        g = make_event(space=space, is_published=True)
        g.recurrence_series_id = "rec_z"
        db.flush()
        assert pub.should_announce_gathering(db, g) is False
        assert pub._belongs_to_series(g) is True
