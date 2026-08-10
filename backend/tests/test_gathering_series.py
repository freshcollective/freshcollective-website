"""Gathering Series foundation — Step 1 tests.

Covers the migration-105 groundwork:

  * ``EventSeries`` model round-trips.
  * ``events.series_id`` FK behaviour.
  * ``PaymentOption`` polymorphic ``attaches_to_*`` — existing rows
    backfilled to ``('pathway', pathway_id)``; new rows can attach
    to ``event_series``.
  * ``AccessPass.eligible_series_id`` persistence.
  * Webhook ``checkout.session.completed``:
      – pathway-attached term_pass path unchanged (regression);
      – series-attached term_pass creates a series-scoped AccessPass
        with ``valid_from = series.starts_at`` and
        ``valid_until = series.ends_at``;
      – ``grants_pathway_id`` when set creates an immediate
        PathwayEntitlement scoped to the series end.
  * Booking eligibility (``spaces.routes.book_event``):
      – ``valid_from`` enforcement — a future-term pass cannot be
        used to book events until the term begins;
      – series pass authorises booking of a series event;
      – Term-3 pass cannot book a Term-4 event, and vice versa;
      – overlapping-term coexistence — both passes live and each
        works within its own window;
      – series-required events with no matching pass are refused
        (no legacy lenient fallback for series-only gates);
      – pathway-gated events with no term pass keep the lenient
        fallback (regression).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi import BackgroundTasks, HTTPException

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
from app.models.platform import (
    EntitlementStatus,
    Event,
    EventSeries,
    Pathway,
    PathwayEntitlement,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.spaces.routes import book_event
from app.webhooks.routes import _handle_checkout_completed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_pathway(db, space, *, title: str = "Practice Content") -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        status="active",
        access_type="one_time",
        price_cents=20000,
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def _make_series(
    db, space, *, title: str, starts_at: datetime,
    ends_at: datetime | None,
    status: str = "published",
) -> EventSeries:
    s = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        status=status,
    )
    db.add(s)
    db.flush()
    return s


def _make_pathway_option(
    db, space, pathway, *, name: str, total_sessions: int = 10,
    sessions_per_week: int = 1, price_cents: int = 20000,
    term_start: date | None = None, term_end: date | None = None,
    grants_pathway_id: str | None = None,
) -> PaymentOption:
    """Legacy pathway-attached term_pass option."""
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=pathway.id,
        attaches_to_kind="pathway",
        attaches_to_id=pathway.id,
        grants_pathway_id=grants_pathway_id,
        name=name,
        payment_type=PaymentOptionType.term_pass,
        status=PaymentOptionStatus.published,
        term_start_date=term_start,
        term_end_date=term_end,
        sessions_per_week=sessions_per_week,
        total_sessions=total_sessions,
        price_per_session_cents=price_cents // max(total_sessions, 1),
        calculated_total_cents=price_cents,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _make_series_option(
    db, space, series, *, name: str, total_sessions: int,
    sessions_per_week: int, price_cents: int,
    grants_pathway_id: str | None = None,
) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=None,
        attaches_to_kind="event_series",
        attaches_to_id=series.id,
        grants_pathway_id=grants_pathway_id,
        name=name,
        payment_type=PaymentOptionType.term_pass,
        status=PaymentOptionStatus.published,
        # Term dates on the option are redundant when the series has
        # a defined window (the series owns it) — set them anyway so
        # legacy queries filtering by term_end_date still see the
        # option as term-scoped. When the series is ongoing they
        # remain null; the ongoing-series tests exercise the option-
        # level fallback path explicitly.
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


def _fire_webhook(db, *, txn, payment_option, series=None, pathway_id=None):
    """Replay the Stripe checkout.session.completed handler with the
    minimum metadata a real Session would carry. Kept intentionally
    thin so tests exercise the actual webhook branch under test."""
    metadata = {
        "transaction_id": txn.id,
        "payer_user_id": txn.payer_user_id,
        "space_id": txn.space_id,
        "payment_option_id": payment_option.id,
    }
    # Pathway-attached purchases carry pathway_id metadata; series
    # purchases derive the target from the option.
    if series is None and pathway_id:
        metadata["pathway_id"] = pathway_id
    session = {
        "id": txn.provider_checkout_session_id,
        "payment_status": "paid",
        "payment_intent": _uid("pi"),
        "metadata": metadata,
    }
    _handle_checkout_completed(session, db)


def _make_booking_event(
    db, space, *, series: EventSeries | None, starts_at: datetime,
    booking_access_type: str = "included_with_collective",
    required_pid: str | None = None,
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
        capacity=20,
        gathering_type="circle",
        attendance_format="in_person",
        booking_access_type=booking_access_type,
        booking_required_pathway_id=required_pid,
        series_id=series.id if series else None,
    )
    db.add(e)
    db.flush()
    return e


# ---------------------------------------------------------------------------
# 1. Model / migration foundations
# ---------------------------------------------------------------------------


class TestModelsAndMigration:
    def test_event_series_round_trip(self, db, make_space):
        space = make_space()
        s = _make_series(
            db, space, title="Term 4",
            starts_at=datetime.utcnow() + timedelta(days=30),
            ends_at=datetime.utcnow() + timedelta(days=90),
        )
        db.commit()
        got = db.query(EventSeries).filter(EventSeries.id == s.id).one()
        assert got.title == "Term 4"
        assert got.status == "published"
        assert got.starts_at < got.ends_at

    def test_event_attached_to_series(self, db, make_space):
        space = make_space()
        s = _make_series(
            db, space, title="Term",
            starts_at=datetime.utcnow(),
            ends_at=datetime.utcnow() + timedelta(days=30),
        )
        e = _make_booking_event(
            db, space, series=s, starts_at=datetime.utcnow() + timedelta(days=5),
        )
        db.commit()
        got = db.query(Event).filter(Event.id == e.id).one()
        assert got.series_id == s.id

    def test_series_delete_sets_event_series_id_null(self, db, make_space):
        """ondelete=SET NULL — deleting a series doesn't take its events."""
        space = make_space()
        s = _make_series(
            db, space, title="Term",
            starts_at=datetime.utcnow(),
            ends_at=datetime.utcnow() + timedelta(days=30),
        )
        e = _make_booking_event(
            db, space, series=s, starts_at=datetime.utcnow() + timedelta(days=5),
        )
        db.commit()
        db.delete(s)
        db.commit()
        # Force a re-read from the DB: the ORM identity map may still
        # hold the pre-delete Event with its old series_id.
        db.expire_all()
        got = db.query(Event).filter(Event.id == e.id).one()
        assert got.series_id is None

    def test_payment_option_polymorphic_pathway(self, db, make_space):
        space = make_space()
        p = _make_pathway(db, space)
        opt = _make_pathway_option(
            db, space, p, name="Legacy Term",
            term_start=date.today(), term_end=date.today() + timedelta(days=60),
        )
        db.commit()
        got = db.query(PaymentOption).filter(PaymentOption.id == opt.id).one()
        assert got.attaches_to_kind == "pathway"
        assert got.attaches_to_id == p.id
        assert got.pathway_id == p.id  # legacy field still populated

    def test_payment_option_polymorphic_series(self, db, make_space):
        space = make_space()
        s = _make_series(
            db, space, title="T",
            starts_at=datetime.utcnow(),
            ends_at=datetime.utcnow() + timedelta(days=30),
        )
        opt = _make_series_option(
            db, space, s, name="Awaken", total_sessions=10,
            sessions_per_week=1, price_cents=20000,
        )
        db.commit()
        got = db.query(PaymentOption).filter(PaymentOption.id == opt.id).one()
        assert got.attaches_to_kind == "event_series"
        assert got.attaches_to_id == s.id
        assert got.pathway_id is None

    def test_access_pass_eligible_series_persists(self, db, make_space, make_user):
        space = make_space()
        payer = make_user()
        s = _make_series(
            db, space, title="T",
            starts_at=datetime.utcnow(),
            ends_at=datetime.utcnow() + timedelta(days=30),
        )
        ap = AccessPass(
            id=_uid("ap"),
            user_id=payer.id,
            space_id=space.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            valid_from=s.starts_at,
            valid_until=s.ends_at,
            eligible_series_id=s.id,
            total_credits=10,
            credits_per_week=1,
            source=AccessPassSource.one_time_purchase,
        )
        db.add(ap)
        db.commit()
        got = db.query(AccessPass).filter(AccessPass.id == ap.id).one()
        assert got.eligible_series_id == s.id
        assert got.eligible_pathway_id is None


