"""Regression: the top-level Stripe webhook dispatcher must not call
``.get()`` on the ``stripe.Event`` returned by
``stripe.Webhook.construct_event``.

``stripe.Event`` is a ``StripeObject`` — supports subscript access
(``event["type"]``) but does NOT expose ``.get()``. A ``.get()``
call raises ``AttributeError: get`` at runtime, which is exactly
what caused the FIP2 in-browser test to 500 during
``checkout.session.completed`` reconciliation.

These tests build a real ``stripe.Event`` StripeObject (NOT a plain
dict) via ``stripe.Event.construct_from`` and drive the dispatcher
through both FIP2 code paths that read ``event.livemode``:

  * ``checkout.session.completed`` with ``purchase_type='finite_plan_setup'``
    metadata — hits the finite-plan setup handler.
  * ``invoice.payment_succeeded`` — hits the invoice handler.

If either dispatcher regressed to ``event.get(...)``, both tests
would fail with ``AttributeError: get``. As long as the dispatcher
uses subscript access, both return HTTP 200 (or the handler's own
safe SkipWebhookEvent semantics), never a 500.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
import stripe
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings


def _make_event(*, event_type: str, event_object: dict) -> stripe.Event:
    """Build a StripeObject event exactly as the SDK would present
    it after ``Webhook.construct_event``. Using ``construct_from`` is
    Stripe's supported way to fabricate a StripeObject for tests."""
    payload = {
        "id": f"evt_test_{uuid.uuid4().hex[:16]}",
        "type": event_type,
        "livemode": False,
        "created": 1_700_000_000,
        "api_version": "2024-10-28.acacia",
        "data": {"object": event_object},
    }
    return stripe.Event.construct_from(payload, "sk_test_dummy")


@pytest.fixture
def client(monkeypatch):
    """A TestClient with Stripe configured and signature verification
    bypassed. Both are needed so ``stripe_webhook`` reaches the
    dispatcher without a real signed request."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")
    return TestClient(app)


class TestDispatcherRejectsStripeObjectGetBug:
    """The tests we would have wanted before the FIP2 in-browser test."""

    def test_checkout_session_completed_stripe_object_dispatches_cleanly(
        self, client, monkeypatch,
    ):
        """A real StripeObject for ``checkout.session.completed`` must
        not crash the dispatcher. This is the exact runtime shape that
        produced the 500 during the browser test."""
        session_obj = {
            "id": f"cs_test_{uuid.uuid4().hex[:16]}",
            "object": "checkout.session",
            "mode": "setup",
            "payment_status": "no_payment_required",
            "metadata": {
                # ``finite_plan_setup`` would normally dispatch to
                # the FIP2 handler; we point at a non-existent plan
                # so the handler falls through to its own
                # ``SkipWebhookEvent`` path — the point of this test
                # is to prove the OUTER dispatcher's ``event.livemode``
                # read doesn't crash, not to test the handler.
                "purchase_type": "finite_plan_setup",
                "purchase_plan_id": "pplan_does_not_exist",
            },
        }
        event = _make_event(
            event_type="checkout.session.completed",
            event_object=session_obj,
        )
        monkeypatch.setattr(stripe.Webhook, "construct_event", lambda **_: event)

        resp = client.post(
            "/api/webhooks/stripe",
            headers={"Stripe-Signature": "irrelevant, mocked"},
            content=b"{}",
        )
        # Would 500 with AttributeError: get if the regression returned.
        assert resp.status_code == 200, (
            f"dispatcher 5xx = regression to event.get(); "
            f"body: {resp.text!r}"
        )
        assert resp.json() == {"received": True}

    def test_invoice_payment_succeeded_stripe_object_dispatches_cleanly(
        self, client, monkeypatch,
    ):
        """Same guarantee for the ``invoice.payment_succeeded`` branch,
        which independently reads ``event.livemode``."""
        invoice_obj = {
            "id": f"in_test_{uuid.uuid4().hex[:16]}",
            "object": "invoice",
            "status": "paid",
            "amount_paid": 2000,
            "currency": "aud",
            "subscription": "sub_does_not_exist",  # → handler SkipWebhookEvent
            "charge": None,
            "payment_intent": None,
        }
        event = _make_event(
            event_type="invoice.payment_succeeded",
            event_object=invoice_obj,
        )
        monkeypatch.setattr(stripe.Webhook, "construct_event", lambda **_: event)

        resp = client.post(
            "/api/webhooks/stripe",
            headers={"Stripe-Signature": "irrelevant, mocked"},
            content=b"{}",
        )
        assert resp.status_code == 200, (
            f"dispatcher 5xx = regression to event.get(); "
            f"body: {resp.text!r}"
        )
        assert resp.json() == {"received": True}

    def test_unhandled_event_type_dispatches_cleanly(
        self, client, monkeypatch,
    ):
        """The else branch also reads ``event["type"]`` — ensure a
        StripeObject flows through it without incident."""
        event = _make_event(
            event_type="customer.updated",
            event_object={"id": "cus_test", "object": "customer"},
        )
        monkeypatch.setattr(stripe.Webhook, "construct_event", lambda **_: event)

        resp = client.post(
            "/api/webhooks/stripe",
            headers={"Stripe-Signature": "irrelevant, mocked"},
            content=b"{}",
        )
        assert resp.status_code == 200
        assert resp.json() == {"received": True}


class TestStripeObjectDoesNotSupportGet:
    """Belt-and-braces: prove the SDK object actually raises when
    ``.get()`` is called. If Stripe ever changes this, we want to
    know — the whole design assumption of the fix depends on it."""

    def test_stripe_event_get_raises_attribute_error(self):
        obj = _make_event(
            event_type="checkout.session.completed",
            event_object={"id": "cs_test"},
        )
        with pytest.raises(AttributeError):
            obj.get("livemode", "default")  # type: ignore[attr-defined]

    def test_stripe_event_subscript_works(self):
        obj = _make_event(
            event_type="checkout.session.completed",
            event_object={"id": "cs_test"},
        )
        assert obj["livemode"] is False
        assert obj["type"] == "checkout.session.completed"
