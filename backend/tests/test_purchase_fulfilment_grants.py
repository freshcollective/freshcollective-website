"""B4A — grant-first fulfilment.

Covers the switch of the runtime resolver source from legacy
``PaymentOption`` fields to ``PaymentOption.grants``. Behaviour
of ``validate_intent`` and ``apply_intent`` is unchanged (proven
by the existing B3 tests); this file focuses on the resolver +
dispatcher.

Structure:

  * ``TestResolveIntentFromGrants`` — grant-only shapes: single
    Pathway grant, single Series grant, multiple grants,
    unsupported Gathering grant returns fatal_error.
  * ``TestLegacyVsGrantsParity`` — for every legacy shape B2 knows
    how to backfill, prove that the grant-first resolver produces
    the same normalised ``FulfilmentIntent`` (semantic parity at
    the intent level, not implementation details).
  * ``TestEmbodyThreeTierGrants`` — Awaken / Activate / Empower
    resolve from grants to the same rows the legacy resolver
    would produce.
  * ``TestDispatcher`` — the runtime rule: grants take
    precedence; no grants → legacy fallback + structured warning;
    no option at all → legacy (metadata pathway_id).
  * ``TestGrantsFirstEndToEnd`` — webhook end-to-end with grants:
    grants-take-precedence-over-legacy-fields, atomic-failure
    blocks the bundle, replay after repair produces no duplicates,
    multi-Series produces independent AccessPasses, multi-Pathway
    keeps singular ``txn.entitlement_id`` null.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from app.commerce.backfill_grants import run_backfill
from app.models.access_pass import (
    AccessPass,
    AccessPassStatus,
    AccessPassType,
)
from app.models.payment import (
    PaymentFulfilmentStatus,
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
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.platform import (
    EntitlementStatus,
    EventSeries,
    Pathway,
    PathwayEntitlement,
    PathwayType,
)
from app.services.purchase_fulfilment import (
    AccessPassIntent,
    EntitlementIntent,
    FulfilmentIntent,
    FulfilmentResolution,
    apply_intent,
    resolve_intent_for_option,
    resolve_intent_from_grants,
    resolve_intent_from_legacy,
    validate_intent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


_UNSET = object()


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


def _make_series(
    db, space, *,
    starts_at: datetime | None = None,
    ends_at=_UNSET,
) -> EventSeries:
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
    term_end_date=_UNSET,
    grants_pathway_id: str | None = None,
) -> PaymentOption:
    resolved_term_end = (
        term_end_date if term_end_date is not _UNSET
        else (series.ends_at.date() if series.ends_at else None)
    )
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, pathway_id=None,
        attaches_to_kind="event_series", attaches_to_id=series.id,
        grants_pathway_id=grants_pathway_id,
        name="Series pass", payment_type=PaymentOptionType.term_pass,
        status=PaymentOptionStatus.published,
        sessions_per_week=sessions_per_week,
        total_sessions=total_sessions,
        term_start_date=series.starts_at.date(),
        term_end_date=resolved_term_end,
        calculated_total_cents=60000, currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _add_pathway_grant(
    db, option, pathway, *,
    valid_from_override=None, valid_until_override=None,
) -> PaymentOptionGrant:
    g = PaymentOptionGrant(
        payment_option_id=option.id,
        grant_kind="pathway", pathway_id=pathway.id,
        valid_from_override=valid_from_override,
        valid_until_override=valid_until_override,
    )
    db.add(g)
    db.flush()
    return g


def _add_series_grant(
    db, option, series, *,
    sessions_per_week=None, total_sessions=None,
    valid_from_override=None, valid_until_override=None,
) -> PaymentOptionGrant:
    g = PaymentOptionGrant(
        payment_option_id=option.id,
        grant_kind="event_series", series_id=series.id,
        sessions_per_week=sessions_per_week,
        total_sessions=total_sessions,
        valid_from_override=valid_from_override,
        valid_until_override=valid_until_override,
    )
    db.add(g)
    db.flush()
    return g


def _add_gathering_grant(db, option, event) -> PaymentOptionGrant:
    g = PaymentOptionGrant(
        payment_option_id=option.id,
        grant_kind="gathering", event_id=event.id,
    )
    db.add(g)
    db.flush()
    return g


def _make_txn(db, *, payer, space, status=PaymentTransactionStatus.pending) -> PaymentTransaction:
    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=status,
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


def _reload_option_with_grants(db, option: PaymentOption) -> PaymentOption:
    """After adding grants, force SQLAlchemy to reload the option
    so ``option.grants`` reflects the new rows. The ``selectin``
    loader would cache the empty list from a prior access."""
    db.expire(option)
    return option


def _intents_equal_semantically(a: FulfilmentIntent, b: FulfilmentIntent) -> bool:
    """Compare two FulfilmentIntents by semantic content. Since
    intent dataclasses are frozen and value-equal, and both
    resolvers produce the same shape, ``==`` is the right test.
    Defined as its own helper only for clarity in assertions."""
    return a == b


# ---------------------------------------------------------------------------
# Grant resolver — shapes
# ---------------------------------------------------------------------------


class TestResolveIntentFromGrants:
    def test_empty_grants_produces_empty_intent(self, db, make_space):
        space = make_space()
        pw = _make_pathway(db, space)
        opt = _make_pathway_option(db, space, pw)
        # No grants on this option.
        resolution = resolve_intent_from_grants(db, payment_option=opt)
        assert resolution.fatal_error is None
        assert resolution.intent == FulfilmentIntent()

    def test_single_pathway_grant_produces_entitlement_intent(
        self, db, make_space,
    ):
        space = make_space()
        pw_option = _make_pathway(db, space, title="stub")
        pw_grant = _make_pathway(db, space, title="Practice")
        opt = _make_pathway_option(db, space, pw_option)
        _add_pathway_grant(db, opt, pw_grant)
        opt = _reload_option_with_grants(db, opt)

        resolution = resolve_intent_from_grants(db, payment_option=opt)
        assert resolution.fatal_error is None
        assert resolution.intent.access_passes == ()
        assert resolution.intent.bookings == ()
        [ent] = resolution.intent.entitlements
        assert ent == EntitlementIntent(
            pathway_id=pw_grant.id, ends_at=None, starts_at=None,
        )

    def test_pathway_grant_carries_valid_from_and_until_overrides(
        self, db, make_space,
    ):
        space = make_space()
        pw_option = _make_pathway(db, space, title="stub")
        pw_grant = _make_pathway(db, space, title="Practice")
        opt = _make_pathway_option(db, space, pw_option)
        start = datetime(2026, 9, 1)
        end = datetime(2026, 12, 1)
        _add_pathway_grant(
            db, opt, pw_grant,
            valid_from_override=start, valid_until_override=end,
        )
        opt = _reload_option_with_grants(db, opt)

        [ent] = resolve_intent_from_grants(db, payment_option=opt).intent.entitlements
        assert ent.starts_at == start
        assert ent.ends_at == end

    def test_single_series_grant_inherits_series_window(
        self, db, make_space,
    ):
        space = make_space()
        pw = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw)
        starts = datetime(2027, 1, 15)
        s = _make_series(db, space, starts_at=starts, ends_at=starts + timedelta(days=60))
        _add_series_grant(
            db, opt, s, sessions_per_week=2, total_sessions=12,
        )
        opt = _reload_option_with_grants(db, opt)

        resolution = resolve_intent_from_grants(db, payment_option=opt)
        assert resolution.intent.entitlements == ()
        [ap] = resolution.intent.access_passes
        assert ap.eligible_series_id == s.id
        assert ap.eligible_pathway_id is None
        assert ap.valid_from == s.starts_at
        assert ap.valid_until == s.ends_at
        assert ap.total_credits == 12
        assert ap.credits_per_week == 2
        # No Pathway grant on this option → grants_pathway_id shadow
        # stays None.
        assert ap.grants_pathway_id is None

    def test_series_grant_override_windows_win(self, db, make_space):
        space = make_space()
        pw = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw)
        starts = datetime(2027, 1, 15)
        s = _make_series(db, space, starts_at=starts, ends_at=starts + timedelta(days=60))
        override_from = datetime(2027, 2, 1)
        override_until = datetime(2027, 4, 1)
        _add_series_grant(
            db, opt, s,
            sessions_per_week=1, total_sessions=8,
            valid_from_override=override_from,
            valid_until_override=override_until,
        )
        opt = _reload_option_with_grants(db, opt)

        [ap] = resolve_intent_from_grants(db, payment_option=opt).intent.access_passes
        assert ap.valid_from == override_from
        assert ap.valid_until == override_until

    def test_series_grant_ongoing_series_no_override_no_end(
        self, db, make_space,
    ):
        space = make_space()
        pw = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw)
        s = _make_series(db, space, starts_at=datetime(2027, 3, 1), ends_at=None)
        _add_series_grant(
            db, opt, s, sessions_per_week=1, total_sessions=10,
        )
        opt = _reload_option_with_grants(db, opt)

        [ap] = resolve_intent_from_grants(db, payment_option=opt).intent.access_passes
        assert ap.valid_from == s.starts_at
        assert ap.valid_until is None

    def test_series_grant_ongoing_series_with_override_end(
        self, db, make_space,
    ):
        space = make_space()
        pw = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw)
        s = _make_series(db, space, starts_at=datetime(2027, 3, 1), ends_at=None)
        end = datetime(2027, 6, 1)
        _add_series_grant(
            db, opt, s,
            sessions_per_week=1, total_sessions=10,
            valid_until_override=end,
        )
        opt = _reload_option_with_grants(db, opt)

        [ap] = resolve_intent_from_grants(db, payment_option=opt).intent.access_passes
        assert ap.valid_until == end

    def test_series_grant_missing_series_row_is_caught_by_validate(
        self, db, make_space,
    ):
        """The B1 CHECK RESTRICT constraint prevents deleting an
        EventSeries while any grant references it — good property.
        To simulate the equivalent "missing target" state
        ``validate_intent`` must catch, construct an intent
        directly with a stale series_id (as if the grant table
        somehow drifted from event_series). ``validate_intent``
        surfaces the missing target so the caller blocks the
        bundle before apply."""
        # Craft an intent that references a Series id that does
        # not exist. Bypasses the resolver entirely — this is
        # ``validate_intent``'s job.
        intent = FulfilmentIntent(
            access_passes=(AccessPassIntent(
                pass_type=AccessPassType.term_pass,
                valid_from=datetime.utcnow(),
                valid_until=datetime.utcnow() + timedelta(days=90),
                total_credits=10, credits_per_week=1,
                eligible_pathway_id=None,
                eligible_series_id="es_stale_grant",
                grants_pathway_id=None,
            ),),
        )
        v = validate_intent(db, intent)
        assert not v.ok
        assert any("es_stale_grant" in err for err in v.errors)

    def test_gathering_grant_returns_fatal_error(self, db, make_space, make_user):
        """Standalone Gathering fulfilment via PaymentOption grants
        is not yet activated. A Gathering grant must NOT silently
        succeed — the resolver returns a fatal_error so the webhook
        marks the txn ``fulfilment_status=blocked``."""
        from app.models.platform import Event
        space = make_space()
        pw = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw)
        # Minimal Event row that satisfies the schema.
        e = Event(
            id=_uid("e"), space_id=space.id,
            created_by_id=space.creator_id,
            title="Standalone workshop",
            starts_at=datetime.utcnow() + timedelta(days=14),
            ends_at=datetime.utcnow() + timedelta(days=14, hours=1),
            location_type="zoom", is_published=True, status="active",
            requires_booking=True, capacity=20,
            booking_access_type="included_with_collective",
            gathering_type="workshop", attendance_format="online",
        )
        db.add(e)
        db.flush()
        _add_gathering_grant(db, opt, e)
        opt = _reload_option_with_grants(db, opt)

        resolution = resolve_intent_from_grants(db, payment_option=opt)
        assert resolution.fatal_error is not None
        assert "gathering" in resolution.fatal_error.lower()
        assert resolution.intent == FulfilmentIntent()

    def test_multiple_pathway_grants(self, db, make_space):
        space = make_space()
        pw = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw)
        pw_a = _make_pathway(db, space, title="A")
        pw_b = _make_pathway(db, space, title="B")
        _add_pathway_grant(db, opt, pw_a)
        _add_pathway_grant(db, opt, pw_b)
        opt = _reload_option_with_grants(db, opt)

        resolution = resolve_intent_from_grants(db, payment_option=opt)
        pathway_ids = {e.pathway_id for e in resolution.intent.entitlements}
        assert pathway_ids == {pw_a.id, pw_b.id}
        assert resolution.intent.access_passes == ()

    def test_multiple_series_grants_produce_independent_passes(
        self, db, make_space,
    ):
        space = make_space()
        pw = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw)
        s1 = _make_series(db, space, starts_at=datetime(2027, 1, 1))
        s2 = _make_series(db, space, starts_at=datetime(2027, 5, 1))
        _add_series_grant(db, opt, s1, sessions_per_week=1, total_sessions=8)
        _add_series_grant(db, opt, s2, sessions_per_week=2, total_sessions=20)
        opt = _reload_option_with_grants(db, opt)

        resolution = resolve_intent_from_grants(db, payment_option=opt)
        passes = list(resolution.intent.access_passes)
        assert len(passes) == 2
        by_series = {ap.eligible_series_id: ap for ap in passes}
        assert by_series[s1.id].total_credits == 8
        assert by_series[s1.id].credits_per_week == 1
        assert by_series[s1.id].valid_from == s1.starts_at
        assert by_series[s2.id].total_credits == 20
        assert by_series[s2.id].credits_per_week == 2
        assert by_series[s2.id].valid_from == s2.starts_at

    def test_multiple_pathways_plus_multiple_series(
        self, db, make_space,
    ):
        """A combined bundle: two Pathway grants + two Series grants
        → four intents (two entitlements + two access_passes)."""
        space = make_space()
        pw = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw)
        pw_a = _make_pathway(db, space, title="A")
        pw_b = _make_pathway(db, space, title="B")
        s1 = _make_series(db, space, starts_at=datetime(2027, 1, 1))
        s2 = _make_series(db, space, starts_at=datetime(2027, 5, 1))
        _add_pathway_grant(db, opt, pw_a)
        _add_pathway_grant(db, opt, pw_b)
        _add_series_grant(db, opt, s1, sessions_per_week=1, total_sessions=8)
        _add_series_grant(db, opt, s2, sessions_per_week=2, total_sessions=20)
        opt = _reload_option_with_grants(db, opt)

        resolution = resolve_intent_from_grants(db, payment_option=opt)
        assert len(resolution.intent.entitlements) == 2
        assert len(resolution.intent.access_passes) == 2
        # Shadow: multi-Pathway → shadow_grants_pathway_id stays None
        # on every AccessPass because there's no single "the" pathway.
        for ap in resolution.intent.access_passes:
            assert ap.grants_pathway_id is None


# ---------------------------------------------------------------------------
# Legacy vs grants — semantic parity at the intent level
# ---------------------------------------------------------------------------


class TestLegacyVsGrantsParity:
    """For every legacy PaymentOption shape B2 backfilled, the
    grant-first resolver must produce a FulfilmentIntent that
    equals the legacy resolver's output. This is the promise B2
    made ("grants can represent everything the legacy fields do")
    verified at the runtime boundary the webhook will use.
    """

    def _both_intents(self, db, option, *, metadata_pathway_id=None):
        # Legacy resolver runs against the option's shadow columns.
        legacy = resolve_intent_from_legacy(
            db, payment_option=option,
            metadata_pathway_id=metadata_pathway_id,
            now=datetime.utcnow(),
        )
        # Grant resolver runs against grants that B2's backfill
        # produced from those same shadow columns.
        db.expire(option)
        grants = resolve_intent_from_grants(db, payment_option=option)
        return legacy, grants

    def test_pathway_only_option_parity(self, db, make_space):
        """A pathway-attached one_time option → one EntitlementIntent
        (pathway from Stripe metadata for the legacy resolver, from
        the grant for the grant resolver)."""
        space = make_space()
        pw = _make_pathway(db, space, title="Home Practice")
        opt = _make_pathway_option(db, space, pw)
        run_backfill(db)
        db.expire(opt)

        legacy = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=pw.id,   # matches what pathway checkout wires
            now=datetime.utcnow(),
        )
        grants = resolve_intent_from_grants(db, payment_option=opt)
        assert legacy.intent == grants.intent
        # And each side agrees on the shape we expect.
        [ent] = grants.intent.entitlements
        assert ent.pathway_id == pw.id
        assert ent.ends_at is None
        assert grants.intent.access_passes == ()

    def test_series_only_option_parity(self, db, make_space):
        space = make_space()
        starts = datetime(2027, 2, 1)
        s = _make_series(db, space, starts_at=starts, ends_at=starts + timedelta(days=90))
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
        )
        run_backfill(db)
        db.expire(opt)

        legacy = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )
        grants = resolve_intent_from_grants(db, payment_option=opt)
        assert legacy.intent == grants.intent
        # Sanity: series-only shape.
        assert grants.intent.entitlements == ()
        [ap] = grants.intent.access_passes
        assert ap.eligible_series_id == s.id
        assert ap.eligible_pathway_id is None

    def test_series_plus_bundled_pathway_parity(self, db, make_space):
        space = make_space()
        practice = _make_pathway(db, space, title="Practice")
        starts = datetime(2027, 2, 1)
        s = _make_series(db, space, starts_at=starts, ends_at=starts + timedelta(days=90))
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
        )
        run_backfill(db)
        db.expire(opt)

        legacy = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )
        grants = resolve_intent_from_grants(db, payment_option=opt)
        assert legacy.intent == grants.intent
        # Sanity.
        [ent] = grants.intent.entitlements
        [ap] = grants.intent.access_passes
        assert ent.pathway_id == practice.id
        assert ent.ends_at == s.ends_at
        assert ap.eligible_series_id == s.id
        # Legacy shadow preserved on the AccessPass — single Pathway
        # grant on the option → shadow points at it.
        assert ap.grants_pathway_id == practice.id

    def test_ongoing_series_with_option_term_end_parity(self, db, make_space):
        space = make_space()
        practice = _make_pathway(db, space, title="Practice")
        s = _make_series(db, space, starts_at=datetime(2027, 1, 1), ends_at=None)
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            term_end_date=date(2027, 4, 1),
            grants_pathway_id=practice.id,
        )
        run_backfill(db)
        db.expire(opt)

        legacy = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )
        grants = resolve_intent_from_grants(db, payment_option=opt)
        assert legacy.intent == grants.intent
        # Both entitlement.ends_at and access_pass.valid_until fall
        # back to the option's term_end_date (as datetime).
        expected_end = datetime(2027, 4, 1, 0, 0)
        [ent] = grants.intent.entitlements
        [ap] = grants.intent.access_passes
        assert ent.ends_at == expected_end
        assert ap.valid_until == expected_end

    def test_immediate_pathway_access_parity(self, db, make_space):
        """Bundled Pathway grant's ``valid_from_override`` is null
        → applier will use NOW; matches the legacy resolver's
        implicit "starts NOW" for the bundled entitlement."""
        space = make_space()
        practice = _make_pathway(db, space, title="Practice")
        starts = datetime.utcnow() + timedelta(days=30)  # future Series
        s = _make_series(db, space, starts_at=starts, ends_at=starts + timedelta(days=60))
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
        )
        run_backfill(db)
        db.expire(opt)

        grants = resolve_intent_from_grants(db, payment_option=opt)
        pathway_intent = next(
            e for e in grants.intent.entitlements if e.pathway_id == practice.id
        )
        # None on both fields for a bundled Pathway with no overrides.
        assert pathway_intent.starts_at is None    # applier will use NOW
        assert pathway_intent.ends_at == s.ends_at


# ---------------------------------------------------------------------------
# EMBODY three-tier parity — Awaken / Activate / Empower
# ---------------------------------------------------------------------------


class TestEmbodyThreeTierGrants:
    @pytest.mark.parametrize(
        "name,spw,total",
        [("Awaken", 1, 10), ("Activate", 2, 20), ("Empower", 3, 30)],
    )
    def test_tier_grant_resolution_matches_legacy(
        self, db, make_space, name, spw, total,
    ):
        space = make_space()
        practice = _make_pathway(db, space, title="The EMBODY Practice")
        starts = datetime(2027, 8, 1)
        s = _make_series(db, space, starts_at=starts, ends_at=starts + timedelta(days=90))
        opt = _make_series_option(
            db, space, s, sessions_per_week=spw, total_sessions=total,
            grants_pathway_id=practice.id,
        )
        run_backfill(db)
        db.expire(opt)

        legacy = resolve_intent_from_legacy(
            db, payment_option=opt,
            metadata_pathway_id=None, now=datetime.utcnow(),
        )
        grants = resolve_intent_from_grants(db, payment_option=opt)

        # Byte-level parity at the intent level.
        assert legacy.intent == grants.intent

        # And the concrete shape for the EMBODY contract:
        [ent] = grants.intent.entitlements
        [ap] = grants.intent.access_passes
        assert ent.pathway_id == practice.id
        assert ent.ends_at == s.ends_at
        assert ent.starts_at is None    # → applier uses NOW → immediate access
        assert ap.eligible_series_id == s.id
        assert ap.valid_from == s.starts_at
        assert ap.valid_until == s.ends_at
        assert ap.total_credits == total
        assert ap.credits_per_week == spw
        assert ap.grants_pathway_id == practice.id


# ---------------------------------------------------------------------------
# Dispatcher — grants-first vs legacy fallback
# ---------------------------------------------------------------------------


class TestDispatcher:
    def test_option_with_grants_uses_grant_resolver(self, db, make_space):
        """Outcome check: with a grant on the option, the
        dispatcher must call the grant resolver — proven by the
        entitlement resolving to the *grant's* target pathway,
        not the option's own ``pathway_id``."""
        space = make_space()
        pw_legacy = _make_pathway(db, space, title="LEGACY")
        pw_grant = _make_pathway(db, space, title="GRANT")
        opt = _make_pathway_option(db, space, pw_legacy)
        _add_pathway_grant(db, opt, pw_grant)
        opt = _reload_option_with_grants(db, opt)

        resolution = resolve_intent_for_option(
            db, payment_option=opt,
            metadata_pathway_id=pw_legacy.id, now=datetime.utcnow(),
        )
        [ent] = resolution.intent.entitlements
        # Grant path picked → target is the grant's pathway, not
        # the option's own ``pathway_id`` or the metadata fallback.
        assert ent.pathway_id == pw_grant.id
        assert ent.pathway_id != pw_legacy.id

    def test_option_without_grants_falls_back_to_legacy_resolver(
        self, db, make_space,
    ):
        """Outcome check: with no grants on the option, the
        dispatcher must call the legacy resolver, which produces
        an entitlement from the ``metadata_pathway_id`` fallback.

        The structured warning fired here is verified separately by
        ``test_fallback_warning_fires_in_fresh_runtime`` below —
        pytest's log-capture layer filters ``isEnabledFor(WARNING)``
        below WARNING regardless of level manipulation, so a
        subprocess-based check is the only reliable observer for
        the emitted warning."""
        space = make_space()
        pw = _make_pathway(db, space, title="Practice")
        opt = _make_pathway_option(db, space, pw)  # no grant rows
        assert list(opt.grants) == []

        resolution = resolve_intent_for_option(
            db, payment_option=opt,
            metadata_pathway_id=pw.id, now=datetime.utcnow(),
        )
        [ent] = resolution.intent.entitlements
        assert ent.pathway_id == pw.id

    def test_no_option_at_all_uses_legacy(self, db, make_space):
        """Legacy option-less purchase path (R.E.A.L. Journey). No
        PaymentOption → legacy resolver is used with the metadata
        pathway_id."""
        space = make_space()
        pw = _make_pathway(db, space, title="R.E.A.L.")

        resolution = resolve_intent_for_option(
            db, payment_option=None,
            metadata_pathway_id=pw.id, now=datetime.utcnow(),
        )
        [ent] = resolution.intent.entitlements
        assert ent.pathway_id == pw.id


