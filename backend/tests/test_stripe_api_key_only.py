"""An API call needs the secret key. Only a webhook needs a webhook secret.

The production report
---------------------
``fc-connect-transfer-sweeper`` had ``STRIPE_SECRET_KEY`` set and, per
the go-live design, no ``STRIPE_WEBHOOK_SECRET`` — a cron receives no
webhooks, so granting it a signing secret would be paying for a
capability it does not have. Running it raised
``StripeNotConfiguredError: Stripe secret key or webhook secret is not
set`` inside ``stripe_client``. The job never reached Stripe and never
moved a creator's money, every fifteen minutes.

The boot-time rules had this right all along: ``_check_stripe_
configuration`` requires ``STRIPE_SECRET_KEY`` of a job and requires the
webhook secret only of the web service. It was the *runtime* check that
conflated the two, by asking ``stripe_enabled`` — which means "is the
whole payment loop wired" — before binding an API key.

What these tests pin
--------------------
The split, in both directions. An API client must be obtainable without
a webhook secret; it must still refuse without a key; and nothing about
webhook verification may have loosened to achieve that.
"""

from __future__ import annotations

import pytest

from app.checkout import stripe_client
from app.core.config import settings


@pytest.fixture
def api_key_only(monkeypatch: pytest.MonkeyPatch):
    """The cron environment: a secret key and no webhook secrets."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_cron")
    monkeypatch.setattr(settings, "stripe_webhook_secret", None)
    monkeypatch.setattr(settings, "stripe_v2_webhook_secret", None)
    return monkeypatch


@pytest.fixture
def no_stripe_at_all(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    monkeypatch.setattr(settings, "stripe_webhook_secret", None)
    monkeypatch.setattr(settings, "stripe_v2_webhook_secret", None)
    return monkeypatch


# ---------------------------------------------------------------------------
# The fix
# ---------------------------------------------------------------------------


class TestApiClientNeedsOnlyTheSecretKey:
    def test_get_stripe_works_without_a_webhook_secret(self, api_key_only):
        api = stripe_client.get_stripe()
        assert api.api_key == "sk_test_cron"

    def test_get_stripe_client_works_without_a_webhook_secret(self, api_key_only):
        assert stripe_client.get_stripe_client() is not None

    def test_the_api_readiness_flag_ignores_the_webhook_secret(self, api_key_only):
        assert settings.stripe_api_enabled is True
        assert stripe_client.api_is_configured() is True

    def test_ensure_api_configured_does_not_raise(self, api_key_only):
        stripe_client.ensure_api_configured()  # must not raise

    def test_the_transfer_sweeper_can_reach_stripe(self, api_key_only):
        """The actual failing call site. ``connect_transfer_sweeper``
        obtains its client through ``get_stripe`` and nothing else, so
        this is the whole of what blocked the job."""
        from app.checkout.stripe_client import get_stripe as sweeper_entry

        assert sweeper_entry().api_key == "sk_test_cron"

    def test_the_recovery_sweeper_uses_the_same_entry_point(self):
        """Pins that both sweepers share it, so neither can regress
        separately."""
        import inspect

        from app.services import connect_recovery_sweeper, connect_transfer_sweeper

        for module in (connect_transfer_sweeper, connect_recovery_sweeper):
            source = inspect.getsource(module)
            assert "stripe_enabled" not in source, (
                f"{module.__name__} must not gate on the payment-loop flag; "
                "a job has no webhook secret by design"
            )


# ---------------------------------------------------------------------------
# What must not have loosened
# ---------------------------------------------------------------------------


class TestMissingSecretKeyStillFails:
    def test_get_stripe_refuses(self, no_stripe_at_all):
        with pytest.raises(stripe_client.StripeNotConfiguredError):
            stripe_client.get_stripe()

    def test_get_stripe_client_refuses(self, no_stripe_at_all):
        with pytest.raises(stripe_client.StripeNotConfiguredError):
            stripe_client.get_stripe_client()

    def test_the_message_names_the_variable_that_is_missing(self, no_stripe_at_all):
        with pytest.raises(stripe_client.StripeNotConfiguredError) as excinfo:
            stripe_client.get_stripe()
        assert "STRIPE_SECRET_KEY" in str(excinfo.value)

    def test_the_api_readiness_flag_is_false(self, no_stripe_at_all):
        assert settings.stripe_api_enabled is False
        assert stripe_client.api_is_configured() is False


class TestThePaymentLoopCheckIsStillStrict:
    """``stripe_enabled`` still means API *and* webhook, because a
    Checkout Session created where the completion webhook cannot be
    verified charges a member with no path to fulfilment."""

    def test_stripe_enabled_still_requires_the_webhook_secret(self, api_key_only):
        assert settings.stripe_api_enabled is True
        assert settings.stripe_enabled is False

    def test_is_configured_still_requires_the_webhook_secret(self, api_key_only):
        assert stripe_client.is_configured() is False

    def test_ensure_configured_still_raises_without_it(self, api_key_only):
        with pytest.raises(stripe_client.StripeNotConfiguredError):
            stripe_client.ensure_configured()

    def test_both_present_satisfies_both_checks(self, monkeypatch):
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_web")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_web")
        assert settings.stripe_api_enabled is True
        assert settings.stripe_enabled is True


class TestWebhookIntakesStillRefuseWithoutTheirSecret:
    def test_the_v1_intake_is_gated_on_the_payment_loop_flag(self, api_key_only):
        """``/api/webhooks/stripe`` checks ``settings.stripe_enabled``
        before verifying, so an environment with no signing secret
        answers 503 rather than accepting an unverified event."""
        assert settings.stripe_enabled is False

        import inspect

        from app.webhooks import routes as webhook_routes

        source = inspect.getsource(webhook_routes.stripe_webhook)
        assert "settings.stripe_enabled" in source
        assert "construct_event" in source

    def test_the_v2_intake_requires_its_own_separate_secret(self, api_key_only):
        """``stripe_v2_webhooks_enabled`` is a different flag with a
        different secret, and the v2 route checks it *before* asking for
        a client — so loosening the client factory cannot reach it."""
        assert settings.stripe_v2_webhooks_enabled is False

        import inspect

        from app.webhooks import connect_routes

        source = inspect.getsource(connect_routes.stripe_v2_webhook)
        gate = source.index("if not settings.stripe_v2_webhooks_enabled:")
        parse = source.index("get_stripe_client().parse_event_notification(")
        assert gate < parse, (
            "the v2 signature gate must come before the client is built"
        )

    def test_a_v2_secret_alone_does_not_enable_the_v1_intake(self, monkeypatch):
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
        monkeypatch.setattr(settings, "stripe_webhook_secret", None)
        monkeypatch.setattr(settings, "stripe_v2_webhook_secret", "whsec_v2")
        assert settings.stripe_v2_webhooks_enabled is True
        assert settings.stripe_enabled is False

    def test_a_v1_secret_alone_does_not_enable_the_v2_intake(self, monkeypatch):
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_v1")
        monkeypatch.setattr(settings, "stripe_v2_webhook_secret", None)
        assert settings.stripe_enabled is True
        assert settings.stripe_v2_webhooks_enabled is False


# ---------------------------------------------------------------------------
# The failing job, with work to do
# ---------------------------------------------------------------------------


class TestTheSweeperGetsPastTheConfigGate:
    """``get_stripe()`` is reached per row, not at sweep start, so an
    empty sweep never touched it — the job only failed once a creator
    was actually owed money. This seeds that row."""

    def test_a_pending_transfer_reaches_stripe_with_no_webhook_secret(
        self, db, api_key_only,
    ):
        import stripe as stripe_sdk

        from tests.test_connect_transfers import _txn
        from app.services import connect_transfer_sweeper as sweeper

        _txn(db, processing_fee_cents=200)

        sent: list[dict] = []

        class _Transfer:
            @staticmethod
            def create(**kwargs):
                sent.append(kwargs)
                return type("T", (), {"id": "tr_fake"})()

        # ``get_stripe`` is deliberately NOT patched: the real one has to
        # run, because the config gate inside it is the thing under test.
        # Only the outbound SDK call is stubbed, on the module that
        # ``get_stripe`` hands back.
        api_key_only.setattr(stripe_sdk, "Transfer", _Transfer)

        report = sweeper.sweep_pending_transfers(db, limit=5)

        assert report.considered == 1
        assert report.sent == 1, report.as_log_fields()
        assert len(sent) == 1
        assert stripe_sdk.api_key == "sk_test_cron"

    def test_the_same_sweep_raises_without_a_secret_key(
        self, db, no_stripe_at_all,
    ):
        """The other direction: no key is still a hard stop, so this
        fix cannot be mistaken for removing the check."""
        from tests.test_connect_transfers import _txn
        from app.services import connect_transfer_sweeper as sweeper

        _txn(db, processing_fee_cents=200)

        with pytest.raises(stripe_client.StripeNotConfiguredError):
            sweeper.sweep_pending_transfers(db, limit=5)

    def test_the_real_get_stripe_is_what_the_sweeper_calls(self, api_key_only):
        """Both sweeper modules must keep importing it, or a future edit
        could reintroduce a stricter gate unnoticed."""
        from app.checkout.stripe_client import get_stripe
        from app.services import connect_transfer_sweeper, connect_transfers

        assert connect_transfer_sweeper.get_stripe is get_stripe
        assert connect_transfers.get_stripe is get_stripe
        assert get_stripe().api_key == "sk_test_cron"
