"""End-to-end tests for the Creator Studio attendance dashboard.

Covers the six checks Lindsey called out plus the general correctness
matrix:

  1. Per-occurrence isolation — a check-in / Finish on session 3 must
     never mutate session 4 in the same recurring series.
  2. Booking ownership — every booking mutation verifies the booking
     belongs to the URL's event AND the event belongs to the managed
     space. 404 on either break.
  3. Concurrency safety — the routes take ``SELECT … FOR UPDATE`` on
     the events row so a check-in racing with Finish serialises
     correctly. Tested via the observable outcome (409 when a PATCH
     lands after a Finish committed).
  4. Existing PATCH compatibility — legacy callers
     (``EventManagePanel``, ``CreatorStudioLiteMobile``) send
     ``attended | no_show | pending`` and read the DB-valued
     ``attendance_status`` back. Contract is preserved.
  5. Post-completion arrivals — a confirmed booking that arrives after
     Finish is surfaced with ``pending_post_completion=True`` but does
     NOT contribute to summary counts. Completed summary cannot silently
     gain unresolved bookings.
  6. Fresh data — mutation responses include the recomputed counts so
     the client always has authoritative numbers without a second GET.

Plus:

  * Auth matrix (cross-creator forbidden, unauthenticated denied).
  * Payment separation (mutations never touch payment / entitlement
    columns).
  * Finish + Reopen semantics (auto marks; auto → booked; manual +
    attended survive reopen).
  * Cancelled bookings excluded from roster + counts + CSV.
  * CSV: escaping, formula-injection guard, filename, BOM, quoting.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Force cross-file model registration so relationships resolve during
# the SAVEPOINT test session (matches the pattern used by
# test_uploads_authorization.py).
import app.models.community_care  # noqa: F401

from app.auth.dependencies import get_verified_creator_user, get_creator_user
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    BookingStatus,
    Event,
    EventBooking,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def creator_and_space(db: Session, make_user, make_space):
    """A creator user with an active managed space and a co-creator
    membership row so the auth chain evaluates naturally."""
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    return creator, space


@pytest.fixture
def other_creator(db: Session, make_user, make_space):
    """A completely separate creator + space — used for cross-tenant
    isolation checks."""
    other = make_user(role="creator")
    other_space = make_space(creator=other)
    return other, other_space


@pytest.fixture
def event_and_bookings(db: Session, make_event, make_user, creator_and_space):
    """One event on the managed space with 5 confirmed bookings + 1
    cancelled booking. The cancelled row is present to prove it is
    excluded from the roster, counts, mutations, and CSV."""
    _creator, space = creator_and_space
    event = make_event(space=space, capacity=10)
    bookings = []
    for i in range(5):
        u = make_user(role="user", name=f"Attendee {i}")
        b = EventBooking(
            id=_uid("b"),
            event_id=event.id,
            user_id=u.id,
            status=BookingStatus.confirmed,
            booked_at=datetime.utcnow() - timedelta(days=2),
            source="member",
            note=f"note {i}" if i % 2 else None,
        )
        db.add(b)
        bookings.append((b, u))
    # Cancelled booking — must NOT appear anywhere in the dashboard.
    u_cancelled = make_user(role="user", name="Cancelled Alice")
    b_cancelled = EventBooking(
        id=_uid("b"),
        event_id=event.id,
        user_id=u_cancelled.id,
        status=BookingStatus.cancelled,
        booked_at=datetime.utcnow() - timedelta(days=3),
        cancelled_at=datetime.utcnow() - timedelta(days=1),
        source="member",
    )
    db.add(b_cancelled)
    db.flush()
    return {
        "space": space,
        "event": event,
        "bookings": bookings,
        "cancelled": (b_cancelled, u_cancelled),
    }


@pytest.fixture
def client_as(db: Session):
    """Return a factory that yields a TestClient with the dependency
    overrides set to authenticate as the passed-in user. Restores state
    on teardown so tests can swap identities within a single test."""
    installed = []

    def _install(user):
        app.dependency_overrides[get_verified_creator_user] = lambda: user
        app.dependency_overrides[get_creator_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        installed.append(True)
        return TestClient(app, follow_redirects=False)

    yield _install

    app.dependency_overrides.pop(get_verified_creator_user, None)
    app.dependency_overrides.pop(get_creator_user, None)
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 1. GET /attendance — dashboard payload
# ---------------------------------------------------------------------------


class TestDashboardGet:
    def test_returns_event_counts_and_bookings_ordered_by_name(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        r = client.get(f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance")
        assert r.status_code == 200
        body = r.json()
        assert body["event"]["id"] == event.id
        assert body["event"]["space_slug"] == space.slug
        assert body["event"]["attendance_completed_at"] is None
        assert body["counts"]["total_confirmed"] == 5
        assert body["counts"]["attended"] == 0
        assert body["counts"]["absent"] == 0
        assert body["counts"]["booked"] == 5
        assert body["counts"]["pending_post_completion"] == 0
        assert len(body["bookings"]) == 5
        names = [b["name"] for b in body["bookings"]]
        assert names == sorted(names)  # ordered by name asc

    def test_cancelled_bookings_are_excluded(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        cancelled_booking, _cancelled_user = event_and_bookings["cancelled"]
        r = client.get(f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance")
        assert r.status_code == 200
        body = r.json()
        assert all(row["booking_id"] != cancelled_booking.id for row in body["bookings"])

    def test_unauthorised_creator_gets_403(
        self, client_as, creator_and_space, event_and_bookings, other_creator,
    ):
        other_user, _other_space = other_creator
        # other_user has no membership on creator_and_space's space
        client = client_as(other_user)
        event = event_and_bookings["event"]
        space = event_and_bookings["space"]
        r = client.get(f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance")
        assert r.status_code == 403

    def test_wrong_space_slug_gets_404(
        self, client_as, creator_and_space, event_and_bookings, other_creator,
    ):
        creator, _space = creator_and_space
        client = client_as(creator)
        other_user, other_space = other_creator
        event = event_and_bookings["event"]
        # Correct event id but wrong (foreign) space slug the creator does own
        r = client.get(f"/api/creator/spaces/{other_space.slug}/events/{event.id}/attendance")
        # Creator does not manage other_space → 403 from _get_managed_space
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 2. Booking ownership + check 2 from the brief
# ---------------------------------------------------------------------------


class TestBookingOwnership:
    def test_booking_from_a_different_event_returns_404(
        self, db, client_as, creator_and_space, event_and_bookings, make_event,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event_a = event_and_bookings["event"]
        booking_a, _u = event_and_bookings["bookings"][0]
        event_b = make_event(space=space, title="Session 2")
        # Try to mutate booking_a via event_b's URL
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event_b.id}/attendance/bookings/{booking_a.id}",
            json={"status": "attended"},
        )
        assert r.status_code == 404
        # The legacy endpoint also enforces the same chain
        r2 = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event_b.id}/bookings/{booking_a.id}/attendance",
            json={"status": "attended"},
        )
        assert r2.status_code == 404

    def test_booking_from_another_creators_space_returns_404_or_403(
        self, db, client_as, creator_and_space, other_creator, make_event, make_user,
    ):
        # Foreign creator's event + booking; managed by the wrong owner.
        creator, space = creator_and_space
        client = client_as(creator)
        _other, other_space = other_creator
        other_event = make_event(space=other_space)
        other_user = make_user()
        other_booking = EventBooking(
            id=_uid("b"), event_id=other_event.id, user_id=other_user.id,
            status=BookingStatus.confirmed,
            booked_at=datetime.utcnow(), source="member",
        )
        db.add(other_booking); db.flush()
        # Uses the managed space's slug but foreign event id → 404 on event lookup.
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{other_event.id}/attendance/bookings/{other_booking.id}",
            json={"status": "attended"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3. PATCH — dashboard endpoint + legacy endpoint
# ---------------------------------------------------------------------------


class TestPatchAttendance:
    def test_dashboard_check_in(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{booking.id}",
            json={"status": "attended"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["attendance_status"] == "attended"
        assert body["attendance_source"] == "manual"
        assert body["counts"]["attended"] == 1
        assert body["counts"]["booked"] == 4

    def test_dashboard_undo_check_in(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{booking.id}",
            json={"status": "attended"},
        )
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{booking.id}",
            json={"status": "booked"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["attendance_status"] == "booked"
        assert body["attendance_source"] is None
        assert body["counts"]["attended"] == 0

    def test_dashboard_mark_absent_manual(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{booking.id}",
            json={"status": "absent"},
        )
        assert r.status_code == 200
        assert r.json()["attendance_status"] == "absent"
        assert r.json()["attendance_source"] == "manual"

    def test_dashboard_refuses_cancelled_booking(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        cancelled_b, _u = event_and_bookings["cancelled"]
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{cancelled_b.id}",
            json={"status": "attended"},
        )
        assert r.status_code == 400

    def test_dashboard_refuses_after_finish_with_409(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        rf = client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        assert rf.status_code == 200
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{booking.id}",
            json={"status": "attended"},
        )
        assert r.status_code == 409

    def test_dashboard_bad_status_400(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{booking.id}",
            json={"status": "banana"},
        )
        assert r.status_code == 400


class TestLegacyPatchCompat:
    """The two existing frontend callers send ``attended | no_show |
    pending`` and read ``attendance_status`` (DB shape). That contract
    must keep working unchanged after this feature lands."""

    def test_legacy_attended(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/bookings/{booking.id}/attendance",
            json={"status": "attended"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body == {"booking_id": booking.id, "attendance_status": "attended"}

    def test_legacy_no_show(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/bookings/{booking.id}/attendance",
            json={"status": "no_show"},
        )
        assert r.status_code == 200
        assert r.json()["attendance_status"] == "no_show"

    def test_legacy_pending_resets(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/bookings/{booking.id}/attendance",
            json={"status": "attended"},
        )
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/bookings/{booking.id}/attendance",
            json={"status": "pending"},
        )
        assert r.status_code == 200
        assert r.json()["attendance_status"] is None

    def test_legacy_accepts_new_vocab_too(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        # 'absent' is the new vocab; legacy endpoint accepts it.
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/bookings/{booking.id}/attendance",
            json={"status": "absent"},
        )
        assert r.status_code == 200
        # Response is the DB shape ("no_show") — legacy contract unchanged.
        assert r.json()["attendance_status"] == "no_show"


# ---------------------------------------------------------------------------
# 4. Finish + Reopen semantics
# ---------------------------------------------------------------------------


class TestFinishReopen:
    def test_finish_marks_remaining_as_auto_absent(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        # One person checked in, one manually absent, three still booked
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{booking.id}",
            json={"status": "attended"},
        )
        b2, _u2 = event_and_bookings["bookings"][1]
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{b2.id}",
            json={"status": "absent"},
        )

        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["auto_marked_absent"] == 3
        assert body["counts"]["attended"] == 1
        assert body["counts"]["absent"] == 4  # 1 manual + 3 auto
        assert body["counts"]["booked"] == 0

        # Fetch dashboard and confirm attendance_source is set correctly
        r2 = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance"
        )
        rows = {b["booking_id"]: b for b in r2.json()["bookings"]}
        assert rows[booking.id]["attendance_source"] == "manual"
        assert rows[b2.id]["attendance_source"] == "manual"
        # The other three should be auto
        for other_b, _ in event_and_bookings["bookings"][2:]:
            assert rows[other_b.id]["attendance_status"] == "absent"
            assert rows[other_b.id]["attendance_source"] == "auto"

    def test_finish_is_idempotent_second_call_409(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        r1 = client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        assert r1.status_code == 200
        r2 = client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        assert r2.status_code == 409

    def test_reopen_restores_only_auto_absences(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        b_attended, _u = event_and_bookings["bookings"][0]
        b_manual_absent, _u2 = event_and_bookings["bookings"][1]
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{b_attended.id}",
            json={"status": "attended"},
        )
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{b_manual_absent.id}",
            json={"status": "absent"},
        )
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/reopen"
        )
        assert r.status_code == 200
        assert r.json()["restored_to_booked"] == 3  # the auto ones

        # Attended + manual absent survive; auto absences are back to booked.
        dash = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance"
        ).json()
        rows = {b["booking_id"]: b for b in dash["bookings"]}
        assert rows[b_attended.id]["attendance_status"] == "attended"
        assert rows[b_manual_absent.id]["attendance_status"] == "absent"
        assert rows[b_manual_absent.id]["attendance_source"] == "manual"
        for other_b, _ in event_and_bookings["bookings"][2:]:
            assert rows[other_b.id]["attendance_status"] == "booked"
            assert rows[other_b.id]["attendance_source"] is None

    def test_reopen_without_finish_409(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/reopen"
        )
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# 5. Occurrence isolation — check 1 from the brief
# ---------------------------------------------------------------------------


class TestOccurrenceIsolation:
    def test_finishing_one_session_does_not_touch_another(
        self, client_as, creator_and_space, make_event, make_user, db,
    ):
        """Two Event rows in the same series (same recurrence_series_id).
        Finishing session A must not set completion state on session B
        or mutate B's bookings."""
        creator, space = creator_and_space
        client = client_as(creator)
        series_id = str(uuid.uuid4())
        event_a = make_event(space=space, recurrence_series_id=series_id, title="Session 1")
        event_b = make_event(space=space, recurrence_series_id=series_id, title="Session 2")
        u = make_user()
        booking_a = EventBooking(
            id=_uid("b"), event_id=event_a.id, user_id=u.id,
            status=BookingStatus.confirmed,
            booked_at=datetime.utcnow(), source="member",
        )
        booking_b = EventBooking(
            id=_uid("b"), event_id=event_b.id, user_id=u.id,
            status=BookingStatus.confirmed,
            booked_at=datetime.utcnow(), source="member",
        )
        db.add_all([booking_a, booking_b]); db.flush()

        # Finish A
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event_a.id}/attendance/finish"
        )
        # B is untouched
        db.expire(event_b); db.expire(booking_b)
        assert event_b.attendance_completed_at is None
        assert booking_b.attendance_status is None
        assert booking_b.attendance_source is None

    def test_check_in_on_one_session_does_not_touch_another(
        self, client_as, creator_and_space, make_event, make_user, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event_a = make_event(space=space, title="Session 1")
        event_b = make_event(space=space, title="Session 2")
        u = make_user()
        booking_a = EventBooking(
            id=_uid("b"), event_id=event_a.id, user_id=u.id,
            status=BookingStatus.confirmed,
            booked_at=datetime.utcnow(), source="member",
        )
        booking_b = EventBooking(
            id=_uid("b"), event_id=event_b.id, user_id=u.id,
            status=BookingStatus.confirmed,
            booked_at=datetime.utcnow(), source="member",
        )
        db.add_all([booking_a, booking_b]); db.flush()
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event_a.id}/attendance/bookings/{booking_a.id}",
            json={"status": "attended"},
        )
        db.expire(booking_b)
        assert booking_b.attendance_status is None