# ---------------------------------------------------------------------------
# End-to-end through the webhook — grants-first cutover regression tests
# ---------------------------------------------------------------------------


def _fire_webhook(db, *, txn, payment_option, pathway_id=None):
    """Replay the Stripe checkout.session.completed handler with
    the minimum metadata a real Session would carry.

    ``pathway_id`` metadata is required by the webhook's metadata
    guard for any option whose ``attaches_to_kind != 'event_series'``.
    When the caller doesn't pass it and the option is not
    series-attached, default to the option's own ``pathway_id``
    (the pathway checkout endpoint always writes this in
    production Stripe metadata).
    """
    from app.webhooks.routes import _handle_checkout_completed
    metadata = {
        "transaction_id": txn.id,
        "payer_user_id": txn.payer_user_id,
        "space_id": txn.space_id,
        "payment_option_id": payment_option.id,
    }
    effective_pathway_id = pathway_id or (
        payment_option.pathway_id
        if payment_option.attaches_to_kind != "event_series"
        else None
    )
    if effective_pathway_id:
        metadata["pathway_id"] = effective_pathway_id
    session = {
        "id": txn.provider_checkout_session_id,
        "payment_status": "paid",
        "payment_intent": _uid("pi"),
        "metadata": metadata,
    }
    _handle_checkout_completed(session, db)


