"""B3 — direct coverage of ``app.services.purchase_fulfilment``.

The webhook path is already covered by ``test_gathering_series.py``
(22 end-to-end tests that fire ``_handle_checkout_completed`` and
inspect the resulting rows). Those all still pass after the
extraction, which is the primary parity guarantee.

The tests here exercise the service functions **directly** so the
resolver + applier keep working even if a future change to the
webhook decouples them further. Each test pins one behavioural
promise the pre-B3 webhook made:

  * Resolver — legacy PaymentOption shapes → FulfilmentIntent
      - pathway-only option → entitlement only, no AccessPass
      - pathway-attached term_pass with dates → both, correct
        AccessPass window from ``term_start_date``/``term_end_date``
      - series-attached term_pass, no ``grants_pathway_id`` →
        AccessPass only, no entitlement
      - series-attached term_pass with ``grants_pathway_id`` →
        both; entitlement ``ends_at`` = ``series.ends_at``
      - ongoing series with option ``term_end_date`` → both
        entitlement.ends_at and AccessPass.valid_until fall back
        to the option's date
      - no ``PaymentOption`` at all → entitlement from metadata
        pathway_id, no AccessPass

  * Applier — writes rows correctly and idempotently
      - creates a new PathwayEntitlement
      - reactivates a revoked entitlement (fresh window)
      - preserves an active entitlement's ``ends_at``
      - auto-joins non-member; skips already-member
      - creates AccessPass with all fields from the intent
      - per-txn AccessPass idempotency: replay creates no dupes

  * End-to-end parity with the EMBODY Awaken/Activate/Empower
    three-tier shape — session limits + bundled Pathway window
    end at the Series end, Pathway grant does not inherit Series
    start.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from app.models.access_pass import (
    AccessPass,
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
    EventSeries,
    Pathway,
    PathwayEntitlement,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.purchase_fulfilment import (
    AccessPassIntent,
    BookingIntent,
    EntitlementIntent,
    FulfilmentIntent,
    FulfilmentResolution,
    apply_intent,
    resolve_intent_from_legacy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_pathway(db, space, *, title: str = "Practice") -> Pathway:
    p = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title, status="active",
        access_type="one_time", price_cents=20000,
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


_UNSET = object()


def _make_series(
    db, space, *, starts_at: datetime | None = None,
    ends_at=_UNSET,
) -> EventSeries:
    """Set ``ends_at=None`` explicitly to model an ongoing Series;
    omit the argument entirely to get the default finite window
    (starts_at + 90 days)."""
    starts_at = starts_at or (datetime.utcnow() + timedelta(days=7))
    if ends_at is _UNSET:
        ends_at = starts_at + timedelta(days=90)
    s = EventSeries(
        id=_uid("es"), space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title="Term", starts_at=starts_at, ends_at=ends_at,
        status="published",
    )
    db.add(s)
    db.flush()
    return s


def _make_pathway_option(
    db, space, pathway, *,
    payment_type: PaymentOptionType = PaymentOptionType.one_time,
    sessions_per_week: int | None = None,
    total_sessions: int | None = None,
    term_start_date: date | None = None,
    term_end_date: date | None = None,
    grants_pathway_id: str | None = None,
) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, pathway_id=pathway.id,
        attaches_to_kind="pathway", attaches_to_id=pathway.id,
        grants_pathway_id=grants_pathway_id,
        name="Course", payment_type=payment_type,
        status=PaymentOptionStatus.published,
        sessions_per_week=sessions_per_week,
        total_sessions=total_sessions,
        term_start_date=term_start_date, term_end_date=term_end_date,
        calculated_total_cents=20000, currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _make_series_option(
    db, space, series, *,
    sessions_per_week: int = 1, total_sessions: int = 10,
    term_end_date: date | None = None,
    grants_pathway_id: str | None = None,
) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, pathway_id=None,
        attaches_to_kind="event_series", attaches_to_id=series.id,
        grants_pathway_id=grants_pathway_id,
        name="Series pass", payment_type=PaymentOptionType.term_pass,
        status=PaymentOptionStatus.published,
        sessions_per_week=sessions_per_week,
        total_sessions=total_sessions,
        term_start_date=series.starts_at.date(),
        term_end_date=term_end_date if term_end_date is not None
                      else (series.ends_at.date() if series.ends_at else None),
        calculated_total_cents=60000, currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _make_txn(db, *, payer, space) -> PaymentTransaction:
    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=payer.id, creator_user_id=space.creator_id,
        space_id=space.id, currency="AUD",
        gross_amount_cents=20000, platform_fee_basis_points=800,
        platform_fee_cents=1600, net_creator_amount_cents=18400,
        stripe_mode="test", payout_status=PayoutStatus.pending,
        provider_checkout_session_id=_uid("cs"),
    )
    db.add(txn)
    db.flush()
    return txn


# ---------------------------------------------------------------------------
# Resolver — legacy PaymentOption fields
# ---------------------------------------------------------------------------


class TestResolveIntentFromLegacy:
    def test_no_option_no_metadata_produces_empty_intent(self, db):
        resolution = resolve_intent_from_legacy(
            db, payment_option=None,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )
        assert resolution.fatal_error is None
        assert resolution.intent == FulfilmentIntent()
        assert resolution.intent.entitlements == ()
        assert resolution.intent.access_passes == ()
        assert resolution.intent.bookings == ()

    def test_no_option_with_metadata_pathway_id_produces_entitlement_only(
        self, db, make_space,
    ):
        """Legacy fallback: an option-less purchase that comes in
        with a ``pathway_id`` in Stripe metadata still creates the
        entitlement (perpetual)."""
        space = make_space()
        pw = _make_pathway(db, space, title="R.E.A.L.")
        resolution = resolve_intent_from_legacy(
            db, payment_option=None,
            metadata_pathway_id=pw.id, now=datetime.utcnow(),
        )
        assert resolution.intent.access_passes == ()
        assert resolution.intent.entitlements == (
            EntitlementIntent(pathway_id=pw.id, ends_at=None),
        )

    def test_pathway_attached_one_time_option_perpetual(
        self, db, make_space,
    ):
        """A pathway-attached one_time purchase gets its
        entitlement from the ``pathway_id`` Stripe metadata (that's
        how the current pathway checkout wires it — the option's
        own ``pathway_id`` column is not the source). No AccessPass
        for one_time — that's term_pass territory."""
        space = make_space()
        pw = _make_pathway(db, space)
        opt = _make_pathway_option(db, space, pw)
        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=pw.id,
            now=datetime.utcnow(),
        )
        assert resolution.intent.access_passes == ()
        assert len(resolution.intent.entitlements) == 1
        [ent] = resolution.intent.entitlements
        assert ent == EntitlementIntent(pathway_id=pw.id, ends_at=None)

    def test_pathway_attached_grants_pathway_id_wins_over_metadata(
        self, db, make_space,
    ):
        """``grants_pathway_id`` explicitly on the option overrides
        the metadata fallback — mirrors the pre-B3 webhook rule
        exactly."""
        space = make_space()
        base = _make_pathway(db, space, title="Base")
        override = _make_pathway(db, space, title="Override")
        opt = _make_pathway_option(
            db, space, base, grants_pathway_id=override.id,
        )
        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=base.id, now=datetime.utcnow(),
        )
        [ent] = resolution.intent.entitlements
        assert ent.pathway_id == override.id

    def test_pathway_attached_term_pass_with_dates(
        self, db, make_space,
    ):
        """Solo pathway-attached term_pass: entitlement ends at
        ``term_end_date``; AccessPass covers the whole term with
        the option's credits + credits_per_week."""
        space = make_space()
        pw = _make_pathway(db, space)
        opt = _make_pathway_option(
            db, space, pw,
            payment_type=PaymentOptionType.term_pass,
            sessions_per_week=2, total_sessions=20,
            term_start_date=date(2026, 8, 1),
            term_end_date=date(2026, 10, 31),
        )
        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=pw.id, now=datetime.utcnow(),
        )
        assert resolution.intent.entitlements == (
            EntitlementIntent(pathway_id=pw.id, ends_at=datetime(2026, 10, 31, 0, 0)),
        )
        assert resolution.intent.access_passes == (
            AccessPassIntent(
                pass_type=AccessPassType.term_pass,
                valid_from=datetime(2026, 8, 1, 0, 0),
                valid_until=datetime(2026, 10, 31, 0, 0),
                total_credits=20,
                credits_per_week=2,
                eligible_pathway_id=pw.id,
                eligible_series_id=None,
                grants_pathway_id=pw.id,
            ),
        )

    def test_series_attached_term_pass_without_bundled_pathway(
        self, db, make_space,
    ):
        space = make_space()
        starts = datetime(2026, 8, 1)
        s = _make_series(db, space, starts_at=starts,
                         ends_at=starts + timedelta(days=90))
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
        )
        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )
        assert resolution.intent.entitlements == ()   # no grants_pathway_id
        assert resolution.intent.access_passes == (
            AccessPassIntent(
                pass_type=AccessPassType.term_pass,
                valid_from=s.starts_at,
                valid_until=s.ends_at,
                total_credits=10,
                credits_per_week=1,
                eligible_pathway_id=None,
                eligible_series_id=s.id,
                grants_pathway_id=None,
            ),
        )

    def test_series_attached_term_pass_with_bundled_pathway(
        self, db, make_space,
    ):
        """EMBODY case: entitlement ends at Series end;
        AccessPass covers full Series window with tier's limits.
        Bundled Pathway is represented as a separate
        ``EntitlementIntent`` in the same ``FulfilmentIntent`` —
        AccessPass ``grants_pathway_id`` is the legacy shadow."""
        space = make_space()
        practice = _make_pathway(db, space, title="EMBODY Practice")
        s = _make_series(db, space,
                         starts_at=datetime(2026, 8, 1),
                         ends_at=datetime(2026, 10, 31))
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
        )
        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )
        [ent] = resolution.intent.entitlements
        [ap] = resolution.intent.access_passes
        assert ent == EntitlementIntent(pathway_id=practice.id, ends_at=s.ends_at)
        assert ap.eligible_series_id == s.id
        assert ap.eligible_pathway_id is None
        assert ap.grants_pathway_id == practice.id     # legacy shadow
        assert ap.total_credits == 10
        assert ap.credits_per_week == 1

    def test_ongoing_series_falls_back_to_option_term_end(
        self, db, make_space,
    ):
        """Series with no ``ends_at`` + option carrying ``term_end_date``
        → both the entitlement and the AccessPass valid_until fall
        back to the option's term_end_date (mirrors the pre-B3
        webhook exactly)."""
        space = make_space()
        practice = _make_pathway(db, space, title="Practice")
        s = _make_series(db, space,
                         starts_at=datetime(2026, 8, 1),
                         ends_at=None)
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            term_end_date=date(2026, 12, 31),
            grants_pathway_id=practice.id,
        )
        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )
        [ent] = resolution.intent.entitlements
        [ap] = resolution.intent.access_passes
        assert ent.ends_at == datetime(2026, 12, 31, 0, 0)
        assert ap.valid_until == datetime(2026, 12, 31, 0, 0)

    def test_missing_series_row_returns_fatal_error(
        self, db, make_space,
    ):
        """Series-attached option whose ``attaches_to_id`` points at
        a stale/missing Series row: resolution carries
        ``fatal_error`` and an empty intent (caller must abort)."""
        space = make_space()
        s = _make_series(db, space)
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
        )
        # Corrupt the pointer.
        opt.attaches_to_id = "es_does_not_exist"
        db.flush()

        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )
        assert resolution.fatal_error is not None
        assert "missing EventSeries" in resolution.fatal_error
        assert resolution.intent == FulfilmentIntent()

    def test_bookings_never_produced_by_legacy_resolver(
        self, db, make_space,
    ):
        """Placeholder for standalone-Gathering fulfilment. B3's
        legacy resolver must NEVER populate a ``BookingIntent`` —
        that path stays on the ticket-hold system for now."""
        space = make_space()
        pw = _make_pathway(db, space)
        opt = _make_pathway_option(db, space, pw)
        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=pw.id, now=datetime.utcnow(),
        )
        assert resolution.intent.bookings == ()