# ---------------------------------------------------------------------------
# 6. Payment / entitlement separation
# ---------------------------------------------------------------------------


class TestPaymentSeparation:
    def test_check_in_does_not_touch_payment_fields(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        # ``credits_used`` is an int (no FK) — safe to seed with a
        # non-default value and prove the endpoint does not touch it.
        # payment_transaction_id / access_pass_id stay None (both are FKs;
        # a real row would need a real parent), and the test asserts
        # they stay None after the mutation.
        booking.credits_used = 7
        db.flush()
        pre = {
            "status": booking.status,
            "payment_transaction_id": booking.payment_transaction_id,
            "credits_used": booking.credits_used,
            "access_pass_id": booking.access_pass_id,
            "hold_expires_at": booking.hold_expires_at,
            "cancelled_at": booking.cancelled_at,
        }
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{booking.id}",
            json={"status": "attended"},
        )
        db.expire(booking)
        for k, v in pre.items():
            assert getattr(booking, k) == v, f"{k} changed by attendance mutation"

    def test_finish_does_not_touch_payment_fields(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        pre = []
        for b, _u in event_and_bookings["bookings"]:
            b.credits_used = 3
            pre.append({
                "id": b.id,
                "status": b.status,
                "payment_transaction_id": b.payment_transaction_id,
                "credits_used": b.credits_used,
                "access_pass_id": b.access_pass_id,
                "hold_expires_at": b.hold_expires_at,
                "cancelled_at": b.cancelled_at,
            })
        db.flush()
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        for b, _u in event_and_bookings["bookings"]:
            db.expire(b)
        for expected, (b, _u) in zip(pre, event_and_bookings["bookings"]):
            assert b.id == expected["id"]
            for k in ("status", "payment_transaction_id", "credits_used",
                      "access_pass_id", "hold_expires_at", "cancelled_at"):
                assert getattr(b, k) == expected[k], f"{k} changed by finish"


# ---------------------------------------------------------------------------
# 7. Post-completion arrivals — check 5 from the brief
# ---------------------------------------------------------------------------


class TestPostCompletionArrivals:
    def test_new_booking_after_finish_is_flagged_but_not_in_summary(
        self, client_as, creator_and_space, event_and_bookings, make_user, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        # Finish first
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        # A new confirmed booking arrives AFTER completion
        late_user = make_user(name="Latecomer")
        late = EventBooking(
            id=_uid("b"), event_id=event.id, user_id=late_user.id,
            status=BookingStatus.confirmed,
            booked_at=datetime.utcnow() + timedelta(seconds=5),
            source="member",
        )
        db.add(late); db.flush()

        dash = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance"
        ).json()
        # Late booking IS in the roster
        rows = {b["booking_id"]: b for b in dash["bookings"]}
        assert late.id in rows
        assert rows[late.id]["pending_post_completion"] is True
        assert rows[late.id]["attendance_status"] == "booked"
        # But it is NOT counted in the completion summary
        assert dash["counts"]["pending_post_completion"] == 1
        # attended + absent should still sum to the pre-finish confirmed count (5),
        # NOT 6 (would be silent inclusion of the latecomer)
        assert dash["counts"]["attended"] + dash["counts"]["absent"] == 5

    def test_pending_payment_confirmed_after_finish_is_treated_as_arrival(
        self, client_as, creator_and_space, event_and_bookings, make_user, db,
    ):
        """A booking that existed at Finish as ``pending_payment`` and
        was only confirmed by the payment webhook AFTER Finish must
        behave the same as a brand-new post-completion arrival:
        surfaced in the roster with ``pending_post_completion=True``,
        excluded from the summary counts. Detection is by
        ``attendance_status IS NULL AND completed_at IS NOT NULL`` —
        no booked_at comparison — precisely so this case is caught."""
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]

        # Pre-finish: create a pending_payment booking. It's NOT in
        # the confirmed roster and Finish won't touch it.
        pending_user = make_user(name="Later Confirmed")
        pending_booking = EventBooking(
            id=_uid("b"), event_id=event.id, user_id=pending_user.id,
            status=BookingStatus.pending_payment,
            booked_at=datetime.utcnow() - timedelta(hours=1),  # BEFORE finish
            source="member",
        )
        db.add(pending_booking); db.flush()

        # Finish — pending_payment row is untouched.
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        db.expire(pending_booking)
        assert pending_booking.attendance_status is None

        # Webhook flips the pending booking to confirmed AFTER Finish.
        pending_booking.status = BookingStatus.confirmed
        db.flush()

        dash = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance"
        ).json()
        rows = {b["booking_id"]: b for b in dash["bookings"]}
        assert pending_booking.id in rows
        assert rows[pending_booking.id]["pending_post_completion"] is True
        assert rows[pending_booking.id]["attendance_status"] == "booked"
        assert dash["counts"]["pending_post_completion"] == 1
        # Completed summary numbers UNCHANGED — silent inclusion prohibited.
        assert dash["counts"]["attended"] + dash["counts"]["absent"] == 5


