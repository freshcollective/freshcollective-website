"""The payout-model snapshot, and the manual-payout double-payment guard.

Two properties carry the weight here.

**The decision is frozen.** A creator who completes Connect onboarding — or
loses a capability — after a purchase exists must not change how that
purchase pays out. Tests mutate the creator's Connect state *after* the
transaction is created and assert the row does not move.

**A Connect row can never enter a manual payout batch.** That is a
double-payment, and ``payout_status`` alone does not prevent it: a Connect
row whose transfer failed, or has not been sent yet, also sits at
``pending``. The regression test deliberately builds exactly that row.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.creator_stripe_account import CreatorStripeAccount, OnboardingState
from app.models.payment import (
    ConnectTransferStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutModel,
    PayoutStatus,
)
from app.services.connect_payout_model import (
    resolve_for_free_purchase,
    resolve_payout_model,
)

ACCT = "acct_1ConnectReady"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _connect_account(db, creator_id, **overrides) -> CreatorStripeAccount:
    """A fully payout-ready, routing-enabled account unless overridden."""
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
        "connect_payouts_enabled_at": datetime(2026, 9, 29, 12, 0, 0),
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


def _txn(db, **overrides) -> PaymentTransaction:
    values = {
        "id": f"txn_{uuid.uuid4().hex[:20]}",
        "transaction_type": PaymentTransactionType.member_payment_option_purchase,
        "status": PaymentTransactionStatus.succeeded,
        "payment_provider": PaymentProvider.stripe,
        "currency": "AUD",
        "gross_amount_cents": 10000,
        "platform_fee_basis_points": 800,
        "platform_fee_cents": 800,
        "net_creator_amount_cents": 9200,
        "net_platform_amount_cents": 800,
        "payout_status": PayoutStatus.pending,
        "stripe_mode": "test",
        "payout_model": PayoutModel.manual.value,
    }
    values.update(overrides)
    # A Connect row always owes a transfer eventually, so the ledger refuses
    # ``not_applicable`` on one. Mirror what the creation paths do and start
    # it ``awaiting_payment`` unless a test is specifically exercising a
    # later state.
    if (
        values["payout_model"] == PayoutModel.connect.value
        and "connect_transfer_status" not in overrides
    ):
        values["connect_transfer_status"] = \
            ConnectTransferStatus.awaiting_payment.value
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# The decision rules
# ---------------------------------------------------------------------------


class TestDecision:
    def test_platform_owned_is_not_applicable(self, db):
        d = resolve_payout_model(db, creator_user_id=None, is_platform_owned=True)
        assert d.payout_model == PayoutModel.not_applicable.value
        assert d.destination_account_id is None

    def test_no_creator_is_not_applicable(self, db):
        d = resolve_payout_model(db, creator_user_id=None)
        assert d.payout_model == PayoutModel.not_applicable.value

    def test_creator_without_a_connect_account_is_manual(self, db, make_user):
        creator = make_user(role="creator")
        d = resolve_payout_model(db, creator_user_id=creator.id)
        assert d.payout_model == PayoutModel.manual.value
        assert d.destination_account_id is None

    def test_account_row_without_a_stripe_id_is_manual(self, db, make_user):
        creator = make_user(role="creator")
        _connect_account(db, creator.id, stripe_account_id=None,
                         onboarding_state=OnboardingState.not_started.value,
                         transfers_status=None, transfers_enabled=False,
                         payouts_status=None, payouts_enabled=False,
                         connect_payouts_enabled_at=None)
        assert resolve_payout_model(db, creator_user_id=creator.id).payout_model == \
            PayoutModel.manual.value

    def test_stripe_ready_but_not_routing_enabled_is_manual(self, db, make_user):
        """The decision that keeps EMBODY on today's behaviour. Stripe saying
        an account is ready must never by itself start moving money."""
        creator = make_user(role="creator")
        _connect_account(db, creator.id, connect_payouts_enabled_at=None)
        d = resolve_payout_model(db, creator_user_id=creator.id)
        assert d.payout_model == PayoutModel.manual.value
        assert d.destination_account_id is None
        assert "not enabled" in d.reason

    def test_routing_enabled_and_payouts_active_is_connect(self, db, make_user):
        creator = make_user(role="creator")
        _connect_account(db, creator.id)
        d = resolve_payout_model(db, creator_user_id=creator.id)
        assert d.payout_model == PayoutModel.connect.value
        assert d.destination_account_id == ACCT
        assert d.is_connect is True

    def test_transfers_active_but_payouts_not_is_manual(self, db, make_user):
        """The trap state. Routing on transfers alone would move real money
        into a Stripe balance the creator has no bank account to empty."""
        creator = make_user(role="creator")
        _connect_account(
            db, creator.id,
            onboarding_state=OnboardingState.transfers_only.value,
            transfers_status="active", transfers_enabled=True,
            payouts_status="restricted", payouts_enabled=False,
            external_account_count=0,
            # Cannot be set at all with payouts inactive — the table's CHECK
            # refuses it — which is itself the guard under test.
            connect_payouts_enabled_at=None,
        )
        assert resolve_payout_model(db, creator_user_id=creator.id).payout_model == \
            PayoutModel.manual.value

    def test_routing_cannot_even_be_enabled_without_payouts(self, db, make_user):
        """Belt and braces: the schema refuses the combination the rule
        above guards against."""
        creator = make_user(role="creator")
        with pytest.raises(IntegrityError):
            _connect_account(
                db, creator.id,
                payouts_status="restricted", payouts_enabled=False,
                connect_payouts_enabled_at=datetime(2026, 9, 29, 12, 0, 0),
            )

    def test_a_live_mode_account_never_produces_connect_in_test_mode(
        self, db, make_user,
    ):
        """Mode separation. A live ``acct_…`` handed to a test key fails only
        at transfer time, so it is excluded at the decision instead."""
        creator = make_user(role="creator")
        _connect_account(
            db, creator.id, stripe_mode="live", stripe_account_id="acct_liveOnly",
        )
        d = resolve_payout_model(db, creator_user_id=creator.id)
        assert d.payout_model == PayoutModel.manual.value
        assert d.destination_account_id is None
        assert "test-mode" in d.reason

    def test_the_matching_mode_account_is_the_one_used(self, db, make_user):
        creator = make_user(role="creator")
        _connect_account(
            db, creator.id, stripe_mode="live", stripe_account_id="acct_liveOnly",
        )
        _connect_account(db, creator.id, stripe_mode="test", stripe_account_id=ACCT)
        d = resolve_payout_model(db, creator_user_id=creator.id)
        assert d.payout_model == PayoutModel.connect.value
        assert d.destination_account_id == ACCT

    def test_a_free_purchase_is_never_connect(self, db, make_user):
        creator = make_user(role="creator")
        _connect_account(db, creator.id)
        d = resolve_for_free_purchase(creator_user_id=creator.id)
        assert d.payout_model == PayoutModel.manual.value
        assert d.destination_account_id is None

    def test_a_platform_owned_free_purchase_is_not_applicable(self, db):
        assert resolve_for_free_purchase(
            creator_user_id=None, is_platform_owned=True,
        ).payout_model == PayoutModel.not_applicable.value


# ---------------------------------------------------------------------------
# The snapshot is frozen
# ---------------------------------------------------------------------------


class TestSnapshotIsFrozen:
    def test_enabling_connect_after_checkout_does_not_change_the_row(
        self, db, make_user,
    ):
        creator = make_user(role="creator")
        account = _connect_account(db, creator.id, connect_payouts_enabled_at=None)

        txn = _txn(db, creator_user_id=creator.id, payout_model=PayoutModel.manual.value)
        assert txn.payout_model == PayoutModel.manual.value

        # The creator is switched over afterwards.
        account.connect_payouts_enabled_at = datetime(2026, 9, 30, 9, 0, 0)
        db.commit()

        db.refresh(txn)
        assert txn.payout_model == PayoutModel.manual.value
        assert txn.connect_destination_account_id is None
        # And a *new* purchase does route.
        assert resolve_payout_model(db, creator_user_id=creator.id).payout_model == \
            PayoutModel.connect.value

    def test_losing_payouts_after_checkout_does_not_change_the_row(
        self, db, make_user,
    ):
        """The direction that matters more: an in-flight Connect purchase
        keeps its destination even if Stripe restricts the account."""
        creator = make_user(role="creator")
        account = _connect_account(db, creator.id)

        txn = _txn(
            db, creator_user_id=creator.id,
            payout_model=PayoutModel.connect.value,
            connect_destination_account_id=ACCT,
        )

        account.connect_payouts_enabled_at = None
        account.payouts_enabled = False
        account.payouts_status = "restricted"
        db.commit()

        db.refresh(txn)
        assert txn.payout_model == PayoutModel.connect.value
        assert txn.connect_destination_account_id == ACCT

    def test_changing_the_stripe_account_does_not_retarget_an_old_sale(
        self, db, make_user,
    ):
        creator = make_user(role="creator")
        account = _connect_account(db, creator.id)
        txn = _txn(
            db, creator_user_id=creator.id,
            payout_model=PayoutModel.connect.value,
            connect_destination_account_id=ACCT,
        )
        account.stripe_account_id = "acct_1Replacement"
        db.commit()
        db.refresh(txn)
        assert txn.connect_destination_account_id == ACCT


# ---------------------------------------------------------------------------
# Every pay-in-full creation path
# ---------------------------------------------------------------------------


class TestAllCreationPaths:
    """The decision must be identical wherever a purchase is recorded.

    Each path is exercised through its own transaction builder rather than a
    shared helper, because the risk being tested is one path being forgotten.
    """

    def test_gathering_ticket_builder_snapshots_the_decision(self, db, make_user, make_space):
        from app.services.gathering_tickets import _build_pending_transaction, TrustedTicketOffer

        creator = make_user(role="creator")
        _connect_account(db, creator.id)
        space = make_space(creator=creator)
        buyer = make_user()

        class _Event:
            id = "evt_x"

        offer = TrustedTicketOffer(
            event=_Event(), space=space, price_cents=5000, currency="AUD",
        )
        txn = _build_pending_transaction(
            db, offer=offer, buyer=buyer, fee_bps=800,
            creator_plan_id=None, creator_subscription_id=None,
        )
        assert txn.payout_model == PayoutModel.connect.value
        assert txn.connect_destination_account_id == ACCT

    def test_gathering_ticket_builder_is_manual_without_routing(
        self, db, make_user, make_space,
    ):
        from app.services.gathering_tickets import _build_pending_transaction, TrustedTicketOffer

        creator = make_user(role="creator")
        _connect_account(db, creator.id, connect_payouts_enabled_at=None)
        space = make_space(creator=creator)

        class _Event:
            id = "evt_x"

        txn = _build_pending_transaction(
            db,
            offer=TrustedTicketOffer(
                event=_Event(), space=space, price_cents=5000, currency="AUD",
            ),
            buyer=make_user(), fee_bps=800,
            creator_plan_id=None, creator_subscription_id=None,
        )
        assert txn.payout_model == PayoutModel.manual.value
        assert txn.connect_destination_account_id is None

    def test_gathering_ticket_builder_is_not_applicable_for_platform_owned(
        self, db, make_user, make_space,
    ):
        from app.services.gathering_tickets import _build_pending_transaction, TrustedTicketOffer

        space = make_space()
        space.creator_id = None
        db.flush()

        class _Event:
            id = "evt_x"

        txn = _build_pending_transaction(
            db,
            offer=TrustedTicketOffer(
                event=_Event(), space=space, price_cents=5000, currency="AUD",
            ),
            buyer=make_user(), fee_bps=0,
            creator_plan_id=None, creator_subscription_id=None,
        )
        assert txn.payout_model == PayoutModel.not_applicable.value

    def test_every_path_calls_the_one_resolver(self):
        """A source check, and the reason it exists: the rules must not be
        re-implemented per path. Asserts on the import, not on a word
        appearing somewhere in the file."""
        import re
        from pathlib import Path

        backend = Path(__file__).resolve().parents[1]
        paths = [
            "app/services/checkout_orchestration.py",
            "app/services/gathering_tickets.py",
            "app/checkout/routes.py",
        ]
        for rel in paths:
            source = (backend / rel).read_text()
            assert re.search(
                r"from app\.services\.connect_payout_model import", source,
            ), f"{rel} does not import the payout-model resolver"


# ---------------------------------------------------------------------------
# Ledger semantics unchanged
# ---------------------------------------------------------------------------


class TestLedgerSemanticsUnchanged:
    def test_net_creator_amount_still_excludes_the_processing_fee(self, db, make_user):
        """The Connect figure belongs in ``transfer_amount_cents``. Moving it
        into ``net_creator_amount_cents`` would break both the payout-batch
        sums and the refund invariant."""
        creator = make_user(role="creator")
        txn = _txn(
            db, creator_user_id=creator.id,
            gross_amount_cents=10000, platform_fee_cents=800,
            net_creator_amount_cents=9200, processing_fee_cents=200,
        )
        db.refresh(txn)
        assert txn.net_creator_amount_cents == 9200
        assert txn.processing_fee_cents == 200
        assert txn.transfer_amount_cents is None

    def test_a_manual_row_carries_no_connect_state(self, db, make_user):
        creator = make_user(role="creator")
        txn = _txn(db, creator_user_id=creator.id)
        db.refresh(txn)
        assert txn.payout_model == PayoutModel.manual.value
        assert txn.connect_destination_account_id is None
        assert txn.transfer_amount_cents is None
        assert txn.provider_transfer_id is None
        assert txn.connect_transfer_status == ConnectTransferStatus.not_applicable.value
        assert txn.transfer_attempt_count == 0
        assert txn.reversed_transfer_amount_cents == 0

    def test_the_default_for_a_new_row_is_manual(self, db, make_user):
        """Anything this commit did not explicitly wire — payment plans,
        admin-recorded payments — stays on today's behaviour."""
        txn = _txn(db, creator_user_id=make_user(role="creator").id)
        db.refresh(txn)
        assert txn.payout_model == PayoutModel.manual.value


