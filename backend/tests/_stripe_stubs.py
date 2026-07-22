"""
Minimal Stripe stubs for tests. We monkey-patch these into the app
modules that call Stripe so tests never hit the network.

We intentionally do NOT bring in an external HTTP mock library —
`unittest.mock` + this tiny helper is enough for what we need.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeSession:
    id: str
    url: str


class FakeSessionsAPI:
    """Records every call to Session.create so tests can inspect."""

    def __init__(self, session_id: str = "cs_test_fake_1", session_url: str = "https://checkout.stripe.test/fake_1"):
        self.session_id = session_id
        self.session_url = session_url
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeSession(id=self.session_id, url=self.session_url)


class FakeCheckoutNamespace:
    def __init__(self, sessions: FakeSessionsAPI) -> None:
        self.Session = sessions


class FakeStripeModule:
    """Just enough surface to satisfy the code under test."""

    def __init__(self):
        self.api_key: str | None = None
        self.sessions = FakeSessionsAPI()
        self.checkout = FakeCheckoutNamespace(self.sessions)


def build_completed_session_payload(
    *,
    session_id: str,
    txn_id: str,
    event_id: str,
    payer_user_id: str,
    space_id: str,
    amount_total: int,
    currency: str,
    payment_intent_id: str = "pi_test_fake_1",
    creator_user_id: str = "",
    platform_fee_bps: str = "800",
) -> dict:
    """Simulate the Stripe SDK's session dict passed into the webhook."""
    return {
        "id": session_id,
        "payment_status": "paid",
        "payment_intent": payment_intent_id,
        "amount_total": amount_total,
        "currency": currency.lower(),
        "metadata": {
            "purchase_type":    "standalone_gathering",
            "transaction_id":   txn_id,
            "event_id":         event_id,
            "space_id":         space_id,
            "payer_user_id":    payer_user_id,
            "creator_user_id":  creator_user_id,
            "platform_fee_bps": platform_fee_bps,
        },
    }


def build_expired_session_payload(session_id: str) -> dict:
    return {"id": session_id}


def build_payment_failed_payload(*, payment_intent_id: str, txn_id: str) -> dict:
    return {
        "id": payment_intent_id,
        "metadata": {
            "purchase_type":  "standalone_gathering",
            "transaction_id": txn_id,
        },
    }
