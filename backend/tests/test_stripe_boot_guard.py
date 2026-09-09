"""Phase 1 — boot-time Stripe configuration guard.

``Settings()`` refuses to instantiate under four conditions:

  1. ``APP_ENV=production`` with either Stripe var missing — production
     must not silently degrade to "checkout returns 503".
  2. ``sk_live_*`` in ``STRIPE_SECRET_KEY`` when ``APP_ENV`` is not
     production — a live key in a sandbox can charge real cards.
  3. ``sk_test_*`` in production — real member purchases would clear
     against play money.
  4. Whitespace on either var is trimmed in place; a whitespace-only
     value is normalised to "unset" so it participates in rule 1.

Fires at ``Settings()`` instantiation — on Render, fc-api's process
start. A ``ValidationError`` there aborts the deploy; the previous
image keeps serving. See ``_check_stripe_configuration`` in
``app.core.config``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# R2 has its own boot-time model_validator that fires before the
# Stripe one when ``app_env=production``. Supply a valid R2 config in
# every production-mode test so the R2 check is a no-op and we're
# actually asserting Stripe rules.
_VALID_R2 = {
    "r2_account_id": "a" * 32,
    "r2_access_key_id": "test-access",
    "r2_secret_access_key": "test-secret",
    "r2_bucket_private": "priv",
    "r2_bucket_public": "pub",
    "r2_public_base_url": "https://cdn.test",
}


def _mk_settings(**kwargs) -> Settings:
    """Instantiate Settings without loading .env so tests only see
    what's passed in."""
    defaults = {
        "database_url": "postgresql://test-only",
        "jwt_secret": "test-only",
        "_env_file": None,
    }
    if kwargs.get("app_env") == "production":
        defaults.update(_VALID_R2)
    defaults.update(kwargs)
    return Settings(**defaults)


class TestProductionRequiresBothStripeVars:
    def test_production_with_no_stripe_vars_refuses_to_boot(self, clean_env):
        with pytest.raises(ValidationError) as exc:
            _mk_settings(app_env="production")
        msg = str(exc.value)
        assert "Stripe is required in production" in msg
        assert "STRIPE_SECRET_KEY" in msg
        assert "STRIPE_WEBHOOK_SECRET" in msg

    def test_production_missing_webhook_secret_refuses(self, clean_env):
        with pytest.raises(ValidationError) as exc:
            _mk_settings(
                app_env="production",
                stripe_secret_key="sk_live_deadbeef",
            )
        assert "STRIPE_WEBHOOK_SECRET" in str(exc.value)

    def test_production_missing_secret_key_refuses(self, clean_env):
        with pytest.raises(ValidationError) as exc:
            _mk_settings(
                app_env="production",
                stripe_webhook_secret="whsec_deadbeef",
            )
        assert "STRIPE_SECRET_KEY" in str(exc.value)

    def test_production_with_both_live_vars_boots(self, clean_env):
        s = _mk_settings(
            app_env="production",
            stripe_secret_key="sk_live_realkey",
            stripe_webhook_secret="whsec_realsecret",
        )
        assert s.stripe_enabled is True
        assert s.stripe_mode == "live"


class TestLiveKeyBlockedOutsideProduction:
    def test_dev_with_live_key_refuses(self, clean_env):
        with pytest.raises(ValidationError) as exc:
            _mk_settings(
                app_env="development",
                stripe_secret_key="sk_live_deadbeef",
                stripe_webhook_secret="whsec_x",
            )
        msg = str(exc.value)
        assert "LIVE key" in msg
        assert "development" in msg

    def test_staging_with_live_key_refuses(self, clean_env):
        with pytest.raises(ValidationError) as exc:
            _mk_settings(
                app_env="staging",
                stripe_secret_key="sk_live_deadbeef",
                stripe_webhook_secret="whsec_x",
            )
        assert "LIVE key" in str(exc.value)


class TestTestKeyBlockedInProduction:
    def test_production_with_test_key_refuses(self, clean_env):
        with pytest.raises(ValidationError) as exc:
            _mk_settings(
                app_env="production",
                stripe_secret_key="sk_test_deadbeef",
                stripe_webhook_secret="whsec_x",
            )
        msg = str(exc.value)
        assert "TEST key" in msg
        assert "production" in msg.lower()


class TestLocalDevWithoutStripeIsFine:
    def test_no_stripe_vars_in_dev_boots(self, clean_env):
        s = _mk_settings(app_env="development")
        assert s.stripe_enabled is False
        assert s.stripe_mode == "test"

    def test_test_key_in_dev_boots(self, clean_env):
        s = _mk_settings(
            app_env="development",
            stripe_secret_key="sk_test_deadbeef",
            stripe_webhook_secret="whsec_x",
        )
        assert s.stripe_enabled is True
        assert s.stripe_mode == "test"


class TestWhitespaceIsTrimmed:
    def test_leading_trailing_whitespace_trimmed(self, clean_env):
        s = _mk_settings(
            app_env="development",
            stripe_secret_key="  sk_test_x  \n",
            stripe_webhook_secret=" whsec_x ",
        )
        assert s.stripe_secret_key == "sk_test_x"
        assert s.stripe_webhook_secret == "whsec_x"

    def test_whitespace_only_normalised_to_missing_and_triggers_rule2(
        self, clean_env,
    ):
        """Rule 2 (production requires both) should still fire when
        an env var is set but contains only whitespace."""
        with pytest.raises(ValidationError) as exc:
            _mk_settings(
                app_env="production",
                stripe_secret_key="   ",
                stripe_webhook_secret="   ",
            )
        assert "STRIPE_SECRET_KEY" in str(exc.value)