class TestSchemaInvariants:
    def test_a_connect_row_must_name_its_destination(self, db, make_user):
        with pytest.raises(IntegrityError):
            _txn(
                db, creator_user_id=make_user(role="creator").id,
                payout_model=PayoutModel.connect.value,
                connect_destination_account_id=None,
            )

    def test_a_manual_row_may_not_carry_a_transfer_id(self, db, make_user):
        with pytest.raises(IntegrityError):
            _txn(
                db, creator_user_id=make_user(role="creator").id,
                payout_model=PayoutModel.manual.value,
                provider_transfer_id="tr_sneaky",
            )

    @pytest.mark.parametrize("status", [
        ConnectTransferStatus.awaiting_payment.value,
        ConnectTransferStatus.pending.value,
        ConnectTransferStatus.sent.value,
    ])
    def test_a_manual_row_may_not_carry_a_transfer_status(self, db, make_user, status):
        with pytest.raises(IntegrityError):
            _txn(
                db, creator_user_id=make_user(role="creator").id,
                payout_model=PayoutModel.manual.value,
                connect_transfer_status=status,
            )

    def test_a_connect_row_may_not_say_not_applicable(self, db, make_user):
        """The other half of the relationship: a transfer always applies to a
        Connect row, even before it is due."""
        with pytest.raises(IntegrityError):
            _txn(
                db, creator_user_id=make_user(role="creator").id,
                payout_model=PayoutModel.connect.value,
                connect_destination_account_id=ACCT,
                connect_transfer_status=ConnectTransferStatus.not_applicable.value,
            )

    def test_a_transfer_id_is_unique_across_transactions(self, db, make_user):
        creator = make_user(role="creator")
        _txn(
            db, creator_user_id=creator.id,
            payout_model=PayoutModel.connect.value,
            connect_destination_account_id=ACCT,
            provider_transfer_id="tr_once",
        )
        with pytest.raises(IntegrityError):
            _txn(
                db, creator_user_id=creator.id,
                payout_model=PayoutModel.connect.value,
                connect_destination_account_id=ACCT,
                provider_transfer_id="tr_once",
            )

    def test_many_rows_may_await_a_transfer_id(self, db, make_user):
        creator = make_user(role="creator")
        for _ in range(3):
            _txn(
                db, creator_user_id=creator.id,
                payout_model=PayoutModel.connect.value,
                connect_destination_account_id=ACCT,
            )
        # no IntegrityError — the unique index is partial

    def test_an_unknown_payout_model_is_rejected(self, db, make_user):
        with pytest.raises(IntegrityError):
            _txn(
                db, creator_user_id=make_user(role="creator").id,
                payout_model="destination_charge",
            )


