"""Stage 3E — why the Refund action was missing, and what now says so.

The reported symptom was that a successful A$5 Payment Option purchase
showed no Refund action while a direct Gathering ticket did. The first
thing to establish was whether Payment Options are refused *as a kind*.

They are not. The gate reads six things — provider, status, remaining
balance, payout model, payout status, Connect transfer state — and
``transaction_type`` is not among them. A Payment Option purchase is
refundable on exactly the same terms as a ticket, which these tests
assert directly so the question cannot be reopened by guesswork.

What was genuinely wrong is that a refusal rendered *nothing*. No
button, no reason, no sign an action existed. So a creator could not
tell whether the action was missing, forbidden or broken — and neither
could anyone reading the page on their behalf.
"""
from __future__ import annotations

import uuid

import pytest

from app.creator.refund_routes import (
    REFUND_BLOCKED_REASONS, refund_eligibility,
)
from app.models.payment import (
    PaymentProvider, PaymentTransaction, PaymentTransactionStatus,
    PaymentTransactionType, PayoutStatus,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:10]}"


def _txn(
    db, space, buyer, *,
    kind=PaymentTransactionType.member_pathway_purchase,
    status=PaymentTransactionStatus.succeeded,
    provider=PaymentProvider.stripe,
    payout_status=PayoutStatus.pending,
    payout_model="manual",
    gross=500, refunded=0,
    payment_option_id=None,
) -> PaymentTransaction:
    t = PaymentTransaction(
        id=_uid("txn"), transaction_type=kind, status=status,
        payment_provider=provider, payer_user_id=buyer.id,
        space_id=space.id, currency="AUD", gross_amount_cents=gross,
        platform_fee_basis_points=0, platform_fee_cents=0,
        net_creator_amount_cents=gross, refunded_amount_cents=refunded,
        payout_status=payout_status, payout_model=payout_model,
        payment_option_id=payment_option_id,
    )
    db.add(t)
    db.flush()
    return t


def _option(db, space):
    from app.models.payment_option import (
        PaymentOption, PaymentOptionStatus, PaymentOptionType,
    )
    o = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="space",
        attaches_to_id=space.id, name="Test Gathering Experience",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published, currency="AUD", position=0,
    )
    db.add(o)
    db.flush()
    return o


@pytest.fixture
def space(make_space):
    return make_space()


class TestTransactionTypeIsNotAGate:
    """The finding that settles the report."""

    @pytest.mark.parametrize("kind", [
        PaymentTransactionType.gathering_ticket_purchase,
        PaymentTransactionType.member_pathway_purchase,
    ])
    def test_every_kind_is_refundable_on_the_same_terms(
        self, db, space, make_user, kind,
    ):
        t = _txn(db, space, make_user(), kind=kind)
        allowed, reason = refund_eligibility(t, actor_is_admin=False)
        assert allowed is True, f"{kind} was refused for being that kind"
        assert reason is None

    def test_a_payment_option_purchase_is_refundable(
        self, db, space, make_user,
    ):
        """The exact shape reported: a succeeded Stripe Payment Option
        purchase on a creator-owned Collective."""
        t = _txn(
            db, space, make_user(),
            payment_option_id=_option(db, space).id,
        )
        assert refund_eligibility(t, actor_is_admin=False)[0] is True

    def test_and_an_instalment_is_too(self, db, space, make_user):
        t = _txn(db, space, make_user(), gross=4500)
        t.purchase_plan_id = None
        db.flush()
        assert refund_eligibility(t, actor_is_admin=False)[0] is True


