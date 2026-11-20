"""Stage 5A.4b — the incident of 19 November 2026, pinned.

A$5.99 was collected from a real card. Stripe created the subscription,
marked the first invoice paid and delivered the webhook. Fresh
Collective showed the membership as "Not finished", told the member
nothing had been charged, and offered them Continue checkout — which
would have opened a second subscription beside the one already billing.

Three defects, each tested here:

1. **The webhook never committed.** Every service on this path is
   written not to commit, because the webhook owns the transaction —
   and the webhook did not. ``get_db`` only closes, so the verified
   payment was built, flushed and discarded while Stripe got a 200 and
   never retried.
2. **Six notification call sites passed the wrong keyword.** No
   membership message had ever been deliverable; ``_safe_emit`` hid it.
3. **A paid-but-pending agreement could be superseded**, which is how a
   member awaiting fulfilment would have been charged twice.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.payment import PaymentTransaction
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.webhooks import collective_membership_handlers as handlers

NOW = datetime.utcnow()


@pytest.fixture(autouse=True)
def billing_on(monkeypatch):
    """Billing on, Stripe unreachable — the suite never spends money."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")


@pytest.fixture
def space(db, make_space, make_user):
    creator = make_user(role="creator")
    s = make_space(creator=creator)
    s.pricing_type = "paid_monthly"
    s.pricing_amount_cents = 599
    s.pricing_currency = "AUD"
    db.flush()
    return s


@pytest.fixture
def member(make_user):
    return make_user()


def _pending(db, space, member, **kw):
    """An agreement in the state the incident left: paid for, pending."""
    kw.setdefault("interval", "month")
    kw.setdefault("interval_count", 1)
    kw.setdefault("amount_cents", 599)
    kw.setdefault("currency", "AUD")
    kw.setdefault("platform_fee_basis_points", 800)
    kw.setdefault("stripe_customer_id", "cus_tom")
    row = CollectiveMembership(
        id=f"cmem_{len(db.query(CollectiveMembership).all())}_5a4b",
        space_id=space.id, user_id=member.id,
        creator_user_id=space.creator_id,
        status=CollectiveMembershipStatus.pending.value,
        created_at=NOW, updated_at=NOW, **kw,
    )
    db.add(row)
    db.flush()
    return row


def _paid_invoice(row, *, invoice_id="in_5a4b_1", amount=599):
    """``invoice.payment_succeeded`` as Stripe sends it."""
    return {
        "id": invoice_id,
        "amount_paid": amount,
        "total": amount,
        "currency": "aud",
        "charge": "ch_5a4b",
        "payment_intent": "pi_5a4b",
        "subscription": "sub_stripe_5a4b",
        "metadata": {"collective_membership_id": row.id},
        "lines": {"data": [{"period": {
            "start": int(NOW.timestamp()),
            "end": int((NOW + timedelta(days=30)).timestamp()),
        }}]},
    }


# ===========================================================================
# 1. The transaction boundary
# ===========================================================================