# ---------------------------------------------------------------------------
# The double-payment guard
# ---------------------------------------------------------------------------


class TestManualPayoutBatchExcludesConnect:
    def _summary(self, db, creator_id) -> dict:
        from app.services.payout_batch_orchestration import compute_payable_summary
        return compute_payable_summary(db, creator_user_id=creator_id, currency="AUD")

    def test_a_manual_row_is_payable(self, db, make_user):
        creator = make_user(role="creator")
        _txn(db, creator_user_id=creator.id, payout_model=PayoutModel.manual.value)
        summary = self._summary(db, creator.id)
        assert summary["transaction_count"] == 1
        assert summary["payable_cents"] == 9200

    def test_a_connect_row_is_not_payable(self, db, make_user):
        creator = make_user(role="creator")
        _txn(
            db, creator_user_id=creator.id,
            payout_model=PayoutModel.connect.value,
            connect_destination_account_id=ACCT,
        )
        summary = self._summary(db, creator.id)
        assert summary["transaction_count"] == 0
        assert summary["payable_cents"] == 0

    @pytest.mark.parametrize("transfer_status", [
        ConnectTransferStatus.awaiting_payment.value,
        ConnectTransferStatus.pending.value,
        ConnectTransferStatus.failed.value,
        ConnectTransferStatus.sent.value,
    ])
    def test_no_transfer_state_lets_a_connect_row_in(
        self, db, make_user, transfer_status,
    ):
        """The regression that matters. ``payout_status`` stays 'pending' on a
        Connect row whose transfer has not been sent or has failed, so a
        guard based on payout_status alone would pay the creator twice."""
        creator = make_user(role="creator")
        _txn(
            db, creator_user_id=creator.id,
            payout_model=PayoutModel.connect.value,
            connect_destination_account_id=ACCT,
            connect_transfer_status=transfer_status,
            payout_status=PayoutStatus.pending,
        )
        assert self._summary(db, creator.id)["transaction_count"] == 0

    def test_creating_a_batch_skips_connect_rows(self, db, make_user):
        from app.services.payout_batch_orchestration import create_payout_batch

        creator = make_user(role="creator")
        manual = _txn(
            db, creator_user_id=creator.id, payout_model=PayoutModel.manual.value,
        )
        connect = _txn(
            db, creator_user_id=creator.id,
            payout_model=PayoutModel.connect.value,
            connect_destination_account_id=ACCT,
        )

        outcome = create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="TEST-BATCH-1", paid_at=datetime.utcnow(),
            submitted_total_cents=9200, note=None, created_by=creator,
        )
        assert outcome.transaction_count == 1
        assert outcome.included_transaction_ids == [manual.id]
        assert connect.id not in outcome.included_transaction_ids

        db.refresh(manual)
        db.refresh(connect)
        assert manual.payout_status == PayoutStatus.paid
        assert manual.payout_batch_id == outcome.batch_id
        # Untouched: its share is owed to the creator's own Stripe account.
        assert connect.payout_status == PayoutStatus.pending
        assert connect.payout_batch_id is None

    def test_a_creator_with_only_connect_rows_has_nothing_to_batch(
        self, db, make_user,
    ):
        from app.services.payout_batch_orchestration import (
            PayoutBatchNoEligibleError,
            create_payout_batch,
        )
        creator = make_user(role="creator")
        _txn(
            db, creator_user_id=creator.id,
            payout_model=PayoutModel.connect.value,
            connect_destination_account_id=ACCT,
        )
        with pytest.raises(PayoutBatchNoEligibleError):
            create_payout_batch(
                db, creator=creator, currency="AUD",
                reference="TEST-BATCH-2", paid_at=datetime.utcnow(),
                submitted_total_cents=9200, note=None, created_by=creator,
            )

    def test_not_applicable_rows_remain_excluded(self, db, make_user):
        creator = make_user(role="creator")
        _txn(
            db, creator_user_id=creator.id,
            payout_model=PayoutModel.not_applicable.value,
            payout_status=PayoutStatus.not_applicable,
        )
        assert self._summary(db, creator.id)["transaction_count"] == 0

    def test_the_guard_is_present_in_both_query_paths(self):
        """Both the summary and the batch-creation query must filter. A guard
        on one of them is a guard on neither."""
        from pathlib import Path
        source = (
            Path(__file__).resolve().parents[1]
            / "app/services/payout_batch_orchestration.py"
        ).read_text()
        assert source.count("pt.payout_model = 'manual'") == 2

