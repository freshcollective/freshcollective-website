"""B4B — unified ``POST /api/checkout`` endpoint.

Covers:

  * Shape validation — option must exist, be published, schedule
    belongs to it, schedule is published + pay_in_full.
  * Grant-based routing — Pathway-only, Series-only, Series +
    bundled Pathway, multi-Pathway, multi-Series, mixed all
    reach the shared paid checkout path.
  * EMBODY Awaken/Activate/Empower pay-in-full via the unified
    endpoint (Stripe mocked).
  * Free options — no Stripe call; ``PaymentTransaction`` is
    created succeeded+applied atomically; entitlements /
    AccessPasses are actually written.
  * Unsupported Gathering grant rejected **before** Stripe.
  * Finite instalment schedule rejected clearly.
  * Legacy compat wrappers still return their existing shapes.
  * Stripe webhook end-to-end for a unified-checkout session
    (no ``pathway_id`` / ``series_id`` metadata) fulfils via
    grants correctly.

Duplicate-purchase policy is intentionally permissive on the
unified endpoint — bundle-aware upgrade / re-purchase policy is
not yet defined. The legacy wrappers keep their existing single-
experience 409s.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe

from app.checkout.schemas import (
    GatheringSeriesCheckoutRequest,
    PathwayCheckoutRequest,
    UnifiedCheckoutRequest,
)
from app.core.config import settings
from app.models.access_pass import AccessPass, AccessPassType
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
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    Event,
    EventSeries,
    Pathway,
    PathwayEntitlement,
    PathwayType,
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
        access_type="free", price_cents=None,
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def _make_series(db, space, *, starts_at=None, ends_at=None) -> EventSeries:
    starts_at = starts_at or (datetime.utcnow() + timedelta(days=7))
    if ends_at is None:
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


def _make_option(
    db, space, *, name: str = "Awaken",
    payment_type: PaymentOptionType = PaymentOptionType.one_time,
    status: PaymentOptionStatus = PaymentOptionStatus.published,
    pathway_id: str | None = None,
) -> PaymentOption:
    """Grant-native option: legacy shadow columns filled to
    minimum viable values (``attaches_to_kind='pathway'`` +
    ``attaches_to_id=`` a real Pathway id), everything semantic
    lives on grants."""
    # ``attaches_to_id`` needs to point at a real pathway row —
    # unless the caller provides one, create a scratch one.
    scratch_pathway_id = pathway_id or _make_pathway(db, space, title=f"scratch-{name}").id
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, pathway_id=None,
        attaches_to_kind="pathway", attaches_to_id=scratch_pathway_id,
        name=name, payment_type=payment_type, status=status,
        calculated_total_cents=10000, currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _make_schedule(
    db, option, *,
    total_amount_cents: int = 10000,
    schedule_type: str = "pay_in_full",
    status: str = "published",
    installment_count: int | None = None,
    installment_amount_cents: int | None = None,
) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        payment_option_id=option.id,
        name="Pay in full", schedule_type=schedule_type, status=status,
        total_amount_cents=total_amount_cents,
        installment_amount_cents=installment_amount_cents,
        installment_count=installment_count,
        currency="AUD",
    )
    db.add(s)
    db.flush()
    return s


def _add_pathway_grant(db, option, pathway, *, valid_until_override=None):
    g = PaymentOptionGrant(
        payment_option_id=option.id, grant_kind="pathway",
        pathway_id=pathway.id, valid_until_override=valid_until_override,
    )
    db.add(g)
    db.flush()
    return g


def _add_series_grant(
    db, option, series, *,
    sessions_per_week=1, total_sessions=10,
    valid_from_override=None, valid_until_override=None,
):
    g = PaymentOptionGrant(
        payment_option_id=option.id, grant_kind="event_series",
        series_id=series.id,
        sessions_per_week=sessions_per_week, total_sessions=total_sessions,
        valid_from_override=valid_from_override,
        valid_until_override=valid_until_override,
    )
    db.add(g)
    db.flush()
    return g


def _add_gathering_grant(db, option, event):
    g = PaymentOptionGrant(
        payment_option_id=option.id, grant_kind="gathering",
        event_id=event.id,
    )
    db.add(g)
    db.flush()
    return g


def _reload(db, obj):
    """Force reload so ``.grants`` reflects newly-inserted rows."""
    db.expire(obj)
    return obj


@pytest.fixture
def stripe_configured(monkeypatch):
    """``settings.stripe_enabled`` is a computed property that
    checks BOTH secret + webhook secret. Set both so the enabled
    guard passes."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")


