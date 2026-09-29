"""Connect routing for finite payment plans.

The property this file mostly exists to protect: **a plan pays out the same way
in month ten as it did in month one.** A creator may finish onboarding, lose a
capability, or swap their Stripe account while a plan is running, and a member's
instalments must not end up split across two payout models with no record of
why.

So the routing decision is snapshotted on the plan and every instalment
inherits it. Tests here mutate the creator's Connect state *after* the plan
exists and assert nothing about the plan moves.

The transfer itself is the shared service, unchanged — so what is tested is the
per-invoice wiring into it, not the transfer mechanics, which
``test_connect_transfers.py`` already covers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
import stripe

from app.models.creator_stripe_account import CreatorStripeAccount, OnboardingState
from app.models.payment import (
    ConnectTransferStatus,
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutModel,
    PayoutStatus,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import finite_plan_lifecycle as lifecycle
from app.services.connect_payout_model import resolve_payout_model

ACCT = "acct_1ConnectReady"
TRANSFER_TARGET = "app.services.connect_transfers.get_stripe"


class _FakeStripe:
    def __init__(self, *, error=None):
        self.calls: list[dict] = []
        outer = self

        class _Transfer:
            @staticmethod
            def create(**kwargs):
                outer.calls.append(kwargs)
                if error is not None:
                    raise error
                return {"id": f"tr_{uuid.uuid4().hex[:14]}"}

        self.Transfer = _Transfer


def _patched(fake):
    return patch(TRANSFER_TARGET, return_value=fake)


def _connect_account(db, creator_id, **overrides) -> CreatorStripeAccount:
    values = {
        "id": f"csa_{uuid.uuid4()}",
        "creator_user_id": creator_id,
        "stripe_mode": "test",
        "stripe_account_id": ACCT,
        "onboarding_state": OnboardingState.ready.value,
        "transfers_status": "active",
        "transfers_enabled": True,
        "payouts_status": "active",
        "payouts_enabled": True,
        "details_submitted": True,
        "external_account_count": 1,
        "connect_payouts_enabled_at": datetime(2026, 9, 1, 9, 0, 0),
        # Routing cannot be on without an acknowledgement — the schema
        # says so (migration 145), so a fixture that skips it is not a
        # state production can reach.
        "fee_disclosure_acknowledged_at": datetime(2026, 9, 1, 8, 0, 0),
        "fee_disclosure_version": "2026-09-connect-v1",
    }
    values.update(overrides)
    row = CreatorStripeAccount(**values)
    db.add(row)
    db.commit()
    return row


def _option_and_schedule(db, space_id):
    """The minimum a plan's FKs require. Shape follows the existing
    finite-plan test fixtures."""
    from app.models.payment_option import (
        PaymentOption, PaymentOptionStatus, PaymentOptionType,
    )
    from app.models.payment_option_schedule import PaymentOptionSchedule

    opt = PaymentOption(
        id=f"po_{uuid.uuid4().hex[:12]}", space_id=space_id,
        attaches_to_kind="event_series",
        attaches_to_id=f"es_{uuid.uuid4().hex[:12]}",
        name="Instalment offer",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=100000, currency="AUD",
    )
    db.add(opt)
    sched = PaymentOptionSchedule(
        id=f"sched_{uuid.uuid4().hex[:12]}", payment_option_id=opt.id,
        name="Monthly × 10", schedule_type="recurring_installments",
        status="published",
        installment_amount_cents=10000, installment_count=10,
        stripe_interval="month", stripe_interval_count=1,
        total_amount_cents=100000, currency="AUD",
    )
    db.add(sched)
    db.flush()
    return opt, sched


def _plan(db, creator_id, space_id, member_id, **overrides) -> PurchasePlan:
    """A ten-instalment plan: A$100 each, 8% platform fee."""
    opt, sched = _option_and_schedule(db, space_id)
    values = {
        "id": f"pplan_{uuid.uuid4().hex[:24]}",
        "member_user_id": member_id,
        "payment_option_id": opt.id,
        "payment_option_schedule_id": sched.id,
        "space_id": space_id,
        "creator_user_id": creator_id,
        "status": PurchasePlanStatus.active,
        "currency": "AUD",
        "installment_amount_cents": 10000,
        "installments_expected": 10,
        "installments_paid": 1,
        "total_expected_cents": 100000,
        "platform_fee_basis_points": 800,
        "stripe_interval": "month",
        "stripe_interval_count": 1,
        "stripe_mode": "test",
        "payout_model": PayoutModel.manual.value,
        "connect_destination_account_id": None,
    }
    values.update(overrides)
    row = PurchasePlan(**values)
    db.add(row)
    db.commit()
    return row


def _connect_plan(db, creator_id, space_id, member_id, **overrides) -> PurchasePlan:
    return _plan(
        db, creator_id, space_id, member_id,
        payout_model=PayoutModel.connect.value,
        connect_destination_account_id=ACCT,
        **overrides,
    )


def _instalment_txn(db, plan, **overrides) -> PaymentTransaction:
    """An instalment row built the way the handler builds it."""
    values = {
        "id": str(uuid.uuid4()),
        "transaction_type": PaymentTransactionType.member_payment_option_purchase,
        "status": PaymentTransactionStatus.succeeded,
        "fulfilment_status": PaymentFulfilmentStatus.applied,
        "payment_provider": PaymentProvider.stripe,
        "payer_user_id": plan.member_user_id,
        "creator_user_id": plan.creator_user_id,
        "space_id": plan.space_id,
        "currency": plan.currency,
        "gross_amount_cents": 10000,
        "platform_fee_basis_points": 800,
        "platform_fee_cents": 800,
        "net_creator_amount_cents": 9200,
        "net_platform_amount_cents": 800,
        "processing_fee_cents": 200,
        "purchase_plan_id": plan.id,
        "installment_number": 2,
        "provider_invoice_id": f"in_{uuid.uuid4().hex[:16]}",
        "provider_charge_id": f"ch_{uuid.uuid4().hex[:16]}",
        "provider_payment_intent_id": f"pi_{uuid.uuid4().hex[:16]}",
        "stripe_mode": "test",
    }
    values.update(lifecycle.plan_payout_fields(plan))
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------


class TestPlanSnapshot:
    def test_a_plan_created_before_enablement_is_manual(self, db, make_user, make_space):
        creator = make_user(role="creator")
        _connect_account(db, creator.id, connect_payouts_enabled_at=None)
        decision = resolve_payout_model(db, creator_user_id=creator.id)
        assert decision.payout_model == PayoutModel.manual.value
        assert decision.destination_account_id is None

    def test_a_plan_created_after_enablement_snapshots_connect(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        _connect_account(db, creator.id)
        decision = resolve_payout_model(db, creator_user_id=creator.id)
        assert decision.payout_model == PayoutModel.connect.value
        assert decision.destination_account_id == ACCT

    def test_a_live_mode_account_never_routes_a_test_mode_plan(self, db, make_user):
        """Same current-mode safety as pay-in-full."""
        creator = make_user(role="creator")
        _connect_account(
            db, creator.id, stripe_mode="live", stripe_account_id="acct_liveOnly",
        )
        assert resolve_payout_model(
            db, creator_user_id=creator.id,
        ).payout_model == PayoutModel.manual.value

    def test_a_platform_owned_plan_is_not_applicable(self, db):
        assert resolve_payout_model(
            db, creator_user_id=None, is_platform_owned=True,
        ).payout_model == PayoutModel.not_applicable.value

    def test_the_plan_must_name_its_destination(self, db, make_user, make_space):
        """Schema-enforced, as on the transaction table."""
        from sqlalchemy.exc import IntegrityError

        creator = make_user(role="creator")
        space = make_space(creator=creator)
        with pytest.raises(IntegrityError):
            _plan(
                db, creator.id, space.id, make_user().id,
                payout_model=PayoutModel.connect.value,
                connect_destination_account_id=None,
            )

    def test_a_manual_plan_may_not_carry_a_destination(self, db, make_user, make_space):
        from sqlalchemy.exc import IntegrityError

        creator = make_user(role="creator")
        space = make_space(creator=creator)
        with pytest.raises(IntegrityError):
            _plan(
                db, creator.id, space.id, make_user().id,
                payout_model=PayoutModel.manual.value,
                connect_destination_account_id=ACCT,
            )


class TestSnapshotIsFrozenAcrossThePlan:
    def test_mid_plan_enablement_does_not_change_routing(
        self, db, make_user, make_space,
    ):
        """The creator switches on Connect in month four. This plan carries on
        paying out the way it always did."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        account = _connect_account(db, creator.id, connect_payouts_enabled_at=None)
        plan = _plan(db, creator.id, space.id, make_user().id)
        assert plan.payout_model == PayoutModel.manual.value

        account.connect_payouts_enabled_at = datetime(2026, 10, 1, 9, 0, 0)
        db.commit()
        db.refresh(plan)

        assert plan.payout_model == PayoutModel.manual.value
        assert plan.connect_destination_account_id is None
        # Every instalment inherits the plan, not the creator's new state.
        fields = lifecycle.plan_payout_fields(plan)
        assert fields["payout_model"] == PayoutModel.manual.value
        assert fields["connect_transfer_status"] == \
            ConnectTransferStatus.not_applicable.value
        assert fields["payout_status"] == PayoutStatus.pending
        # And a *new* plan would route.
        assert resolve_payout_model(
            db, creator_user_id=creator.id,
        ).payout_model == PayoutModel.connect.value

    def test_mid_plan_disablement_does_not_change_routing(
        self, db, make_user, make_space,
    ):
        """The direction that matters more: a Connect plan keeps its
        destination even if the creator is switched off."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        account = _connect_account(db, creator.id)
        plan = _connect_plan(db, creator.id, space.id, make_user().id)

        account.connect_payouts_enabled_at = None
        account.payouts_enabled = False
        account.payouts_status = "restricted"
        db.commit()
        db.refresh(plan)

        assert plan.payout_model == PayoutModel.connect.value
        assert plan.connect_destination_account_id == ACCT
        assert lifecycle.plan_payout_fields(plan)["payout_model"] == \
            PayoutModel.connect.value

    def test_replacing_the_account_does_not_redirect_the_plan(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        account = _connect_account(db, creator.id)
        plan = _connect_plan(db, creator.id, space.id, make_user().id)

        account.stripe_account_id = "acct_1Replacement"
        db.commit()
        db.refresh(plan)

        assert plan.connect_destination_account_id == ACCT
        assert lifecycle.plan_payout_fields(plan)[
            "connect_destination_account_id"
        ] == ACCT

    def test_every_instalment_of_a_connect_plan_inherits_it(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _connect_account(db, creator.id)
        plan = _connect_plan(db, creator.id, space.id, make_user().id)

        for ordinal in (1, 2, 3):
            txn = _instalment_txn(db, plan, installment_number=ordinal)
            assert txn.payout_model == PayoutModel.connect.value
            assert txn.connect_destination_account_id == ACCT
            assert txn.payout_status == PayoutStatus.not_applicable


# ---------------------------------------------------------------------------
# What an instalment row inherits
# ---------------------------------------------------------------------------


class TestInstalmentRowFields:
    def test_a_connect_instalment_starts_awaiting_payment(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        plan = _connect_plan(
            db, creator.id, make_space(creator=creator).id, make_user().id,
        )
        fields = lifecycle.plan_routing_fields(plan)
        assert fields["connect_transfer_status"] == \
            ConnectTransferStatus.awaiting_payment.value
        assert fields["connect_destination_account_id"] == ACCT

    def test_a_manual_instalment_is_not_applicable_and_payout_pending(
        self, db, make_user, make_space,
    ):
        """Unchanged from today: a manual instalment is payable by batch."""
        creator = make_user(role="creator")
        plan = _plan(db, creator.id, make_space(creator=creator).id, make_user().id)
        fields = lifecycle.plan_payout_fields(plan)
        assert fields["payout_model"] == PayoutModel.manual.value
        assert fields["connect_transfer_status"] == \
            ConnectTransferStatus.not_applicable.value
        assert fields["connect_destination_account_id"] is None
        assert fields["payout_status"] == PayoutStatus.pending

    def test_a_failed_instalment_keeps_routing_but_owes_nothing(
        self, db, make_user, make_space,
    ):
        """``plan_routing_fields`` without ``payout_status``: a payment that did
        not happen owes nobody, but the row must know where it pays if Stripe's
        retry succeeds and it is upgraded in place."""
        creator = make_user(role="creator")
        plan = _connect_plan(
            db, creator.id, make_space(creator=creator).id, make_user().id,
        )
        routing = lifecycle.plan_routing_fields(plan)
        assert "payout_status" not in routing
        assert routing["payout_model"] == PayoutModel.connect.value

    def test_the_per_invoice_processing_fee_is_used(self, db, make_user, make_space):
        """Each instalment has its own fee — never reused from a sibling."""
        creator = make_user(role="creator")
        plan = _connect_plan(
            db, creator.id, make_space(creator=creator).id, make_user().id,
        )
        first = _instalment_txn(
            db, plan, installment_number=1, processing_fee_cents=200,
        )
        second = _instalment_txn(
            db, plan, installment_number=2, processing_fee_cents=235,
        )

        from app.services import connect_transfers as ct
        assert ct.compute_transfer_amount(first) == 9000    # 9200 − 200
        assert ct.compute_transfer_amount(second) == 8965   # 9200 − 235


# ---------------------------------------------------------------------------
# Owing and sending
# ---------------------------------------------------------------------------


class TestOwedAndSent:
    def test_a_paid_instalment_becomes_owed_then_sent(self, db, make_user, make_space):
        from app.services import connect_transfers as ct

        creator = make_user(role="creator")
        plan = _connect_plan(
            db, creator.id, make_space(creator=creator).id, make_user().id,
        )
        txn = _instalment_txn(db, plan)
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.awaiting_payment.value

        assert ct.mark_transfer_owed(db, txn) is True
        db.commit()
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value

        fake = _FakeStripe()
        with _patched(fake):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)

        assert outcome.sent is True
        assert len(fake.calls) == 1
        assert fake.calls[0]["amount"] == 9000
        assert fake.calls[0]["destination"] == ACCT
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.sent.value
        assert txn.transfer_amount_cents == 9000

    def test_each_paid_instalment_produces_exactly_one_transfer(
        self, db, make_user, make_space,
    ):
        from app.services import connect_transfers as ct

        creator = make_user(role="creator")
        plan = _connect_plan(
            db, creator.id, make_space(creator=creator).id, make_user().id,
        )
        rows = [_instalment_txn(db, plan, installment_number=n) for n in (1, 2, 3)]

        fake = _FakeStripe()
        with _patched(fake):
            for txn in rows:
                ct.mark_transfer_owed(db, txn)
                db.commit()
                ct.execute_transfer(db, payment_transaction_id=txn.id)
                # And again, as a duplicate delivery would.
                ct.execute_transfer(db, payment_transaction_id=txn.id)

        assert len(fake.calls) == 3
        ids = {r.provider_transfer_id for r in rows}
        assert len(ids) == 3 and None not in ids

    def test_a_duplicate_delivery_sends_one_transfer(self, db, make_user, make_space):
        from app.services import connect_transfers as ct

        creator = make_user(role="creator")
        plan = _connect_plan(
            db, creator.id, make_space(creator=creator).id, make_user().id,
        )
        txn = _instalment_txn(db, plan)
        ct.mark_transfer_owed(db, txn)
        db.commit()

        fake = _FakeStripe()
        with _patched(fake):
            for _ in range(3):
                ct.execute_transfer(db, payment_transaction_id=txn.id)
        assert len(fake.calls) == 1
        db.refresh(txn)
        assert txn.transfer_attempt_count == 1

    def test_a_manual_instalment_is_never_transferred(self, db, make_user, make_space):
        from app.services import connect_transfers as ct

        creator = make_user(role="creator")
        plan = _plan(db, creator.id, make_space(creator=creator).id, make_user().id)
        txn = _instalment_txn(db, plan)

        assert ct.mark_transfer_owed(db, txn) is False
        fake = _FakeStripe()
        with _patched(fake):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)
        assert outcome.status == ct.SKIPPED
        assert fake.calls == []
        db.refresh(txn)
        # Payable by batch, exactly as today.
        assert txn.payout_status == PayoutStatus.pending

    def test_a_retryable_failure_is_recovered_by_the_existing_sweeper(
        self, db, make_user, make_space,
    ):
        from app.services import connect_transfer_sweeper as sweeper
        from app.services import connect_transfers as ct

        creator = make_user(role="creator")
        plan = _connect_plan(
            db, creator.id, make_space(creator=creator).id, make_user().id,
        )
        txn = _instalment_txn(db, plan)
        ct.mark_transfer_owed(db, txn)
        db.commit()

        err = stripe.InvalidRequestError(
            "insufficient available funds", param=None, code="balance_insufficient",
        )
        with _patched(_FakeStripe(error=err)):
            ct.execute_transfer(db, payment_transaction_id=txn.id)
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value

        # The shared sweeper picks the instalment up — no plan-specific sweeper.
        fake = _FakeStripe()
        with _patched(fake):
            report = sweeper.sweep_pending_transfers(db)
        assert report.sent == 1
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.sent.value
        assert txn.transfer_amount_cents == 9000

    def test_an_unpaid_instalment_row_is_never_swept(self, db, make_user, make_space):
        """A failed instalment carries the plan's routing but owes nothing."""
        from app.services import connect_transfer_sweeper as sweeper

        creator = make_user(role="creator")
        plan = _connect_plan(
            db, creator.id, make_space(creator=creator).id, make_user().id,
        )
        _instalment_txn(
            db, plan,
            status=PaymentTransactionStatus.failed,
            installment_number=None,
            platform_fee_cents=0, net_creator_amount_cents=0,
            net_platform_amount_cents=0, processing_fee_cents=None,
            payout_status=PayoutStatus.not_applicable,
        )
        fake = _FakeStripe()
        with _patched(fake):
            assert sweeper.sweep_pending_transfers(db).considered == 0
        assert fake.calls == []


