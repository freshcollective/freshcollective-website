"""Advance-booking regression — pay-in-full member buys a future Series
and reserves individual sessions before the series start date.

Covers the fix that keys pass-window enforcement to ``event.starts_at``
(the calendar position of the session) instead of the booking creation
time. Previously, a Term 4 pass whose ``valid_from`` was 5 October
could not be used to reserve any session until October, even though
the buyer legitimately held the seat from the September purchase.

Guardrails still enforced:

  * ``eligible_series_id`` must match ``event.series_id``;
  * total_credits and credits_per_week still cap bookings;
  * ``valid_until`` still terminates the pass window;
  * a pass cannot be used to book an event *outside* its window
    (e.g. a mis-scheduled session with the wrong ``starts_at``);
  * duplicate-pass checkout guard still rejects re-purchase.

The final-Saturday boundary case is exercised explicitly: a pass whose
``valid_until = series.ends_at`` on 12 December must still cover the
Saturday 12 December 9am (Melbourne) session, which is stored as
2026-12-11T22:00:00 UTC.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.checkout.routes import create_gathering_series_checkout_session
from app.checkout.schemas import GatheringSeriesCheckoutRequest
from app.core.config import settings
from app.models.access_pass import (
    AccessPass,
    AccessPassSource,
    AccessPassStatus,
    AccessPassType,
)
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    Event,
    EventBooking,
    EventSeries,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.creator.routes import list_space_passes
from app.spaces._series_member_routes import (
    _find_active_series_pass,
    get_member_gathering_series,
)
from app.spaces.routes import (
    _viewer_has_series_pass,
    book_event,
    get_event,
    get_my_passes,
    list_events,
)
from app.webhooks.routes import _handle_checkout_completed


# ---------------------------------------------------------------------------
# Helpers — small on purpose. Mirror the shape used in
# tests/test_gathering_series.py so a future consolidation is easy.
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _member(db, user, space, *, role: SpaceRole = SpaceRole.learner) -> SpaceMembership:
    m = SpaceMembership(
        id=_uid("sm"),
        user_id=user.id,
        space_id=space.id,
        role=role,
        status=SpaceMembershipStatus.active,
    )
    db.add(m)
    db.flush()
    return m


def _make_series(
    db, space, *, title: str, starts_at: datetime,
    ends_at: datetime | None,
) -> EventSeries:
    s = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        status="published",
    )
    db.add(s)
    db.flush()
    return s


def _make_series_option(
    db, space, series, *, name: str,
    total_sessions: int, sessions_per_week: int, price_cents: int,
) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=None,
        attaches_to_kind="event_series",
        attaches_to_id=series.id,
        name=name,
        payment_type=PaymentOptionType.term_pass,
        status=PaymentOptionStatus.published,
        term_start_date=series.starts_at.date(),
        term_end_date=series.ends_at.date() if series.ends_at else None,
        sessions_per_week=sessions_per_week,
        total_sessions=total_sessions,
        price_per_session_cents=price_cents // max(total_sessions, 1),
        calculated_total_cents=price_cents,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _make_schedule(db, option) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"),
        payment_option_id=option.id,
        name="Pay in full",
        schedule_type="pay_in_full",
        status="published",
        total_amount_cents=option.calculated_total_cents,
        currency="AUD",
    )
    db.add(s)
    db.flush()
    return s


def _make_txn(db, *, payer, space, gross_cents: int) -> PaymentTransaction:
    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.pending,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=payer.id,
        creator_user_id=space.creator_id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=gross_cents,
        platform_fee_basis_points=800,
        platform_fee_cents=int(gross_cents * 0.08),
        net_creator_amount_cents=gross_cents - int(gross_cents * 0.08),
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
        provider_checkout_session_id=_uid("cs"),
    )
    db.add(txn)
    db.flush()
    return txn


def _fire_webhook(db, *, txn, payment_option, series):
    """Replay checkout.session.completed for a Series purchase."""
    session = {
        "id": txn.provider_checkout_session_id,
        "payment_status": "paid",
        "payment_intent": _uid("pi"),
        "metadata": {
            "transaction_id": txn.id,
            "payer_user_id": txn.payer_user_id,
            "space_id": txn.space_id,
            "payment_option_id": payment_option.id,
        },
    }
    _handle_checkout_completed(session, db)


def _make_event(
    db, space, *, series: EventSeries, starts_at: datetime,
    capacity: int | None = 20,
) -> Event:
    e = Event(
        id=_uid("e"),
        space_id=space.id,
        created_by_id=space.creator_id,
        title="Session",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        is_published=True,
        status="active",
        requires_booking=True,
        capacity=capacity,
        gathering_type="circle",
        attendance_format="online",
        booking_access_type="included_with_series",
        series_id=series.id,
    )
    db.add(e)
    db.flush()
    return e


def _purchase_term_pass(
    db, *, payer, space, series,
    total_sessions: int = 10, sessions_per_week: int = 1,
    price_cents: int = 20000,
) -> AccessPass:
    """Full end-to-end: seed the option, run the webhook, return the AP."""
    opt = _make_series_option(
        db, space, series, name="Awaken",
        total_sessions=total_sessions,
        sessions_per_week=sessions_per_week,
        price_cents=price_cents,
    )
    txn = _make_txn(db, payer=payer, space=space, gross_cents=price_cents)
    db.commit()
    _fire_webhook(db, txn=txn, payment_option=opt, series=series)
    return (
        db.query(AccessPass)
        .filter(
            AccessPass.user_id == payer.id,
            AccessPass.eligible_series_id == series.id,
        )
        .one()
    )


# Fixed "today" — 10 September 2026, matching the production scenario.
NOW_SEP = datetime(2026, 9, 10, 12, 0, 0)


# ---------------------------------------------------------------------------
# 1. Future purchase, September now — reads and booking commit
# ---------------------------------------------------------------------------


class TestFuturePurchaseReadsAndBooking:
    def _term4(self, db, space):
        """Term 4 2026: 5 October → 12 December, Melbourne dates stored
        as naive UTC. Series starts at 05 Oct 07:00 UTC (Monday 6pm-ish
        Melbourne — matches the shape in ``term4_2026_repair.py``)."""
        return _make_series(
            db, space, title="EMBODY Term 4 2026",
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
            ends_at=datetime(2026, 12, 12, 12, 0, 0),
        )

    def test_september_purchase_can_book_first_october_gathering(
        self, db, make_space, make_user,
    ):
        """Product intent: buy in September, reserve the October 5
        opening session immediately. Pass credits decrement by 1."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = self._term4(db, space)
        first_monday = _make_event(
            db, space, series=term4,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        ap = _purchase_term_pass(db, payer=payer, space=space, series=term4)
        db.commit()

        # Sanity: purchase created a future pass.
        assert ap.valid_from == term4.starts_at
        assert ap.valid_until == term4.ends_at
        assert ap.used_credits == 0

        result = book_event(
            slug=space.slug, event_id=first_monday.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        assert result.status == "confirmed"
        db.refresh(ap)
        assert ap.used_credits == 1

    def test_viewer_has_series_pass_true_for_future_series(
        self, db, make_space, make_user,
    ):
        """UI-side ``_viewer_has_series_pass`` must report True for a
        member who legitimately holds a future-window pass — this is
        what feeds ``EventDetail.user_has_series_pass`` and gates the
        "Reserve" CTA on the per-event page."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = self._term4(db, space)
        _purchase_term_pass(db, payer=payer, space=space, series=term4)
        db.commit()

        assert _viewer_has_series_pass(payer, term4.id, db, NOW_SEP) is True

    def test_series_member_page_finds_future_pass(
        self, db, make_space, make_user,
    ):
        """``_find_active_series_pass`` powers the Series page's access
        summary card. A future-window pass must be surfaced there too
        so the buyer sees "10 total, 0 booked, 10 available" as soon
        as the purchase clears."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = self._term4(db, space)
        ap = _purchase_term_pass(db, payer=payer, space=space, series=term4)
        db.commit()

        found = _find_active_series_pass(payer, term4.id, db, NOW_SEP)
        assert found is not None
        assert found.id == ap.id

    def test_events_list_reports_user_has_series_pass(
        self, db, make_space, make_user,
    ):
        """The ``GET /events`` list endpoint must set
        ``user_has_series_pass=True`` and ``can_book=True`` for the
        future-Series events, so the member gathering grid renders
        the "Reserve" CTA (not "Pass required")."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = self._term4(db, space)
        first_monday = _make_event(
            db, space, series=term4,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        _purchase_term_pass(db, payer=payer, space=space, series=term4)
        db.commit()

        rows = list_events(
            slug=space.slug, scope="upcoming",
            db=db, current_user=payer,
        )
        [row] = [r for r in rows if r.id == first_monday.id]
        assert row.user_has_series_pass is True
        assert row.booking_access_type == "included_with_series"
        assert row.can_book is True

    def test_event_detail_reports_user_has_series_pass(
        self, db, make_space, make_user,
    ):
        """The ``GET /events/{id}`` detail endpoint must set
        ``user_has_series_pass=True`` so the client-side
        ``GatheringBookingClient`` renders Reserve instead of the
        "Term 4 2026 pass is required" fallback."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = self._term4(db, space)
        first_monday = _make_event(
            db, space, series=term4,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        _purchase_term_pass(db, payer=payer, space=space, series=term4)
        db.commit()

        detail = get_event(
            slug=space.slug, event_id=first_monday.id,
            db=db, current_user=payer,
        )
        assert detail["user_has_series_pass"] is True
        assert detail["booking_access_type"] == "included_with_series"
        assert detail["can_book"] is True


# ---------------------------------------------------------------------------
# 2. Credit caps continue to apply for advance bookings
# ---------------------------------------------------------------------------


class TestCreditCapsUnderAdvanceBooking:
    def test_ten_weekly_sessions_all_bookable_in_advance(
        self, db, make_space, make_user,
    ):
        """A 1-per-week × 10-total pass, bought in September, can
        immediately reserve one Monday event per week for the full
        ten weeks. Every booking succeeds; used_credits climbs to 10.
        Boundary: the last two Mondays sit against Dec 14 / Dec 21 —
        beyond the 12 Dec pass window — so the ten distinct
        booked-events must all fall inside the window."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = _make_series(
            db, space, title="EMBODY Term 4 2026",
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
            ends_at=datetime(2026, 12, 12, 12, 0, 0),
        )
        # Ten Mondays: 5 Oct → 7 Dec inclusive (still inside window).
        events = [
            _make_event(
                db, space, series=term4,
                starts_at=datetime(2026, 10, 5, 7, 0, 0) + timedelta(weeks=w),
            )
            for w in range(10)
        ]
        ap = _purchase_term_pass(
            db, payer=payer, space=space, series=term4,
            total_sessions=10, sessions_per_week=1,
        )
        db.commit()

        for e in events:
            book_event(
                slug=space.slug, event_id=e.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        db.refresh(ap)
        assert ap.used_credits == 10

    def test_weekly_cap_still_blocks_two_in_same_week(
        self, db, make_space, make_user,
    ):
        """1-per-week cap: two events in the same event-week — even
        though both are future dates — the second is 409."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = _make_series(
            db, space, title="EMBODY Term 4 2026",
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
            ends_at=datetime(2026, 12, 12, 12, 0, 0),
        )
        # Same event-week: Monday 5 Oct + Thursday 8 Oct.
        mon = _make_event(
            db, space, series=term4,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        thu = _make_event(
            db, space, series=term4,
            starts_at=datetime(2026, 10, 8, 7, 0, 0),
        )
        _purchase_term_pass(
            db, payer=payer, space=space, series=term4,
            total_sessions=10, sessions_per_week=1,
        )
        db.commit()

        book_event(
            slug=space.slug, event_id=mon.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        with pytest.raises(HTTPException) as exc:
            book_event(
                slug=space.slug, event_id=thu.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert exc.value.status_code == 409

    def test_total_cap_blocks_eleventh_advance_booking(
        self, db, make_space, make_user,
    ):
        """total_credits=10 → the eleventh booking is 409 even when
        every session is scheduled inside the pass window."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = _make_series(
            db, space, title="EMBODY Term 4 2026",
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
            ends_at=datetime(2026, 12, 12, 12, 0, 0),
        )
        # 11 events, all comfortably *inside* the pass window (so the
        # window check does not trip first) and at most 3 per event-
        # week (so the 5/week cap does not trip either). What we're
        # asserting is the total-credit boundary — the 11th booking.
        # Mon/Wed/Fri × weeks 1..4 = 11 sessions.
        day_offsets = [0, 2, 4, 7, 9, 11, 14, 16, 18, 21, 23]
        events = [
            _make_event(
                db, space, series=term4,
                starts_at=datetime(2026, 10, 5, 7, 0, 0) + timedelta(days=d),
            )
            for d in day_offsets
        ]
        _purchase_term_pass(
            db, payer=payer, space=space, series=term4,
            total_sessions=10, sessions_per_week=5,
        )
        db.commit()

        for e in events[:10]:
            book_event(
                slug=space.slug, event_id=e.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        with pytest.raises(HTTPException) as exc:
            book_event(
                slug=space.slug, event_id=events[10].id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# 3. Window boundaries — the 12 December Saturday case + genuine
#    over-the-end refusal.
# ---------------------------------------------------------------------------


class TestWindowBoundaries:
    def test_final_saturday_9am_melbourne_is_bookable(
        self, db, make_space, make_user,
    ):
        """The load-bearing case the user called out: Term 4 ends on
        12 December 2026 and there is a Saturday gathering that day
        at 9am (Melbourne). In UTC that session is stored as
        ``2026-12-11T22:00:00``. A pass with
        ``valid_until = 2026-12-12T12:00:00`` (any time later than
        the event start) must still cover it."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = _make_series(
            db, space, title="EMBODY Term 4 2026",
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
            # Series ends the same calendar day as the final session
            # (12 Dec Melbourne). Whether the Creator entered noon,
            # end-of-day, or midnight-next-day, the value MUST be
            # >= 22:00 UTC on Dec 11 (= 9am Dec 12 Melbourne) for
            # the final session to be bookable. Assert the boundary
            # case explicitly against noon UTC on 12 Dec (a plausible
            # choice for "end of term day").
            ends_at=datetime(2026, 12, 12, 12, 0, 0),
        )
        final_saturday = _make_event(
            db, space, series=term4,
            starts_at=datetime(2026, 12, 11, 22, 0, 0),  # Sat 12 Dec 9am AEDT
        )
        _purchase_term_pass(
            db, payer=payer, space=space, series=term4,
            total_sessions=10, sessions_per_week=1,
        )
        db.commit()

        result = book_event(
            slug=space.slug, event_id=final_saturday.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        assert result.status == "confirmed"

    def test_event_after_pass_end_is_refused(
        self, db, make_space, make_user,
    ):
        """An event tagged to Term 4 but scheduled *after* the pass
        window closes (e.g. a stray 15-December session with the
        Term-4 series_id) is refused. The pass window bounds which
        dates the pass covers."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = _make_series(
            db, space, title="EMBODY Term 4 2026",
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
            ends_at=datetime(2026, 12, 12, 12, 0, 0),
        )
        beyond_window = _make_event(
            db, space, series=term4,
            starts_at=datetime(2026, 12, 15, 7, 0, 0),  # 3 days after end
        )
        _purchase_term_pass(
            db, payer=payer, space=space, series=term4,
            total_sessions=10, sessions_per_week=1,
        )
        db.commit()

        with pytest.raises(HTTPException) as exc:
            book_event(
                slug=space.slug, event_id=beyond_window.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert exc.value.status_code == 403

    def test_event_before_pass_start_is_refused(
        self, db, make_space, make_user,
    ):
        """A misaligned event scheduled *before* the pass window opens
        — e.g. a September session that somehow carries the Term-4
        ``series_id`` — is refused. The series-match predicate would
        also block a legitimate Term-3 session; this test isolates
        the window bound."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = _make_series(
            db, space, title="EMBODY Term 4 2026",
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
            ends_at=datetime(2026, 12, 12, 12, 0, 0),
        )
        before_window = _make_event(
            db, space, series=term4,
            starts_at=datetime(2026, 9, 20, 7, 0, 0),
        )
        _purchase_term_pass(
            db, payer=payer, space=space, series=term4,
            total_sessions=10, sessions_per_week=1,
        )
        db.commit()

        with pytest.raises(HTTPException) as exc:
            book_event(
                slug=space.slug, event_id=before_window.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 4. Duplicate-pass checkout guard — must block re-purchase even when
#    the existing pass is still in its pre-window period.
# ---------------------------------------------------------------------------


class TestFuturePassBlocksRepurchase:
    def test_future_series_pass_blocks_repurchase(
        self, db, make_space, make_user, monkeypatch,
    ):
        """A member who already owns a Term-4 pass (valid_from in the
        future, valid_until at term end) must not be able to buy the
        same Series again while sitting in September. Regression for
        the ``valid_from <= now`` filter that previously masked the
        existing pass out of the duplicate-guard query."""
        # Stripe must appear configured for the endpoint's boot guard.
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")

        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term4 = _make_series(
            db, space, title="EMBODY Term 4 2026",
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
            ends_at=datetime(2026, 12, 12, 12, 0, 0),
        )
        opt = _make_series_option(
            db, space, term4, name="Awaken",
            total_sessions=10, sessions_per_week=1, price_cents=20000,
        )
        schedule = _make_schedule(db, opt)
        # Seed the pre-existing future-window pass directly (skipping
        # the webhook path — this test is about the guard, not the
        # fulfilment).
        db.add(AccessPass(
            id=_uid("ap"),
            user_id=payer.id,
            space_id=space.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            valid_from=term4.starts_at,
            valid_until=term4.ends_at,
            eligible_series_id=term4.id,
            total_credits=10,
            credits_per_week=1,
            source=AccessPassSource.one_time_purchase,
        ))
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_gathering_series_checkout_session(
                GatheringSeriesCheckoutRequest(
                    series_id=term4.id,
                    payment_option_id=opt.id,
                    payment_option_schedule_id=schedule.id,
                    success_url="https://app.test/ok",
                    cancel_url="https://app.test/cancel",
                ),
                current_user=payer, db=db,
            )
        assert exc.value.status_code == 409

    def test_expired_pass_does_not_block_repurchase(
        self, db, make_space, make_user, monkeypatch,
    ):
        """Sanity companion — an *expired* prior pass (valid_until in
        the past) does NOT trip the duplicate guard. Without this
        check the pre-existing dropped ``valid_from`` filter could
        also weaken the ``valid_until`` intent."""
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")

        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        # A prior Term-3 series that ended a year ago.
        term3 = _make_series(
            db, space, title="Prior Term",
            starts_at=datetime(2025, 7, 1, 7, 0, 0),
            ends_at=datetime(2025, 9, 30, 12, 0, 0),
        )
        db.add(AccessPass(
            id=_uid("ap-expired"),
            user_id=payer.id,
            space_id=space.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            valid_from=term3.starts_at,
            valid_until=term3.ends_at,  # already elapsed
            eligible_series_id=term3.id,
        ))

        # Now a fresh Term-4 offering. New series, new pass window —
        # the guard must not confuse the expired Term-3 pass for a
        # duplicate of Term-4.
        term4 = _make_series(
            db, space, title="EMBODY Term 4 2026",
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
            ends_at=datetime(2026, 12, 12, 12, 0, 0),
        )
        opt4 = _make_series_option(
            db, space, term4, name="Awaken",
            total_sessions=10, sessions_per_week=1, price_cents=20000,
        )
        schedule4 = _make_schedule(db, opt4)
        db.commit()

        # We can't complete the full Stripe roundtrip here without
        # heavy mocking; the guard's negative path is what we're
        # asserting — pass the guard, land on the *next* checkpoint
        # (Stripe not configured / other downstream behaviour) rather
        # than 409. The endpoint should NOT raise 409.
        try:
            create_gathering_series_checkout_session(
                GatheringSeriesCheckoutRequest(
                    series_id=term4.id,
                    payment_option_id=opt4.id,
                    payment_option_schedule_id=schedule4.id,
                    success_url="https://app.test/ok",
                    cancel_url="https://app.test/cancel",
                ),
                current_user=payer, db=db,
            )
        except HTTPException as exc:
            # Anything except 409 means the guard let us past — that's
            # what we care about.
            assert exc.status_code != 409, (
                "Expired prior pass wrongly tripped the duplicate-pass guard."
            )
        except Exception:
            # Stripe SDK bubble — also proves we're past the guard.
            pass


# ---------------------------------------------------------------------------
# 5. Privileged-role behaviour on booking + pass consumption
#
# Product rule (see book_event's Privilege rule comment):
#
#   * Privilege bypasses REJECTION (403/409) so a creator or moderator
#     can attend or test a gathering they don't have a pass for, or
#     one whose caps are already met.
#   * Privilege does NOT bypass CONSUMPTION. When a matching pass
#     exists AND the booking fits inside its remaining weekly + total
#     allowance, the pass is charged normally — otherwise a creator
#     who buys their own offering sees perpetually-stale accounting.
#   * Privilege NEVER inflates accounting past what was purchased.
#     When caps are met, the booking proceeds without a pass link.
# ---------------------------------------------------------------------------


def _term4_series(db, space):
    """Same shape as the production Term 4 window."""
    return _make_series(
        db, space, title="EMBODY Term 4 2026",
        starts_at=datetime(2026, 10, 5, 7, 0, 0),
        ends_at=datetime(2026, 12, 12, 12, 0, 0),
    )


def _seed_pass_directly(
    db, *, user, space, series, role_membership: SpaceMembership,
    total_credits: int = 10, credits_per_week: int = 1,
    used_credits: int = 0,
) -> AccessPass:
    """Bypass the webhook and seed a pass in one place — lets the
    per-case tests be explicit about the starting ``used_credits``
    and role, rather than driving every case through the checkout
    fulfilment. Roles are set on the SpaceMembership fixture."""
    ap = AccessPass(
        id=_uid("ap"),
        user_id=user.id,
        space_id=space.id,
        pass_type=AccessPassType.term_pass,
        status=AccessPassStatus.active,
        valid_from=series.starts_at,
        valid_until=series.ends_at,
        eligible_series_id=series.id,
        total_credits=total_credits,
        used_credits=used_credits,
        credits_per_week=credits_per_week,
        source=AccessPassSource.one_time_purchase,
    )
    db.add(ap)
    db.flush()
    return ap


# NOW must be inside the series pass window so weekly-usage counters
# read against a real "current week" at the time the booking happens
# — otherwise `_weekly_usage_for()` sits in September and never sees
# the Oct 5 booking during the same test call. All the privilege
# cases test consumption at book time, which is where the fix lives.


class TestLearnerBaseline:
    """Learner behaviour must NOT change under the fix. These cases
    pin the pre-existing enforcement semantics so a refactor that
    accidentally weakens them fails loudly."""

    def test_learner_with_available_allowance_consumes_pass(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space, role=SpaceRole.learner)
        series = _term4_series(db, space)
        event = _make_event(
            db, space, series=series,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        ap = _seed_pass_directly(
            db, user=payer, space=space, series=series,
            role_membership=None,
        )
        db.commit()

        result = book_event(
            slug=space.slug, event_id=event.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        assert result.status == "confirmed"

        db.refresh(ap)
        assert ap.used_credits == 1
        booking = (
            db.query(EventBooking)
            .filter(EventBooking.event_id == event.id,
                    EventBooking.user_id == payer.id)
            .one()
        )
        assert booking.access_pass_id == ap.id
        assert booking.credits_used == 1

    def test_learner_without_pass_series_gated_rejected(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space, role=SpaceRole.learner)
        series = _term4_series(db, space)
        event = _make_event(
            db, space, series=series,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        db.commit()

        with pytest.raises(HTTPException) as exc:
            book_event(
                slug=space.slug, event_id=event.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert exc.value.status_code == 403

    def test_learner_total_cap_exhausted_rejected(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space, role=SpaceRole.learner)
        series = _term4_series(db, space)
        event = _make_event(
            db, space, series=series,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        # 10 of 10 already used.
        _seed_pass_directly(
            db, user=payer, space=space, series=series,
            role_membership=None,
            total_credits=10, used_credits=10,
        )
        db.commit()

        with pytest.raises(HTTPException) as exc:
            book_event(
                slug=space.slug, event_id=event.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert exc.value.status_code == 409

    def test_learner_weekly_cap_hit_rejected(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space, role=SpaceRole.learner)
        series = _term4_series(db, space)
        first = _make_event(
            db, space, series=series,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        second = _make_event(
            db, space, series=series,
            starts_at=datetime(2026, 10, 8, 7, 0, 0),  # same week
        )
        _seed_pass_directly(
            db, user=payer, space=space, series=series,
            role_membership=None,
            total_credits=10, credits_per_week=1,
        )
        db.commit()

        book_event(
            slug=space.slug, event_id=first.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        with pytest.raises(HTTPException) as exc:
            book_event(
                slug=space.slug, event_id=second.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert exc.value.status_code == 409


class TestPrivilegedRoleWithPass:
    """Creator / moderator + matching pass with headroom → consume
    the pass. Fixes the production bug where a privileged buyer
    saw perpetual 0/10."""

    @pytest.mark.parametrize("role", [SpaceRole.creator, SpaceRole.moderator])
    def test_privileged_with_available_allowance_consumes_pass(
        self, db, make_space, make_user, role,
    ):
        # ``make_space`` seeds a fresh creator user as space.creator_id.
        # For this case we want a *distinct* privileged user (either a
        # co-creator or moderator) so we're not conflating "the Space's
        # owner" with the tester.
        space = make_space()
        payer = make_user()
        _member(db, payer, space, role=role)
        series = _term4_series(db, space)
        event = _make_event(
            db, space, series=series,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        ap = _seed_pass_directly(
            db, user=payer, space=space, series=series,
            role_membership=None,
        )
        db.commit()

        result = book_event(
            slug=space.slug, event_id=event.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        assert result.status == "confirmed"

        db.refresh(ap)
        assert ap.used_credits == 1, (
            f"{role.value} with a matching pass must have used_credits "
            "incremented when the booking fits inside the allowance."
        )
        booking = (
            db.query(EventBooking)
            .filter(EventBooking.event_id == event.id,
                    EventBooking.user_id == payer.id)
            .one()
        )
        assert booking.access_pass_id == ap.id
        assert booking.credits_used == 1


class TestPrivilegedRoleWithoutPass:
    """Creator / moderator without a matching pass → booking allowed
    via privilege, no pass consumption. Unchanged bypass semantic."""

    @pytest.mark.parametrize("role", [SpaceRole.creator, SpaceRole.moderator])
    def test_privileged_without_pass_series_gated_allowed(
        self, db, make_space, make_user, role,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space, role=role)
        series = _term4_series(db, space)
        event = _make_event(
            db, space, series=series,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        db.commit()

        result = book_event(
            slug=space.slug, event_id=event.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        assert result.status == "confirmed"

        booking = (
            db.query(EventBooking)
            .filter(EventBooking.event_id == event.id,
                    EventBooking.user_id == payer.id)
            .one()
        )
        assert booking.access_pass_id is None
        assert booking.credits_used == 0
        # Sanity: no phantom pass was created.
        assert db.query(AccessPass).filter(
            AccessPass.user_id == payer.id
        ).count() == 0


class TestPrivilegedRoleWithCappedPass:
    """Privileged users with a pass whose caps are met — booking
    allowed via privilege, but the pass must NOT be charged past
    the allowance. Privilege can permit attendance outside the
    entitlement; it must not inflate the accounting."""

    @pytest.mark.parametrize("role", [SpaceRole.creator, SpaceRole.moderator])
    def test_privileged_with_total_exhausted_does_not_charge_pass(
        self, db, make_space, make_user, role,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space, role=role)
        series = _term4_series(db, space)
        event = _make_event(
            db, space, series=series,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        ap = _seed_pass_directly(
            db, user=payer, space=space, series=series,
            role_membership=None,
            total_credits=10, used_credits=10,
        )
        db.commit()

        result = book_event(
            slug=space.slug, event_id=event.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        assert result.status == "confirmed"

        db.refresh(ap)
        assert ap.used_credits == 10, (
            "Privilege must not push used_credits past total_credits."
        )
        booking = (
            db.query(EventBooking)
            .filter(EventBooking.event_id == event.id,
                    EventBooking.user_id == payer.id)
            .one()
        )
        assert booking.access_pass_id is None
        assert booking.credits_used == 0

    @pytest.mark.parametrize("role", [SpaceRole.creator, SpaceRole.moderator])
    def test_privileged_with_weekly_cap_hit_does_not_charge_pass(
        self, db, make_space, make_user, role,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space, role=role)
        series = _term4_series(db, space)
        first = _make_event(
            db, space, series=series,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        second = _make_event(
            db, space, series=series,
            starts_at=datetime(2026, 10, 8, 7, 0, 0),  # same event-week
        )
        ap = _seed_pass_directly(
            db, user=payer, space=space, series=series,
            role_membership=None,
            total_credits=10, credits_per_week=1,
        )
        db.commit()

        # First booking uses the pass (within cap for that week).
        book_event(
            slug=space.slug, event_id=first.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        db.refresh(ap)
        assert ap.used_credits == 1

        # Second booking in the same event-week: privilege permits
        # attendance but must not charge the pass a second time.
        result = book_event(
            slug=space.slug, event_id=second.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        assert result.status == "confirmed"

        db.refresh(ap)
        assert ap.used_credits == 1, (
            "Privileged booking beyond the weekly cap must not increment "
            "used_credits."
        )
        second_booking = (
            db.query(EventBooking)
            .filter(EventBooking.event_id == second.id,
                    EventBooking.user_id == payer.id)
            .one()
        )
        assert second_booking.access_pass_id is None
        assert second_booking.credits_used == 0


class TestReadThroughSummariesAfterPrivilegedBooking:
    """After a privileged buyer with an in-allowance booking, the
    three surfaces the user called out must all reflect the
    consumption. Verifies both the write (in earlier tests) and the
    read paths together — no stale-cache-y intermediate."""

    def _setup_creator_with_pass_and_booking(
        self, db, make_space, make_user, *, role=SpaceRole.creator,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space, role=role)
        series = _term4_series(db, space)
        event = _make_event(
            db, space, series=series,
            starts_at=datetime(2026, 10, 5, 7, 0, 0),
        )
        ap = _seed_pass_directly(
            db, user=payer, space=space, series=series,
            role_membership=None,
            total_credits=10, credits_per_week=1,
        )
        # Attach the payment_option so the my-passes / access page
        # can resolve option_name — mirrors the production shape
        # without needing to run the full checkout webhook.
        opt = _make_series_option(
            db, space, series, name="Awaken",
            total_sessions=10, sessions_per_week=1, price_cents=20000,
        )
        ap.payment_option_id = opt.id
        db.flush()
        db.commit()

        book_event(
            slug=space.slug, event_id=event.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        db.refresh(ap)
        return space, payer, series, event, ap

    def test_my_passes_endpoint_shows_1_booked_9_remaining(
        self, db, make_space, make_user,
    ):
        """Powers the Collective Gatherings page "Booked" /
        "Available to book" widget (spaces.routes.get_my_passes,
        rendered by frontend/.../events/page.tsx:150)."""
        space, payer, _, _, _ = self._setup_creator_with_pass_and_booking(
            db, make_space, make_user,
        )
        rows = get_my_passes(slug=space.slug, db=db, current_user=payer)
        [row] = [r for r in rows if r.pass_type == "term_pass"]
        assert row.used_credits == 1
        assert row.remaining_credits == 9
        assert row.total_credits == 10

    def test_series_your_access_shows_1_of_10_and_remaining_9(
        self, db, make_space, make_user,
    ):
        """Powers the Series page "Your Access" card
        (_series_access_summary via get_member_gathering_series,
        rendered by SeriesSidebar.tsx)."""
        space, payer, series, _, _ = self._setup_creator_with_pass_and_booking(
            db, make_space, make_user,
        )
        detail = get_member_gathering_series(
            slug=space.slug, series_slug=series.slug,
            db=db, current_user=payer,
        )
        assert detail.access.has_access is True
        assert detail.access.gatherings_used == 1
        assert detail.access.gatherings_total == 10
        assert detail.access.gatherings_remaining == 9
        assert detail.access.gatherings_per_week == 1

    def test_creator_studio_access_endpoint_shows_credit_and_booking(
        self, db, make_space, make_user,
    ):
        """Powers the Creator Studio Access page rows
        (creator.routes.list_space_passes, rendered by AccessClient.tsx).
        The "Gathering allowance" column reads used/total and the
        "Bookings (30d)" column counts EventBooking rows with
        access_pass_id == this pass — the exact metric production
        currently shows as 10/10 and 0 bookings."""
        space, payer, _, _, ap = self._setup_creator_with_pass_and_booking(
            db, make_space, make_user,
        )
        # list_space_passes requires a creator/admin of the Space to
        # call it. The Space's owner (space.creator_id) satisfies
        # ``_get_managed_space`` via is_owner.
        owner = db.query(User).filter(User.id == space.creator_id).one()
        rows = list_space_passes(
            slug=space.slug, status_filter=None,
            db=db, current_user=owner,
        )
        [row] = [r for r in rows if r.id == ap.id]
        # CreditBar source — the "Gathering allowance" column.
        assert row.used_credits == 1
        assert row.total_credits == 10
        assert row.remaining_credits == 9
        # "Bookings (30d)" column source. The booking was just made,
        # so both counters see it.
        assert row.total_bookings == 1
        assert row.recent_bookings == 1
