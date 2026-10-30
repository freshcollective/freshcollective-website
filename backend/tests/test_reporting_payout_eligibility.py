"""Which ledger rows a money metric is allowed to see.

The defect these cover
----------------------
The BI registry declared its own tuple of member transaction types, five
long, while ``app.admin.routes`` carried seven. The two missing were
``member_series_pass_purchase`` and ``member_payment_option_purchase`` —
the type the unified checkout writes, and so the type every modern
EMBODY purchase is. The result was a Money dashboard where gross sales,
creator earnings, platform fee, processing costs, refunds and
contribution could not see EMBODY at all, while
``outstanding_payouts_cents`` — which filtered on payout status and
nothing else — could. A liability was reported larger than the earnings
it was a share of.

So these tests assert three separate things, and the third is the one
that matters most:

* every member purchase type reaches every revenue metric;
* a payout figure counts only rows that can actually carry a payout;
* **paid and outstanding are complements** — the same population seen
  from either side, so a dollar that leaves one total must arrive in the
  other. Two queries with independently maintained filters is how the
  original defect happened, and arithmetic is the only guard that keeps
  noticing.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

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


def val(db, key, window=ALL_TIME):
    return REGISTRY.get(key).evaluate(db, platform_scope(), window)


def _txn(db, *, space, creator, payer, **over):
    """A settled member purchase, paid in full, awaiting a manual payout.

    Defaults are the shape the defect was found in: $100 gross, a 10%
    platform fee, $90 owed to the creator, manual payout model, test
    mode — which is what ``settings.stripe_mode`` reports under pytest,
    so the mode filter admits these rows rather than silently dropping
    the whole suite's fixtures.
    """
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
def cast(make_user, make_space):
    """A creator with a Collective, and somebody to buy from them."""
    creator = make_user(role="creator")
    return {
        "creator": creator,
        "space": make_space(creator=creator),
        "payer": make_user(),
    }


# ---------------------------------------------------------------------------
# One definition, in one place
# ---------------------------------------------------------------------------

class TestThereIsOnlyOneDefinition:
    def test_admin_and_the_registry_use_the_very_same_set(self):
        """Not "equal" — the same object, so they cannot drift."""
        from app.admin.routes import _MEMBER_TXN_TYPES

        assert set(_MEMBER_TXN_TYPES) == set(eligibility.MEMBER_TXN_TYPES)

    def test_the_payment_option_type_is_included(self):
        """The regression itself.

        Every modern EMBODY and Life in Full Colour purchase is this
        type. Its absence was invisible — no error, no empty page, just
        revenue figures quietly missing a Collective.
        """
        assert (
            PaymentTransactionType.member_payment_option_purchase
            in eligibility.MEMBER_TXN_TYPES
        )

    def test_series_passes_are_included(self):
        assert (
            PaymentTransactionType.member_series_pass_purchase
            in eligibility.MEMBER_TXN_TYPES
        )

    def test_a_creator_plan_fee_is_never_a_member_purchase(self):
        """Fresh Collective's own revenue, not a creator's earnings."""
        assert (
            PaymentTransactionType.creator_subscription_payment
            not in eligibility.MEMBER_TXN_TYPES
        )
        assert (
            PaymentTransactionType.creator_subscription_payment
            in eligibility.CREATOR_PLAN_TXN_TYPES
        )

    def test_refunds_and_adjustments_are_not_purchases(self):
        for t in (
            PaymentTransactionType.refund,
            PaymentTransactionType.adjustment,
        ):
            assert t not in eligibility.MEMBER_TXN_TYPES

    def test_every_member_type_in_the_enum_is_accounted_for(self):
        """A new member purchase type cannot be added and forgotten.

        Anything that is neither a member purchase, a creator plan fee,
        nor a bookkeeping entry fails here — which is the prompt to
        decide where it belongs rather than discovering months later
        that a revenue figure was short.
        """
        bookkeeping = {
            PaymentTransactionType.refund,
            PaymentTransactionType.adjustment,
        }
        classified = (
            set(eligibility.MEMBER_TXN_TYPES)
            | set(eligibility.CREATOR_PLAN_TXN_TYPES)
            | bookkeeping
        )
        unclassified = set(PaymentTransactionType) - classified
        assert not unclassified, (
            f"unclassified transaction types: {sorted(t.value for t in unclassified)}"
        )

    def test_no_module_declares_a_second_member_type_tuple(self):
        """A source contract, because this is how the bug came back.

        Two copies of the set existed and one went stale. The guard is
        on *declaring* a collection of member types, not on mentioning
        a type — plenty of code legitimately refers to one.
        """
        root = Path(__file__).resolve().parents[1] / "app"
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == "eligibility.py":
                continue
            text = path.read_text()
            for marker in ("_MEMBER_TXN_TYPES = {", "MEMBER_TXN_TYPES = ("):
                if marker in text:
                    offenders.append(f"{path.relative_to(root)}: {marker!r}")
        assert not offenders, (
            "member transaction types must come from app.reporting.eligibility: "
            + "; ".join(offenders)
        )


# ---------------------------------------------------------------------------
# Revenue metrics see every member purchase
# ---------------------------------------------------------------------------

class TestEveryMemberPurchaseTypeIsCounted:
    @pytest.mark.parametrize(
        "txn_type",
        list(eligibility.MEMBER_TXN_TYPES),
        ids=lambda t: t.value,
    )
    def test_gross_sales_and_creator_earnings_see_it(self, db, cast, txn_type):
        _txn(db, **cast, transaction_type=txn_type)
        assert val(db, "gross_collective_sales_cents").value == 10000, txn_type
        assert val(db, "creator_earnings_cents").value == 9000, txn_type
        assert val(db, "platform_fee_revenue_cents").value == 1000, txn_type
        assert val(db, "processing_costs_cents").value == 205, txn_type

    def test_a_creator_plan_fee_is_revenue_but_not_volume(self, db, cast):
        _txn(
            db,
            **cast,
            transaction_type=PaymentTransactionType.creator_subscription_payment,
            platform_fee_cents=0,
            net_creator_amount_cents=None,
            payout_status=PayoutStatus.not_applicable,
            payout_model=PayoutModel.not_applicable,
        )
        assert val(db, "subscription_revenue_cents").value == 10000
        assert val(db, "gross_collective_sales_cents").value == 0
        assert val(db, "creator_earnings_cents").value == 0


class TestRefundsStayOnTheirOwnSideOfTheLine:
    def test_a_member_refund_is_reported(self, db, cast):
        _txn(
            db,
            **cast,
            status=PaymentTransactionStatus.refunded,
            refunded_amount_cents=10000,
            refunded_creator_amount_cents=9000,
            refunded_platform_fee_cents=1000,
            last_refunded_at=datetime.utcnow(),
        )
        assert val(db, "refunds_cents").value == 10000

    def test_a_refunded_creator_plan_fee_is_not_a_member_refund(self, db, cast):
        """Fresh Collective refunding a creator's plan fee is its own
        revenue going back out, not money returned to a member. Reporting
        it on the member side inverts the one distinction the Money page
        is built around."""
        _txn(
            db,
            **cast,
            transaction_type=PaymentTransactionType.creator_subscription_payment,
            status=PaymentTransactionStatus.refunded,
            net_creator_amount_cents=None,
            refunded_amount_cents=10000,
            last_refunded_at=datetime.utcnow(),
            payout_status=PayoutStatus.not_applicable,
            payout_model=PayoutModel.not_applicable,
        )
        assert val(db, "refunds_cents").value == 0


# ---------------------------------------------------------------------------
# A payout figure counts only rows that can carry a payout
# ---------------------------------------------------------------------------

class TestOutstandingCountsOnlyRealObligations:
    def test_a_settled_manual_purchase_is_owed(self, db, cast):
        _txn(db, **cast)
        assert val(db, "outstanding_payouts_cents").value == 9000

    @pytest.mark.parametrize(
        "status",
        list(eligibility.UNSETTLED_STATUSES),
        ids=lambda s: s.value,
    )
    def test_money_nobody_paid_is_never_owed(self, db, cast, status):
        """A ledger row is created when the Checkout Session opens, with
        ``payout_status='pending'`` already on it. An abandoned,
        cancelled or failed checkout is not a creator obligation however
        that column reads."""
        _txn(db, **cast, status=status)
        assert val(db, "outstanding_payouts_cents").value == 0

    def test_a_sandbox_row_is_not_a_liability(self, db, cast):
        """``settings.stripe_mode`` is ``test`` under pytest, so a
        ``live`` row is the foreign one here. The assertion is about
        separation, which holds whichever way round the deployment is."""
        _txn(db, **cast, stripe_mode="live")
        assert val(db, "outstanding_payouts_cents").value == 0

    def test_a_platform_owned_collective_owes_nobody(self, db, make_space, make_user):
        """``spaces.creator_id IS NULL`` means Fresh Collective is the
        seller. There is no creator share to owe, so the row is created
        ``not_applicable`` and must stay out of the liability."""
        space = make_space(creator_id=None)
        _txn(
            db,
            space=space,
            creator=make_user(role="creator"),
            payer=make_user(),
            creator_user_id=None,
            platform_fee_cents=0,
            net_creator_amount_cents=None,
            payout_status=PayoutStatus.not_applicable,
            payout_model=PayoutModel.not_applicable,
        )
        assert val(db, "outstanding_payouts_cents").value == 0

    def test_a_connect_row_is_stripes_business_not_ours(self, db, cast):
        """Connect rows are created ``not_applicable`` on purpose, so
        Fresh Collective's manual payout queue cannot claim money Stripe
        has already sent. ``connect_transfer_status`` is their
        authority."""
        _txn(
            db,
            **cast,
            payout_status=PayoutStatus.not_applicable,
            payout_model=PayoutModel.connect,
            connect_destination_account_id="acct_test_fixture",
            connect_transfer_status=ConnectTransferStatus.sent,
            transfer_amount_cents=9000,
            provider_transfer_id="tr_test_123",
        )
        assert val(db, "outstanding_payouts_cents").value == 0
        assert val(db, "paid_out_cents").value == 0

    def test_a_refund_reduces_what_is_owed(self, db, cast):
        _txn(
            db,
            **cast,
            status=PaymentTransactionStatus.partially_refunded,
            refunded_amount_cents=5000,
            refunded_creator_amount_cents=4500,
            refunded_platform_fee_cents=500,
            last_refunded_at=datetime.utcnow(),
        )
        assert val(db, "outstanding_payouts_cents").value == 4500

    def test_the_period_does_not_narrow_a_liability(self, db, cast):
        """A snapshot. What is owed today is owed today, whichever month
        the dashboard is showing."""
        _txn(db, **cast, settled_at=datetime.utcnow() - timedelta(days=400))
        narrow = Window(
            starts_at=datetime.utcnow() - timedelta(days=1),
            ends_at=datetime.utcnow(),
        )
        assert val(db, "outstanding_payouts_cents", narrow).value == 9000


class TestPaidOutMeansRecordedAsPaid:
    def test_a_marked_row_is_counted_on_the_date_it_was_marked(self, db, cast):
        marked = datetime.utcnow() - timedelta(days=2)
        _txn(
            db,
            **cast,
            payout_status=PayoutStatus.paid,
            payout_marked_at=marked,
            payout_reference="batch-1",
        )
        assert val(db, "paid_out_cents").value == 9000
        assert val(db, "outstanding_payouts_cents").value == 0

    def test_paid_without_a_date_is_not_counted(self, db, cast):
        """``payout_marked_at`` is what gives the cash movement its
        date. A paid row without one cannot be placed in a period, so it
        is left out rather than dated by something else."""
        _txn(db, **cast, payout_status=PayoutStatus.paid, payout_marked_at=None)
        assert val(db, "paid_out_cents").value == 0

    def test_an_unsettled_row_cannot_be_paid_out(self, db, cast):
        _txn(
            db,
            **cast,
            status=PaymentTransactionStatus.cancelled,
            payout_status=PayoutStatus.paid,
            payout_marked_at=datetime.utcnow(),
        )
        assert val(db, "paid_out_cents").value == 0


class TestPaidAndOutstandingAreComplements:
    """The arithmetic guard.

    Two queries whose filters are maintained apart is exactly how the
    original defect arose. If one gains a condition the other lacks, a
    dollar vanishes from the sum, and this notices without anybody
    having thought to check that particular condition.
    """

    def test_together_they_account_for_every_eligible_dollar(self, db, cast):
        _txn(db, **cast)                                           # owed
        _txn(db, **cast, gross_amount_cents=5000, platform_fee_cents=500,
             net_creator_amount_cents=4500)                        # owed
        _txn(db, **cast, payout_status=PayoutStatus.paid,
             payout_marked_at=datetime.utcnow())                   # paid
        _txn(db, **cast, status=PaymentTransactionStatus.failed)    # neither
        _txn(db, **cast, stripe_mode="live")                       # neither

        owed = val(db, "outstanding_payouts_cents").value
        paid = val(db, "paid_out_cents").value
        earnings = val(db, "creator_earnings_cents").value

        assert owed == 13500
        assert paid == 9000
        # Earnings counts settled sales in this mode regardless of payout
        # state, so it is the total the two payout figures divide up.
        assert owed + paid == earnings

    def test_marking_a_row_paid_moves_the_money_rather_than_losing_it(self, db, cast):
        t = _txn(db, **cast)
        before_owed = val(db, "outstanding_payouts_cents").value
        t.payout_status = PayoutStatus.paid
        t.payout_marked_at = datetime.utcnow()
        db.flush()
        assert val(db, "outstanding_payouts_cents").value == before_owed - 9000
        assert val(db, "paid_out_cents").value == 9000


# ---------------------------------------------------------------------------
# Founder-operated Collectives
# ---------------------------------------------------------------------------

class TestTheOwnershipSplitIsReportingOnly:
    """Fresh Collective's owner is also a creator, so part of the
    liability is the platform owing itself. The split says so without
    deciding anything: it never changes the total, and nothing is marked
    settled on the strength of it.
    """

    def test_an_external_creators_earnings_are_external(self, db, cast):
        _txn(db, **cast)
        q = val(db, "outstanding_payouts_cents").qualifiers
        assert q["owed_to_external_creators_cents"] == 9000
        assert q["owed_to_founder_operated_collectives_cents"] == 0

    def test_an_admins_own_collective_is_identified_as_founder_operated(
        self, db, make_user, make_space
    ):
        founder = make_user(role="admin")
        _txn(
            db,
            space=make_space(creator=founder),
            creator=founder,
            payer=make_user(),
        )
        q = val(db, "outstanding_payouts_cents").qualifiers
        assert q["owed_to_founder_operated_collectives_cents"] == 9000
        assert q["owed_to_external_creators_cents"] == 0

    def test_the_split_always_sums_to_the_total(self, db, make_user, make_space):
        founder = make_user(role="admin")
        external = make_user(role="creator")
        payer = make_user()
        _txn(db, space=make_space(creator=founder), creator=founder, payer=payer)
        _txn(db, space=make_space(creator=external), creator=external, payer=payer)

        m = val(db, "outstanding_payouts_cents")
        assert m.value == 18000
        assert (
            m.qualifiers["owed_to_external_creators_cents"]
            + m.qualifiers["owed_to_founder_operated_collectives_cents"]
            == m.value
        )

    def test_an_unclassified_collective_is_not_assumed_to_be_production(
        self, db, cast
    ):
        """``reporting_class`` is NULL until an operator assigns one, and
        nothing is ever inferred from a Collective's name. Counting an
        unreviewed Collective as production would make the review
        pointless."""
        _txn(db, **cast)
        by_class = val(db, "outstanding_payouts_cents").qualifiers[
            "by_reporting_class_cents"
        ]
        assert by_class["unclassified"] == 9000
        assert by_class["production"] == 0
        assert by_class["demonstration"] == 0

    def test_a_demonstration_collectives_live_charge_is_still_real_money(
        self, db, make_user, make_space
    ):
        """A demonstration Collective is labelled, never discounted. The
        charge went through Stripe and the money moved, so it stays in
        the total and is reported under its own class."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, reporting_class="demonstration")
        _txn(db, space=space, creator=creator, payer=make_user())

        m = val(db, "outstanding_payouts_cents")
        assert m.value == 9000, "a demonstration charge is not excluded"
        assert m.qualifiers["by_reporting_class_cents"]["demonstration"] == 9000

    def test_the_classification_split_also_sums_to_the_total(
        self, db, make_user, make_space
    ):
        payer = make_user()
        for cls in ("production", "internal_operations", "demonstration", None):
            creator = make_user(role="creator")
            _txn(
                db,
                space=make_space(creator=creator, reporting_class=cls),
                creator=creator,
                payer=payer,
            )
        m = val(db, "outstanding_payouts_cents")
        assert sum(m.qualifiers["by_reporting_class_cents"].values()) == m.value

    def test_the_two_splits_are_independent_questions(
        self, db, make_user, make_space
    ):
        """Who is owed and what kind of activity it was are different
        facts. A founder-operated demonstration Collective is both, and
        each split must report it in full rather than halving it."""
        founder = make_user(role="admin")
        space = make_space(creator=founder, reporting_class="demonstration")
        _txn(db, space=space, creator=founder, payer=make_user())

        q = val(db, "outstanding_payouts_cents").qualifiers
        assert q["owed_to_founder_operated_collectives_cents"] == 9000
        assert q["by_reporting_class_cents"]["demonstration"] == 9000

    def test_the_split_does_not_claim_anything_is_settled(self, db, make_user, make_space):
        founder = make_user(role="admin")
        t = _txn(
            db,
            space=make_space(creator=founder),
            creator=founder,
            payer=make_user(),
        )
        val(db, "outstanding_payouts_cents")
        db.refresh(t)
        assert t.payout_status == PayoutStatus.pending
        assert t.payout_marked_at is None
        assert val(db, "paid_out_cents").value == 0
