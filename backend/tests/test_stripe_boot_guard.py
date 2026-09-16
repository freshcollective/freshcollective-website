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


class TestJobRoleStripeRequirement:
    """``FC_SERVICE_ROLE=job`` interaction with the Stripe validator.

    Regression: the fc-creator-subscription-grace-reconciler is DB-only
    and previously failed to boot because the production Stripe check
    fired uniformly for every role. The flag ``FC_JOB_REQUIRES_STRIPE``
    lets a specific DB-only job opt out; jobs that DO call Stripe
    (fc-refund-reconciler) leave the flag at its default True and
    continue to fail-fast on missing config.
    """

    def test_job_role_default_requires_stripe_key_in_production(
        self, clean_env,
    ):
        """Baseline: fc-refund-reconciler (job + implicit
        ``fc_job_requires_stripe=True``) still fails-fast when
        STRIPE_SECRET_KEY is missing."""
        with pytest.raises(ValidationError) as exc:
            _mk_settings(
                app_env="production",
                fc_service_role="job",
                # STRIPE_SECRET_KEY deliberately unset
            )
        assert "STRIPE_SECRET_KEY" in str(exc.value)

    def test_job_role_with_flag_false_boots_without_stripe_key(
        self, clean_env,
    ):
        """Fix: fc-creator-subscription-grace-reconciler sets
        ``FC_JOB_REQUIRES_STRIPE=false`` in its Render env and boots
        cleanly on DATABASE_URL alone (in production)."""
        s = _mk_settings(
            app_env="production",
            fc_service_role="job",
            fc_job_requires_stripe=False,
            # STRIPE_SECRET_KEY deliberately unset
        )
        assert s.stripe_secret_key is None
        assert s.fc_service_role == "job"
        assert s.fc_job_requires_stripe is False

    def test_web_role_still_requires_stripe_regardless_of_flag(
        self, clean_env,
    ):
        """Rule 5 defence: setting ``fc_job_requires_stripe=false`` on
        the WEB service must not weaken the validator — web always
        needs Stripe in production."""
        with pytest.raises(ValidationError) as exc:
            _mk_settings(
                app_env="production",
                fc_service_role="web",
                fc_job_requires_stripe=False,
                # STRIPE_SECRET_KEY deliberately unset
            )
        assert "STRIPE_SECRET_KEY" in str(exc.value)


class TestGraceReconcilerScriptBoot:
    """Smoke: the grace-reconciler script can import + resolve its
    ``sweep_expired_creator_grace`` entry point under the intended
    minimal job env (production + FC_SERVICE_ROLE=job +
    FC_JOB_REQUIRES_STRIPE=false, no Stripe/R2 secrets).

    Doesn't run the cron end-to-end (that requires a live DB) — the
    goal here is to catch Settings-validation regressions before they
    reach Render, which is exactly the failure mode this fix
    addresses.
    """

    def test_settings_boot_with_minimal_grace_reconciler_env(
        self, monkeypatch,
    ):
        """Rebuild Settings from environ under the exact env vars the
        cron declares in ``render.yaml`` (minus DATABASE_URL, which
        Settings requires to exist but doesn't need to be reachable
        for validation)."""
        for name in (
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
            "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET_PRIVATE", "R2_BUCKET_PUBLIC", "R2_PUBLIC_BASE_URL",
            "JWT_SECRET",
        ):
            monkeypatch.delenv(name, raising=False)
        s = Settings(
            database_url="postgresql://test-only",
            app_env="production",
            fc_service_role="job",
            fc_job_requires_stripe=False,
            _env_file=None,
        )
        # None of the "web-only" secrets need to be set for this job
        # to boot cleanly.
        assert s.stripe_secret_key is None
        assert s.stripe_webhook_secret is None
        assert s.jwt_secret is None
