"""FIP4A — the member is told when their first payment is declined.

Before this, a declined first instalment was completely silent: the
plan was terminated, the Stripe schedule cancelled and Rule D
unblocked, but nothing reached the member. They had saved a card, been
shown "we're confirming your payment plan and access", and then heard
nothing ever again.

This adds ``purchase.first_payment_failed`` on the shared termination
path. **No lifecycle behaviour changes** — the assertions below
re-pin the FIP4A state machine alongside the new communication
precisely so a future change cannot quietly alter one while adding to
the other.

Reuses the harness in ``test_fip4a_first_payment.py`` (``pending_plan``,
``_Stripe``, ``_do_setup_completed``) rather than rebuilding it, so
these tests exercise the real handler path.
"""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest
import stripe

import app.comms.templates  # noqa: F401 — registers templates
import app.comms.routing.resolvers  # noqa: F401 — registers resolvers
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, get_resolver_for
from app.comms.templates.registry import get_template_for
from app.models.purchase_plan import PurchasePlanStatus

# Harness from the sibling FIP4A suite — same fixtures, same handler.
from tests.test_fip4a_first_payment import (  # noqa: F401
    _Stripe,
    _do_setup_completed,
    pending_plan,
)


EVENT_TYPE = "purchase.first_payment_failed"


@pytest.fixture(autouse=True)
def _no_dispatch():
    """Assert on emitted events, never on delivery."""
    with patch("app.comms.rollout.schedule_routing_if_needed", return_value=None):
        yield


def _events(db, plan_id: str) -> list[CommunicationEvent]:
    return (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.event_type == EVENT_TYPE,
            CommunicationEvent.subject_id == plan_id,
        )
        .all()
    )


def _decline() -> stripe.CardError:
    return stripe.CardError(
        "Your card was declined.", param=None, code="card_declined",
    )


# ---------------------------------------------------------------------------
# Synchronous card decline
# ---------------------------------------------------------------------------


class TestSynchronousDecline:
    def test_emits_exactly_one_communication(self, db, pending_plan):
        s = pending_plan
        with _Stripe(raise_on_pay=_decline()):
            _do_setup_completed(
                db, session={"id": s.session_id}, plan_id=s.plan.id,
                event_livemode=False,
            )
        evs = _events(db, s.plan.id)
        assert len(evs) == 1
        assert evs[0].payload["experience_name"]
        assert evs[0].payload["retry_url"]

    def test_lifecycle_behaviour_is_unchanged(self, db, pending_plan):
        """The whole point of Option 1: comms added, state machine
        untouched."""
        from app.models.platform import PathwayEntitlement
        s = pending_plan
        with _Stripe(raise_on_pay=_decline()) as stripe_mock:
            _do_setup_completed(
                db, session={"id": s.session_id}, plan_id=s.plan.id,
                event_livemode=False,
            )
        db.refresh(s.plan)
        # Plan terminated, not left pending.
        assert s.plan.status == PurchasePlanStatus.failed
        assert (s.plan.cancelled_reason or "").startswith("first_payment_failed")
        assert s.plan.cancelled_at is not None
        # Provider schedule cancelled exactly once — unchanged.
        assert stripe_mock.schedule_cancel_calls == 1
        # No access.
        assert db.query(PathwayEntitlement).filter(
            PathwayEntitlement.user_id == s.member.id,
        ).count() == 0

    def test_a_replayed_delivery_does_not_email_twice(self, db, pending_plan):
        """Stripe redelivers the same session. The already-failed guard
        returns before the emit, and the plan-scoped dedupe key is the
        second line of defence."""
        s = pending_plan
        for _ in range(3):
            with _Stripe(raise_on_pay=_decline()):
                _do_setup_completed(
                    db, session={"id": s.session_id}, plan_id=s.plan.id,
                    event_livemode=False,
                )
        assert len(_events(db, s.plan.id)) == 1

    def test_comms_failure_never_breaks_termination(self, db, pending_plan):
        """A broken emit must not leave a live Stripe schedule behind."""
        s = pending_plan
        with patch(
            "app.services.purchase_lifecycle_emit.emit_first_payment_failed",
            side_effect=RuntimeError("comms down"),
        ):
            with _Stripe(raise_on_pay=_decline()) as stripe_mock:
                _do_setup_completed(
                    db, session={"id": s.session_id}, plan_id=s.plan.id,
                    event_livemode=False,
                )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.failed
        assert stripe_mock.schedule_cancel_calls == 1


# ---------------------------------------------------------------------------
# Non-paid invoice status (e.g. 3DS requires_action)
# ---------------------------------------------------------------------------


class TestNonPaidStatusTerminates:
    def test_also_emits_and_carries_the_invoice_id(self, db, pending_plan):
        s = pending_plan
        with _Stripe(first_invoice_status="requires_action"):
            _do_setup_completed(
                db, session={"id": s.session_id}, plan_id=s.plan.id,
                event_livemode=False,
            )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.failed
        evs = _events(db, s.plan.id)
        assert len(evs) == 1
        # This path has an invoice id; the card-decline path does not,
        # which is why dedupe is keyed on the plan rather than the
        # invoice.
        assert evs[0].payload["invoice_id"]


# ---------------------------------------------------------------------------
# Dedupe identity
# ---------------------------------------------------------------------------