class TestGrantsFirstEndToEnd:
    def test_grants_take_precedence_over_legacy_fields(
        self, db, make_space, make_user,
    ):
        """The option's legacy shadow says pathway_A; the option's
        grant says pathway_B. Grants must win."""
        space = make_space()
        buyer = make_user()
        pw_legacy = _make_pathway(db, space, title="LEGACY")
        pw_grant = _make_pathway(db, space, title="GRANT")
        # Legacy fields point at pathway_A.
        opt = _make_pathway_option(
            db, space, pw_legacy,
            grants_pathway_id=pw_legacy.id,
        )
        # Grant points at pathway_B.
        _add_pathway_grant(db, opt, pw_grant)
        opt = _reload_option_with_grants(db, opt)
        txn = _make_txn(db, payer=buyer, space=space)

        _fire_webhook(
            db, txn=txn, payment_option=opt,
            pathway_id=pw_legacy.id,  # deliberate legacy "lie"
        )
        db.refresh(txn)

        # Fulfilment succeeded.
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        # Entitlement was created for the GRANT pathway, not the LEGACY one.
        ents = (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .all()
        )
        pathway_ids = {e.pathway_id for e in ents}
        assert pathway_ids == {pw_grant.id}
        assert pw_legacy.id not in pathway_ids

    def test_legacy_option_without_grants_still_fulfils(
        self, db, make_space, make_user,
    ):
        """Cutover safety net: an option that pre-dates the B2
        backfill (no grants) still fulfils through the legacy
        resolver end-to-end. The fallback warning firing is
        verified separately by
        ``test_fallback_warning_fires_in_fresh_runtime`` — pytest's
        log-capture layer filters WARNING records here regardless
        of level manipulation."""
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Practice")
        opt = _make_pathway_option(db, space, pw)  # no grants
        txn = _make_txn(db, payer=buyer, space=space)

        _fire_webhook(db, txn=txn, payment_option=opt, pathway_id=pw.id)
        db.refresh(txn)

        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        [ent] = (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .all()
        )
        assert ent.pathway_id == pw.id

    def test_multi_experience_atomicity_via_grants(
        self, db, make_space, make_user,
    ):
        """Option with two Pathway grants + one Series grant.
        Validation reports a missing target for one of the
        pathways → the whole bundle is blocked; no entitlements
        and no AccessPasses are written.

        The DB's B1 FK constraints prevent us from *actually*
        pointing a grant at a non-existent target (RESTRICT +
        FK trigger), which is exactly the property that makes
        production safe. To exercise the runtime's response to
        the "target missing at validation time" state, patch
        ``validate_intent`` to synthesise the error. The
        realistic in-DB variant is covered by
        ``TestFulfilmentStatusOnTransaction::test_blocked_when_validation_fails``
        (which uses a metadata pathway_id pointing at a ghost)."""
        from unittest.mock import patch
        from app.services.purchase_fulfilment import ValidationResult
        space = make_space()
        buyer = make_user()
        pw_stub = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw_stub)
        pw_a = _make_pathway(db, space, title="A")
        pw_b = _make_pathway(db, space, title="B")
        s_c = _make_series(db, space)
        _add_pathway_grant(db, opt, pw_a)
        _add_pathway_grant(db, opt, pw_b)
        _add_series_grant(db, opt, s_c, sessions_per_week=1, total_sessions=10)
        opt = _reload_option_with_grants(db, opt)
        txn = _make_txn(db, payer=buyer, space=space)

        # Simulate "target went missing between resolve and apply"
        # by patching the validator to fail. The webhook must
        # commit ``fulfilment_status='blocked'`` and write zero
        # downstream rows.
        with patch(
            "app.webhooks.routes.validate_intent",
            return_value=ValidationResult(
                errors=(f"pathway {pw_b.id!r} referenced by intent does not exist",),
            ),
        ):
            _fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)

        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.blocked
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

    def test_replay_after_repair_produces_no_duplicates_via_grants(
        self, db, make_space, make_user,
    ):
        """First webhook delivery is blocked (validation fails);
        the underlying issue is fixed; the second delivery flips
        blocked → applied with exactly the right row counts —
        no duplicates from the blocked first attempt.

        Same DB-safety caveat as
        ``test_multi_experience_atomicity_via_grants``: the real
        "stale grant" state can't be constructed through DML
        under the B1 FK constraints. Patch ``validate_intent``
        for the first attempt and then let the real validator
        run for the second."""
        from unittest.mock import patch
        from app.services.purchase_fulfilment import ValidationResult
        space = make_space()
        buyer = make_user()
        pw_stub = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw_stub)
        practice = _make_pathway(db, space, title="Practice")
        s = _make_series(db, space, starts_at=datetime(2027, 9, 1))
        _add_pathway_grant(db, opt, practice)
        _add_series_grant(
            db, opt, s, sessions_per_week=1, total_sessions=10,
        )
        opt = _reload_option_with_grants(db, opt)
        txn = _make_txn(db, payer=buyer, space=space)

        # First delivery: blocked (simulated missing target).
        with patch(
            "app.webhooks.routes.validate_intent",
            return_value=ValidationResult(
                errors=(f"event_series {s.id!r} referenced by intent does not exist",),
            ),
        ):
            _fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)
        assert txn.fulfilment_status == PaymentFulfilmentStatus.blocked
        # No downstream rows written yet.
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

        # Second delivery: real validator runs, everything is
        # present, bundle applies cleanly — one entitlement,
        # one AccessPass, no duplicates from the blocked attempt.
        _fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        assert (
            db.query(PathwayEntitlement)
            .filter(
                PathwayEntitlement.user_id == buyer.id,
                PathwayEntitlement.pathway_id == practice.id,
            )
            .count()
        ) == 1
        assert (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .count()
        ) == 1

    def test_multi_series_produces_independent_access_passes(
        self, db, make_space, make_user,
    ):
        """Two Series grants → two AccessPass rows with their own
        limits + windows. Each key is unique on
        (payment_transaction_id, eligible_series_id, eligible_pathway_id)."""
        space = make_space()
        buyer = make_user()
        pw_stub = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw_stub)
        s1 = _make_series(db, space, starts_at=datetime(2027, 1, 1))
        s2 = _make_series(db, space, starts_at=datetime(2027, 5, 1))
        _add_series_grant(db, opt, s1, sessions_per_week=1, total_sessions=8)
        _add_series_grant(db, opt, s2, sessions_per_week=2, total_sessions=20)
        opt = _reload_option_with_grants(db, opt)
        txn = _make_txn(db, payer=buyer, space=space)

        _fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied

        passes = (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .all()
        )
        assert len(passes) == 2
        by_series = {ap.eligible_series_id: ap for ap in passes}
        assert by_series[s1.id].total_credits == 8
        assert by_series[s1.id].credits_per_week == 1
        assert by_series[s1.id].valid_from == s1.starts_at
        assert by_series[s2.id].total_credits == 20
        assert by_series[s2.id].credits_per_week == 2
        assert by_series[s2.id].valid_from == s2.starts_at

    def test_multi_pathway_keeps_singular_entitlement_id_null(
        self, db, make_space, make_user,
    ):
        """Two Pathway grants → two entitlements, but the singular
        ``txn.entitlement_id`` pointer stays null (see B3 rule)."""
        space = make_space()
        buyer = make_user()
        pw_stub = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw_stub)
        pw_a = _make_pathway(db, space, title="A")
        pw_b = _make_pathway(db, space, title="B")
        _add_pathway_grant(db, opt, pw_a)
        _add_pathway_grant(db, opt, pw_b)
        opt = _reload_option_with_grants(db, opt)
        txn = _make_txn(db, payer=buyer, space=space)

        _fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        assert (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .count()
        ) == 2
        # Singular legacy pointer stays null — no honest way to pick.
        assert txn.entitlement_id is None

    def test_gathering_grant_blocks_fulfilment(
        self, db, make_space, make_user,
    ):
        """An option carrying a Gathering grant does not silently
        succeed — the resolver returns fatal_error → txn ends up
        succeeded + blocked."""
        from app.models.platform import Event
        space = make_space()
        buyer = make_user()
        pw_stub = _make_pathway(db, space, title="stub")
        opt = _make_pathway_option(db, space, pw_stub)
        e = Event(
            id=_uid("e"), space_id=space.id,
            created_by_id=space.creator_id,
            title="Workshop",
            starts_at=datetime.utcnow() + timedelta(days=14),
            ends_at=datetime.utcnow() + timedelta(days=14, hours=1),
            location_type="zoom", is_published=True, status="active",
            requires_booking=True, capacity=20,
            booking_access_type="included_with_collective",
            gathering_type="workshop", attendance_format="online",
        )
        db.add(e)
        db.flush()
        _add_gathering_grant(db, opt, e)
        opt = _reload_option_with_grants(db, opt)
        txn = _make_txn(db, payer=buyer, space=space)

        _fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)

        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.blocked
        # No fanout rows.
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