# ---------------------------------------------------------------------------
# The backfill
# ---------------------------------------------------------------------------


class TestBackfill:
    """Migration 142's backfill statement, run against seeded rows.

    ``ADD COLUMN … DEFAULT 'manual'`` is what every pre-existing row gets
    first, so seeding rows at that value reproduces the state the UPDATE
    then corrects. The alembic run itself was verified separately by an
    upgrade / downgrade / upgrade cycle; what is checked here is that the
    statement classifies rows the way the ledger requires.
    """

    BACKFILL = text(
        """
        UPDATE payment_transactions
        SET payout_model = 'not_applicable'
        WHERE payout_status = 'not_applicable'
        """
    )

    def test_platform_owned_rows_become_not_applicable(self, db, make_user):
        creator = make_user(role="creator")
        platform_owned = _txn(
            db, creator_user_id=None,
            payout_status=PayoutStatus.not_applicable,
            payout_model=PayoutModel.manual.value,   # the ADD COLUMN default
        )
        creator_row = _txn(
            db, creator_user_id=creator.id,
            payout_status=PayoutStatus.pending,
            payout_model=PayoutModel.manual.value,
        )

        db.execute(self.BACKFILL)
        db.commit()

        db.refresh(platform_owned)
        db.refresh(creator_row)
        assert platform_owned.payout_model == PayoutModel.not_applicable.value
        assert creator_row.payout_model == PayoutModel.manual.value

    @pytest.mark.parametrize("payout_status", [
        PayoutStatus.pending, PayoutStatus.paid,
        PayoutStatus.held, PayoutStatus.cancelled,
    ])
    def test_every_other_payout_status_stays_manual(
        self, db, make_user, payout_status,
    ):
        """Including ``paid`` and ``cancelled`` historical rows — none of them
        were ever Connect-routed, so all of them are manual."""
        row = _txn(
            db, creator_user_id=make_user(role="creator").id,
            payout_status=payout_status,
            payout_model=PayoutModel.manual.value,
        )
        db.execute(self.BACKFILL)
        db.commit()
        db.refresh(row)
        assert row.payout_model == PayoutModel.manual.value

    def test_the_backfill_never_produces_connect(self, db, make_user):
        """No historical row can be Connect-routed: no creator has ever been
        enabled, and the migration has no branch that could say otherwise."""
        creator = make_user(role="creator")
        for status in (PayoutStatus.pending, PayoutStatus.not_applicable):
            _txn(
                db, creator_user_id=creator.id, payout_status=status,
                payout_model=PayoutModel.manual.value,
            )
        db.execute(self.BACKFILL)
        db.commit()
        models = {
            m for (m,) in db.execute(
                text("SELECT DISTINCT payout_model FROM payment_transactions")
            ).all()
        }
        assert PayoutModel.connect.value not in models

    def test_backfilled_rows_satisfy_the_new_invariants(self, db, make_user):
        """The CHECK constraints were added after the backfill, so the
        backfilled shape has to pass them."""
        row = _txn(
            db, creator_user_id=None,
            payout_status=PayoutStatus.not_applicable,
            payout_model=PayoutModel.manual.value,
        )
        db.execute(self.BACKFILL)
        db.commit()   # would raise if any CHECK rejected the result
        db.refresh(row)
        assert row.connect_destination_account_id is None
        assert row.connect_transfer_status == \
            ConnectTransferStatus.not_applicable.value
        assert row.reversed_transfer_amount_cents == 0