# ---------------------------------------------------------------------------
# Applier
# ---------------------------------------------------------------------------


class TestApplyIntent:
    def _txn_kwargs(self, db, txn):
        return dict(
            txn=txn, payer_user_id=txn.payer_user_id,
            space_id=txn.space_id,
            payment_option_id=None,
            payment_option_schedule_id=None,
            session_id=txn.provider_checkout_session_id,
            payment_intent_id="pi_test",
            now=datetime.utcnow(),
        )

    def test_creates_new_entitlement_and_auto_joins(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space)
        txn = _make_txn(db, payer=buyer, space=space)
        intent = FulfilmentIntent(
            entitlements=(EntitlementIntent(pathway_id=pw.id, ends_at=None),),
        )
        result = apply_intent(db, intent=intent, **self._txn_kwargs(db, txn))
        assert len(result.entitlements) == 1
        [ent] = result.entitlements
        assert ent.pathway_id == pw.id
        assert ent.status == EntitlementStatus.active
        assert result.membership_created is True
        # Singular txn.entitlement_id: exactly one entitlement → set.
        assert txn.entitlement_id == ent.id

    def test_preserves_active_entitlement_ends_at_on_replay(
        self, db, make_space, make_user,
    ):
        """Re-delivery of a purchase whose entitlement is still
        active must NOT extend its window — the pre-B3 comment made
        this rule explicit."""
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space)
        txn = _make_txn(db, payer=buyer, space=space)
        existing_end = datetime(2026, 12, 31, 0, 0)
        db.add(PathwayEntitlement(
            id=_uid("ent"), user_id=buyer.id, space_id=space.id,
            pathway_id=pw.id, source="one_time_purchase",
            status=EntitlementStatus.active,
            starts_at=datetime.utcnow() - timedelta(days=30),
            ends_at=existing_end,
        ))
        db.flush()

        intent = FulfilmentIntent(
            entitlements=(EntitlementIntent(
                pathway_id=pw.id,
                ends_at=datetime(2027, 6, 30, 0, 0),   # ignored
            ),),
        )
        result = apply_intent(db, intent=intent, **self._txn_kwargs(db, txn))
        [ent] = result.entitlements
        assert ent.ends_at == existing_end

    def test_reactivates_expired_entitlement_with_fresh_window(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space)
        txn = _make_txn(db, payer=buyer, space=space)
        db.add(PathwayEntitlement(
            id=_uid("ent"), user_id=buyer.id, space_id=space.id,
            pathway_id=pw.id, source="one_time_purchase",
            status=EntitlementStatus.expired,
            starts_at=datetime.utcnow() - timedelta(days=200),
            ends_at=datetime.utcnow() - timedelta(days=100),
        ))
        db.flush()

        fresh_end = datetime(2027, 3, 31, 0, 0)
        intent = FulfilmentIntent(
            entitlements=(EntitlementIntent(pathway_id=pw.id, ends_at=fresh_end),),
        )
        result = apply_intent(db, intent=intent, **self._txn_kwargs(db, txn))
        [ent] = result.entitlements
        assert ent.status == EntitlementStatus.active
        assert ent.ends_at == fresh_end

    def test_skips_membership_when_already_member(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=buyer.id, space_id=space.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
        ))
        db.flush()
        txn = _make_txn(db, payer=buyer, space=space)
        pw = _make_pathway(db, space)
        result = apply_intent(
            db,
            intent=FulfilmentIntent(
                entitlements=(EntitlementIntent(pathway_id=pw.id, ends_at=None),),
            ),
            **self._txn_kwargs(db, txn),
        )
        assert result.membership_created is False

    def test_missing_target_caught_by_validate_intent(
        self, db, make_space,
    ):
        """Missing target Pathway → ``validate_intent`` reports the
        error and the applier is never called. The pre-B3 partial-
        error path is gone: this is now the front door for a
        blocked bundle."""
        from app.services.purchase_fulfilment import validate_intent
        space = make_space()
        intent = FulfilmentIntent(
            entitlements=(EntitlementIntent(
                pathway_id="pw_does_not_exist", ends_at=None,
            ),),
        )
        v = validate_intent(db, intent)
        assert not v.ok
        assert any("pw_does_not_exist" in e for e in v.errors)

    def test_access_pass_idempotent_per_transaction(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space)
        s = _make_series(db, space)
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            grants_pathway_id=pw.id,
        )
        txn = _make_txn(db, payer=buyer, space=space)
        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )

        # First apply — creates entitlement + AccessPass.
        kwargs = self._txn_kwargs(db, txn) | {"payment_option_id": opt.id}
        result_1 = apply_intent(db, intent=resolution.intent, **kwargs)
        [ap_1] = result_1.access_passes
        original_pass_id = ap_1.id
        db.flush()

        # Second apply — same txn. Must reuse the existing pass.
        result_2 = apply_intent(db, intent=resolution.intent, **kwargs)
        [ap_2] = result_2.access_passes
        assert ap_2.id == original_pass_id
        assert (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        ) == 1

    def test_access_pass_carries_all_intent_fields(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space)
        s = _make_series(db, space)
        opt = _make_series_option(
            db, space, s, sessions_per_week=3, total_sessions=30,
            grants_pathway_id=pw.id,
        )
        txn = _make_txn(db, payer=buyer, space=space)
        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )
        kwargs = self._txn_kwargs(db, txn) | {"payment_option_id": opt.id}
        result = apply_intent(db, intent=resolution.intent, **kwargs)
        [ap] = result.access_passes
        [ent] = result.entitlements
        assert ap.total_credits == 30
        assert ap.credits_per_week == 3
        assert ap.eligible_series_id == s.id
        assert ap.eligible_pathway_id is None
        assert ap.grants_pathway_id == pw.id
        assert ap.pathway_entitlement_id == ent.id
        assert ap.payment_transaction_id == txn.id
        assert ap.payment_option_id == opt.id
        assert ap.payment_option_schedule_id is None