class TestTheWebhookCommitsItsWork:
    """The defect that lost the money.

    A note on how this is asserted. The suite's ``db`` fixture wraps each
    test in a SAVEPOINT so production code may commit freely without
    escaping the test, which means a literally separate connection
    cannot observe these rows — the outer transaction is never
    committed by design. So persistence is checked the two ways that
    *are* honest here: the handler is proved to call ``commit`` (its
    absence was the whole bug), and the rows are re-read after
    ``expire_all()`` so nothing is being answered from the identity
    map.
    """

    def _counting(self, db):
        calls = {"commit": 0, "rollback": 0}
        real_commit, real_rollback = db.commit, db.rollback
        db.commit = lambda *a, **k: (calls.__setitem__("commit", calls["commit"] + 1), real_commit(*a, **k))[1]  # noqa: E501
        db.rollback = lambda *a, **k: (calls.__setitem__("rollback", calls["rollback"] + 1), real_rollback(*a, **k))[1]  # noqa: E501
        return calls

    def test_a_verified_invoice_is_committed_not_discarded(
        self, db, space, member,
    ):
        space.pricing_type = "paid_monthly"
        space.pricing_amount_cents = 599
        db.flush()
        row = _pending(db, space, member)
        calls = self._counting(db)

        handlers.handle_invoice_payment_succeeded(
            _paid_invoice(row), db, event_id="evt_5a4b",
        )

        assert calls["commit"] >= 1, (
            "the handler did not commit — this is the 19 November defect"
        )
        assert calls["rollback"] == 0

        # Re-read rather than trust the identity map.
        db.expire_all()
        agreement = db.query(CollectiveMembership).filter(
            CollectiveMembership.id == row.id,
        ).one()
        assert agreement.status == CollectiveMembershipStatus.active.value
        assert agreement.activated_at is not None

        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.space_id == space.id,
            PaymentTransaction.payer_user_id == member.id,
        ).one()
        assert txn.gross_amount_cents == 599
        assert txn.platform_fee_basis_points == 800
        assert txn.platform_fee_cents == 48          # 599 * 8% = 47.92
        assert txn.net_creator_amount_cents == 551

        membership = db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == member.id,
        ).one()
        assert membership.status == SpaceMembershipStatus.active

    def test_a_failure_rolls_back_and_is_raised_so_stripe_retries(
        self, db, space, member, monkeypatch,
    ):
        """Silently acknowledging a failure is what loses money."""
        space.pricing_type = "paid_monthly"
        space.pricing_amount_cents = 599
        db.flush()
        row = _pending(db, space, member)
        calls = self._counting(db)

        def _boom(*a, **k):
            raise RuntimeError("fulfilment exploded")

        monkeypatch.setattr(
            "app.webhooks.collective_membership_handlers"
            ".activate_from_first_invoice", _boom,
        )
        with pytest.raises(RuntimeError):
            handlers.handle_invoice_payment_succeeded(
                _paid_invoice(row), db, event_id="evt_boom",
            )
        assert calls["rollback"] >= 1
        assert calls["commit"] == 0

    def test_replaying_the_same_invoice_changes_nothing(
        self, db, space, member,
    ):
        """Recovery depends on this: the fix is replay, not re-charge."""
        space.pricing_type = "paid_monthly"
        space.pricing_amount_cents = 599
        db.flush()
        row = _pending(db, space, member)
        invoice = _paid_invoice(row)

        handlers.handle_invoice_payment_succeeded(invoice, db, event_id="e1")
        handlers.handle_invoice_payment_succeeded(invoice, db, event_id="e2")

        db.expire_all()
        assert db.query(PaymentTransaction).filter(
            PaymentTransaction.space_id == space.id,
            PaymentTransaction.payer_user_id == member.id,
        ).count() == 1
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == member.id,
        ).count() == 1

    def test_every_state_changing_handler_owns_a_transaction(self):
        """The fault was one handler short of a rule, so this is the rule."""
        source = Path(handlers.__file__).read_text()
        for name in (
            "handle_payment_method_setup_completed",
            "handle_one_time_completed",
            "handle_checkout_completed",
            "handle_invoice_payment_succeeded",
            "handle_invoice_payment_failed",
            "handle_subscription_updated",
            "handle_subscription_deleted",
        ):
            assert re.search(rf"@_commits\s*\ndef {name}\(", source), name


# ===========================================================================
# 2. The notification call sites
# ===========================================================================


class TestNotificationsReachTheirCallers:
    """``_safe_emit`` swallowed a ``TypeError`` on every one of them.

    Driven through ``activate_from_first_invoice`` — the real caller —
    rather than by calling the emit function directly, which is what
    the existing tests did and why six broken call sites went unseen.
    """

    def test_the_purchase_message_is_emitted_by_its_real_caller(
        self, db, space, member,
    ):
        from app.comms.models import CommunicationEvent
        from app.services.collective_membership_lifecycle import (
            activate_from_first_invoice,
        )
        space.pricing_type = "paid_monthly"
        space.pricing_amount_cents = 599
        db.flush()
        row = _pending(db, space, member)

        activate_from_first_invoice(
            db, subscription=row, invoice_id="in_emit_1",
            invoice_amount_cents=599, invoice_currency="AUD",
            stripe_subscription_id="sub_x", charge_id="ch_x",
            payment_intent_id="pi_x",
            period_start=NOW, period_end=NOW + timedelta(days=30),
            now=NOW,
        )
        db.flush()
        assert db.query(CommunicationEvent).filter(
            CommunicationEvent.event_type == "collective.membership.purchased",
            CommunicationEvent.subject_id == row.id,
        ).count() == 1

    def test_no_call_site_passes_the_wrong_keyword(self):
        """Every emit takes ``sub``; six callers passed ``subscription``.

        Matched on the call itself, so a doc comment cannot satisfy it.
        """
        root = Path(handlers.__file__).resolve().parents[1]
        offenders = []
        for path in (root / "services").glob("collective_membership_*.py"):
            text = path.read_text()
            for match in re.finditer(
                r"emit_membership_\w+\(\s*db,\s*(\w+)=", text,
            ):
                if match.group(1) != "sub":
                    offenders.append(f"{path.name}: {match.group(0)}")
        assert offenders == [], offenders

    def test_a_broken_message_cannot_undo_a_committed_payment(
        self, db, space, member, monkeypatch,
    ):
        """The property that made the incident survivable."""
        space.pricing_type = "paid_monthly"
        space.pricing_amount_cents = 599
        db.flush()
        row = _pending(db, space, member)

        # Break the emit from *inside*, the way the real defect did.
        # Replacing the exported name instead would replace the
        # ``_safe_emit`` wrapper too — removing the very protection
        # this test exists to prove.
        monkeypatch.setattr(
            "app.comms.events.emit",
            lambda *a, **k: (_ for _ in ()).throw(TypeError("as it was")),
        )
        handlers.handle_invoice_payment_succeeded(
            _paid_invoice(row), db, event_id="evt_emitfail",
        )
        db.expire_all()
        assert db.query(CollectiveMembership).filter(
            CollectiveMembership.id == row.id,
        ).one().status == CollectiveMembershipStatus.active.value