def _mock_stripe_session(session_id: str = "cs_test_x", url: str = "https://checkout.stripe.test/x"):
    return SimpleNamespace(id=session_id, url=url)


# ---------------------------------------------------------------------------
# Endpoint plumbing — direct-invocation tests (no TestClient) so DB
# state is visible under the pytest SAVEPOINT fixture.
# ---------------------------------------------------------------------------


def _call_unified(db, current_user, *, option, schedule,
                  success_url="https://ok/success",
                  cancel_url="https://ok/cancel"):
    from app.checkout.routes import create_unified_checkout_session
    return create_unified_checkout_session(
        UnifiedCheckoutRequest(
            payment_option_id=option.id,
            payment_option_schedule_id=schedule.id,
            success_url=success_url, cancel_url=cancel_url,
        ),
        current_user=current_user, db=db,
    )


# ---------------------------------------------------------------------------
# Request-shape validation
# ---------------------------------------------------------------------------


class TestUnifiedShapeValidation:
    def test_missing_option_returns_404(self, db, make_user, stripe_configured):
        from fastapi import HTTPException
        buyer = make_user()
        with pytest.raises(HTTPException) as e:
            _call_unified(db, buyer, option=SimpleNamespace(id="po_missing"),
                          schedule=SimpleNamespace(id="pos_missing"))
        assert e.value.status_code == 404

    def test_unpublished_option_returns_400(self, db, make_space, make_user, stripe_configured):
        from fastapi import HTTPException
        space = make_space()
        buyer = make_user()
        opt = _make_option(db, space, status=PaymentOptionStatus.draft)
        sched = _make_schedule(db, opt)
        with pytest.raises(HTTPException) as e:
            _call_unified(db, buyer, option=opt, schedule=sched)
        assert e.value.status_code == 400

    def test_schedule_from_different_option_returns_404(self, db, make_space, make_user, stripe_configured):
        from fastapi import HTTPException
        space = make_space()
        buyer = make_user()
        opt_a = _make_option(db, space, name="A")
        opt_b = _make_option(db, space, name="B")
        sched_b = _make_schedule(db, opt_b)
        with pytest.raises(HTTPException) as e:
            _call_unified(db, buyer, option=opt_a, schedule=sched_b)
        assert e.value.status_code == 404

    def test_unpublished_schedule_returns_400(self, db, make_space, make_user, stripe_configured):
        from fastapi import HTTPException
        space = make_space()
        buyer = make_user()
        opt = _make_option(db, space)
        sched = _make_schedule(db, opt, status="draft")
        with pytest.raises(HTTPException) as e:
            _call_unified(db, buyer, option=opt, schedule=sched)
        assert e.value.status_code == 400

    def test_recurring_instalments_invalid_schedule_returns_422(
        self, db, make_space, make_user, stripe_configured,
    ):
        """FIP2 removed the blanket 503 for recurring_installments.

        A recurring schedule missing cadence fields
        (``stripe_interval`` / ``stripe_interval_count``) now fails
        finite-plan validation with 422 instead of the pre-FIP2 503.
        A validly-shaped recurring schedule reaches the FIP2 setup
        path; that happy path is covered by
        ``tests/test_finite_plan_start.py``.
        """
        from fastapi import HTTPException
        space = make_space()
        buyer = make_user()
        opt = _make_option(db, space)
        sched = _make_schedule(
            db, opt, schedule_type="recurring_installments",
            installment_amount_cents=1000, installment_count=10,
        )
        with pytest.raises(HTTPException) as e:
            _call_unified(db, buyer, option=opt, schedule=sched)
        assert e.value.status_code == 422
        detail = e.value.detail
        assert isinstance(detail, dict)
        assert "stripe_interval" in " ".join(detail.get("errors", []))

    def test_manual_schedule_returns_400(self, db, make_space, make_user, stripe_configured):
        from fastapi import HTTPException
        space = make_space()
        buyer = make_user()
        opt = _make_option(db, space)
        sched = _make_schedule(db, opt, schedule_type="manual")
        with pytest.raises(HTTPException) as e:
            _call_unified(db, buyer, option=opt, schedule=sched)
        assert e.value.status_code == 400


# ---------------------------------------------------------------------------
# Grant-based routing — every supported grant shape reaches Stripe
# ---------------------------------------------------------------------------