# ---------------------------------------------------------------------------
# End-to-end parity for the EMBODY three-tier shape
# ---------------------------------------------------------------------------


class TestEmbodyThreeTierParity:
    """Awaken (1/wk × 10), Activate (2/wk × 20), Empower (3/wk × 30)
    all bundle The EMBODY Practice. Confirms the extraction produces
    the exact rows the pre-B3 webhook did for each tier."""

    @pytest.mark.parametrize(
        "name,spw,total",
        [("Awaken", 1, 10), ("Activate", 2, 20), ("Empower", 3, 30)],
    )
    def test_tier_produces_expected_rows(
        self, db, make_space, make_user, name, spw, total,
    ):
        space = make_space()
        buyer = make_user()
        practice = _make_pathway(db, space, title="The EMBODY Practice")
        # Series in the future so we can prove the entitlement's
        # ``starts_at`` (NOW) is earlier than the Series start —
        # immediate access even when the term hasn't begun.
        starts = datetime.utcnow() + timedelta(days=30)
        s = _make_series(db, space, starts_at=starts,
                         ends_at=starts + timedelta(days=90))
        opt = _make_series_option(
            db, space, s, sessions_per_week=spw, total_sessions=total,
            grants_pathway_id=practice.id,
        )
        txn = _make_txn(db, payer=buyer, space=space)

        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )
        result = apply_intent(
            db, intent=resolution.intent, txn=txn,
            payer_user_id=buyer.id, space_id=space.id,
            payment_option_id=opt.id,
            payment_option_schedule_id=None,
            session_id=txn.provider_checkout_session_id,
            payment_intent_id="pi_test",
            now=datetime.utcnow(),
        )

        # PathwayEntitlement — starts immediately, ends at Series end.
        [ent] = result.entitlements
        assert ent.pathway_id == practice.id
        assert ent.ends_at == s.ends_at
        assert abs((ent.starts_at - datetime.utcnow()).total_seconds()) < 5
        assert ent.starts_at < s.starts_at   # immediate access, Series in future

        # AccessPass — Series-scoped, tier-specific credits.
        [ap] = result.access_passes
        assert ap.eligible_series_id == s.id
        assert ap.eligible_pathway_id is None
        assert ap.valid_from == s.starts_at
        assert ap.valid_until == s.ends_at
        assert ap.total_credits == total
        assert ap.credits_per_week == spw
        assert ap.payment_transaction_id == txn.id
        assert ap.payment_option_id == opt.id
        assert ap.pathway_entitlement_id == ent.id

        # Singular txn.entitlement_id → set (exactly one entitlement).
        assert txn.entitlement_id == ent.id


