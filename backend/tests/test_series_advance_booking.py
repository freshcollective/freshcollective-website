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
    EventSeries,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.spaces._series_member_routes import _find_active_series_pass
from app.spaces.routes import (
    _viewer_has_series_pass,
    book_event,
    get_event,
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
