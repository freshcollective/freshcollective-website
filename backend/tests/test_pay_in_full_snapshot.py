"""Phase 1 — pay-in-full grants snapshot end-to-end.

The behavioural contract:

* ``orchestrate_paid_checkout`` writes a JSON grants snapshot onto the
  ``PaymentTransaction`` at checkout-session creation.
* The Stripe webhook (``_handle_checkout_completed``) prefers the
  snapshot over a live-DB resolve when the row carries one — so a
  Creator edit to the Payment Option's grants between "buyer clicked
  Pay" and the webhook cannot silently alter what the purchase
  grants.
* When the snapshot is absent (pre-migration rows or free-path), the
  webhook falls back to ``resolve_intent_for_option`` for
  backwards-compat.
* A malformed snapshot is not silently swallowed — the webhook marks
  the fulfilment ``blocked`` so a re-delivery after operator fix can
  retry.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.checkout.schemas import UnifiedCheckoutRequest
from app.core.config import settings
from app.models.access_pass import AccessPass
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentTransaction,
    PaymentTransactionStatus,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    Pathway,
    PathwayEntitlement,
    PathwayType,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_pathway(db, space, *, title="Test Pathway") -> Pathway:
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


def _make_option(db, space, *, name="Awaken", pathway=None) -> PaymentOption:
    scratch_pathway_id = (pathway or _make_pathway(db, space, title=f"scratch-{name}")).id
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, pathway_id=None,
        attaches_to_kind="pathway", attaches_to_id=scratch_pathway_id,
        name=name, payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=20000, currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _make_schedule(db, option, *, total=20000) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        payment_option_id=option.id,
        name="Pay in full", schedule_type="pay_in_full", status="published",
        total_amount_cents=total, currency="AUD",
    )
    db.add(s)
    db.flush()
    return s


def _add_pathway_grant(db, option, pathway):
    g = PaymentOptionGrant(
        payment_option_id=option.id, grant_kind="pathway",
        pathway_id=pathway.id,
    )
    db.add(g)
    db.flush()
    return g


def _mock_stripe_session(session_id="cs_test_snapshot"):
    return SimpleNamespace(
        id=session_id,
        url="https://checkout.stripe.test/x",
    )


@pytest.fixture
def stripe_configured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")


def _call_unified(db, buyer, *, option, schedule):
    from app.checkout.routes import create_unified_checkout_session
    return create_unified_checkout_session(
        UnifiedCheckoutRequest(
            payment_option_id=option.id,
            payment_option_schedule_id=schedule.id,
            success_url="https://ok/s", cancel_url="https://ok/c",
        ),
        current_user=buyer, db=db,
    )


class TestSnapshotIsWrittenAtCheckout:
    def test_pathway_grant_snapshot_is_serialised(
        self, db, make_space, make_user, stripe_configured,
    ):
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="EMBODY Awaken pathway")
        opt = _make_option(db, space, name="Awaken", pathway=pw)
        _add_pathway_grant(db, opt, pw)
        db.expire(opt)
        sched = _make_schedule(db, opt)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_snapshot_1")
            res = _call_unified(db, buyer, option=opt, schedule=sched)

        txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.id == res.transaction_id)
            .one()
        )
        snap = txn.snapshot_grants_json
        assert snap is not None
        assert snap["version"] == 1
        pathway_ids = [e["pathway_id"] for e in snap["entitlements"]]
        assert pw.id in pathway_ids


class TestSnapshotIsMandatoryPreStripe:
    """After the tightening: snapshot creation is mandatory for new
    checkouts. A resolver failure must stop the buyer with a
    retryable 503 BEFORE Stripe is called — otherwise a Stripe
    Session would exist for a purchase that will later fulfil
    against live grants (the race we're closing)."""

    def test_resolver_exception_returns_503_and_never_calls_stripe(
        self, db, make_space, make_user, stripe_configured,
    ):
        from fastapi import HTTPException
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Broken resolver path")
        opt = _make_option(db, space, name="Broken", pathway=pw)
        _add_pathway_grant(db, opt, pw)
        db.expire(opt)
        sched = _make_schedule(db, opt)

        with patch(
            "app.services.checkout_orchestration.resolve_intent_for_option",
            side_effect=RuntimeError("resolver blew up"),
        ):
            with patch("stripe.checkout.Session.create") as stripe_m:
                with pytest.raises(HTTPException) as exc_info:
                    _call_unified(db, buyer, option=opt, schedule=sched)
        assert exc_info.value.status_code == 503
        # Critical: Stripe was NEVER called — no Session exists.
        assert stripe_m.call_count == 0
        # No txn was written either.
        txns = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.payer_user_id == buyer.id)
            .all()
        )
        assert txns == []

    def test_resolver_fatal_error_returns_503_and_never_calls_stripe(
        self, db, make_space, make_user, stripe_configured,
    ):
        from fastapi import HTTPException
        from app.services.purchase_fulfilment import (
            FulfilmentIntent,
            FulfilmentResolution,
        )
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Fatal resolver path")
        opt = _make_option(db, space, name="Fatal", pathway=pw)
        _add_pathway_grant(db, opt, pw)
        db.expire(opt)
        sched = _make_schedule(db, opt)

        bad = FulfilmentResolution(
            intent=FulfilmentIntent(),
            fatal_error="option grants a Series that no longer exists",
        )
        with patch(
            "app.services.checkout_orchestration.resolve_intent_for_option",
            return_value=bad,
        ):
            with patch("stripe.checkout.Session.create") as stripe_m:
                with pytest.raises(HTTPException) as exc_info:
                    _call_unified(db, buyer, option=opt, schedule=sched)
        assert exc_info.value.status_code == 503
        assert stripe_m.call_count == 0

    def test_successful_checkout_always_has_snapshot(
        self, db, make_space, make_user, stripe_configured,
    ):
        """Every new pay-in-full transaction row from this codebase
        must carry a snapshot — NULL would be a Phase-1 regression."""
        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Solid path")
        opt = _make_option(db, space, name="Solid", pathway=pw)
        _add_pathway_grant(db, opt, pw)
        db.expire(opt)
        sched = _make_schedule(db, opt)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_solid")
            res = _call_unified(db, buyer, option=opt, schedule=sched)

        txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.id == res.transaction_id)
            .one()
        )
        assert txn.snapshot_grants_json is not None


