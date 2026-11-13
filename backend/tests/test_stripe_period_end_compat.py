"""``period_end_from_stripe`` across Stripe API versions.

The bug, found while validating Stage 5A.2 against real test-mode
Stripe: on ``2026-05-27.dahlia`` — the version this account serves — a
Subscription has **no top-level ``current_period_end``**. It moved onto
each subscription item. The helper read only the top level, so against
the real provider response it returned ``None``.

Nothing raised. Two things quietly emptied instead:

* the renewal date on the creator's billing page
  (``creator/routes.py`` builds it from
  ``CreatorSubscription.current_period_end``);
* ``pending_downgrade_effective_at``, which is assigned from the same
  column — so a creator scheduling a downgrade got one with no date.

Only newly-written rows were affected; rows written under an older API
version kept their value, which is why this was invisible.

These tests pin both shapes, because the fix is not "use the new place"
— it is "read either", so that a Stripe account on an older version and
this one both work.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.services.stripe_creator_billing import period_end_from_stripe

#: 13 December 2026, the value a real test-mode subscription returned.
REAL_TS = 1797145396
REAL_DT = datetime.utcfromtimestamp(REAL_TS)


class TestBothProviderShapes:
    def test_the_legacy_top_level_shape(self):
        """What Stripe sent before the move, and still sends on older
        API versions. Must keep working."""
        assert period_end_from_stripe(
            {"id": "sub_1", "current_period_end": REAL_TS},
        ) == REAL_DT

    def test_the_current_item_shape(self):
        """The real payload from ``2026-05-27.dahlia``, trimmed. There
        is no top-level field at all — reading only that returned
        ``None``, which is the bug."""
        payload = {
            "id": "sub_1UbEW0IHWmUObCoGPNIXx31d",
            "status": "active",
            "items": {
                "object": "list",
                "data": [{
                    "id": "si_1",
                    "current_period_start": 1794553396,
                    "current_period_end": REAL_TS,
                }],
            },
        }
        assert "current_period_end" not in payload, (
            "the shape that broke it: no top-level field"
        )
        assert period_end_from_stripe(payload) == REAL_DT

    def test_both_present_agree(self):
        assert period_end_from_stripe({
            "current_period_end": REAL_TS,
            "items": {"data": [{"current_period_end": REAL_TS}]},
        }) == REAL_DT

    def test_several_items_report_the_latest(self):
        """A creator plan has one item. Taking the maximum means a
        subscription that somehow carries several cannot report a period
        ending before one of its items does."""
        early, late = REAL_TS - 86_400, REAL_TS
        assert period_end_from_stripe({
            "items": {"data": [
                {"current_period_end": early},
                {"current_period_end": late},
            ]},
        }) == datetime.utcfromtimestamp(late)


class TestItNeverRaises:
    """A webhook must not fail over a field it can do without."""

    @pytest.mark.parametrize("payload", [
        {},
        {"current_period_end": None},
        {"current_period_end": 0},
        {"items": None},
        {"items": {}},
        {"items": {"data": []}},
        {"items": {"data": [{}]}},
        {"items": {"data": [{"current_period_end": None}]}},
        {"items": {"data": ["not-a-dict"]}},
        {"current_period_end": "next Tuesday"},
        {"items": {"data": [{"current_period_end": "soon"}]}},
    ])
    def test_unusable_input_answers_none(self, payload):
        assert period_end_from_stripe(payload) is None

    def test_junk_beside_a_good_value_still_finds_it(self):
        assert period_end_from_stripe({
            "current_period_end": "junk",
            "items": {"data": ["junk", {"current_period_end": REAL_TS}]},
        }) == REAL_DT


class TestTheTwoThingsThatWereEmpty:
    """The consequences, asserted at their own call sites rather than
    only at the helper — the helper returning a value proves nothing if
    the caller stopped using it."""

    def test_the_renewal_date_is_taken_from_the_subscription_row(self):
        import inspect

        from app.creator import routes
        src = inspect.getsource(routes)
        assert "current_period_end=subscription.current_period_end" in src

    def test_a_scheduled_downgrade_takes_its_date_from_the_same_column(self):
        import inspect

        from app.creator import routes
        src = inspect.getsource(routes)
        assert (
            "pending_downgrade_effective_at = sub.current_period_end" in src
        )

    def test_both_webhook_writers_use_the_helper(self):
        """So fixing the helper fixes both, and neither reads the raw
        field itself."""
        import inspect

        from app.webhooks import creator_billing_handlers
        src = inspect.getsource(creator_billing_handlers)
        assert src.count("scb.period_end_from_stripe(subscription)") == 2

    def test_a_real_shape_subscription_populates_the_column(self):
        """End to end at the helper's boundary: the value that would be
        written is a date, not ``None``."""
        payload = {
            "id": "sub_real",
            "items": {"data": [{"current_period_end": REAL_TS}]},
        }
        written = period_end_from_stripe(payload)
        assert written is not None
        assert written == REAL_DT