# ---------------------------------------------------------------------------
# Multi-intent shape — B3 makes fulfilment genuinely multi-grant capable
# even though the legacy resolver still only produces the three
# historically-supported shapes.
# ---------------------------------------------------------------------------


class TestMultipleEntitlementsFromOnePurchase:
    """Construct a FulfilmentIntent directly (bypassing the legacy
    resolver, which never produces this shape) and confirm the
    applier iterates cleanly."""

    def _kwargs(self, txn):
        return dict(
            txn=txn, payer_user_id=txn.payer_user_id,
            space_id=txn.space_id,
            payment_option_id=None,
            payment_option_schedule_id=None,
            session_id=txn.provider_checkout_session_id,
            payment_intent_id="pi_test",
            now=datetime.utcnow(),
        )

    def test_two_entitlements_are_both_created(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        pw1 = _make_pathway(db, space, title="First")
        pw2 = _make_pathway(db, space, title="Second")
        txn = _make_txn(db, payer=buyer, space=space)
        intent = FulfilmentIntent(
            entitlements=(
                EntitlementIntent(pathway_id=pw1.id, ends_at=None),
                EntitlementIntent(pathway_id=pw2.id, ends_at=None),
            ),
        )
        result = apply_intent(db, intent=intent, **self._kwargs(txn))
        assert len(result.entitlements) == 2
        pathway_ids = {e.pathway_id for e in result.entitlements}
        assert pathway_ids == {pw1.id, pw2.id}
        assert all(
            e.status == EntitlementStatus.active
            for e in result.entitlements
        )
        # Auto-join membership happens exactly once regardless of
        # entitlement count.
        assert result.membership_created is True

    def test_singular_txn_entitlement_id_null_when_multiple_entitlements(
        self, db, make_space, make_user,
    ):
        """The legacy singular ``PaymentTransaction.entitlement_id``
        pointer cannot honestly speak for a multi-entitlement
        purchase. It stays null; new readers should query
        PathwayEntitlement by (user, txn.id) instead."""
        space = make_space()
        buyer = make_user()
        pw1 = _make_pathway(db, space, title="First")
        pw2 = _make_pathway(db, space, title="Second")
        txn = _make_txn(db, payer=buyer, space=space)
        assert txn.entitlement_id is None  # sanity — starts null
        intent = FulfilmentIntent(
            entitlements=(
                EntitlementIntent(pathway_id=pw1.id, ends_at=None),
                EntitlementIntent(pathway_id=pw2.id, ends_at=None),
            ),
        )
        apply_intent(db, intent=intent, **self._kwargs(txn))
        assert txn.entitlement_id is None

    def test_singular_txn_entitlement_id_null_when_zero_entitlements(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        txn = _make_txn(db, payer=buyer, space=space)
        apply_intent(db, intent=FulfilmentIntent(), **self._kwargs(txn))
        assert txn.entitlement_id is None


class TestMultipleAccessPassesFromOnePurchase:
    """Same shape as above but for AccessPass rows. Multiple
    passes on one purchase — e.g. a future bundle covering two
    Series — must each be applied idempotently per
    (txn, series, pathway) triple, matching the extended
    idempotency key."""

    def _kwargs(self, txn, payment_option_id):
        return dict(
            txn=txn, payer_user_id=txn.payer_user_id,
            space_id=txn.space_id,
            payment_option_id=payment_option_id,
            payment_option_schedule_id=None,
            session_id=txn.provider_checkout_session_id,
            payment_intent_id="pi_test",
            now=datetime.utcnow(),
        )

    def test_two_series_passes_on_one_purchase(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        s1 = _make_series(db, space)
        s2 = _make_series(db, space)
        # Use ANY option row for the FK — the passes reference it
        # via ``payment_option_id`` regardless of the option's own
        # attachment shape.
        pw = _make_pathway(db, space)
        opt = _make_pathway_option(db, space, pw)
        txn = _make_txn(db, payer=buyer, space=space)
        intent = FulfilmentIntent(
            access_passes=(
                AccessPassIntent(
                    pass_type=AccessPassType.term_pass,
                    valid_from=s1.starts_at, valid_until=s1.ends_at,
                    total_credits=10, credits_per_week=1,
                    eligible_pathway_id=None, eligible_series_id=s1.id,
                    grants_pathway_id=None,
                ),
                AccessPassIntent(
                    pass_type=AccessPassType.term_pass,
                    valid_from=s2.starts_at, valid_until=s2.ends_at,
                    total_credits=8, credits_per_week=2,
                    eligible_pathway_id=None, eligible_series_id=s2.id,
                    grants_pathway_id=None,
                ),
            ),
        )
        result = apply_intent(db, intent=intent, **self._kwargs(txn, opt.id))
        assert len(result.access_passes) == 2
        series_ids = {ap.eligible_series_id for ap in result.access_passes}
        assert series_ids == {s1.id, s2.id}
        assert (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        ) == 2

    def test_replay_of_multi_pass_purchase_is_idempotent(
        self, db, make_space, make_user,
    ):
        """Applying the same multi-pass intent twice against the
        same txn produces no duplicate rows. Idempotency key is
        (payment_transaction_id, eligible_series_id, eligible_pathway_id)."""
        space = make_space()
        buyer = make_user()
        s1 = _make_series(db, space)
        s2 = _make_series(db, space)
        pw = _make_pathway(db, space)
        opt = _make_pathway_option(db, space, pw)
        txn = _make_txn(db, payer=buyer, space=space)
        intent = FulfilmentIntent(
            access_passes=(
                AccessPassIntent(
                    pass_type=AccessPassType.term_pass,
                    valid_from=s1.starts_at, valid_until=s1.ends_at,
                    total_credits=10, credits_per_week=1,
                    eligible_pathway_id=None, eligible_series_id=s1.id,
                    grants_pathway_id=None,
                ),
                AccessPassIntent(
                    pass_type=AccessPassType.term_pass,
                    valid_from=s2.starts_at, valid_until=s2.ends_at,
                    total_credits=8, credits_per_week=2,
                    eligible_pathway_id=None, eligible_series_id=s2.id,
                    grants_pathway_id=None,
                ),
            ),
        )
        result_1 = apply_intent(db, intent=intent, **self._kwargs(txn, opt.id))
        ids_1 = {ap.id for ap in result_1.access_passes}
        db.flush()

        result_2 = apply_intent(db, intent=intent, **self._kwargs(txn, opt.id))
        ids_2 = {ap.id for ap in result_2.access_passes}

        # Same rows returned; no duplicates in the table.
        assert ids_1 == ids_2
        assert (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        ) == 2


class TestOneEntitlementOnePassParityPreserved:
    """EMBODY's current shape (one entitlement + one AccessPass on
    the same purchase) must continue producing exactly the same
    rows under the tuple abstraction."""

    def test_replay_of_embody_purchase_is_idempotent(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        practice = _make_pathway(db, space, title="EMBODY Practice")
        starts = datetime.utcnow() + timedelta(days=30)
        s = _make_series(db, space, starts_at=starts,
                         ends_at=starts + timedelta(days=90))
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
        )
        txn = _make_txn(db, payer=buyer, space=space)
        resolution = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )

        kwargs = dict(
            txn=txn, payer_user_id=buyer.id, space_id=space.id,
            payment_option_id=opt.id,
            payment_option_schedule_id=None,
            session_id=txn.provider_checkout_session_id,
            payment_intent_id="pi_test",
            now=datetime.utcnow(),
        )
        r1 = apply_intent(db, intent=resolution.intent, **kwargs)
        [ent_1] = r1.entitlements
        [ap_1] = r1.access_passes
        db.flush()

        r2 = apply_intent(db, intent=resolution.intent, **kwargs)
        [ent_2] = r2.entitlements
        [ap_2] = r2.access_passes

        assert ent_1.id == ent_2.id
        assert ap_1.id == ap_2.id
        # Row counts stay at 1.
        assert (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .count()
        ) == 1
        assert (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        ) == 1
        # Singular txn.entitlement_id still points at the sole ent.
        assert txn.entitlement_id == ent_1.id


class TestBookingIntentReservedForFuture:
    def test_legacy_resolver_never_emits_bookings(self, db, make_space):
        """Every combination of legacy inputs the pre-B3 webhook
        knew about must produce an empty ``bookings`` tuple."""
        space = make_space()
        pw = _make_pathway(db, space)
        s = _make_series(db, space)

        # Pathway-attached option.
        opt_p = _make_pathway_option(db, space, pw)
        assert resolve_intent_from_legacy(
            db, payment_option=opt_p, metadata_pathway_id=pw.id,
            now=datetime.utcnow(),
        ).intent.bookings == ()

        # Series-attached option with bundled pathway.
        opt_s = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            grants_pathway_id=pw.id,
        )
        assert resolve_intent_from_legacy(
            db, payment_option=opt_s, metadata_pathway_id=None,
            now=datetime.utcnow(),
        ).intent.bookings == ()

        # Option-less legacy purchase.
        assert resolve_intent_from_legacy(
            db, payment_option=None, metadata_pathway_id=pw.id,
            now=datetime.utcnow(),
        ).intent.bookings == ()


# ---------------------------------------------------------------------------
# Atomicity — B3 hardening
#
# The shared service is atomic on the whole bundle:
#   resolve → validate → apply
# There is no partial-fulfilment path. A bundle either applies
# cleanly (all rows) or nothing is applied.
# ---------------------------------------------------------------------------


class TestValidateIntent:
    def test_empty_intent_is_valid(self, db):
        from app.services.purchase_fulfilment import validate_intent
        assert validate_intent(db, FulfilmentIntent()).ok

    def test_all_targets_present_is_valid(self, db, make_space):
        from app.services.purchase_fulfilment import validate_intent
        space = make_space()
        pw = _make_pathway(db, space)
        s = _make_series(db, space)
        intent = FulfilmentIntent(
            entitlements=(EntitlementIntent(pathway_id=pw.id, ends_at=None),),
            access_passes=(AccessPassIntent(
                pass_type=AccessPassType.term_pass,
                valid_from=s.starts_at, valid_until=s.ends_at,
                total_credits=10, credits_per_week=1,
                eligible_pathway_id=None, eligible_series_id=s.id,
                grants_pathway_id=pw.id,
            ),),
        )
        assert validate_intent(db, intent).ok

    def test_missing_pathway_reported(self, db):
        from app.services.purchase_fulfilment import validate_intent
        intent = FulfilmentIntent(
            entitlements=(EntitlementIntent(
                pathway_id="pw_missing", ends_at=None,
            ),),
        )
        v = validate_intent(db, intent)
        assert not v.ok
        assert any("pw_missing" in e for e in v.errors)

    def test_missing_series_on_access_pass_reported(self, db, make_space):
        from app.services.purchase_fulfilment import validate_intent
        space = make_space()
        pw = _make_pathway(db, space)
        intent = FulfilmentIntent(
            access_passes=(AccessPassIntent(
                pass_type=AccessPassType.term_pass,
                valid_from=datetime.utcnow(),
                valid_until=datetime.utcnow() + timedelta(days=90),
                total_credits=10, credits_per_week=1,
                eligible_pathway_id=None,
                eligible_series_id="es_missing",
                grants_pathway_id=pw.id,
            ),),
        )
        v = validate_intent(db, intent)
        assert not v.ok
        assert any("es_missing" in e for e in v.errors)

    def test_multiple_missing_targets_all_reported(self, db):
        from app.services.purchase_fulfilment import validate_intent
        intent = FulfilmentIntent(
            entitlements=(
                EntitlementIntent(pathway_id="pw_missing_a", ends_at=None),
                EntitlementIntent(pathway_id="pw_missing_b", ends_at=None),
            ),
            access_passes=(AccessPassIntent(
                pass_type=AccessPassType.term_pass,
                valid_from=datetime.utcnow(),
                valid_until=datetime.utcnow() + timedelta(days=90),
                total_credits=10, credits_per_week=1,
                eligible_pathway_id=None,
                eligible_series_id="es_missing_c",
                grants_pathway_id=None,
            ),),
        )
        v = validate_intent(db, intent)
        assert not v.ok
        # Both missing pathways and the missing series all reported.
        joined = " ".join(v.errors)
        assert "pw_missing_a" in joined
        assert "pw_missing_b" in joined
        assert "es_missing_c" in joined


class TestAtomicMultiExperienceBundle:
    """The shared service is atomic across every experience a
    Payment Option may promise. A future bundle carrying multiple
    Pathways + Series must either commit all rows or none."""

    def _kwargs(self, txn, payment_option_id=None):
        return dict(
            txn=txn, payer_user_id=txn.payer_user_id,
            space_id=txn.space_id,
            payment_option_id=payment_option_id,
            payment_option_schedule_id=None,
            session_id=txn.provider_checkout_session_id,
            payment_intent_id="pi_test",
            now=datetime.utcnow(),
        )

    def test_complete_bundle_succeeds(self, db, make_space, make_user):
        """Two Pathway entitlements + two Series AccessPasses — all
        or nothing. Here: all."""
        space = make_space()
        buyer = make_user()
        pw1 = _make_pathway(db, space, title="Pathway A")
        pw2 = _make_pathway(db, space, title="Pathway B")
        s1 = _make_series(db, space)
        s2 = _make_series(db, space)
        pw_stub = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw_stub)
        txn = _make_txn(db, payer=buyer, space=space)
        intent = FulfilmentIntent(
            entitlements=(
                EntitlementIntent(pathway_id=pw1.id, ends_at=None),
                EntitlementIntent(pathway_id=pw2.id, ends_at=None),
            ),
            access_passes=(
                AccessPassIntent(
                    pass_type=AccessPassType.term_pass,
                    valid_from=s1.starts_at, valid_until=s1.ends_at,
                    total_credits=10, credits_per_week=1,
                    eligible_pathway_id=None, eligible_series_id=s1.id,
                    grants_pathway_id=None,
                ),
                AccessPassIntent(
                    pass_type=AccessPassType.term_pass,
                    valid_from=s2.starts_at, valid_until=s2.ends_at,
                    total_credits=8, credits_per_week=2,
                    eligible_pathway_id=None, eligible_series_id=s2.id,
                    grants_pathway_id=None,
                ),
            ),
        )
        from app.services.purchase_fulfilment import validate_intent, FulfilmentStatus
        assert validate_intent(db, intent).ok
        result = apply_intent(db, intent=intent, **self._kwargs(txn, opt.id))
        db.flush()

        assert result.status == FulfilmentStatus.APPLIED
        assert len(result.entitlements) == 2
        assert len(result.access_passes) == 2
        assert (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .count()
        ) == 2
        assert (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        ) == 2

    def test_missing_target_in_bundle_blocks_everything(
        self, db, make_space, make_user,
    ):
        """Pathway A valid + Pathway B missing + Series C valid →
        no writes at all. The pre-B3 webhook would have created A
        and skipped C; the new contract refuses the whole bundle
        upfront."""
        from app.services.purchase_fulfilment import validate_intent
        space = make_space()
        buyer = make_user()
        pw_a = _make_pathway(db, space, title="A")
        s_c = _make_series(db, space)
        pw_stub = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw_stub)
        txn = _make_txn(db, payer=buyer, space=space)
        intent = FulfilmentIntent(
            entitlements=(
                EntitlementIntent(pathway_id=pw_a.id, ends_at=None),
                EntitlementIntent(pathway_id="pw_B_missing", ends_at=None),
            ),
            access_passes=(AccessPassIntent(
                pass_type=AccessPassType.term_pass,
                valid_from=s_c.starts_at, valid_until=s_c.ends_at,
                total_credits=10, credits_per_week=1,
                eligible_pathway_id=None, eligible_series_id=s_c.id,
                grants_pathway_id=None,
            ),),
        )
        # Validation catches the missing pathway before any writes.
        v = validate_intent(db, intent)
        assert not v.ok
        # Caller (webhook) will NOT invoke apply_intent — but even
        # if some future caller forgot, the DB has no new rows.
        assert (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .count()
        ) == 0
        assert (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        ) == 0

    def test_race_during_apply_raises_and_leaves_txn_uncommitted(
        self, db, make_space, make_user,
    ):
        """Simulate the race window between validation and apply:
        pretend validation passed, then feed apply_intent an intent
        whose target Pathway does not exist. The FK constraint
        raises IntegrityError. The webhook's ``try/except`` around
        apply_intent then rolls back the whole session — including
        the txn's ``status='succeeded'`` update — so on Stripe
        re-delivery we start fresh.

        This test asserts the raise behaviour of ``apply_intent``.
        The webhook-level rollback + fulfilment_status behaviour is
        covered by the ``TestFulfilmentStatusOnTransaction`` suite
        below (end-to-end through the webhook)."""
        from sqlalchemy.exc import IntegrityError

        space = make_space()
        buyer = make_user()
        pw_a = _make_pathway(db, space, title="A")
        pw_stub = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw_stub)
        txn = _make_txn(db, payer=buyer, space=space)

        intent = FulfilmentIntent(
            entitlements=(
                EntitlementIntent(pathway_id=pw_a.id, ends_at=None),
                # No such pathway — validation would catch this,
                # but we deliberately skip validation here to
                # simulate the race and prove apply raises.
                EntitlementIntent(pathway_id="pw_race_gone", ends_at=None),
            ),
        )

        with pytest.raises(IntegrityError):
            apply_intent(db, intent=intent, **self._kwargs(txn, opt.id))
            db.flush()
        db.rollback()

    def test_replay_after_fix_produces_no_duplicates(
        self, db, make_space, make_user,
    ):
        """The Series row is missing on first attempt → the whole
        bundle is blocked. The Series row is created, the webhook
        is replayed → fulfilment completes cleanly with no
        duplicate rows from any partial first attempt."""
        from app.services.purchase_fulfilment import (
            validate_intent, FulfilmentStatus,
        )
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Bundled Practice")
        pw_stub = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw_stub)
        txn = _make_txn(db, payer=buyer, space=space)

        # First attempt: series is missing. Validation blocks.
        intent = FulfilmentIntent(
            entitlements=(EntitlementIntent(pathway_id=pw.id, ends_at=None),),
            access_passes=(AccessPassIntent(
                pass_type=AccessPassType.term_pass,
                valid_from=datetime.utcnow(),
                valid_until=datetime.utcnow() + timedelta(days=90),
                total_credits=10, credits_per_week=1,
                eligible_pathway_id=None,
                eligible_series_id="es_will_appear",
                grants_pathway_id=pw.id,
            ),),
        )
        v = validate_intent(db, intent)
        assert not v.ok

        # Nothing committed yet.
        assert (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .count()
        ) == 0
        assert (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        ) == 0

        # Someone creates the missing Series row (the "fix").
        s = EventSeries(
            id="es_will_appear", space_id=space.id,
            slug="fix", title="Recovered",
            starts_at=datetime.utcnow(),
            ends_at=datetime.utcnow() + timedelta(days=90),
            status="published",
        )
        db.add(s)
        db.flush()

        # Replay validates cleanly this time.
        v2 = validate_intent(db, intent)
        assert v2.ok
        result = apply_intent(db, intent=intent, **self._kwargs(txn, opt.id))
        assert result.status == FulfilmentStatus.APPLIED
        db.flush()

        # Exactly one entitlement + one AccessPass — no duplicates.
        assert (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .count()
        ) == 1
        assert (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        ) == 1


