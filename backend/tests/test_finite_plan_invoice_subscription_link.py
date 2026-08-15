"""Regression: current Stripe API nests the invoice→subscription
link at ``invoice.parent.subscription_details.subscription``. The
top-level ``invoice.subscription`` field was removed. Our handler
must find the subscription id via the current path AND fall back
to the legacy top-level path for older Stripe API versions —
without ever calling ``.get()`` on a StripeObject (StripeObject
inherits from dict but does not expose ``.get()`` and raises
``AttributeError`` on access).

Covers ``_sfield`` (safe nested reader) and
``_extract_subscription_id`` (invoice-shaped lookup that uses it).
"""

from __future__ import annotations

import uuid
import pytest
import stripe

from app.webhooks.finite_plan_handlers import (
    _extract_subscription_id,
    _sfield,
)


# ---------------------------------------------------------------------------
# _sfield — never uses .get(), safe on both dict and StripeObject
# ---------------------------------------------------------------------------


class TestSFieldOnDict:
    def test_returns_deep_value(self):
        assert _sfield({"a": {"b": {"c": 42}}}, "a", "b", "c") == 42

    def test_missing_intermediate_returns_default(self):
        assert _sfield({"a": {}}, "a", "b", "c") is None
        assert _sfield({"a": {}}, "a", "b", "c", default="fallback") == "fallback"

    def test_missing_top_level_returns_default(self):
        assert _sfield({"a": 1}, "z") is None

    def test_none_interior_returns_default(self):
        assert _sfield({"parent": None}, "parent", "type") is None

    def test_non_subscriptable_interior_returns_default(self):
        assert _sfield({"a": 5}, "a", "b") is None

    def test_zero_path_returns_object(self):
        obj = {"x": 1}
        assert _sfield(obj) is obj


class TestSFieldOnStripeObject:
    """StripeObject raises KeyError on missing subscript AND does
    not expose ``.get()``. The helper must handle both."""

    def _stripe_object(self, payload):
        # ``stripe.Invoice.construct_from`` is the SDK's supported way
        # to produce a real ``StripeObject`` from a dict — matches
        # what ``stripe.Webhook.construct_event`` returns internally.
        return stripe.Invoice.construct_from(payload, "sk_test_dummy")

    def test_returns_deep_value_from_stripe_object(self):
        obj = self._stripe_object({"parent": {"subscription_details": {"subscription": "sub_x"}}})
        assert _sfield(obj, "parent", "subscription_details", "subscription") == "sub_x"

    def test_missing_intermediate_on_stripe_object_returns_default(self):
        obj = self._stripe_object({"parent": {"type": "quote_details"}})
        assert _sfield(obj, "parent", "subscription_details", "subscription") is None

    def test_stripe_object_does_not_expose_get(self):
        """Belt-and-braces: confirm the SDK's StripeObject really raises."""
        obj = self._stripe_object({"a": 1})
        with pytest.raises(AttributeError):
            obj.get("a")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _extract_subscription_id — the semantic call
# ---------------------------------------------------------------------------


def _current_shape_invoice(sub_id: str) -> dict:
    """Invoice payload shape emitted by the current Stripe API."""
    return {
        "id": f"in_test_{uuid.uuid4().hex[:12]}",
        "object": "invoice",
        "status": "paid",
        "amount_paid": 2000,
        "currency": "aud",
        "billing_reason": "subscription_create",
        "parent": {
            "type": "subscription_details",
            "subscription_details": {
                "subscription": sub_id,
                "metadata": {"purchase_plan_id": "pplan_x"},
            },
            "quote_details": None,
        },
    }


def _legacy_shape_invoice(sub_id: str) -> dict:
    """Invoice payload shape emitted by older Stripe API versions."""
    return {
        "id": f"in_test_{uuid.uuid4().hex[:12]}",
        "object": "invoice",
        "status": "paid",
        "amount_paid": 2000,
        "currency": "aud",
        "subscription": sub_id,  # top-level (deprecated)
        # No ``parent`` field on older versions.
    }


class TestExtractSubscriptionIdFromDict:
    def test_current_api_shape(self):
        inv = _current_shape_invoice("sub_current_1")
        assert _extract_subscription_id(inv) == "sub_current_1"

    def test_legacy_api_shape(self):
        inv = _legacy_shape_invoice("sub_legacy_1")
        assert _extract_subscription_id(inv) == "sub_legacy_1"

    def test_non_subscription_invoice_returns_none(self):
        """parent.type != 'subscription_details' (e.g. a quote-generated
        invoice) means this isn't a plan invoice."""
        inv = {
            "id": "in_quote",
            "parent": {
                "type": "quote_details",
                "quote_details": {"quote": "qt_x"},
                "subscription_details": None,
            },
        }
        assert _extract_subscription_id(inv) is None

    def test_malformed_parent_returns_none(self):
        """Any partial/malformed parent — missing type, wrong nested
        shape, missing subscription id — yields None without raising."""
        assert _extract_subscription_id({"parent": {}}) is None
        assert _extract_subscription_id({"parent": None}) is None
        assert _extract_subscription_id({}) is None
        assert _extract_subscription_id(
            {"parent": {"type": "subscription_details"}}
        ) is None
        assert _extract_subscription_id(
            {"parent": {
                "type": "subscription_details",
                "subscription_details": {},   # no subscription key
            }}
        ) is None

    def test_current_shape_takes_precedence_over_legacy(self):
        """When both fields are present, prefer the current API path —
        that's what Stripe fills on the response the SDK sends us today."""
        inv = _current_shape_invoice("sub_current_wins")
        inv["subscription"] = "sub_legacy_should_be_ignored"  # legacy field
        assert _extract_subscription_id(inv) == "sub_current_wins"


class TestExtractSubscriptionIdFromStripeObject:
    """StripeObject shape — real SDK objects, not dicts. Every path
    that ever touches ``event.data.object`` or a
    ``stripe.Invoice.retrieve`` result must work here."""

    def _stripe_object(self, payload):
        # ``stripe.Invoice.construct_from`` is the SDK's supported way
        # to produce a real ``StripeObject`` from a dict — matches
        # what ``stripe.Webhook.construct_event`` returns internally.
        return stripe.Invoice.construct_from(payload, "sk_test_dummy")

    def test_current_shape_on_stripe_object(self):
        obj = self._stripe_object(_current_shape_invoice("sub_so_current"))
        assert _extract_subscription_id(obj) == "sub_so_current"

    def test_legacy_shape_on_stripe_object(self):
        obj = self._stripe_object(_legacy_shape_invoice("sub_so_legacy"))
        assert _extract_subscription_id(obj) == "sub_so_legacy"

    def test_non_subscription_on_stripe_object(self):
        obj = self._stripe_object({
            "id": "in_quote_so",
            "parent": {
                "type": "quote_details",
                "quote_details": {"quote": "qt_so"},
                "subscription_details": None,
            },
        })
        assert _extract_subscription_id(obj) is None
