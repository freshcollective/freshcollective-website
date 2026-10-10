"""Reading a setup Session before deciding to supersede it.

``inspect_setup_session`` answers one question — did the member get far
enough that a payment arrangement might exist? — and it has to answer
it through stripe-python 15.x objects, where ``StripeObject.get()``
raises ``AttributeError`` and ``dict(obj)`` raises ``KeyError``. Every
field is therefore read with ``getattr``, and these tests pin that:
a regression to ``.get()`` would fail at runtime in production while
looking perfectly reasonable in review.

The ``usable`` property is the safety gate for the whole supersession
feature. Four independent signals each mean "do not release this plan",
and all four are asserted separately so none can be dropped quietly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import stripe

from app.services.discount_stripe_sessions import StripeUnavailable
from app.services.stripe_finite_plan import (
    SetupSessionState, inspect_setup_session,
)

SESS = "app.services.stripe_finite_plan.stripe.checkout.Session.retrieve"
SI = "app.services.stripe_finite_plan.stripe.SetupIntent.retrieve"
STATUS = "app.services.discount_stripe_sessions.session_status"


def _session(**kw):
    data = {
        "id": "cs_1", "object": "checkout.session", "status": "expired",
        "mode": "setup", "subscription": None, "setup_intent": "seti_1",
        "metadata": {},
    }
    data.update(kw)
    return stripe.checkout.Session.construct_from(data, "sk_test_x")


def _si(**kw):
    data = {"id": "seti_1", "object": "setup_intent",
            "status": "canceled", "payment_method": None}
    data.update(kw)
    return stripe.SetupIntent.construct_from(data, "sk_test_x")


class TestReading:
    def test_it_reads_an_abandoned_session(self):
        with patch(STATUS, return_value="expired"), \
             patch(SESS, return_value=_session()), \
             patch(SI, return_value=_si()):
            st = inspect_setup_session("cs_1")
        assert st == SetupSessionState(
            session_id="cs_1", status="expired", setup_intent_id="seti_1",
            setup_intent_status="canceled", payment_method_id=None,
            subscription_id=None,
        )
        assert st.usable is False

    def test_a_session_with_no_setup_intent_reads_cleanly(self):
        with patch(STATUS, return_value="expired"), \
             patch(SESS, return_value=_session(setup_intent=None)), \
             patch(SI) as si:
            st = inspect_setup_session("cs_1")
        si.assert_not_called()
        assert st.setup_intent_id is None
        assert st.setup_intent_status is None
        assert st.usable is False

    def test_an_expanded_setup_intent_object_is_accepted(self):
        """Stripe returns either an id or the object, depending on expand."""
        with patch(STATUS, return_value="expired"), \
             patch(SESS, return_value=_session(setup_intent=_si())), \
             patch(SI, return_value=_si()) as si:
            st = inspect_setup_session("cs_1")
        si.assert_called_once_with("seti_1")
        assert st.setup_intent_id == "seti_1"

    def test_an_expanded_subscription_object_is_accepted(self):
        sub = stripe.Subscription.construct_from(
            {"id": "sub_9", "object": "subscription"}, "sk_test_x")
        with patch(STATUS, return_value="complete"), \
             patch(SESS, return_value=_session(subscription=sub)), \
             patch(SI, return_value=_si()):
            st = inspect_setup_session("cs_1")
        assert st.subscription_id == "sub_9"
        assert st.usable is True

    def test_no_get_is_used_on_stripe_objects(self):
        """stripe 15.x raises AttributeError on StripeObject.get().

        If the implementation regressed to ``.get()`` this would raise
        rather than return, which is the point of the test.
        """
        with patch(STATUS, return_value="open"), \
             patch(SESS, return_value=_session(status="open")), \
             patch(SI, return_value=_si(status="requires_payment_method")):
            st = inspect_setup_session("cs_1")
        assert st.status == "open"
        assert st.setup_intent_status == "requires_payment_method"


class TestUsableGate:
    @pytest.mark.parametrize("session_kw,si_kw", [
        ({"status": "complete"}, {}),
        ({}, {"status": "succeeded"}),
        ({}, {"payment_method": "pm_1"}),
        ({"subscription": "sub_1"}, {}),
    ])
    def test_each_signal_alone_marks_it_usable(self, session_kw, si_kw):
        status = session_kw.get("status", "expired")
        with patch(STATUS, return_value=status), \
             patch(SESS, return_value=_session(**session_kw)), \
             patch(SI, return_value=_si(**si_kw)):
            assert inspect_setup_session("cs_1").usable is True

    def test_an_open_unused_session_is_not_usable(self):
        with patch(STATUS, return_value="open"), \
             patch(SESS, return_value=_session(status="open")), \
             patch(SI, return_value=_si(status="requires_payment_method")):
            assert inspect_setup_session("cs_1").usable is False


class TestRefusesToGuess:
    def test_an_unreadable_session_raises(self):
        with patch(STATUS, side_effect=StripeUnavailable("down")):
            with pytest.raises(StripeUnavailable):
                inspect_setup_session("cs_1")

    def test_an_unreadable_setup_intent_raises(self):
        with patch(STATUS, return_value="expired"), \
             patch(SESS, return_value=_session()), \
             patch(SI, side_effect=stripe.APIConnectionError("timeout")):
            with pytest.raises(StripeUnavailable):
                inspect_setup_session("cs_1")

    def test_a_session_retrieve_failure_raises(self):
        with patch(STATUS, return_value="expired"), \
             patch(SESS, side_effect=stripe.APIConnectionError("timeout")):
            with pytest.raises(StripeUnavailable):
                inspect_setup_session("cs_1")