class TestUnifiedGrantShapes:
    def test_pathway_only_option(
        self, db, make_space, make_user, stripe_configured,
    ):
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Solo Pathway")
        opt = _make_option(db, space)
        _add_pathway_grant(db, opt, pw)
        _reload(db, opt)
        sched = _make_schedule(db, opt)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_pw_only")
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        assert res.free is False
        assert res.checkout_url == "https://checkout.stripe.test/x"
        # Stripe metadata for unified checkout: no pathway_id / series_id.
        meta = m.call_args.kwargs["metadata"]
        assert "pathway_id" not in meta
        assert "series_id" not in meta
        assert meta["payment_option_id"] == opt.id
        assert meta["payment_option_schedule_id"] == sched.id

    def test_series_only_option(
        self, db, make_space, make_user, stripe_configured,
    ):
        space = make_space()
        buyer = make_user()
        s = _make_series(db, space)
        opt = _make_option(db, space)
        _add_series_grant(db, opt, s, sessions_per_week=1, total_sessions=10)
        _reload(db, opt)
        sched = _make_schedule(db, opt)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_series_only")
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        assert res.free is False
        # Ledger type: generic PaymentOption purchase — the option's
        # grants (not the ledger classification) are the source of
        # truth for what was granted.
        txn = db.query(PaymentTransaction).filter(PaymentTransaction.id == res.transaction_id).one()
        assert txn.transaction_type == PaymentTransactionType.member_payment_option_purchase

    def test_series_plus_bundled_pathway(
        self, db, make_space, make_user, stripe_configured,
    ):
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Bundled")
        s = _make_series(db, space)
        opt = _make_option(db, space)
        _add_series_grant(db, opt, s, sessions_per_week=1, total_sessions=10)
        _add_pathway_grant(db, opt, pw, valid_until_override=s.ends_at)
        _reload(db, opt)
        sched = _make_schedule(db, opt)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_series_plus_pw")
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        assert res.free is False
        txn = db.query(PaymentTransaction).filter(PaymentTransaction.id == res.transaction_id).one()
        # Generic PaymentOption purchase — "primary grant"
        # classification would embed an incorrect assumption for
        # multi-experience options.
        assert txn.transaction_type == PaymentTransactionType.member_payment_option_purchase

    def test_multi_pathway_option(
        self, db, make_space, make_user, stripe_configured,
    ):
        space = make_space()
        buyer = make_user()
        pw_a = _make_pathway(db, space, title="A")
        pw_b = _make_pathway(db, space, title="B")
        opt = _make_option(db, space)
        _add_pathway_grant(db, opt, pw_a)
        _add_pathway_grant(db, opt, pw_b)
        _reload(db, opt)
        sched = _make_schedule(db, opt)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_multi_pw")
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        assert res.free is False

    def test_multi_series_option(
        self, db, make_space, make_user, stripe_configured,
    ):
        space = make_space()
        buyer = make_user()
        s1 = _make_series(db, space)
        s2 = _make_series(db, space, starts_at=datetime.utcnow() + timedelta(days=100))
        opt = _make_option(db, space)
        _add_series_grant(db, opt, s1, sessions_per_week=1, total_sessions=8)
        _add_series_grant(db, opt, s2, sessions_per_week=2, total_sessions=20)
        _reload(db, opt)
        sched = _make_schedule(db, opt)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_multi_series")
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        assert res.free is False

    def test_mixed_pathways_and_series(
        self, db, make_space, make_user, stripe_configured,
    ):
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space)
        s = _make_series(db, space)
        opt = _make_option(db, space)
        _add_pathway_grant(db, opt, pw)
        _add_series_grant(db, opt, s, sessions_per_week=1, total_sessions=10)
        _reload(db, opt)
        sched = _make_schedule(db, opt)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_mixed")
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        assert res.free is False


# ---------------------------------------------------------------------------
# EMBODY Awaken / Activate / Empower via unified endpoint (Stripe mocked)
# ---------------------------------------------------------------------------