# ---------------------------------------------------------------------------
# Refunds reuse the per-transaction machinery
# ---------------------------------------------------------------------------


class TestInstalmentRefunds:
    def test_refunding_one_instalment_reverses_only_that_transfer(
        self, db, make_user, make_space,
    ):
        """No plan-level reversal maths: the existing per-transaction recovery
        pipeline already scopes to the row its charge belongs to."""
        from app.services import connect_reversals as cr
        from app.services import connect_transfers as ct

        creator = make_user(role="creator")
        plan = _connect_plan(
            db, creator.id, make_space(creator=creator).id, make_user().id,
        )
        first = _instalment_txn(db, plan, installment_number=1)
        second = _instalment_txn(db, plan, installment_number=2)

        fake = _FakeStripe()
        with _patched(fake):
            for txn in (first, second):
                ct.mark_transfer_owed(db, txn)
                db.commit()
                ct.execute_transfer(db, payment_transaction_id=txn.id)

        # The member is refunded for instalment 2 only.
        second.refunded_amount_cents = 10000
        second.refunded_platform_fee_cents = 800
        second.refunded_creator_amount_cents = 9200
        second.status = PaymentTransactionStatus.refunded
        db.commit()

        class _ReversalStripe:
            def __init__(self):
                self.reversals = []
                outer = self

                class _Transfer:
                    @staticmethod
                    def create_reversal(transfer_id, **kwargs):
                        outer.reversals.append(
                            {"transfer": transfer_id, **kwargs},
                        )
                        return {"id": "trr_1"}

                self.Transfer = _Transfer

        rev = _ReversalStripe()
        with patch(
            "app.services.connect_reversals.get_stripe", return_value=rev,
        ):
            outcome = cr.reverse_to_target(db, payment_transaction_id=second.id)

        assert outcome.reversed_now == 9000
        assert len(rev.reversals) == 1
        assert rev.reversals[0]["transfer"] == second.provider_transfer_id

        db.refresh(first)
        db.refresh(second)
        # Instalment 1 is untouched — different transfer, different row.
        assert first.connect_transfer_status == ConnectTransferStatus.sent.value
        assert first.reversed_transfer_amount_cents == 0
        assert second.connect_transfer_status == ConnectTransferStatus.reversed.value
        assert second.reversed_transfer_amount_cents == 9000

    def test_a_partial_instalment_refund_reverses_proportionally(
        self, db, make_user, make_space,
    ):
        from app.services import connect_reversals as cr

        creator = make_user(role="creator")
        plan = _connect_plan(
            db, creator.id, make_space(creator=creator).id, make_user().id,
        )
        txn = _instalment_txn(
            db, plan,
            connect_transfer_status=ConnectTransferStatus.sent.value,
            transfer_amount_cents=9000,
            provider_transfer_id=f"tr_{uuid.uuid4().hex[:12]}",
            refunded_amount_cents=5000,
            refunded_platform_fee_cents=400,
            refunded_creator_amount_cents=4600,
            status=PaymentTransactionStatus.partially_refunded,
        )
        # 9000 × 4600 / 9200 = 4500 — the same formula as pay-in-full.
        assert cr.compute_reversal_target(txn) == 4500

    def test_a_refund_of_a_manual_instalment_attempts_no_reversal(
        self, db, make_user, make_space,
    ):
        from app.services import connect_reversals as cr

        creator = make_user(role="creator")
        plan = _plan(db, creator.id, make_space(creator=creator).id, make_user().id)
        txn = _instalment_txn(
            db, plan,
            refunded_amount_cents=10000,
            refunded_platform_fee_cents=800,
            refunded_creator_amount_cents=9200,
            status=PaymentTransactionStatus.refunded,
        )
        rev = _FakeStripe()
        with patch(
            "app.services.connect_reversals.get_stripe", return_value=rev,
        ):
            outcome = cr.reverse_to_target(db, payment_transaction_id=txn.id)
        assert outcome.status == cr.SKIPPED


# ---------------------------------------------------------------------------
# No second implementation
# ---------------------------------------------------------------------------


def test_plans_reuse_the_shared_transfer_service():
    """A plan-specific transfer implementation would drift from the
    pay-in-full one, and the amounts would eventually disagree."""
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    for rel in (
        "app/webhooks/finite_plan_handlers.py",
        "app/services/finite_plan_lifecycle.py",
    ):
        source = (backend / rel).read_text()
        assert "Transfer.create" not in source, (
            f"{rel} calls Stripe Transfer directly — plans must go through "
            "connect_transfers"
        )
        for forbidden in ("transfer_data", "application_fee"):
            assert forbidden not in source, f"{forbidden} in {rel}"


def test_the_instalment_transfer_runs_after_the_plan_work_commits():
    """Ordering is structural: the attempt sits after ``process_webhook_event``,
    which is what commits the instalment and its fulfilment."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app/webhooks/finite_plan_handlers.py"
    ).read_text()
    start = source.index("def handle_invoice_payment_succeeded(")
    end = source.index("def _attempt_instalment_transfer(")
    body = source[start:end]
    assert body.index("process_webhook_event(") < body.index(
        "_attempt_instalment_transfer(",
    )