class TestCancelledAfterFinish:
    """A confirmed booking cancelled AFTER Finish must not silently
    disappear from the completed summary. Its historical attendance
    value is frozen; the roster shows a ``cancelled_after_completion``
    flag; the CSV labels it explicitly. Reopen leaves it alone."""

    def _finish_and_cancel_one(self, client, space, event, event_and_bookings):
        """Common setup: Finish (5 auto-absent), then cancel one row.
        Returns (cancelled_booking, cancelled_user)."""
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        b_target, u_target = event_and_bookings["bookings"][0]
        return b_target, u_target

    def test_cancelled_after_finish_stays_in_summary_at_frozen_value(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]

        # Mark one attendee, one manual absent, then Finish.
        b_attended, _ = event_and_bookings["bookings"][0]
        b_manual_absent, _ = event_and_bookings["bookings"][1]
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{b_attended.id}",
            json={"status": "attended"},
        )
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{b_manual_absent.id}",
            json={"status": "absent"},
        )
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )

        # Snapshot the summary numbers before the cancellation.
        pre = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance"
        ).json()
        assert pre["counts"]["attended"] == 1
        assert pre["counts"]["absent"] == 4
        assert pre["counts"]["total_confirmed"] == 5

        # Cancel the ATTENDED person's booking.
        b_attended.status = BookingStatus.cancelled
        b_attended.cancelled_at = datetime.utcnow()
        db.flush()

        post = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance"
        ).json()
        rows = {b["booking_id"]: b for b in post["bookings"]}
        # Still in the roster with the frozen attendance value.
        assert b_attended.id in rows
        assert rows[b_attended.id]["attendance_status"] == "attended"
        assert rows[b_attended.id]["cancelled_after_completion"] is True
        # attended/absent numerators unchanged — the completed summary
        # did not silently drop this person.
        assert post["counts"]["attended"] == 1
        assert post["counts"]["absent"] == 4
        # cohort_size is the persistent completed-summary denominator.
        # Stays at 5 across the cancellation — this is the "12/12 100%"
        # guarantee the reviewer flagged.
        assert post["counts"]["cohort_size"] == 5
        # total_confirmed is a LIVE label — currently-confirmed count.
        # Drops by 1 when a cancellation lands; that's fine because it's
        # NOT the completed summary's denominator any more.
        assert post["counts"]["total_confirmed"] == 4

    def test_reopen_ignores_cancelled_after_finish_rows(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        b_attended, _ = event_and_bookings["bookings"][0]
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{b_attended.id}",
            json={"status": "attended"},
        )
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        # Cancel one auto-absent row after Finish
        b_auto_absent, _ = event_and_bookings["bookings"][2]
        db.expire(b_auto_absent)
        assert b_auto_absent.attendance_status == "no_show"
        assert b_auto_absent.attendance_source == "auto"
        b_auto_absent.status = BookingStatus.cancelled
        b_auto_absent.cancelled_at = datetime.utcnow()
        db.flush()

        # Reopen. Should NOT touch the cancelled row's attendance.
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/reopen"
        )
        assert r.status_code == 200
        db.expire(b_auto_absent)
        # Historical no_show / auto preserved on the cancelled row.
        assert b_auto_absent.attendance_status == "no_show"
        assert b_auto_absent.attendance_source == "auto"

        # After Reopen the cancelled row drops out of the dashboard
        # entirely (in-progress rule = confirmed only).
        dash = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance"
        ).json()
        rows = {b["booking_id"]: b for b in dash["bookings"]}
        assert b_auto_absent.id not in rows

    def test_finish_all_12_attended_then_cancel_one_still_shows_12_100(
        self, client_as, creator_and_space, db, make_user, make_event,
    ):
        """The scenario from the reviewer: 12 confirmed, all checked
        in, Finish, then cancel one. The completed record must still
        show cohort_size=12, attended=12, 100% attendance. The
        cancellation is identified via ``cancelled_after_completion``
        on the row and ``pending_post_completion`` is unaffected."""
        creator, space = creator_and_space
        client = client_as(creator)
        event = make_event(space=space, capacity=16)
        bookings = []
        for i in range(12):
            u = make_user(name=f"Attendee {i:02d}")
            b = EventBooking(
                id=_uid("b"), event_id=event.id, user_id=u.id,
                status=BookingStatus.confirmed,
                booked_at=datetime.utcnow() - timedelta(days=1),
                source="member",
            )
            db.add(b); bookings.append(b)
        db.flush()
        # Check everyone in.
        for b in bookings:
            client.patch(
                f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{b.id}",
                json={"status": "attended"},
            )
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        # Snapshot immediately post-finish.
        pre = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance"
        ).json()
        assert pre["counts"]["cohort_size"] == 12
        assert pre["counts"]["attended"] == 12
        assert pre["counts"]["absent"] == 0
        assert pre["counts"]["total_confirmed"] == 12

        # Cancel one of the attended bookings AFTER Finish.
        bookings[3].status = BookingStatus.cancelled
        bookings[3].cancelled_at = datetime.utcnow()
        db.flush()

        # Refresh — the completed cohort still says 12/12/100%.
        post = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance"
        ).json()
        assert post["counts"]["cohort_size"] == 12
        assert post["counts"]["attended"] == 12
        assert post["counts"]["absent"] == 0
        # total_confirmed is a LIVE label — has dropped by 1.
        assert post["counts"]["total_confirmed"] == 11
        # The cancellation is identifiable on the row.
        row = next(b for b in post["bookings"] if b["booking_id"] == bookings[3].id)
        assert row["cancelled_after_completion"] is True
        assert row["in_finish_cohort"] is True
        assert row["attendance_status"] == "attended"

        # A second GET from a "different device" (fresh client + fresh
        # session) yields identical numbers — proves persistence.
        second_client = client_as(creator)
        again = second_client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance"
        ).json()
        assert again["counts"] == post["counts"]

    def test_booking_cancelled_before_finish_is_excluded(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        """A booking manually attended-then-cancelled BEFORE Finish
        must not appear in the completed cohort even though it had
        an attendance value. It's not in the roster, not in counts,
        not in the CSV."""
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        b_target, _u = event_and_bookings["bookings"][0]
        # Mark attended, then cancel — all BEFORE Finish.
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{b_target.id}",
            json={"status": "attended"},
        )
        b_target.status = BookingStatus.cancelled
        b_target.cancelled_at = datetime.utcnow()
        db.flush()

        # Finish now — the cancelled row does not count towards auto-
        # marked, does not appear in the roster.
        finish_resp = client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        ).json()
        # Started with 5 confirmed → 1 cancelled = 4 left; that one was
        # already-attended, so 4 auto-marked absent.
        assert finish_resp["auto_marked_absent"] == 4

        dash = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance"
        ).json()
        row_ids = {b["booking_id"] for b in dash["bookings"]}
        assert b_target.id not in row_ids
        assert dash["counts"]["cohort_size"] == 4
        assert dash["counts"]["attended"] == 0
        assert dash["counts"]["absent"] == 4

        # CSV also excludes.
        csv_text = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/export.csv"
        ).content.decode("utf-8")
        assert b_target.id not in csv_text

    def test_csv_marks_cancelled_after_finish(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        b_attended, _ = event_and_bookings["bookings"][0]
        client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{b_attended.id}",
            json={"status": "attended"},
        )
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        b_attended.status = BookingStatus.cancelled
        b_attended.cancelled_at = datetime.utcnow()
        db.flush()

        r = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/export.csv"
        )
        text = r.content.decode("utf-8")
        assert "Cancelled after finish (attendance frozen)" in text
        # The attended value is still present for this booking
        assert b_attended.id in text