class TestEmbodyPayInFullViaUnifiedEndpoint:
    # Distinct prices per tier ensure a wrong-schedule selection
    # would be detectable (Awaken $200 / Activate $340 / Empower
    # $420 — matches the production tier ladder).
    @pytest.mark.parametrize(
        "name,spw,total,price_cents",
        [
            ("Awaken",   1, 10, 20000),
            ("Activate", 2, 20, 34000),
            ("Empower",  3, 30, 42000),
        ],
    )
    def test_tier(self, db, make_space, make_user, stripe_configured, name, spw, total, price_cents):
        space = make_space()
        buyer = make_user()
        practice = _make_pathway(db, space, title="The EMBODY Practice")
        starts = datetime.utcnow() + timedelta(days=30)
        s = _make_series(db, space, starts_at=starts, ends_at=starts + timedelta(days=90))
        opt = _make_option(db, space, name=name)
        _add_series_grant(db, opt, s, sessions_per_week=spw, total_sessions=total)
        _add_pathway_grant(db, opt, practice, valid_until_override=s.ends_at)
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=price_cents)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session(f"cs_{name.lower()}")
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        assert res.free is False
        # Product name defaults to the option's name (no pathway/
        # series naming baked in — grants-first).
        pdata = m.call_args.kwargs["line_items"][0]["price_data"]["product_data"]
        assert pdata["name"] == name
        # Stripe unit_amount matches the selected schedule's price.
        assert m.call_args.kwargs["line_items"][0]["price_data"]["unit_amount"] == price_cents
        # Metadata slim — no pathway_id or series_id.
        meta = m.call_args.kwargs["metadata"]
        assert "pathway_id" not in meta
        assert "series_id" not in meta
        # Txn created pending with the generic classification and
        # the correct price recorded on the ledger.
        txn = db.query(PaymentTransaction).filter(PaymentTransaction.id == res.transaction_id).one()
        assert txn.status == PaymentTransactionStatus.pending
        assert txn.fulfilment_status == PaymentFulfilmentStatus.pending
        assert txn.transaction_type == PaymentTransactionType.member_payment_option_purchase
        assert txn.gross_amount_cents == price_cents


# ---------------------------------------------------------------------------
# Free option — no Stripe; fulfilment applies immediately
# ---------------------------------------------------------------------------


class TestFreeOption:
    def test_free_pathway_option(self, db, make_space, make_user, stripe_configured):
        """Zero-price pay-in-full option → no Stripe call; the
        entitlement is created immediately; txn is succeeded +
        applied."""
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Free Pathway")
        opt = _make_option(
            db, space, payment_type=PaymentOptionType.free,
        )
        _add_pathway_grant(db, opt, pw)
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=0)

        with patch("stripe.checkout.Session.create") as m:
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        assert m.called is False   # Stripe never touched
        assert res.free is True
        assert res.checkout_url == "https://ok/success"

        # Txn: succeeded + applied, provider=manual, gross=0,
        # generic classification.
        txn = db.query(PaymentTransaction).filter(PaymentTransaction.id == res.transaction_id).one()
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        assert txn.payment_provider == PaymentProvider.manual
        assert txn.gross_amount_cents == 0
        assert txn.provider_checkout_session_id is None
        assert txn.transaction_type == PaymentTransactionType.member_payment_option_purchase
        # Real entitlement written.
        [ent] = (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .all()
        )
        assert ent.pathway_id == pw.id

    def test_free_series_plus_pathway_option(
        self, db, make_space, make_user, stripe_configured,
    ):
        """A free bundled option → both entitlement AND
        AccessPass created atomically."""
        space = make_space()
        buyer = make_user()
        practice = _make_pathway(db, space, title="Practice")
        starts = datetime.utcnow() + timedelta(days=7)
        s = _make_series(db, space, starts_at=starts, ends_at=starts + timedelta(days=90))
        opt = _make_option(
            db, space, payment_type=PaymentOptionType.free,
        )
        _add_series_grant(db, opt, s, sessions_per_week=1, total_sessions=10)
        _add_pathway_grant(db, opt, practice, valid_until_override=s.ends_at)
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=0)

        with patch("stripe.checkout.Session.create") as m:
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        assert m.called is False
        assert res.free is True

        txn = db.query(PaymentTransaction).filter(PaymentTransaction.id == res.transaction_id).one()
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        # Both grants materialised.
        assert (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id, PathwayEntitlement.pathway_id == practice.id)
            .count()
        ) == 1
        [ap] = (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .all()
        )
        assert ap.eligible_series_id == s.id
        assert ap.credits_per_week == 1
        assert ap.total_credits == 10

    def test_free_option_with_invalid_grant_rejects_before_writing(
        self, db, make_space, make_user, stripe_configured,
    ):
        """Free option whose grant references a Gathering →
        rejected BEFORE any txn is inserted."""
        from fastapi import HTTPException
        space = make_space()
        buyer = make_user()
        e = Event(
            id=_uid("e"), space_id=space.id,
            created_by_id=space.creator_id, title="Workshop",
            starts_at=datetime.utcnow() + timedelta(days=14),
            ends_at=datetime.utcnow() + timedelta(days=14, hours=1),
            location_type="zoom", is_published=True, status="active",
            requires_booking=True, capacity=20,
            booking_access_type="included_with_collective",
            gathering_type="workshop", attendance_format="online",
        )
        db.add(e); db.flush()
        opt = _make_option(db, space, payment_type=PaymentOptionType.free)
        _add_gathering_grant(db, opt, e)
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=0)

        pre_txn_count = db.query(PaymentTransaction).count()
        with pytest.raises(HTTPException) as e_ctx:
            _call_unified(db, buyer, option=opt, schedule=sched)
        # 400 — refused before any writes.
        assert e_ctx.value.status_code == 400
        assert db.query(PaymentTransaction).count() == pre_txn_count


