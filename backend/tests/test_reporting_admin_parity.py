"""The two financial surfaces must agree about the same money.

Fresh Collective reports money twice — ``/admin/commerce/*`` for the
caretaker's day-to-day view and ``/reporting/query`` for World Insights
— and every discrepancy found so far has been the two surfaces computing
the same figure from different rules:

* **BI-3a.** One attributed by ``settled_at``, the other by
  ``created_at``, so a September-created October-settled payment landed
  in different months. Fixed by sharing ``app.reporting.dates``.
* **This change.** One knew about seven member transaction types, the
  other about five, so every PaymentOption purchase — all of EMBODY —
  was absent from World Insights revenue while still counted as an
  outstanding payout. Fixed by sharing
  ``app.reporting.eligibility``.

Two shared modules is not a guarantee; it is only where the shared rules
live. These tests are the guarantee. They put the same rows in front of
both surfaces and insist the figures match, which is a question neither
surface can answer about itself.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.admin.routes import _compute_revenue_summary
from app.models.payment import (
    ConnectTransferStatus,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutModel,
    PayoutStatus,
)
from app.reporting import eligibility
from app.reporting.registry import REGISTRY, Window
from app.reporting.scope import platform_scope

ALL_TIME = Window()


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def bi(db, key):
    return REGISTRY.get(key).evaluate(db, platform_scope(), ALL_TIME).value


def _txn(db, *, space, creator, payer, **over):
    d = dict(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payer_user_id=payer.id,
        creator_user_id=creator.id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=10000,
        platform_fee_basis_points=1000,
        platform_fee_cents=1000,
        net_creator_amount_cents=9000,
        processing_fee_cents=205,
        payout_status=PayoutStatus.pending,
        payout_model=PayoutModel.manual,
        connect_transfer_status=ConnectTransferStatus.not_applicable,
        stripe_mode="test",
        settled_at=datetime.utcnow() - timedelta(days=1),
    )
    d.update(over)
    t = PaymentTransaction(**d)
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def ledger(db, make_user, make_space):
    """One settled purchase of every member type, plus the awkward rows.

    Deliberately includes what the October reconciliation turned up: a
    founder-operated Collective, a demonstration Collective, a Connect
    creator whose share Stripe has already sent, an already-paid row, a
    refund, and an abandoned checkout still carrying ``pending``.
    """
    payer = make_user()
    founder = make_user(role="admin")
    external = make_user(role="creator")
    connect_creator = make_user(role="creator")

    founder_space = make_space(creator=founder, reporting_class="production")
    demo_space = make_space(creator=founder, reporting_class="demonstration")
    external_space = make_space(creator=external, reporting_class="production")
    connect_space = make_space(creator=connect_creator, reporting_class="production")

    # Every member purchase type, so a type dropped from the shared set
    # changes both surfaces' totals and the parity assertions still hold
    # while the amount assertions below do not.
    for t in eligibility.MEMBER_TXN_TYPES:
        _txn(
            db,
            space=founder_space,
            creator=founder,
            payer=payer,
            transaction_type=t,
        )

    _txn(db, space=demo_space, creator=founder, payer=payer,
         gross_amount_cents=200, platform_fee_cents=20,
         net_creator_amount_cents=180)

    _txn(db, space=external_space, creator=external, payer=payer,
         payout_status=PayoutStatus.paid,
         payout_marked_at=datetime.utcnow() - timedelta(days=3),
         payout_reference="batch-parity")

    _txn(db, space=connect_space, creator=connect_creator, payer=payer,
         payout_status=PayoutStatus.not_applicable,
         payout_model=PayoutModel.connect,
         connect_destination_account_id="acct_parity_fixture",
         connect_transfer_status=ConnectTransferStatus.sent,
         transfer_amount_cents=9000)

    _txn(db, space=external_space, creator=external, payer=payer,
         status=PaymentTransactionStatus.partially_refunded,
         refunded_amount_cents=2500,
         refunded_creator_amount_cents=2250,
         refunded_platform_fee_cents=250,
         last_refunded_at=datetime.utcnow())

    # Abandoned checkout: born 'pending' on both columns, never paid.
    _txn(db, space=external_space, creator=external, payer=payer,
         status=PaymentTransactionStatus.pending, settled_at=None)

    # A creator paying Fresh Collective for their plan. Revenue, not volume.
    _txn(db, space=external_space, creator=external, payer=external,
         transaction_type=PaymentTransactionType.creator_subscription_payment,
         gross_amount_cents=4900, platform_fee_cents=0,
         net_creator_amount_cents=None,
         payout_status=PayoutStatus.not_applicable,
         payout_model=PayoutModel.not_applicable)

    db.flush()
    return {"payer": payer, "founder": founder, "external": external}


def summary(db):
    from app.core.config import settings

    return _compute_revenue_summary(db, stripe_mode=settings.stripe_mode)


class TestTheTwoSurfacesAgree:
    """Each assertion is one figure, computed two independent ways."""

    def test_gross_sales_match(self, db, ledger):
        assert bi(db, "gross_collective_sales_cents") == (
            summary(db).total_gross_sales_cents
        )

    def test_platform_fee_revenue_matches(self, db, ledger):
        assert bi(db, "platform_fee_revenue_cents") == (
            summary(db).platform_fee_revenue_cents
        )

    def test_creator_subscription_revenue_matches(self, db, ledger):
        assert bi(db, "subscription_revenue_cents") == (
            summary(db).subscription_revenue_cents
        )

    def test_creator_earnings_match(self, db, ledger):
        assert bi(db, "creator_earnings_cents") == (
            summary(db).total_creator_net_cents
        )

    def test_outstanding_payouts_match(self, db, ledger):
        """The figure the whole investigation was about.

        Admin's "Pending Payouts" has carried the right filters all
        along. Agreement here is the assertion that World Insights has
        stopped answering a looser question.
        """
        assert bi(db, "outstanding_payouts_cents") == (
            summary(db).pending_payout_cents
        )

    def test_paid_out_matches(self, db, ledger):
        assert bi(db, "paid_out_cents") == summary(db).paid_out_cents

    def test_a_payment_option_purchase_reaches_both_surfaces(
        self, db, make_user, make_space
    ):
        """The regression, stated as the smallest case that shows it.

        One EMBODY-shaped purchase and nothing else. Before the fix the
        registry returned 0 here while admin returned 10000.
        """
        creator = make_user(role="creator")
        _txn(
            db,
            space=make_space(creator=creator),
            creator=creator,
            payer=make_user(),
            transaction_type=(
                PaymentTransactionType.member_payment_option_purchase
            ),
        )
        assert bi(db, "gross_collective_sales_cents") == 10000
        assert summary(db).total_gross_sales_cents == 10000

    def test_a_series_pass_reaches_both_surfaces(self, db, make_user, make_space):
        creator = make_user(role="creator")
        _txn(
            db,
            space=make_space(creator=creator),
            creator=creator,
            payer=make_user(),
            transaction_type=PaymentTransactionType.member_series_pass_purchase,
        )
        assert bi(db, "gross_collective_sales_cents") == 10000
        assert summary(db).total_gross_sales_cents == 10000


class TestNothingIsCountedTwice:
    def test_one_purchase_contributes_once_to_gross(self, db, cast_one):
        assert bi(db, "gross_collective_sales_cents") == 10000

    def test_a_purchase_is_either_owed_or_paid_never_both(self, db, cast_one):
        assert bi(db, "outstanding_payouts_cents") == 9000
        assert bi(db, "paid_out_cents") == 0

    def test_fee_and_creator_share_partition_the_gross(self, db, cast_one):
        """No dollar is both Fresh Collective's and the creator's.

        The arithmetic is the payment system's and is read, never
        recomputed — this asserts the metrics read it consistently.
        """
        gross = bi(db, "gross_collective_sales_cents")
        fee = bi(db, "platform_fee_revenue_cents")
        creator = bi(db, "creator_earnings_cents")
        assert fee + creator == gross

    def test_contribution_is_revenue_less_processing_and_nothing_else(
        self, db, cast_one
    ):
        fee = bi(db, "platform_fee_revenue_cents")
        subs = bi(db, "subscription_revenue_cents")
        costs = bi(db, "processing_costs_cents")
        assert bi(db, "contribution_after_processing_cents") == fee + subs - costs

    def test_contribution_never_includes_the_creators_share(self, db, cast_one):
        """The mistake that would flatter the business most.

        Gross volume is mostly creators' money. A contribution figure
        that absorbed it would be wrong by an order of magnitude.
        """
        assert bi(db, "contribution_after_processing_cents") < bi(
            db, "creator_earnings_cents"
        )


@pytest.fixture
def cast_one(db, make_user, make_space):
    """Exactly one settled $100 purchase, 10% fee, awaiting payout."""
    creator = make_user(role="creator")
    _txn(
        db,
        space=make_space(creator=creator),
        creator=creator,
        payer=make_user(),
    )
    return True


class TestSettlementDatesStayShared:
    def test_both_surfaces_place_a_payment_in_the_same_month(
        self, db, make_user, make_space
    ):
        """Created in one month, settled in the next.

        This is the BI-3a defect's own fixture, kept because the shared
        date module is the only reason it passes and a future refactor
        could quietly unshare it.
        """
        creator = make_user(role="creator")
        created = datetime(2026, 9, 28, 23, 0)
        settled = datetime(2026, 10, 2, 1, 0)
        _txn(
            db,
            space=make_space(creator=creator),
            creator=creator,
            payer=make_user(),
            created_at=created,
            settled_at=settled,
        )
        october = Window(
            starts_at=datetime(2026, 10, 1),
            ends_at=datetime(2026, 11, 1),
        )
        september = Window(
            starts_at=datetime(2026, 9, 1),
            ends_at=datetime(2026, 10, 1),
        )
        from app.core.config import settings

        in_october = REGISTRY.get("gross_collective_sales_cents").evaluate(
            db, platform_scope(), october
        )
        in_september = REGISTRY.get("gross_collective_sales_cents").evaluate(
            db, platform_scope(), september
        )
        admin_october = _compute_revenue_summary(
            db,
            starts_at=october.starts_at,
            ends_at=october.ends_at,
            stripe_mode=settings.stripe_mode,
        )

        assert in_october.value == 10000, "settlement month, not creation month"
        assert in_september.value == 0
        assert admin_october.total_gross_sales_cents == 10000

    def test_a_refund_is_dated_by_the_refund_not_the_sale(
        self, db, make_user, make_space
    ):
        """A closed month's refund figure must never move afterwards."""
        creator = make_user(role="creator")
        _txn(
            db,
            space=make_space(creator=creator),
            creator=creator,
            payer=make_user(),
            status=PaymentTransactionStatus.refunded,
            settled_at=datetime(2026, 9, 10),
            refunded_amount_cents=10000,
            refunded_creator_amount_cents=9000,
            refunded_platform_fee_cents=1000,
            last_refunded_at=datetime(2026, 10, 15),
        )
        sale_month = Window(
            starts_at=datetime(2026, 9, 1), ends_at=datetime(2026, 10, 1)
        )
        refund_month = Window(
            starts_at=datetime(2026, 10, 1), ends_at=datetime(2026, 11, 1)
        )
        m = REGISTRY.get("refunds_cents")
        assert m.evaluate(db, platform_scope(), sale_month).value == 0
        assert m.evaluate(db, platform_scope(), refund_month).value == 10000