class TestFulfilmentStatusOnTransaction:
    """The webhook path (covered end-to-end by
    ``test_gathering_series.py``) writes ``fulfilment_status`` on
    the txn. Here we assert the status values are what we expect
    for each terminal case."""

    def _fire_webhook(
        self, db, *, txn, payment_option=None, pathway_id=None,
    ):
        from app.webhooks.routes import _handle_checkout_completed
        metadata = {
            "transaction_id": txn.id,
            "payer_user_id": txn.payer_user_id,
            "space_id": txn.space_id,
        }
        if payment_option is not None:
            metadata["payment_option_id"] = payment_option.id
        if pathway_id:
            metadata["pathway_id"] = pathway_id
        session = {
            "id": txn.provider_checkout_session_id,
            "payment_status": "paid",
            "payment_intent": "pi_test",
            "metadata": metadata,
        }
        _handle_checkout_completed(session, db)

    def test_applied_on_successful_purchase(
        self, db, make_space, make_user,
    ):
        from app.models.payment import (
            PaymentFulfilmentStatus, PaymentTransactionStatus,
        )
        space = make_space()
        buyer = make_user()
        practice = _make_pathway(db, space, title="Practice")
        starts = datetime.utcnow() + timedelta(days=30)
        s = _make_series(db, space, starts_at=starts,
                         ends_at=starts + timedelta(days=90))
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
        )
        txn = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_pathway_purchase,
            status=PaymentTransactionStatus.pending,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=buyer.id, creator_user_id=space.creator_id,
            space_id=space.id, currency="AUD",
            gross_amount_cents=20000, platform_fee_basis_points=800,
            platform_fee_cents=1600, net_creator_amount_cents=18400,
            stripe_mode="test", payout_status=PayoutStatus.pending,
            provider_checkout_session_id=_uid("cs"),
        )
        db.add(txn)
        db.commit()

        self._fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied

    def test_blocked_when_resolver_fatal_error(
        self, db, make_space, make_user,
    ):
        """Series-attached option → resolver detects missing
        Series → txn ends up succeeded + blocked."""
        from app.models.payment import (
            PaymentFulfilmentStatus, PaymentTransactionStatus,
        )
        space = make_space()
        buyer = make_user()
        s = _make_series(db, space)
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
        )
        opt.attaches_to_id = "es_gone"   # simulate stale pointer
        db.flush()

        txn = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_pathway_purchase,
            status=PaymentTransactionStatus.pending,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=buyer.id, creator_user_id=space.creator_id,
            space_id=space.id, currency="AUD",
            gross_amount_cents=20000, platform_fee_basis_points=800,
            platform_fee_cents=1600, net_creator_amount_cents=18400,
            stripe_mode="test", payout_status=PayoutStatus.pending,
            provider_checkout_session_id=_uid("cs"),
        )
        db.add(txn)
        db.commit()

        self._fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)
        # Payment succeeded (Stripe took the money).
        assert txn.status == PaymentTransactionStatus.succeeded
        # But we could not fulfil — blocked, awaiting reconciliation.
        assert txn.fulfilment_status == PaymentFulfilmentStatus.blocked

    def test_blocked_when_validation_fails(
        self, db, make_space, make_user,
    ):
        """Pathway-attached option resolves fine but the metadata
        pathway_id points at a Pathway that no longer exists →
        validation catches it → blocked."""
        from app.models.payment import (
            PaymentFulfilmentStatus, PaymentTransactionStatus,
        )
        space = make_space()
        buyer = make_user()
        pw_stub = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw_stub)
        txn = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_pathway_purchase,
            status=PaymentTransactionStatus.pending,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=buyer.id, creator_user_id=space.creator_id,
            space_id=space.id, currency="AUD",
            gross_amount_cents=20000, platform_fee_basis_points=800,
            platform_fee_cents=1600, net_creator_amount_cents=18400,
            stripe_mode="test", payout_status=PayoutStatus.pending,
            provider_checkout_session_id=_uid("cs"),
        )
        db.add(txn)
        db.commit()

        # Metadata pathway_id points at nothing.
        self._fire_webhook(
            db, txn=txn, payment_option=opt, pathway_id="pw_ghost",
        )
        db.refresh(txn)
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.blocked
        # No entitlement was created for the ghost pathway.
        assert (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .count()
        ) == 0

    def test_blocked_txn_can_be_replayed_after_fix(
        self, db, make_space, make_user,
    ):
        """Once the missing Series row is created, replaying the
        webhook flips the txn from blocked → applied and produces
        the correct downstream rows."""
        from app.models.payment import (
            PaymentFulfilmentStatus, PaymentTransactionStatus,
        )
        space = make_space()
        buyer = make_user()
        practice = _make_pathway(db, space, title="Practice")
        s = _make_series(db, space)   # this one exists — good
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
        )
        # Break the pointer so the first delivery fails.
        original_series_id = opt.attaches_to_id
        opt.attaches_to_id = "es_temp_gone"
        db.flush()

        txn = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_pathway_purchase,
            status=PaymentTransactionStatus.pending,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=buyer.id, creator_user_id=space.creator_id,
            space_id=space.id, currency="AUD",
            gross_amount_cents=20000, platform_fee_basis_points=800,
            platform_fee_cents=1600, net_creator_amount_cents=18400,
            stripe_mode="test", payout_status=PayoutStatus.pending,
            provider_checkout_session_id=_uid("cs"),
        )
        db.add(txn)
        db.commit()

        # First delivery: blocked.
        self._fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)
        assert txn.fulfilment_status == PaymentFulfilmentStatus.blocked

        # Fix the data: restore the Series pointer.
        opt.attaches_to_id = original_series_id
        db.commit()

        # Second delivery (Stripe re-delivery, or operator replay):
        # the applied-vs-blocked idempotency check lets us through,
        # and the bundle now applies cleanly.
        self._fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        # Downstream rows exist and are the correct count (no dupes).
        assert (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        ) == 1
        assert (
            db.query(PathwayEntitlement)
            .filter(
                PathwayEntitlement.user_id == buyer.id,
                PathwayEntitlement.pathway_id == practice.id,
            )
            .count()
        ) == 1

    def test_already_applied_replay_skips_cleanly(
        self, db, make_space, make_user,
    ):
        """Standard Stripe re-delivery after successful fulfilment
        — the webhook short-circuits on ``fulfilment_status ==
        applied`` and touches nothing."""
        from app.models.payment import PaymentFulfilmentStatus
        space = make_space()
        buyer = make_user()
        practice = _make_pathway(db, space, title="Practice")
        starts = datetime.utcnow() + timedelta(days=30)
        s = _make_series(db, space, starts_at=starts,
                         ends_at=starts + timedelta(days=90))
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
        )
        txn = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_pathway_purchase,
            status=PaymentTransactionStatus.pending,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=buyer.id, creator_user_id=space.creator_id,
            space_id=space.id, currency="AUD",
            gross_amount_cents=20000, platform_fee_basis_points=800,
            platform_fee_cents=1600, net_creator_amount_cents=18400,
            stripe_mode="test", payout_status=PayoutStatus.pending,
            provider_checkout_session_id=_uid("cs"),
        )
        db.add(txn)
        db.commit()

        self._fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        ap_count_1 = (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        )

        # Re-deliver. Count must not change.
        self._fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        ap_count_2 = (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        )
        assert ap_count_1 == ap_count_2 == 1