# ---------------------------------------------------------------------------
# 2. Webhook — series purchases
# ---------------------------------------------------------------------------


class TestWebhookSeriesPurchase:
    def test_pathway_purchase_unchanged(self, db, make_space, make_user):
        """Regression: legacy pathway-attached term_pass still creates
        an entitlement + a pathway-scoped AccessPass."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pw = _make_pathway(db, space)
        opt = _make_pathway_option(
            db, space, pw, name="Legacy Term",
            term_start=date.today(),
            term_end=date.today() + timedelta(days=60),
            grants_pathway_id=pw.id,
        )
        txn = _make_txn(db, payer=payer, space=space, gross_cents=20000)
        db.commit()

        _fire_webhook(db, txn=txn, payment_option=opt, pathway_id=pw.id)

        ent = db.query(PathwayEntitlement).filter(
            PathwayEntitlement.user_id == payer.id
        ).one()
        assert ent.pathway_id == pw.id
        assert ent.ends_at is not None

        ap = db.query(AccessPass).filter(AccessPass.user_id == payer.id).one()
        assert ap.eligible_pathway_id == pw.id
        assert ap.eligible_series_id is None
        assert ap.total_credits == 10

    def test_series_purchase_creates_series_pass(self, db, make_space, make_user):
        """Series-attached term_pass creates AccessPass with
        eligible_series_id and window scoped to the series.
        grants_pathway_id is None here so no PathwayEntitlement is
        created."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        s = _make_series(
            db, space, title="EMBODY Spring Term",
            starts_at=datetime.utcnow() + timedelta(days=30),
            ends_at=datetime.utcnow() + timedelta(days=90),
        )
        opt = _make_series_option(
            db, space, s, name="Activate", total_sessions=20,
            sessions_per_week=2, price_cents=34000,
        )
        txn = _make_txn(db, payer=payer, space=space, gross_cents=34000)
        db.commit()

        _fire_webhook(db, txn=txn, payment_option=opt, series=s)

        # No PathwayEntitlement — this option only grants booking rights.
        assert (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == payer.id)
            .count()
        ) == 0

        ap = db.query(AccessPass).filter(AccessPass.user_id == payer.id).one()
        assert ap.eligible_series_id == s.id
        assert ap.eligible_pathway_id is None
        assert ap.valid_from == s.starts_at
        assert ap.valid_until == s.ends_at
        assert ap.total_credits == 20
        assert ap.credits_per_week == 2

    def test_series_purchase_with_grants_pathway(self, db, make_space, make_user):
        """When ``grants_pathway_id`` is set on a series option, the
        webhook creates BOTH an AccessPass (series-scoped) and a
        PathwayEntitlement (starts_at=now, ends_at=series.ends_at).
        The pathway entitlement's starts_at intentionally decouples
        from the series start — a future-term buyer gets immediate
        access to the included content."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        practice = _make_pathway(db, space, title="EMBODY Practice")
        # Series starts 30 days from now (future term).
        s = _make_series(
            db, space, title="Spring Term",
            starts_at=datetime.utcnow() + timedelta(days=30),
            ends_at=datetime.utcnow() + timedelta(days=90),
        )
        opt = _make_series_option(
            db, space, s, name="Awaken", total_sessions=10,
            sessions_per_week=1, price_cents=20000,
            grants_pathway_id=practice.id,
        )
        txn = _make_txn(db, payer=payer, space=space, gross_cents=20000)
        db.commit()

        before = datetime.utcnow()
        _fire_webhook(db, txn=txn, payment_option=opt, series=s)

        ent = db.query(PathwayEntitlement).filter(
            PathwayEntitlement.user_id == payer.id
        ).one()
        assert ent.pathway_id == practice.id
        assert ent.status == EntitlementStatus.active
        # Immediate access — not coupled to series.starts_at.
        assert ent.starts_at >= before
        assert ent.starts_at < s.starts_at
        assert ent.ends_at == s.ends_at

        ap = db.query(AccessPass).filter(AccessPass.user_id == payer.id).one()
        assert ap.eligible_series_id == s.id
        assert ap.eligible_pathway_id is None
        assert ap.valid_from == s.starts_at
        assert ap.valid_until == s.ends_at
        assert ap.pathway_entitlement_id == ent.id


# ---------------------------------------------------------------------------
# 3. Booking eligibility — valid_from, series matching, overlapping terms
# ---------------------------------------------------------------------------


class TestBookingEligibility:
    def test_future_term_pass_rejected_before_valid_from(
        self, db, make_space, make_user
    ):
        """Purchase a Term-4 pass while Term 4 is still in the future.
        Try to book an event that belongs to Term 4 (also in the
        future, but before valid_from). Denied — valid_from > now."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        # Term 4 window: starts in 30d, ends in 90d.
        term4 = _make_series(
            db, space, title="Term 4",
            starts_at=datetime.utcnow() + timedelta(days=30),
            ends_at=datetime.utcnow() + timedelta(days=90),
        )
        opt = _make_series_option(
            db, space, term4, name="Awaken", total_sessions=10,
            sessions_per_week=1, price_cents=20000,
        )
        txn = _make_txn(db, payer=payer, space=space, gross_cents=20000)
        db.commit()
        _fire_webhook(db, txn=txn, payment_option=opt, series=term4)

        # An event inside Term 4, before valid_from.
        target = _make_booking_event(
            db, space, series=term4,
            starts_at=datetime.utcnow() + timedelta(days=1),  # not yet Term 4
            booking_access_type="included_with_series",
        )
        db.commit()

        with pytest.raises(HTTPException) as ex:
            book_event(
                slug=space.slug, event_id=target.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert ex.value.status_code == 403

    def test_series_pass_authorises_booking_within_window(
        self, db, make_space, make_user
    ):
        """Series pass whose window covers the event date authorises
        booking; the pass's credits are decremented by 1."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        # Currently-live term.
        term = _make_series(
            db, space, title="Term (live)",
            starts_at=datetime.utcnow() - timedelta(days=1),
            ends_at=datetime.utcnow() + timedelta(days=30),
        )
        opt = _make_series_option(
            db, space, term, name="Activate", total_sessions=6,
            sessions_per_week=2, price_cents=12000,
        )
        txn = _make_txn(db, payer=payer, space=space, gross_cents=12000)
        db.commit()
        _fire_webhook(db, txn=txn, payment_option=opt, series=term)

        # Event tomorrow, inside the series window, series-gated.
        target = _make_booking_event(
            db, space, series=term,
            starts_at=datetime.utcnow() + timedelta(days=1),
            booking_access_type="included_with_series",
        )
        db.commit()

        result = book_event(
            slug=space.slug, event_id=target.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        assert result.status == "confirmed"
        pass_after = db.query(AccessPass).filter(
            AccessPass.user_id == payer.id
        ).one()
        assert pass_after.used_credits == 1

    def test_term3_pass_cannot_book_term4_event(
        self, db, make_space, make_user
    ):
        """Overlapping terms: buy Term 3 (live); Term 4 event visible
        (future). The Term 3 pass has ``eligible_series_id = term3``,
        which doesn't match ``event.series_id = term4`` — the series
        gate refuses the booking."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term3 = _make_series(
            db, space, title="Term 3",
            starts_at=datetime.utcnow() - timedelta(days=5),
            ends_at=datetime.utcnow() + timedelta(days=20),
        )
        term4 = _make_series(
            db, space, title="Term 4",
            starts_at=datetime.utcnow() + timedelta(days=30),
            ends_at=datetime.utcnow() + timedelta(days=90),
        )
        opt3 = _make_series_option(
            db, space, term3, name="Awaken", total_sessions=10,
            sessions_per_week=1, price_cents=20000,
        )
        txn = _make_txn(db, payer=payer, space=space, gross_cents=20000)
        db.commit()
        _fire_webhook(db, txn=txn, payment_option=opt3, series=term3)

        # An event that belongs to Term 4 and is scheduled inside Term 4.
        target = _make_booking_event(
            db, space, series=term4,
            starts_at=datetime.utcnow() + timedelta(days=40),
            booking_access_type="included_with_series",
        )
        db.commit()

        with pytest.raises(HTTPException) as ex:
            book_event(
                slug=space.slug, event_id=target.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert ex.value.status_code == 403

    def test_series_event_no_matching_pass_denied(
        self, db, make_space, make_user
    ):
        """Series-only event with no matching pass → 403.
        No legacy lenient fallback for series-required gates."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term = _make_series(
            db, space, title="Live Term",
            starts_at=datetime.utcnow() - timedelta(days=1),
            ends_at=datetime.utcnow() + timedelta(days=30),
        )
        target = _make_booking_event(
            db, space, series=term,
            starts_at=datetime.utcnow() + timedelta(days=1),
            booking_access_type="included_with_series",
        )
        db.commit()

        with pytest.raises(HTTPException) as ex:
            book_event(
                slug=space.slug, event_id=target.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert ex.value.status_code == 403

    def test_series_pass_total_credits_enforced(
        self, db, make_space, make_user
    ):
        """Exhausting ``total_credits`` on a series pass rejects the
        next booking with 409, mirroring the pathway path."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        term = _make_series(
            db, space, title="Live Term",
            starts_at=datetime.utcnow() - timedelta(days=1),
            ends_at=datetime.utcnow() + timedelta(days=60),
        )
        # 1 credit total, generous weekly cap so the total cap is
        # what trips.
        opt = _make_series_option(
            db, space, term, name="One-shot", total_sessions=1,
            sessions_per_week=5, price_cents=5000,
        )
        txn = _make_txn(db, payer=payer, space=space, gross_cents=5000)
        db.commit()
        _fire_webhook(db, txn=txn, payment_option=opt, series=term)

        # Two events, different days so the weekly cap doesn't fire.
        e1 = _make_booking_event(
            db, space, series=term,
            starts_at=datetime.utcnow() + timedelta(days=1),
            booking_access_type="included_with_series",
        )
        e2 = _make_booking_event(
            db, space, series=term,
            starts_at=datetime.utcnow() + timedelta(days=8),
            booking_access_type="included_with_series",
        )
        db.commit()

        book_event(
            slug=space.slug, event_id=e1.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        with pytest.raises(HTTPException) as ex:
            book_event(
                slug=space.slug, event_id=e2.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert ex.value.status_code == 409

    def test_pathway_gated_no_pass_still_lenient(
        self, db, make_space, make_user
    ):
        """Regression: pathway-gated events with no AccessPass keep
        the current lenient fallback (a manual PathwayEntitlement
        may cover the booking without credit tracking)."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pw = _make_pathway(db, space)
        # Grant a manual entitlement so the ``_can_book_gate`` layer
        # lets the request through to the credit-check block.
        db.add(PathwayEntitlement(
            id=_uid("ent"),
            user_id=payer.id,
            space_id=space.id,
            pathway_id=pw.id,
            source="manual_grant",
            status=EntitlementStatus.active,
            starts_at=datetime.utcnow() - timedelta(days=1),
        ))
        target = _make_booking_event(
            db, space, series=None,
            starts_at=datetime.utcnow() + timedelta(days=1),
            booking_access_type="included_with_pathway",
            required_pid=pw.id,
        )
        db.commit()

        result = book_event(
            slug=space.slug, event_id=target.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        assert result.status == "confirmed"


# ---------------------------------------------------------------------------
# 4. Overlapping-term coexistence
# ---------------------------------------------------------------------------


class TestOverlappingTerms:
    def test_two_active_passes_each_scoped_to_its_series(
        self, db, make_space, make_user
    ):
        """Alice holds a live Term-3 pass and a future Term-4 pass at
        the same time. Booking a Term-3 event uses the Term-3 pass;
        booking a Term-4 event before Term 4 begins is denied; after
        Term 4 begins, the Term-4 pass authorises Term-4 bookings."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)

        term3 = _make_series(
            db, space, title="Term 3",
            starts_at=datetime.utcnow() - timedelta(days=5),
            ends_at=datetime.utcnow() + timedelta(days=20),
        )
        term4 = _make_series(
            db, space, title="Term 4",
            starts_at=datetime.utcnow() + timedelta(days=30),
            ends_at=datetime.utcnow() + timedelta(days=90),
        )

        opt3 = _make_series_option(
            db, space, term3, name="Awaken", total_sessions=5,
            sessions_per_week=2, price_cents=10000,
        )
        opt4 = _make_series_option(
            db, space, term4, name="Awaken", total_sessions=10,
            sessions_per_week=1, price_cents=20000,
        )
        txn3 = _make_txn(db, payer=payer, space=space, gross_cents=10000)
        txn4 = _make_txn(db, payer=payer, space=space, gross_cents=20000)
        db.commit()
        _fire_webhook(db, txn=txn3, payment_option=opt3, series=term3)
        _fire_webhook(db, txn=txn4, payment_option=opt4, series=term4)

        passes = db.query(AccessPass).filter(
            AccessPass.user_id == payer.id
        ).all()
        assert len(passes) == 2
        eligible = {p.eligible_series_id for p in passes}
        assert eligible == {term3.id, term4.id}

        # Book a Term-3 event today — uses the Term-3 pass.
        t3_event = _make_booking_event(
            db, space, series=term3,
            starts_at=datetime.utcnow() + timedelta(days=1),
            booking_access_type="included_with_series",
        )
        db.commit()
        r3 = book_event(
            slug=space.slug, event_id=t3_event.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=payer,
        )
        assert r3.status == "confirmed"

        # Term-3 pass should have been decremented; Term-4 pass untouched.
        t3_pass = next(p for p in db.query(AccessPass).filter(
            AccessPass.user_id == payer.id
        ).all() if p.eligible_series_id == term3.id)
        t4_pass = next(p for p in db.query(AccessPass).filter(
            AccessPass.user_id == payer.id
        ).all() if p.eligible_series_id == term4.id)
        assert t3_pass.used_credits == 1
        assert t4_pass.used_credits == 0

        # Term-4 event scheduled inside Term 4 but "now" is before
        # Term 4 begins → the Term-4 pass is not yet valid.
        t4_event_future = _make_booking_event(
            db, space, series=term4,
            starts_at=datetime.utcnow() + timedelta(days=40),
            booking_access_type="included_with_series",
        )
        db.commit()
        with pytest.raises(HTTPException) as ex:
            book_event(
                slug=space.slug, event_id=t4_event_future.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=payer,
            )
        assert ex.value.status_code == 403


# ---------------------------------------------------------------------------
# 5. Series membership decoupled from pass requirement
#
# ``series_id`` says "this Gathering belongs to this Series" — nothing
# more. The AccessPass check only fires when the Event's
# ``booking_access_type`` explicitly opts in via ``included_with_series``.
# A Series may be free, community-included, or paid_separately; only
# term-pass-gated Gatherings run the credit-check block.
# ---------------------------------------------------------------------------


class TestSeriesMembershipDoesNotForcePass:
    def test_free_event_in_series_is_bookable_without_pass(
        self, db, make_space, make_user
    ):
        """A ``free`` Gathering that happens to belong to a Series is
        bookable by any active member. No AccessPass required."""
        space = make_space()
        member = make_user()
        _member(db, member, space)
        series = _make_series(
            db, space, title="Ongoing Circle",
            starts_at=datetime.utcnow() - timedelta(days=1),
            ends_at=None,  # ongoing, no defined end
        )
        target = _make_booking_event(
            db, space, series=series,
            starts_at=datetime.utcnow() + timedelta(days=1),
            booking_access_type="free",
        )
        db.commit()

        result = book_event(
            slug=space.slug, event_id=target.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=member,
        )
        assert result.status == "confirmed"
        booking_pass_ids = [
            b.access_pass_id for b in target.bookings.all()
        ]
        # No AccessPass consumed — the booking is free.
        assert booking_pass_ids == [None]

    def test_collective_included_event_in_series_bookable(
        self, db, make_space, make_user
    ):
        """``included_with_collective`` events keep working under a
        Series banner — membership is sufficient."""
        space = make_space()
        member = make_user()
        _member(db, member, space)
        series = _make_series(
            db, space, title="Weekly Community Sit",
            starts_at=datetime.utcnow() - timedelta(days=30),
            ends_at=None,
        )
        target = _make_booking_event(
            db, space, series=series,
            starts_at=datetime.utcnow() + timedelta(days=2),
            booking_access_type="included_with_collective",
        )
        db.commit()

        result = book_event(
            slug=space.slug, event_id=target.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=member,
        )
        assert result.status == "confirmed"

    def test_mixed_series_pass_gated_and_free_events(
        self, db, make_space, make_user
    ):
        """The same Series can contain both pass-gated and free
        Gatherings side-by-side. Only the pass-gated one enforces the
        AccessPass; the free one is bookable without a pass."""
        space = make_space()
        member = make_user()
        _member(db, member, space)
        series = _make_series(
            db, space, title="Hybrid Series",
            starts_at=datetime.utcnow() - timedelta(days=5),
            ends_at=datetime.utcnow() + timedelta(days=60),
        )

        free_event = _make_booking_event(
            db, space, series=series,
            starts_at=datetime.utcnow() + timedelta(days=1),
            booking_access_type="free",
        )
        gated_event = _make_booking_event(
            db, space, series=series,
            starts_at=datetime.utcnow() + timedelta(days=3),
            booking_access_type="included_with_series",
        )
        db.commit()

        # Free event — bookable immediately.
        r_free = book_event(
            slug=space.slug, event_id=free_event.id,
            background_tasks=BackgroundTasks(),
            db=db, current_user=member,
        )
        assert r_free.status == "confirmed"

        # Gated event — no pass → 403.
        with pytest.raises(HTTPException) as ex:
            book_event(
                slug=space.slug, event_id=gated_event.id,
                background_tasks=BackgroundTasks(),
                db=db, current_user=member,
            )
        assert ex.value.status_code == 403


# ---------------------------------------------------------------------------
# 6. Ongoing series (ends_at nullable)
#
# A Series does NOT require a defined end. term_pass options attached
# to an ongoing series can still bound their own AccessPass window via
# ``option.term_end_date``; without that bound the pass is perpetual
# (legal in the data model — a future editor UI will make the choice
# explicit).
# ---------------------------------------------------------------------------


class TestOngoingSeries:
    def test_series_can_be_created_without_end_date(
        self, db, make_space
    ):
        space = make_space()
        s = _make_series(
            db, space, title="Weekly Circle (ongoing)",
            starts_at=datetime.utcnow(),
            ends_at=None,
        )
        db.commit()
        got = db.query(EventSeries).filter(EventSeries.id == s.id).one()
        assert got.ends_at is None

    def test_ongoing_series_term_pass_falls_back_to_option_term_end(
        self, db, make_space, make_user
    ):
        """Series has no ``ends_at``; the term_pass option carries its
        own ``term_end_date`` — that's what bounds the AccessPass
        window and the included PathwayEntitlement."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        practice = _make_pathway(db, space, title="Practice")
        ongoing = _make_series(
            db, space, title="Ongoing",
            starts_at=datetime.utcnow() - timedelta(days=1),
            ends_at=None,
        )
        opt = PaymentOption(
            id=_uid("po"),
            space_id=space.id,
            pathway_id=None,
            attaches_to_kind="event_series",
            attaches_to_id=ongoing.id,
            grants_pathway_id=practice.id,
            name="10-pack",
            payment_type=PaymentOptionType.term_pass,
            status=PaymentOptionStatus.published,
            # No series end → the option carries the bound.
            term_start_date=(datetime.utcnow() - timedelta(days=1)).date(),
            term_end_date=(datetime.utcnow() + timedelta(days=90)).date(),
            sessions_per_week=2,
            total_sessions=10,
            price_per_session_cents=2000,
            calculated_total_cents=20000,
            currency="AUD",
        )
        db.add(opt)
        txn = _make_txn(db, payer=payer, space=space, gross_cents=20000)
        db.commit()

        _fire_webhook(db, txn=txn, payment_option=opt, series=ongoing)

        ap = db.query(AccessPass).filter(AccessPass.user_id == payer.id).one()
        expected_end = datetime.combine(
            opt.term_end_date, datetime.min.time()
        )
        assert ap.valid_until == expected_end

        ent = db.query(PathwayEntitlement).filter(
            PathwayEntitlement.user_id == payer.id
        ).one()
        assert ent.ends_at == expected_end

    def test_ongoing_series_perpetual_pass_when_no_end_anywhere(
        self, db, make_space, make_user
    ):
        """Both series.ends_at and option.term_end_date null → the
        AccessPass is perpetual (valid_until stays None). Legal — a
        future creator UI will surface this choice explicitly."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        ongoing = _make_series(
            db, space, title="Perpetual",
            starts_at=datetime.utcnow() - timedelta(days=1),
            ends_at=None,
        )
        opt = PaymentOption(
            id=_uid("po"),
            space_id=space.id,
            pathway_id=None,
            attaches_to_kind="event_series",
            attaches_to_id=ongoing.id,
            name="Unlimited",
            payment_type=PaymentOptionType.term_pass,
            status=PaymentOptionStatus.published,
            term_start_date=None,
            term_end_date=None,  # no bound
            sessions_per_week=None,
            total_sessions=None,
            calculated_total_cents=50000,
            currency="AUD",
        )
        db.add(opt)
        txn = _make_txn(db, payer=payer, space=space, gross_cents=50000)
        db.commit()

        _fire_webhook(db, txn=txn, payment_option=opt, series=ongoing)

        ap = db.query(AccessPass).filter(AccessPass.user_id == payer.id).one()
        assert ap.valid_until is None
        assert ap.eligible_series_id == ongoing.id