# ---------------------------------------------------------------------------
# Unsupported Gathering grant rejected before payment
# ---------------------------------------------------------------------------


class TestGatheringGrantSafety:
    def test_paid_option_with_gathering_grant_rejected_before_stripe(
        self, db, make_space, make_user, stripe_configured,
    ):
        from fastapi import HTTPException
        space = make_space()
        buyer = make_user()
        e = Event(
            id=_uid("e"), space_id=space.id,
            created_by_id=space.creator_id, title="Workshop",
            starts_at=datetime.utcnow() + timedelta(days=14),
            ends_at=datetime.utcnow() + timedelta(days=14, hours=1),
            location_type="zoom", is_published=True, status="active",
            requires_booking=True, capacity=20,
            booking_access_type="included_with_collective",
            gathering_type="workshop", attendance_format="online",
        )
        db.add(e); db.flush()
        opt = _make_option(db, space)
        _add_gathering_grant(db, opt, e)
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=4500)

        pre_txn_count = db.query(PaymentTransaction).count()
        with patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as ctx:
                _call_unified(db, buyer, option=opt, schedule=sched)
        assert ctx.value.status_code == 400
        assert m.called is False   # Stripe never touched
        assert db.query(PaymentTransaction).count() == pre_txn_count


# ---------------------------------------------------------------------------
# Legacy compat wrappers preserve behaviour
# ---------------------------------------------------------------------------


class TestLegacyWrappersUnchanged:
    def test_pathway_wrapper_still_returns_checkout_url(
        self, db, make_space, make_user, stripe_configured,
    ):
        from app.checkout.routes import create_pathway_checkout_session
        space = make_space()
        buyer = make_user()
        # Legacy pathway wrapper accepts option-less requests
        # against a pathway carrying its own price.
        pw = Pathway(
            id=_uid("pw"), space_id=space.id,
            slug=f"pw-{uuid.uuid4().hex[:8]}", title="Legacy path",
            status="active", access_type="one_time", price_cents=15000,
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pw); db.flush()

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_legacy_pw")
            res = create_pathway_checkout_session(
                PathwayCheckoutRequest(
                    pathway_id=pw.id,
                    success_url="https://ok/s", cancel_url="https://ok/c",
                ),
                current_user=buyer, db=db,
            )
        assert res.checkout_url == "https://checkout.stripe.test/x"
        # Legacy metadata still carries pathway_id.
        meta = m.call_args.kwargs["metadata"]
        assert meta["pathway_id"] == pw.id
        # And txn linked to the pathway.
        [txn] = db.query(PaymentTransaction).filter(PaymentTransaction.provider_checkout_session_id == "cs_legacy_pw").all()
        assert txn.pathway_id == pw.id

    def test_pathway_wrapper_duplicate_entitlement_still_409s(
        self, db, make_space, make_user, stripe_configured,
    ):
        from fastapi import HTTPException
        from app.checkout.routes import create_pathway_checkout_session
        from app.models.platform import EntitlementStatus, PathwayEntitlement
        space = make_space()
        buyer = make_user()
        pw = Pathway(
            id=_uid("pw"), space_id=space.id,
            slug=f"pw-{uuid.uuid4().hex[:8]}", title="Owned",
            status="active", access_type="one_time", price_cents=15000,
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pw)
        db.add(PathwayEntitlement(
            id=_uid("ent"), user_id=buyer.id, space_id=space.id,
            pathway_id=pw.id, source="one_time_purchase",
            status=EntitlementStatus.active,
            starts_at=datetime.utcnow() - timedelta(days=1),
        ))
        db.flush()

        with pytest.raises(HTTPException) as e:
            create_pathway_checkout_session(
                PathwayCheckoutRequest(
                    pathway_id=pw.id,
                    success_url="https://ok/s", cancel_url="https://ok/c",
                ),
                current_user=buyer, db=db,
            )
        assert e.value.status_code == 409

    def test_series_wrapper_still_returns_checkout_url(
        self, db, make_space, make_user, stripe_configured,
    ):
        from app.checkout.routes import create_gathering_series_checkout_session
        space = make_space()
        buyer = make_user()
        s = _make_series(db, space)
        # Legacy series wrapper expects an option attached to
        # this specific Series via legacy shadow columns.
        opt = PaymentOption(
            id=_uid("po"), space_id=space.id,
            pathway_id=None,
            attaches_to_kind="event_series", attaches_to_id=s.id,
            name="Standard", payment_type=PaymentOptionType.term_pass,
            status=PaymentOptionStatus.published,
            calculated_total_cents=45000, currency="AUD",
        )
        db.add(opt); db.flush()
        sched = _make_schedule(db, opt, total_amount_cents=45000)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_legacy_series")
            res = create_gathering_series_checkout_session(
                GatheringSeriesCheckoutRequest(
                    series_id=s.id, payment_option_id=opt.id,
                    payment_option_schedule_id=sched.id,
                    success_url="https://ok/s", cancel_url="https://ok/c",
                ),
                current_user=buyer, db=db,
            )
        assert res.checkout_url == "https://checkout.stripe.test/x"
        meta = m.call_args.kwargs["metadata"]
        assert meta["series_id"] == s.id
        assert "pathway_id" not in meta
        assert meta["payment_option_id"] == opt.id