# ===========================================================================
# 3. Never a second charge
# ===========================================================================


class TestAPaidAgreementIsNeverSuperseded:

    def test_an_agreement_with_a_stripe_subscription_blocks_supersede(
        self, db, space, member,
    ):
        from app.services.collective_membership_billing import (
            _payment_may_already_be_taken,
        )
        row = _pending(db, space, member,
                       stripe_subscription_id="sub_already_billing")
        assert _payment_may_already_be_taken(row) is not None

    def test_an_agreement_that_never_opened_a_session_is_free_to_supersede(
        self, db, space, member,
    ):
        from app.services.collective_membership_billing import (
            _payment_may_already_be_taken,
        )
        row = _pending(db, space, member)
        assert _payment_may_already_be_taken(row) is None

    @pytest.mark.parametrize(
        "status,blocked",
        [("open", False), ("expired", False), ("complete", True)],
    )
    def test_the_session_status_decides(
        self, db, space, member, monkeypatch, status, blocked,
    ):
        """``complete`` means paid. ``open`` is a genuinely abandoned
        checkout and must keep working exactly as before."""
        import app.services.collective_membership_billing as billing
        row = _pending(db, space, member,
                       stripe_checkout_session_id="cs_1")
        monkeypatch.setattr(
            billing, "_inspect_session",
            lambda _sid: {"status": status, "url": "https://x"},
        )
        assert (billing._payment_may_already_be_taken(row) is not None) is blocked

    def test_an_unreadable_session_is_treated_as_possibly_paid(
        self, db, space, member, monkeypatch,
    ):
        """Erring towards a second charge is the one unacceptable
        direction."""
        import app.services.collective_membership_billing as billing
        row = _pending(db, space, member,
                       stripe_checkout_session_id="cs_1")
        monkeypatch.setattr(billing, "_inspect_session", lambda _sid: None)
        assert billing._payment_may_already_be_taken(row) is not None

    def test_opening_checkout_refuses_rather_than_charging_again(
        self, db, space, member, monkeypatch,
    ):
        import app.services.collective_membership_billing as billing
        space.pricing_type = "paid_monthly"
        space.pricing_amount_cents = 599
        db.flush()
        _pending(db, space, member,
                 stripe_subscription_id="sub_already_billing",
                 stripe_checkout_session_id="cs_paid")
        monkeypatch.setattr(
            billing, "_inspect_session",
            lambda _sid: {"status": "complete", "url": None},
        )
        with pytest.raises(HTTPException) as caught:
            billing.open_membership_checkout(
                db, space=space, member=member,
                success_url="https://x/ok", cancel_url="https://x/no",
                now=NOW,
            )
        assert caught.value.status_code == 409
        assert caught.value.detail["code"] == "membership_payment_verifying"


class TestTheMemberIsToldTheTruth:

    def test_a_paid_pending_agreement_reports_awaiting_verification(
        self, db, space, member,
    ):
        from app.services.collective_membership_view import (
            awaiting_payment_verification,
        )
        row = _pending(db, space, member,
                       stripe_subscription_id="sub_already_billing")
        assert awaiting_payment_verification(row) is True

    def test_an_abandoned_checkout_does_not(self, db, space, member):
        from app.services.collective_membership_view import (
            awaiting_payment_verification,
        )
        assert awaiting_payment_verification(
            _pending(db, space, member),
        ) is False

    def test_an_active_agreement_is_not_awaiting_anything(
        self, db, space, member,
    ):
        from app.services.collective_membership_view import (
            awaiting_payment_verification,
        )
        row = _pending(db, space, member,
                       stripe_subscription_id="sub_1")
        row.status = CollectiveMembershipStatus.active.value
        db.flush()
        assert awaiting_payment_verification(row) is False
