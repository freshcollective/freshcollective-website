"""Electing to continue early must not forfeit the complimentary term.

A creator on a finite complimentary grant who decides to keep paying
should commit now and be charged when the free period actually ends.
Stripe supports that directly: ``subscription_data.trial_end`` on the
Checkout Session collects the card immediately, creates the
subscription, and issues no invoice until that date.

The constraint worth testing is Stripe's 48-hour floor on
``trial_end``. It is always resolved **forwards** — a creator who elects
inside the final two days gets a little extra free access rather than
being charged before the date they were shown. Charging early to
satisfy an API constraint is the one outcome this must never produce.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.services.stripe_creator_billing import (
    TRIAL_END_MIN_LEAD,
    resolve_deferred_trial_end,
)

NOW = datetime(2027, 3, 21, 12, 0, 0)
ENDS_AT = datetime(2027, 4, 4, 12, 0, 0)


class TestDeferredTrialEnd:
    def test_stripes_floor_is_forty_eight_hours(self):
        assert TRIAL_END_MIN_LEAD == timedelta(hours=48)

    def test_an_early_election_bills_on_the_complimentary_end_date(self):
        assert resolve_deferred_trial_end(ENDS_AT, NOW) == ENDS_AT

    def test_the_creator_keeps_every_remaining_free_day(self):
        """The whole point: electing on day 1 of the renewal window must
        not shorten the term."""
        elected_early = resolve_deferred_trial_end(ENDS_AT, NOW)
        elected_later = resolve_deferred_trial_end(
            ENDS_AT, ENDS_AT - timedelta(days=3),
        )
        assert elected_early == elected_later == ENDS_AT

    def test_a_last_minute_election_is_pushed_out_never_pulled_in(self):
        """Inside the 48-hour floor Stripe will not accept ``ends_at``.
        The resolution direction must be later, never earlier."""
        ends_tomorrow = NOW + timedelta(hours=20)
        resolved = resolve_deferred_trial_end(ends_tomorrow, NOW)
        assert resolved == NOW + TRIAL_END_MIN_LEAD
        assert resolved > ends_tomorrow, (
            "a creator must never be charged before the date they were shown"
        )

    @pytest.mark.parametrize("hours_left", [1, 6, 23, 47])
    def test_no_election_time_ever_charges_before_the_end_date(
        self, hours_left,
    ):
        ends_at = NOW + timedelta(hours=hours_left)
        resolved = resolve_deferred_trial_end(ends_at, NOW)
        assert resolved is not None
        assert resolved >= ends_at

    def test_exactly_on_the_floor_uses_the_end_date(self):
        ends_at = NOW + TRIAL_END_MIN_LEAD
        assert resolve_deferred_trial_end(ends_at, NOW) == ends_at

    def test_an_election_during_grace_bills_immediately(self):
        """The term is already over, so there is nothing left to defer
        and no second free period is granted."""
        assert resolve_deferred_trial_end(NOW - timedelta(days=2), NOW) is None

    def test_no_grant_means_ordinary_billing(self):
        assert resolve_deferred_trial_end(None, NOW) is None


class TestCheckoutSessionCarriesTheTrial:
    """The resolved date must actually reach Stripe, and the metadata
    the webhooks depend on must survive alongside it."""

    def _session_kwargs(self, trial_end):
        from app.models.creator_billing import CreatorPlan
        from app.services import stripe_creator_billing as scb

        plan = CreatorPlan(
            id="cp_x", name="Creator", slug="creator",
            monthly_price_cents=1900, currency="AUD",
            transaction_fee_basis_points=800, collective_limit=1,
            is_active=True,
        )
        user = type("U", (), {"id": "u_1", "email": "c@example.test",
                              "name": "C"})()

        with patch.object(scb, "resolve_price_id", return_value="price_x"), \
             patch.object(scb, "find_or_create_customer", return_value="cus_x"), \
             patch("stripe.checkout.Session.create") as create:
            create.return_value = {"url": "https://checkout.stripe.test/x"}
            scb.create_checkout_session(
                user=user, plan=plan,
                success_url="https://x/ok", cancel_url="https://x/no",
                db=None, trial_end=trial_end,
            )
        return create.call_args.kwargs

    def test_trial_end_is_sent_as_a_unix_timestamp(self):
        kwargs = self._session_kwargs(ENDS_AT)
        assert kwargs["subscription_data"]["trial_end"] == int(ENDS_AT.timestamp())

    def test_metadata_still_travels_with_the_trial(self):
        """The webhooks discriminate on ``subscription_data.metadata``;
        adding a trial must not displace it."""
        kwargs = self._session_kwargs(ENDS_AT)
        assert kwargs["subscription_data"]["metadata"]["purchase_type"] == (
            "creator_subscription"
        )

    def test_no_trial_key_is_sent_when_nothing_is_deferred(self):
        kwargs = self._session_kwargs(None)
        assert "trial_end" not in kwargs["subscription_data"]
        assert kwargs["subscription_data"]["metadata"]["purchase_type"] == (
            "creator_subscription"
        )

    def test_the_subscription_mode_is_unchanged(self):
        kwargs = self._session_kwargs(ENDS_AT)
        assert kwargs["mode"] == "subscription"
        assert kwargs["payment_method_types"] == ["card"]