class TestEveryRefusalExplainsItself:
    """Silence was the bug. Each refusal now names itself, and every
    name has copy a creator can read."""

    def test_a_non_stripe_payment(self, db, space, make_user):
        t = _txn(db, space, make_user(), provider=PaymentProvider.manual)
        allowed, reason = refund_eligibility(t, actor_is_admin=False)
        assert allowed is False
        assert reason == "not_stripe"

    def test_a_payment_that_never_succeeded(self, db, space, make_user):
        t = _txn(db, space, make_user(),
                 status=PaymentTransactionStatus.pending)
        assert refund_eligibility(t, actor_is_admin=False)[1] == (
            "not_refundable_status"
        )

    def test_an_already_fully_refunded_payment(self, db, space, make_user):
        t = _txn(db, space, make_user(),
                 status=PaymentTransactionStatus.refunded,
                 gross=500, refunded=500)
        # Refunded status is itself not refundable, which is the first
        # refusal reached.
        assert refund_eligibility(t, actor_is_admin=False)[0] is False

    def test_a_partially_refunded_payment_keeps_its_remainder(
        self, db, space, make_user,
    ):
        t = _txn(db, space, make_user(),
                 status=PaymentTransactionStatus.partially_refunded,
                 gross=500, refunded=200)
        assert refund_eligibility(t, actor_is_admin=False)[0] is True

    def test_and_is_refused_once_nothing_is_left(
        self, db, space, make_user,
    ):
        t = _txn(db, space, make_user(),
                 status=PaymentTransactionStatus.partially_refunded,
                 gross=500, refunded=500)
        assert refund_eligibility(t, actor_is_admin=False)[1] == "nothing_left"

    def test_a_payout_outside_the_manual_process(
        self, db, space, make_user,
    ):
        """The most likely cause of the reported row. It is about the
        Collective's payout arrangement, not about what was bought."""
        t = _txn(db, space, make_user(),
                 payout_status=PayoutStatus.not_applicable,
                 payout_model="not_applicable")
        allowed, reason = refund_eligibility(t, actor_is_admin=False)
        assert allowed is False
        assert reason == "payout_not_applicable"

    def test_a_settled_payout_defers_to_an_admin(
        self, db, space, make_user,
    ):
        t = _txn(db, space, make_user(), payout_status=PayoutStatus.paid)
        assert refund_eligibility(t, actor_is_admin=False) == (
            False, "payout_settled",
        )
        assert refund_eligibility(t, actor_is_admin=True)[0] is True

    def test_every_reason_has_copy(self):
        """A reason with no wording would render as nothing again,
        which is the failure this whole change is about."""
        for key in (
            "not_stripe", "not_refundable_status", "nothing_left",
            "payout_not_applicable", "payout_settled",
            "connect_state_unknown",
        ):
            assert key in REFUND_BLOCKED_REASONS
            assert REFUND_BLOCKED_REASONS[key].strip()


class TestTheRowCarriesTheAnswer:
    """So the page shows a button or a reason, never silence."""

    def test_an_eligible_row_says_so(self, db, space, make_user):
        from app.creator.routes import _refund_eligibility, _refund_blocked_copy

        t = _txn(db, space, make_user())
        assert _refund_eligibility(t, False)[0] is True
        assert _refund_blocked_copy(t, False) is None

    def test_a_blocked_row_carries_readable_copy(
        self, db, space, make_user,
    ):
        from app.creator.routes import _refund_eligibility, _refund_blocked_copy

        t = _txn(db, space, make_user(),
                 payout_status=PayoutStatus.not_applicable,
                 payout_model="not_applicable")
        assert _refund_eligibility(t, False)[0] is False
        copy = _refund_blocked_copy(t, False)
        assert copy and "payout" in copy.lower()

    def test_the_gate_and_the_endpoint_cannot_disagree(
        self, db, space, make_user,
    ):
        """Both call the same function, which is the point: the button
        a creator sees and the endpoint behind it are one rule."""
        from app.creator.refund_routes import _payout_gate_action

        t = _txn(db, space, make_user())
        gate_allowed, _ = _payout_gate_action(txn=t, actor_is_admin=False)
        row_allowed, _ = refund_eligibility(t, actor_is_admin=False)
        assert gate_allowed == row_allowed