class TestDedupeKey:
    def test_key_is_plan_scoped_and_survives_a_missing_invoice(
        self, db, pending_plan,
    ):
        s = pending_plan
        with _Stripe(raise_on_pay=_decline()):
            _do_setup_completed(
                db, session={"id": s.session_id}, plan_id=s.plan.id,
                event_livemode=False,
            )
        ev = _events(db, s.plan.id)[0]
        assert ev.dedupe_key == f"first_payment_failed:{s.plan.id}"
        # The card-decline path genuinely has no invoice id — an
        # invoice-keyed dedupe would have had nothing to key on.
        assert ev.payload["invoice_id"] is None

    def test_the_key_does_not_depend_on_the_invoice(self, db, pending_plan):
        """Two deliveries quoting different invoices for the same dead
        plan must still collapse to one email. (The end-to-end replay
        behaviour is covered by
        ``test_a_replayed_delivery_does_not_email_twice`` through the
        real handler — the savepoint fixture cannot host
        emit-commit-emit directly.)"""
        s = pending_plan
        with _Stripe(raise_on_pay=_decline()):
            _do_setup_completed(
                db, session={"id": s.session_id}, plan_id=s.plan.id,
                event_livemode=False,
            )
        ev = _events(db, s.plan.id)[0]
        assert ev.dedupe_key == f"first_payment_failed:{s.plan.id}"
        assert "in_" not in ev.dedupe_key


# ---------------------------------------------------------------------------
# Unchanged neighbours
# ---------------------------------------------------------------------------


class TestNeighbouringBehaviourUnchanged:
    def test_a_successful_first_payment_emits_no_failure_event(
        self, db, pending_plan,
    ):
        s = pending_plan
        with _Stripe(first_invoice_status="paid"):
            _do_setup_completed(
                db, session={"id": s.session_id}, plan_id=s.plan.id,
                event_livemode=False,
            )
        assert _events(db, s.plan.id) == []
        db.refresh(s.plan)
        # Activation is the succeeded-webhook's job, not this handler's.
        assert s.plan.status == PurchasePlanStatus.pending_setup

    def test_later_instalment_failure_still_uses_the_dunning_event(
        self, db, pending_plan,
    ):
        """An ``active`` plan keeps FIP3 grace semantics and the
        existing ``payment.instalment_failed`` email — the new event
        must not leak into that path."""
        from app.services.finite_plan_lifecycle import (
            handle_invoice_failed_for_plan,
        )
        s = pending_plan
        s.plan.status = PurchasePlanStatus.active
        s.plan.installments_paid = 1
        db.flush()

        from datetime import datetime
        outcome = handle_invoice_failed_for_plan(
            db, plan=s.plan, invoice_id="in_later_1",
            failed_at=datetime.utcnow(),
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.payment_problem
        assert s.plan.grace_expires_at is not None
        # The new event is for first payments only.
        assert _events(db, s.plan.id) == []
        assert outcome.transitioned_to == PurchasePlanStatus.payment_problem.value


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------


def _render(**ctx):
    return get_template_for(EVENT_TYPE, CHANNEL_EMAIL_TRANSACTIONAL).render(
        None, None,
        ResolvedRecipient(
            user_id="u", role_in_event="buyer", human_reason="h",
            template_context=ctx,
        ),
    )


class TestCopy:
    @pytest.fixture
    def html(self):
        return _render(
            first_name="Ada", experience_name="EMBODY — All sessions",
            retry_url="https://fc.test/spaces/embody/offers/all",
            amount_cents=3780, currency="AUD", installments_expected=10,
        ).body_html

    def test_subject(self):
        assert _render(experience_name="X").subject == (
            "Your payment didn't go through"
        )

    def test_states_the_three_reassurances(self, html):
        assert "hasn't started" in html
        assert "No access has been activated" in html
        assert "haven't been charged" in html

    def test_never_promises_an_automatic_retry(self, html):
        """FIP4A cancels the schedule — nothing retries on its own, and
        saying otherwise would be the same error we just fixed on the
        Stripe setup page."""
        lowered = html.lower()
        assert "automatically" not in lowered
        assert "we'll try again" not in lowered
        assert "stripe will" not in lowered

    def test_does_not_reuse_the_dunning_reassurance(self, html):
        """``payment.instalment_failed`` says access continues. Here it
        never started — the opposite claim."""
        assert "still active" not in html
        assert "access remains" not in html.lower()

    def test_cta_returns_to_the_existing_offer(self, html):
        m = re.search(
            r'<a href="([^"]+)"\s+style="[^"]*border-radius:999px[^"]*">'
            r'\s*(.*?)\s*</a>', html, re.S,
        )
        assert m is not None
        assert m.group(1) == "https://fc.test/spaces/embody/offers/all"
        assert m.group(2).strip() == "Try payment again"

    def test_no_cta_when_no_url_is_available(self):
        html = _render(experience_name="X", retry_url="").body_html
        assert "or copy this link:" not in html

    def test_uses_the_shared_branded_shell(self, html):
        assert html.lstrip().startswith("<!DOCTYPE html>")
        assert "#F5F0E8" in html
        assert "text-transform:uppercase" not in html

    def test_escapes_the_offer_name(self):
        html = _render(
            experience_name='<img src=x onerror="alert(1)">',
        ).body_html
        assert "<img" not in html
        assert "&lt;img src=x" in html

    def test_resolver_targets_the_buyer(self, db):
        ev = CommunicationEvent(
            id="ce_fp", event_type=EVENT_TYPE, actor_user_id="u_buyer",
            payload={"first_name": "Ada", "experience_name": "X",
                     "retry_url": "https://fc.test/x"},
        )
        recipients = get_resolver_for(EVENT_TYPE).resolve(db, ev)
        assert [r.user_id for r in recipients] == ["u_buyer"]