# ---------------------------------------------------------------------------
# Transfer status at creation: applicable vs due
# ---------------------------------------------------------------------------


class TestInitialTransferStatus:
    """A Connect row owes a transfer eventually, but not until it is paid.

    ``awaiting_payment`` carries that difference. The sweeper acts only on
    ``pending``, so an abandoned or still-open Checkout Session never enters
    its queue — and no Connect row has to claim a transfer will never apply
    to it.
    """

    def test_the_decision_supplies_awaiting_payment_for_connect(self, db, make_user):
        creator = make_user(role="creator")
        _connect_account(db, creator.id)
        d = resolve_payout_model(db, creator_user_id=creator.id)
        assert d.initial_transfer_status == \
            ConnectTransferStatus.awaiting_payment.value

    @pytest.mark.parametrize("factory", ["manual", "platform_owned", "free"])
    def test_every_other_model_supplies_not_applicable(self, db, make_user, factory):
        if factory == "manual":
            creator = make_user(role="creator")
            d = resolve_payout_model(db, creator_user_id=creator.id)
        elif factory == "platform_owned":
            d = resolve_payout_model(db, creator_user_id=None, is_platform_owned=True)
        else:
            d = resolve_for_free_purchase(
                creator_user_id=make_user(role="creator").id,
            )
        assert d.initial_transfer_status == \
            ConnectTransferStatus.not_applicable.value

    def test_a_connect_ticket_starts_awaiting_payment(self, db, make_user, make_space):
        from app.services.gathering_tickets import (
            TrustedTicketOffer, _build_pending_transaction,
        )

        creator = make_user(role="creator")
        _connect_account(db, creator.id)
        space = make_space(creator=creator)

        class _Event:
            id = "evt_x"

        txn = _build_pending_transaction(
            db,
            offer=TrustedTicketOffer(
                event=_Event(), space=space, price_cents=5000, currency="AUD",
            ),
            buyer=make_user(), fee_bps=800,
            creator_plan_id=None, creator_subscription_id=None,
        )
        assert txn.payout_model == PayoutModel.connect.value
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.awaiting_payment.value

    def test_a_manual_ticket_starts_not_applicable(self, db, make_user, make_space):
        from app.services.gathering_tickets import (
            TrustedTicketOffer, _build_pending_transaction,
        )

        creator = make_user(role="creator")
        space = make_space(creator=creator)

        class _Event:
            id = "evt_x"

        txn = _build_pending_transaction(
            db,
            offer=TrustedTicketOffer(
                event=_Event(), space=space, price_cents=5000, currency="AUD",
            ),
            buyer=make_user(), fee_bps=800,
            creator_plan_id=None, creator_subscription_id=None,
        )
        assert txn.payout_model == PayoutModel.manual.value
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.not_applicable.value

    def test_a_platform_owned_ticket_starts_not_applicable(
        self, db, make_user, make_space,
    ):
        from app.services.gathering_tickets import (
            TrustedTicketOffer, _build_pending_transaction,
        )

        space = make_space()
        space.creator_id = None
        db.flush()

        class _Event:
            id = "evt_x"

        txn = _build_pending_transaction(
            db,
            offer=TrustedTicketOffer(
                event=_Event(), space=space, price_cents=5000, currency="AUD",
            ),
            buyer=make_user(), fee_bps=0,
            creator_plan_id=None, creator_subscription_id=None,
        )
        assert txn.payout_model == PayoutModel.not_applicable.value
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.not_applicable.value

    def test_an_unpaid_connect_transaction_is_not_in_the_sweeper_queue(
        self, db, make_user,
    ):
        """The reason ``awaiting_payment`` exists. A buyer who opens Checkout
        and walks away leaves a Connect row behind forever; it must never
        look like a transfer FC owes."""
        creator = make_user(role="creator")
        abandoned = _txn(
            db, creator_user_id=creator.id,
            status=PaymentTransactionStatus.pending,
            payout_model=PayoutModel.connect.value,
            connect_destination_account_id=ACCT,
            connect_transfer_status=ConnectTransferStatus.awaiting_payment.value,
        )
        owed = _txn(
            db, creator_user_id=creator.id,
            payout_model=PayoutModel.connect.value,
            connect_destination_account_id=ACCT,
            connect_transfer_status=ConnectTransferStatus.pending.value,
        )

        # The query the future sweeper will run.
        queued = {
            row_id for (row_id,) in db.execute(
                text(
                    "SELECT id FROM payment_transactions "
                    "WHERE connect_transfer_status = 'pending'"
                )
            ).all()
        }
        assert owed.id in queued
        assert abandoned.id not in queued

    def test_an_abandoned_connect_row_stays_awaiting_payment(self, db, make_user):
        """Nothing in this commit moves it on. Only fulfilment will."""
        creator = make_user(role="creator")
        row = _txn(
            db, creator_user_id=creator.id,
            status=PaymentTransactionStatus.pending,
            payout_model=PayoutModel.connect.value,
            connect_destination_account_id=ACCT,
            connect_transfer_status=ConnectTransferStatus.awaiting_payment.value,
        )
        db.refresh(row)
        assert row.connect_transfer_status == \
            ConnectTransferStatus.awaiting_payment.value
        assert row.transfer_amount_cents is None
        assert row.provider_transfer_id is None
        assert row.transfer_attempt_count == 0

    def test_an_awaiting_payment_row_is_still_excluded_from_manual_batches(
        self, db, make_user,
    ):
        """The double-payment guard keys on ``payout_model``, so the new
        status cannot open a hole in it."""
        from app.services.payout_batch_orchestration import compute_payable_summary

        creator = make_user(role="creator")
        _txn(
            db, creator_user_id=creator.id,
            payout_model=PayoutModel.connect.value,
            connect_destination_account_id=ACCT,
            connect_transfer_status=ConnectTransferStatus.awaiting_payment.value,
        )
        summary = compute_payable_summary(
            db, creator_user_id=creator.id, currency="AUD",
        )
        assert summary["transaction_count"] == 0