# ---------------------------------------------------------------------------
# Webhook end-to-end for a unified-checkout session
# ---------------------------------------------------------------------------


class TestWebhookEndToEndAfterUnifiedCheckout:
    def test_series_pass_via_unified_webhook_flow(
        self, db, make_space, make_user, stripe_configured,
    ):
        """Unified checkout → Stripe → webhook → fulfilment.
        The Stripe Session metadata for a unified checkout has
        NO ``pathway_id`` / ``series_id`` — the webhook must
        still fulfil correctly from the option's grants."""
        from app.webhooks.routes import _handle_checkout_completed
        space = make_space()
        buyer = make_user()
        s = _make_series(db, space)
        practice = _make_pathway(db, space, title="Practice")
        opt = _make_option(db, space, name="Awaken")
        _add_series_grant(db, opt, s, sessions_per_week=1, total_sessions=10)
        _add_pathway_grant(db, opt, practice, valid_until_override=s.ends_at)
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=60000)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_unified_e2e")
            res = _call_unified(db, buyer, option=opt, schedule=sched)

        # Simulate Stripe delivering the completed session with the
        # slim metadata the unified endpoint wrote.
        stripe_metadata = m.call_args.kwargs["metadata"]
        assert "pathway_id" not in stripe_metadata

        _handle_checkout_completed(
            {
                "id": "cs_unified_e2e",
                "payment_status": "paid",
                "payment_intent": "pi_test",
                "metadata": stripe_metadata,
            },
            db,
        )
        txn = db.query(PaymentTransaction).filter(PaymentTransaction.id == res.transaction_id).one()
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        [ent] = (
            db.query(PathwayEntitlement)
            .filter(
                PathwayEntitlement.user_id == buyer.id,
                PathwayEntitlement.pathway_id == practice.id,
            )
            .all()
        )
        assert ent.ends_at == s.ends_at
        [ap] = (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn.id)
            .all()
        )
        assert ap.eligible_series_id == s.id
        assert ap.total_credits == 10
        assert ap.credits_per_week == 1


# ---------------------------------------------------------------------------
# Generic ledger classification — every shape gets the same type
# ---------------------------------------------------------------------------