# ---------------------------------------------------------------------------
# Fresh-runtime subprocess check for the structured fallback warning
#
# pytest's log-capture plugin manipulates ``isEnabledFor(WARNING)`` in
# a way that makes intra-process caplog / direct-handler assertions
# unreliable for records emitted below the plugin's floor — same class
# of issue that motivated ``test_runtime_mapper_registration.py``.
# A fresh Python subprocess with normal ``logging.basicConfig(...)``
# observes the warning deterministically.
# ---------------------------------------------------------------------------


import subprocess
import sys
import textwrap
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_fallback_warning_fires_in_fresh_runtime():
    """Spawn a fresh interpreter, construct a grant-less
    PaymentOption in-memory, call the dispatcher, and assert the
    "falling back to legacy resolver" warning is emitted to
    stderr. Proves the runtime-visible operational signal exists
    even though pytest's log-capture layer can't observe it
    inside this process."""
    code = textwrap.dedent(
        """
        import logging, sys, uuid
        from datetime import datetime
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr, force=True)

        # Register every model the fulfilment path might touch.
        import app.models.user           # noqa: F401
        import app.models.platform       # noqa: F401
        import app.models.payment        # noqa: F401
        import app.models.payment_option # noqa: F401
        import app.models.payment_option_grant  # noqa: F401
        import app.models.payment_option_schedule  # noqa: F401
        import app.models.access_pass    # noqa: F401
        import app.models.creator_billing  # noqa: F401

        from app.core.database import SessionLocal
        from app.services.purchase_fulfilment import resolve_intent_for_option
        from app.models.platform import Space, Pathway, PathwayType
        from app.models.payment_option import (
            PaymentOption, PaymentOptionStatus, PaymentOptionType,
        )

        db = SessionLocal()
        try:
            space = db.query(Space).first()
            if space is None:
                print("SKIP: no space in DB", file=sys.stderr)
                sys.exit(0)
            pw = Pathway(
                id=f"pw_probe_{uuid.uuid4().hex[:6]}",
                space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:6]}",
                title="Probe", status="active", access_type="one_time",
                price_cents=20000,
                pathway_type=PathwayType.guided_experience,
            )
            db.add(pw); db.flush()
            opt = PaymentOption(
                id=f"po_probe_{uuid.uuid4().hex[:6]}",
                space_id=space.id, pathway_id=pw.id,
                attaches_to_kind="pathway", attaches_to_id=pw.id,
                name="probe", payment_type=PaymentOptionType.one_time,
                status=PaymentOptionStatus.draft,
                calculated_total_cents=0, currency="AUD",
            )
            db.add(opt); db.flush()
            resolve_intent_for_option(
                db, payment_option=opt,
                metadata_pathway_id=pw.id, now=datetime.utcnow(),
            )
        finally:
            db.rollback()
            db.close()
        """
    ).strip()

    import os
    env = {
        **os.environ,
        # The subprocess must talk to the same DB the parent
        # test process was pointed at (conftest overwrote
        # DATABASE_URL to fc_test at import time).
        "DATABASE_URL": os.environ["DATABASE_URL"],
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, (
        f"subprocess failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    # The structured warning must appear on stderr from the
    # subprocess. Names the option id and the fallback reason.
    assert "falling back to legacy resolver" in result.stderr, (
        f"expected fallback warning in stderr, got:\n{result.stderr}"
    )
    assert "PaymentOption po_probe_" in result.stderr


# ---------------------------------------------------------------------------
# Grant-readiness rule — pathway-attached term_pass options carry
# session limits that Pathway grants cannot represent, so the
# dispatcher must fall back to the legacy resolver even when
# grant rows exist for them.
# ---------------------------------------------------------------------------


class TestOptionGrantReadiness:
    """Direct unit tests of ``option_grant_readiness``."""

    def test_series_attached_option_is_ready(self, db, make_space):
        from app.services.purchase_fulfilment import option_grant_readiness
        space = make_space()
        s = _make_series(db, space)
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
        )
        ready, reason = option_grant_readiness(opt)
        assert ready is True
        assert reason is None

    def test_pathway_attached_one_time_option_is_ready(self, db, make_space):
        """A pathway-attached one_time option has no term_pass
        semantics → nothing to lose in the grant representation."""
        from app.services.purchase_fulfilment import option_grant_readiness
        space = make_space()
        pw = _make_pathway(db, space)
        opt = _make_pathway_option(db, space, pw)   # payment_type=one_time
        ready, reason = option_grant_readiness(opt)
        assert ready is True
        assert reason is None

    def test_pathway_attached_term_pass_is_not_ready(self, db, make_space):
        """The EMBODY-duplicate shape: pathway-attached term_pass
        with Series-style session fields. Legacy would emit an
        AccessPass; Pathway grant cannot carry those fields; so
        the option is not grant-ready."""
        from app.services.purchase_fulfilment import option_grant_readiness
        space = make_space()
        pw = _make_pathway(db, space)
        opt = _make_pathway_option(
            db, space, pw,
            payment_type=PaymentOptionType.term_pass,
            sessions_per_week=1, total_sessions=10,
            term_start_date=date(2026, 7, 1),
            term_end_date=date(2026, 9, 19),
        )
        ready, reason = option_grant_readiness(opt)
        assert ready is False
        assert reason and "sessions_per_week" in reason
        assert "total_sessions" in reason

    def test_pathway_attached_term_pass_with_only_end_date_still_not_ready(
        self, db, make_space,
    ):
        """A pathway-attached term_pass carrying only
        ``term_end_date`` (no session credits) is still not
        grant-ready — the legacy resolver's term_pass branch
        still emits an AccessPass row (credits nulled) that the
        grant resolver would omit entirely."""
        from app.services.purchase_fulfilment import option_grant_readiness
        space = make_space()
        pw = _make_pathway(db, space)
        opt = _make_pathway_option(
            db, space, pw,
            payment_type=PaymentOptionType.term_pass,
            term_end_date=date(2026, 9, 19),
        )
        ready, reason = option_grant_readiness(opt)
        assert ready is False
        assert reason and "term_pass" in reason

    def test_migration_to_series_attached_makes_option_ready(
        self, db, make_space,
    ):
        """Simulate the cleanup migration: reshape the option
        into a Series-attached one. Readiness re-evaluates to
        True automatically — no manual flag needed."""
        from app.services.purchase_fulfilment import option_grant_readiness
        space = make_space()
        pw = _make_pathway(db, space)
        s = _make_series(db, space)
        opt = _make_pathway_option(
            db, space, pw,
            payment_type=PaymentOptionType.term_pass,
            sessions_per_week=1, total_sessions=10,
            term_end_date=date(2026, 9, 19),
        )
        assert option_grant_readiness(opt)[0] is False   # baseline

        # Cleanup: reshape into a Series-attached term_pass.
        opt.attaches_to_kind = "event_series"
        opt.attaches_to_id = s.id
        db.flush()
        ready, reason = option_grant_readiness(opt)
        assert ready is True
        assert reason is None

    def test_clearing_legacy_term_pass_fields_makes_option_ready(
        self, db, make_space,
    ):
        """Alternative cleanup: keep the option pathway-attached
        but strip the term_pass semantics (change payment_type
        and clear credits). Readiness re-evaluates to True."""
        from app.services.purchase_fulfilment import option_grant_readiness
        space = make_space()
        pw = _make_pathway(db, space)
        opt = _make_pathway_option(
            db, space, pw,
            payment_type=PaymentOptionType.term_pass,
            sessions_per_week=1, total_sessions=10,
        )
        assert option_grant_readiness(opt)[0] is False

        opt.payment_type = PaymentOptionType.one_time
        opt.sessions_per_week = None
        opt.total_sessions = None
        db.flush()
        ready, reason = option_grant_readiness(opt)
        assert ready is True
        assert reason is None


class TestDispatcherRespectsReadiness:
    """Integration: the dispatcher picks the resolver based on
    readiness, not just on grant-row presence."""

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

    def test_series_attached_with_grants_uses_grant_resolver(
        self, db, make_space, make_user,
    ):
        """Grant-ready + has grants → grant resolver is picked.
        Verified by pointing legacy shadow to a distractor
        pathway and confirming the grant's pathway is what
        actually gets granted."""
        space = make_space()
        buyer = make_user()
        practice = _make_pathway(db, space, title="Practice")
        distractor = _make_pathway(db, space, title="DISTRACTOR")
        s = _make_series(db, space, starts_at=datetime(2027, 1, 1))
        opt = _make_series_option(
            db, space, s, sessions_per_week=1, total_sessions=10,
            # Legacy shadow points at distractor.
            grants_pathway_id=distractor.id,
        )
        # Backfill produces both grants; then rewrite the Pathway
        # grant to point at ``practice`` to prove the runtime
        # reads from grants, not shadow.
        run_backfill(db)
        db.expire(opt)
        (
            db.query(PaymentOptionGrant)
            .filter(PaymentOptionGrant.payment_option_id == opt.id,
                    PaymentOptionGrant.grant_kind == "pathway")
            .update({"pathway_id": practice.id})
        )
        db.flush()
        db.expire(opt)
        txn = _make_txn(db, payer=buyer, space=space)

        _fire_webhook(db, txn=txn, payment_option=opt)
        db.refresh(txn)

        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        # Grant-side pathway granted; legacy shadow's distractor was NOT.
        ents = (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .all()
        )
        pathway_ids = {e.pathway_id for e in ents}
        assert practice.id in pathway_ids
        assert distractor.id not in pathway_ids

    def test_pathway_attached_term_pass_falls_back_to_legacy_even_with_grants(
        self, db, make_space, make_user,
    ):
        """The EMBODY-duplicate case. The option has a grant row
        (Pathway grant with ``valid_until_override`` = term end)
        AND legacy Series-style session limits. Readiness must
        reject grants; the webhook must produce the FULL legacy
        outcome: PathwayEntitlement + AccessPass with credits.

        This is the correctness fix — a naive
        "grants-present → grants-authoritative" would have
        silently dropped the AccessPass."""
        space = make_space()
        buyer = make_user()
        practice = _make_pathway(db, space, title="Practice")
        opt = _make_pathway_option(
            db, space, practice,
            payment_type=PaymentOptionType.term_pass,
            sessions_per_week=2, total_sessions=20,
            term_start_date=date(2026, 7, 1),
            term_end_date=date(2026, 9, 19),
        )
        # Backfill will produce a Pathway grant with
        # valid_until_override derived from term_end_date.
        run_backfill(db)
        db.expire(opt)
        assert len(list(opt.grants)) == 1   # grants exist
        txn = _make_txn(db, payer=buyer, space=space)

        _fire_webhook(db, txn=txn, payment_option=opt, pathway_id=practice.id)
        db.refresh(txn)

        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        # PathwayEntitlement created (matches legacy shape).
        [ent] = (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .all()
        )
        assert ent.pathway_id == practice.id
        assert ent.ends_at == datetime(2026, 9, 19, 0, 0)
        # AND the AccessPass — this is the row the grant resolver
        # would have silently dropped.
        [ap] = (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .all()
        )
        assert ap.eligible_pathway_id == practice.id
        assert ap.eligible_series_id is None
        assert ap.total_credits == 20
        assert ap.credits_per_week == 2


# ---------------------------------------------------------------------------
# Warning-distinguishing subprocess check
#
# pytest's log-capture filters WARNING records in-process — same
# reason ``test_fallback_warning_fires_in_fresh_runtime`` uses a
# subprocess. Extend the same pattern to prove the dispatcher
# emits DIFFERENT warning messages for the two fallback reasons.
# ---------------------------------------------------------------------------


def test_fallback_warnings_distinguish_reason():
    """One subprocess per scenario. Two scenarios:

      (a) option with no grants           → "has no grants — …"
      (b) option with grants but not ready
                                          → "has grants but is not
                                             grant-ready — …"
    """
    import os
    code_no_grants = textwrap.dedent(
        """
        import logging, sys, uuid
        from datetime import datetime
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr, force=True)
        import app.models.user, app.models.platform, app.models.payment  # noqa
        import app.models.payment_option, app.models.payment_option_grant  # noqa
        import app.models.payment_option_schedule, app.models.access_pass  # noqa
        import app.models.creator_billing  # noqa
        from app.core.database import SessionLocal
        from app.services.purchase_fulfilment import resolve_intent_for_option
        from app.models.platform import Space, Pathway, PathwayType
        from app.models.payment_option import (
            PaymentOption, PaymentOptionStatus, PaymentOptionType,
        )
        db = SessionLocal()
        try:
            space = db.query(Space).first()
            pw = Pathway(
                id=f"pw_no_grants_{uuid.uuid4().hex[:6]}",
                space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:6]}",
                title="Probe", status="active", access_type="one_time",
                price_cents=1, pathway_type=PathwayType.guided_experience,
            )
            db.add(pw); db.flush()
            opt = PaymentOption(
                id=f"po_no_grants_{uuid.uuid4().hex[:6]}",
                space_id=space.id, pathway_id=pw.id,
                attaches_to_kind="pathway", attaches_to_id=pw.id,
                name="probe", payment_type=PaymentOptionType.one_time,
                status=PaymentOptionStatus.draft,
                calculated_total_cents=0, currency="AUD",
            )
            db.add(opt); db.flush()
            resolve_intent_for_option(
                db, payment_option=opt,
                metadata_pathway_id=pw.id, now=datetime.utcnow(),
            )
        finally:
            db.rollback(); db.close()
        """
    ).strip()

    code_not_ready = textwrap.dedent(
        """
        import logging, sys, uuid
        from datetime import date, datetime
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr, force=True)
        import app.models.user, app.models.platform, app.models.payment  # noqa
        import app.models.payment_option, app.models.payment_option_grant  # noqa
        import app.models.payment_option_schedule, app.models.access_pass  # noqa
        import app.models.creator_billing  # noqa
        from app.core.database import SessionLocal
        from app.services.purchase_fulfilment import resolve_intent_for_option
        from app.models.platform import Space, Pathway, PathwayType
        from app.models.payment_option import (
            PaymentOption, PaymentOptionStatus, PaymentOptionType,
        )
        from app.models.payment_option_grant import PaymentOptionGrant
        db = SessionLocal()
        try:
            space = db.query(Space).first()
            pw = Pathway(
                id=f"pw_not_ready_{uuid.uuid4().hex[:6]}",
                space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:6]}",
                title="Probe", status="active", access_type="one_time",
                price_cents=1, pathway_type=PathwayType.guided_experience,
            )
            db.add(pw); db.flush()
            # Pathway-attached term_pass carrying Series-style credits
            # — the EMBODY-duplicate shape. Grant-ready = False.
            opt = PaymentOption(
                id=f"po_not_ready_{uuid.uuid4().hex[:6]}",
                space_id=space.id, pathway_id=pw.id,
                attaches_to_kind="pathway", attaches_to_id=pw.id,
                name="probe", payment_type=PaymentOptionType.term_pass,
                status=PaymentOptionStatus.draft,
                sessions_per_week=1, total_sessions=10,
                term_end_date=date(2026, 9, 19),
                calculated_total_cents=0, currency="AUD",
            )
            db.add(opt); db.flush()
            # Add a Pathway grant so ``option.grants`` is non-empty
            # — otherwise we'd hit the "no grants" branch.
            db.add(PaymentOptionGrant(
                payment_option_id=opt.id,
                grant_kind="pathway", pathway_id=pw.id,
                valid_until_override=datetime(2026, 9, 19),
            ))
            db.flush()
            db.expire(opt)
            resolve_intent_for_option(
                db, payment_option=opt,
                metadata_pathway_id=pw.id, now=datetime.utcnow(),
            )
        finally:
            db.rollback(); db.close()
        """
    ).strip()

    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    r1 = subprocess.run(
        [sys.executable, "-c", code_no_grants],
        cwd=str(BACKEND_ROOT), env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert r1.returncode == 0, r1.stderr
    assert "has no grants" in r1.stderr
    assert "has grants but is not grant-ready" not in r1.stderr

    r2 = subprocess.run(
        [sys.executable, "-c", code_not_ready],
        cwd=str(BACKEND_ROOT), env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert r2.returncode == 0, r2.stderr
    assert "has grants but is not grant-ready" in r2.stderr
    assert "pathway-attached term_pass" in r2.stderr
    assert "has no grants" not in r2.stderr
