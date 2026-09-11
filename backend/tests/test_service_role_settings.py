"""Least-privilege Settings validation for background jobs.

Covers ``FC_SERVICE_ROLE=job`` for services like fc-refund-reconciler
and fc-fip3-grace-reconciler that never touch uploads or auth
encode/decode:

* Job role in production boots without R2 credentials.
* Job role in production boots without JWT_SECRET.
* Job role in production boots without STRIPE_WEBHOOK_SECRET.
* Job role still requires STRIPE_SECRET_KEY in production
  (needed for Stripe API calls).
* Job role still refuses a live Stripe key outside production.

* Web role (default) production boots STILL refuse without R2
  (no weakening of the fc-api production boot invariants).
* Web role production boots STILL refuse without JWT_SECRET.
* Web role production boots STILL refuse without STRIPE_WEBHOOK_SECRET.

Uses a helper that clears every relevant env var + constructs a
fresh Settings instance, so tests don't share state.
"""

from __future__ import annotations

import os

import pytest


_KEYS = (
    "APP_ENV", "FC_SERVICE_ROLE",
    "DATABASE_URL", "JWT_SECRET",
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
    "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_PRIVATE", "R2_BUCKET_PUBLIC", "R2_PUBLIC_BASE_URL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)


def _make(monkeypatch, **env):
    # Every Settings instance in these tests reads env directly rather
    # than the .env file — makes the test's declared env authoritative.
    monkeypatch.setenv("DATABASE_URL", env.pop(
        "DATABASE_URL", "postgresql://localhost/fc_test",
    ))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.core.config import Settings
    return Settings(_env_file=None)


class TestJobRole:
    def test_production_job_boots_without_r2(self, monkeypatch):
        s = _make(
            monkeypatch,
            APP_ENV="production",
            FC_SERVICE_ROLE="job",
            STRIPE_SECRET_KEY="sk_live_abc",
        )
        assert s.app_env == "production"
        assert s.fc_service_role == "job"
        assert s.r2_account_id is None
        assert s.is_r2_enabled is False

    def test_production_job_boots_without_jwt_secret(self, monkeypatch):
        s = _make(
            monkeypatch,
            APP_ENV="production",
            FC_SERVICE_ROLE="job",
            STRIPE_SECRET_KEY="sk_live_abc",
        )
        assert s.jwt_secret is None

    def test_production_job_boots_without_stripe_webhook_secret(self, monkeypatch):
        s = _make(
            monkeypatch,
            APP_ENV="production",
            FC_SERVICE_ROLE="job",
            STRIPE_SECRET_KEY="sk_live_abc",
        )
        assert s.stripe_webhook_secret is None

    def test_production_job_still_requires_stripe_secret_key(self, monkeypatch):
        # Job services that use Stripe (like fc-refund-reconciler) must
        # still have the API key. Missing it in production is a real
        # deploy-time failure.
        with pytest.raises(ValueError, match="STRIPE_SECRET_KEY"):
            _make(
                monkeypatch,
                APP_ENV="production",
                FC_SERVICE_ROLE="job",
            )

    def test_job_role_still_refuses_live_key_outside_production(self, monkeypatch):
        # Live-key protection applies to both roles — a job with a
        # live key must be in production.
        with pytest.raises(ValueError, match="LIVE key"):
            _make(
                monkeypatch,
                APP_ENV="development",
                FC_SERVICE_ROLE="job",
                STRIPE_SECRET_KEY="sk_live_something",
            )


class TestWebRoleUnaffected:
    def test_production_web_still_refuses_missing_r2(self, monkeypatch):
        with pytest.raises(ValueError, match="R2 storage is required"):
            _make(
                monkeypatch,
                APP_ENV="production",
                FC_SERVICE_ROLE="web",
                JWT_SECRET="test-jwt",
                STRIPE_SECRET_KEY="sk_live_abc",
                STRIPE_WEBHOOK_SECRET="whsec_abc",
            )

    def test_production_web_default_role_still_refuses_missing_r2(self, monkeypatch):
        # Not setting FC_SERVICE_ROLE at all → defaults to 'web' →
        # R2 still required.
        with pytest.raises(ValueError, match="R2 storage is required"):
            _make(
                monkeypatch,
                APP_ENV="production",
                JWT_SECRET="test-jwt",
                STRIPE_SECRET_KEY="sk_live_abc",
                STRIPE_WEBHOOK_SECRET="whsec_abc",
            )

    def test_web_role_still_requires_jwt_secret(self, monkeypatch):
        # Missing JWT_SECRET on web role → fails (auth encode/decode
        # would 500 at request time).
        with pytest.raises(ValueError, match="JWT_SECRET is required"):
            _make(
                monkeypatch,
                APP_ENV="development",
                FC_SERVICE_ROLE="web",
            )

    def test_production_web_still_requires_stripe_webhook_secret(self, monkeypatch):
        # Web role in production needs BOTH stripe vars.
        with pytest.raises(ValueError, match="STRIPE_WEBHOOK_SECRET"):
            _make(
                monkeypatch,
                APP_ENV="production",
                FC_SERVICE_ROLE="web",
                JWT_SECRET="test-jwt",
                STRIPE_SECRET_KEY="sk_live_abc",
                # Fully configured R2 so the R2 validator doesn't fire first.
                R2_ACCOUNT_ID="0123456789abcdef0123456789abcdef",
                R2_ACCESS_KEY_ID="ak",
                R2_SECRET_ACCESS_KEY="sk",
                R2_BUCKET_PRIVATE="priv",
                R2_BUCKET_PUBLIC="pub",
                R2_PUBLIC_BASE_URL="https://cdn.example.test",
            )


class TestServiceRoleValidation:
    def test_unknown_role_rejected(self, monkeypatch):
        with pytest.raises(ValueError, match="not a known value"):
            _make(
                monkeypatch,
                APP_ENV="development",
                FC_SERVICE_ROLE="worker",  # not in {web, job}
                JWT_SECRET="test-jwt",
            )


class TestReconcilerImportSurface:
    """The reconciler script must be import-safe with the exact env
    that will be set on the fc-refund-reconciler Render cron:
    DATABASE_URL + STRIPE_SECRET_KEY + APP_ENV=production + FC_SERVICE_ROLE=job.
    No R2, no JWT, no webhook secret.
    """

    def test_reconciler_module_imports_under_job_env(self, monkeypatch):
        # We test Settings() alone here rather than actually running
        # the reconciler script (which would need a real DB + Stripe
        # network access). The dependency chain to fail on is Settings
        # → validators; if that clears, the script's model imports
        # are ordinary Python imports that never touch env config.
        s = _make(
            monkeypatch,
            APP_ENV="production",
            FC_SERVICE_ROLE="job",
            STRIPE_SECRET_KEY="sk_live_reconciler_only",
        )
        assert s.stripe_enabled is False  # webhook_secret unset → False by design
        assert s.stripe_secret_key == "sk_live_reconciler_only"
        assert s.fc_service_role == "job"
        assert s.app_env == "production"