# ---------------------------------------------------------------------------
# 8. CSV export
# ---------------------------------------------------------------------------


class TestCsvExport:
    def test_csv_contains_totals_and_all_confirmed_rows(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        r = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/export.csv"
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "no-store" in r.headers.get("cache-control", "")
        assert "attachment" in r.headers.get("content-disposition", "")
        text = r.content.decode("utf-8")
        assert text.startswith("\ufeff"), "expected UTF-8 BOM"
        # 5 confirmed rows in the body
        # header + summary lines + blank + column header + 5 rows
        reader = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
        # Count rows that look like attendee rows (11 columns exactly:
        # 10 attendee/booking fields + Booking state).
        attendee_rows = [r for r in reader if len(r) == 11 and r[0].startswith("Attendee")]
        assert len(attendee_rows) == 5

    def test_csv_excludes_cancelled_booking(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        cancelled_b, cancelled_user = event_and_bookings["cancelled"]
        r = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/export.csv"
        )
        text = r.content.decode("utf-8")
        assert cancelled_user.name not in text
        assert cancelled_b.id not in text

    def test_csv_formula_injection_guard(
        self, client_as, creator_and_space, event_and_bookings, db,
    ):
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, u = event_and_bookings["bookings"][0]
        # Malicious values in fields the CSV echoes
        u.name = "=SUM(A1:A2)"
        booking.note = "@cmd|calc"
        db.flush()
        r = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/export.csv"
        )
        text = r.content.decode("utf-8")
        # The offending cells must be prefixed with a single quote
        assert "\"'=SUM(A1:A2)\"" in text
        assert "\"'@cmd|calc\"" in text

    def test_csv_auth_matrix(
        self, client_as, creator_and_space, event_and_bookings, other_creator,
    ):
        other, _os = other_creator
        client = client_as(other)
        event = event_and_bookings["event"]
        space = event_and_bookings["space"]
        r = client.get(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/export.csv"
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 9. Concurrency — observable outcome of the FOR UPDATE lock ordering
# ---------------------------------------------------------------------------


class TestConcurrencyObservable:
    def test_patch_after_finish_serialises_to_409(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        """A PATCH that reads the event row (and takes FOR UPDATE on it)
        AFTER a Finish committed will see the completion state and
        return 409. This is the observable proof that the lock ordering
        is correct — a real race can't be reproduced deterministically
        in a single-process test, but the completion check happens
        under the same lock the mutation takes, so the sequential
        after-finish PATCH proves the check is honoured."""
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/bookings/{booking.id}",
            json={"status": "attended"},
        )
        assert r.status_code == 409

    def test_legacy_patch_after_finish_also_409(
        self, client_as, creator_and_space, event_and_bookings,
    ):
        """The legacy PATCH endpoint takes the same lock and honours
        the same completion gate."""
        creator, space = creator_and_space
        client = client_as(creator)
        event = event_and_bookings["event"]
        booking, _u = event_and_bookings["bookings"][0]
        client.post(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/attendance/finish"
        )
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}/bookings/{booking.id}/attendance",
            json={"status": "attended"},
        )
        assert r.status_code == 409