class TestUnifiedTransactionTypeIsGeneric:
    """Every shape purchased through the unified endpoint records
    the ledger row as ``member_payment_option_purchase`` — the
    option's grants (not the ledger classification) tell the
    reader what was granted."""

    @pytest.mark.parametrize("shape", [
        "pathway_only", "series_only", "series_plus_pathway",
        "multi_pathway", "multi_series", "mixed",
    ])
    def test_shape_uses_generic_type(
        self, db, make_space, make_user, stripe_configured, shape,
    ):
        space = make_space()
        buyer = make_user()
        opt = _make_option(db, space)

        if shape == "pathway_only":
            _add_pathway_grant(db, opt, _make_pathway(db, space))
        elif shape == "series_only":
            _add_series_grant(db, opt, _make_series(db, space))
        elif shape == "series_plus_pathway":
            s = _make_series(db, space)
            _add_series_grant(db, opt, s)
            _add_pathway_grant(db, opt, _make_pathway(db, space),
                               valid_until_override=s.ends_at)
        elif shape == "multi_pathway":
            _add_pathway_grant(db, opt, _make_pathway(db, space, title="A"))
            _add_pathway_grant(db, opt, _make_pathway(db, space, title="B"))
        elif shape == "multi_series":
            _add_series_grant(db, opt, _make_series(db, space))
            _add_series_grant(db, opt, _make_series(
                db, space, starts_at=datetime.utcnow() + timedelta(days=200)))
        elif shape == "mixed":
            _add_pathway_grant(db, opt, _make_pathway(db, space))
            _add_series_grant(db, opt, _make_series(db, space))
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=5000)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session(f"cs_{shape}")
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id).one()
        assert txn.transaction_type == (
            PaymentTransactionType.member_payment_option_purchase
        ), f"shape={shape}"


# ---------------------------------------------------------------------------
# Same-option duplicate-purchase guard
# ---------------------------------------------------------------------------