class TestSnapshotIsHonouredByWebhook:
    def test_editing_grants_after_checkout_does_not_change_fulfilment(
        self, db, make_space, make_user, stripe_configured,
    ):
        """The bug this closes: an operator or Creator edits the
        Payment Option's grants in the window between checkout-
        session creation and Stripe firing checkout.session.completed.
        Without the snapshot, the webhook would fulfil against the
        NEW grants. With the snapshot, it fulfils against what the
        buyer saw."""
        from app.webhooks.routes import _handle_checkout_completed

        space = make_space()
        buyer = make_user()
        pw_original = _make_pathway(db, space, title="Original pathway")
        pw_swapped = _make_pathway(db, space, title="Swapped pathway")
        opt = _make_option(db, space, name="Awaken", pathway=pw_original)
        _add_pathway_grant(db, opt, pw_original)
        db.expire(opt)
        sched = _make_schedule(db, opt)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_snapshot_2")
            res = _call_unified(db, buyer, option=opt, schedule=sched)

        # Simulate a creator editing the grants after the buyer clicks
        # Pay: delete the original grant, add a different one.
        db.query(PaymentOptionGrant).filter(
            PaymentOptionGrant.payment_option_id == opt.id,
        ).delete()
        db.flush()
        _add_pathway_grant(db, opt, pw_swapped)
        db.commit()

        stripe_metadata = m.call_args.kwargs["metadata"]
        _handle_checkout_completed(
            {
                "id": "cs_snapshot_2",
                "payment_status": "paid",
                "payment_intent": "pi_test",
                "metadata": stripe_metadata,
            },
            db,
        )

        txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.id == res.transaction_id)
            .one()
        )
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied

        # Entitlement was written against the ORIGINAL pathway — the
        # snapshot, not the current DB, is authoritative.
        [ent] = (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .all()
        )
        assert ent.pathway_id == pw_original.id


class TestSnapshotAbsentFallsBackToLiveResolve:
    def test_null_snapshot_uses_live_resolver(
        self, db, make_space, make_user, stripe_configured,
    ):
        """Historical rows and any Phase-1 blip where snapshotting
        failed at checkout still fulfil via the live resolver."""
        from app.webhooks.routes import _handle_checkout_completed

        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Legacy path")
        opt = _make_option(db, space, name="Legacy", pathway=pw)
        _add_pathway_grant(db, opt, pw)
        db.expire(opt)
        sched = _make_schedule(db, opt)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_legacy_null")
            res = _call_unified(db, buyer, option=opt, schedule=sched)

        # Simulate a pre-migration row: clear the snapshot column.
        txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.id == res.transaction_id)
            .one()
        )
        txn.snapshot_grants_json = None
        db.commit()

        stripe_metadata = m.call_args.kwargs["metadata"]
        _handle_checkout_completed(
            {
                "id": "cs_legacy_null",
                "payment_status": "paid",
                "payment_intent": "pi_test",
                "metadata": stripe_metadata,
            },
            db,
        )

        db.expire(txn)
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied

        [ent] = (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .all()
        )
        assert ent.pathway_id == pw.id


class TestMalformedSnapshotBlocksFulfilment:
    def test_bad_snapshot_marks_blocked(
        self, db, make_space, make_user, stripe_configured,
    ):
        """A malformed snapshot is a bug — the webhook must block
        rather than silently swallow it (so operator tooling can
        surface the state and re-run once fixed)."""
        from app.webhooks.routes import _handle_checkout_completed

        space = make_space()
        buyer = make_user()
        pw = _make_pathway(db, space, title="Bad snapshot path")
        opt = _make_option(db, space, name="Bad", pathway=pw)
        _add_pathway_grant(db, opt, pw)
        db.expire(opt)
        sched = _make_schedule(db, opt)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_bad_snap")
            res = _call_unified(db, buyer, option=opt, schedule=sched)

        # Overwrite with something obviously invalid.
        txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.id == res.transaction_id)
            .one()
        )
        txn.snapshot_grants_json = {"version": 999, "entitlements": [], "access_passes": []}
        db.commit()

        _handle_checkout_completed(
            {
                "id": "cs_bad_snap",
                "payment_status": "paid",
                "payment_intent": "pi_test",
                "metadata": m.call_args.kwargs["metadata"],
            },
            db,
        )

        db.expire(txn)
        assert txn.fulfilment_status == PaymentFulfilmentStatus.blocked
        # No entitlement should have been created.
        ents = (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == buyer.id)
            .all()
        )
        assert ents == []