class TestSameOptionDuplicateGuard:
    """Guard scope: block a second purchase of the *same* Payment
    Option while at least one grant it produced is still actively
    providing access. Never block different options, expired
    grants, or historic failed/pending purchases."""

    def test_series_option_repurchase_blocked_while_pass_active(
        self, db, make_space, make_user, stripe_configured,
    ):
        from fastapi import HTTPException
        space = make_space()
        buyer = make_user()
        s = _make_series(db, space)
        opt = _make_option(db, space)
        _add_series_grant(db, opt, s, sessions_per_week=1, total_sessions=10)
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=30000)

        # First purchase → captured via webhook path (mock Stripe +
        # manually simulate the AccessPass write the fulfilment
        # service would perform).
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_first")
            first = _call_unified(db, buyer, option=opt, schedule=sched)
        # Simulate the AccessPass row the webhook fulfilment would
        # write on payment success (Rule A target).
        db.add(AccessPass(
            id=_uid("ap"), user_id=buyer.id, space_id=space.id,
            payment_transaction_id=first.transaction_id,
            payment_option_id=opt.id,
            payment_option_schedule_id=sched.id,
            pass_type=AccessPassType.term_pass, status="active",
            valid_from=datetime.utcnow() - timedelta(days=1),
            valid_until=datetime.utcnow() + timedelta(days=90),
            eligible_series_id=s.id,
        ))
        db.flush()

        # Second attempt on the same option must 409.
        with pytest.raises(HTTPException) as e:
            _call_unified(db, buyer, option=opt, schedule=sched)
        assert e.value.status_code == 409

    def test_pathway_option_repurchase_blocked_when_paid_previously(
        self, db, make_space, make_user, stripe_configured,
    ):
        """Rule B — paid Pathway-only purchase links back via
        ``provider_checkout_session_id`` on both the txn and the
        entitlement it produced."""
        from fastapi import HTTPException
        from app.models.platform import PathwayEntitlement, EntitlementStatus
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Pathway-only")
        opt = _make_option(db, space)
        _add_pathway_grant(db, opt, pw)
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=15000)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_paid_pw")
            first = _call_unified(db, buyer, option=opt, schedule=sched)
        # Flip the pending txn to succeeded and add the
        # PathwayEntitlement the webhook would write (session_id
        # matches the txn's provider_checkout_session_id).
        first_txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == first.transaction_id).one()
        first_txn.status = PaymentTransactionStatus.succeeded
        first_txn.fulfilment_status = PaymentFulfilmentStatus.applied
        db.add(PathwayEntitlement(
            id=_uid("ent"), user_id=buyer.id, space_id=space.id,
            pathway_id=pw.id, source="one_time_purchase",
            status=EntitlementStatus.active,
            starts_at=datetime.utcnow() - timedelta(hours=1),
            stripe_checkout_session_id=first_txn.provider_checkout_session_id,
        ))
        db.flush()

        with pytest.raises(HTTPException) as e:
            _call_unified(db, buyer, option=opt, schedule=sched)
        assert e.value.status_code == 409

    def test_free_single_pathway_repurchase_blocked_via_singular_pointer(
        self, db, make_space, make_user, stripe_configured,
    ):
        """Rule C — free single-Pathway purchase populates
        ``txn.entitlement_id`` via ``_link_singular_entitlement``."""
        from fastapi import HTTPException
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Free single")
        opt = _make_option(db, space, payment_type=PaymentOptionType.free)
        _add_pathway_grant(db, opt, pw)
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=0)

        _call_unified(db, buyer, option=opt, schedule=sched)

        # Second call → 409, before any second txn is written.
        pre_count = db.query(PaymentTransaction).count()
        with pytest.raises(HTTPException) as e:
            _call_unified(db, buyer, option=opt, schedule=sched)
        assert e.value.status_code == 409
        assert db.query(PaymentTransaction).count() == pre_count

    def test_different_option_purchase_not_blocked(
        self, db, make_space, make_user, stripe_configured,
    ):
        """Awaken already held → Empower still purchasable.
        Guard is same-option only, never sibling-tier."""
        space = make_space()
        buyer = make_user()
        s = _make_series(db, space)
        awaken = _make_option(db, space, name="Awaken")
        _add_series_grant(db, awaken, s, sessions_per_week=1, total_sessions=10)
        _reload(db, awaken)
        empower = _make_option(db, space, name="Empower")
        _add_series_grant(db, empower, s, sessions_per_week=3, total_sessions=30)
        _reload(db, empower)
        empower_sched = _make_schedule(db, empower, total_amount_cents=42000)

        # Pretend the buyer already has an active Awaken pass.
        db.add(AccessPass(
            id=_uid("ap"), user_id=buyer.id, space_id=space.id,
            payment_transaction_id=None,
            payment_option_id=awaken.id,
            pass_type=AccessPassType.term_pass, status="active",
            valid_from=datetime.utcnow() - timedelta(days=1),
            valid_until=datetime.utcnow() + timedelta(days=90),
            eligible_series_id=s.id,
        ))
        db.flush()

        # Empower purchase must proceed.
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_empower")
            res = _call_unified(db, buyer, option=empower, schedule=empower_sched)
        assert res.free is False

    def test_expired_pass_does_not_block_repurchase(
        self, db, make_space, make_user, stripe_configured,
    ):
        """Same option, but the previous pass ``valid_until`` is
        in the past → guard is silent."""
        space = make_space()
        buyer = make_user()
        s = _make_series(db, space)
        opt = _make_option(db, space)
        _add_series_grant(db, opt, s, sessions_per_week=1, total_sessions=10)
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=30000)

        db.add(AccessPass(
            id=_uid("ap"), user_id=buyer.id, space_id=space.id,
            payment_transaction_id=None,
            payment_option_id=opt.id,
            pass_type=AccessPassType.term_pass, status="active",
            valid_from=datetime.utcnow() - timedelta(days=200),
            valid_until=datetime.utcnow() - timedelta(days=30),
            eligible_series_id=s.id,
        ))
        db.flush()

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_after_expiry")
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        assert res.free is False

    def test_prior_pending_or_failed_txn_does_not_block(
        self, db, make_space, make_user, stripe_configured,
    ):
        """A pending/failed txn that never produced access grants
        must not defeat the guard for a fresh purchase."""
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Fresh attempt")
        opt = _make_option(db, space)
        _add_pathway_grant(db, opt, pw)
        _reload(db, opt)
        sched = _make_schedule(db, opt, total_amount_cents=15000)

        # Historic failed txn with a session id but NO entitlement
        # written for it — the buyer never gained access.
        db.add(PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.failed,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=buyer.id, space_id=space.id,
            currency="AUD", gross_amount_cents=15000,
            platform_fee_basis_points=800, platform_fee_cents=1200,
            net_creator_amount_cents=13800, net_platform_amount_cents=1200,
            provider_checkout_session_id="cs_historic_failed",
            payment_option_id=opt.id,
            payment_option_schedule_id=sched.id,
            payout_status=PayoutStatus.not_applicable,
            stripe_mode="test",
        ))
        db.flush()

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_fresh")
            res = _call_unified(db, buyer, option=opt, schedule=sched)
        assert res.free is False
