"""Persistent Media Storage Stage B — boot-time R2 config guard.

``Settings()`` refuses to instantiate under two conditions:

  1. ``APP_ENV=production`` with any R2 variable missing — production
     must not silently downgrade uploads to the container's ephemeral
     disk.
  2. Any environment with a partial R2 config (some vars set, others
     missing) — refuses to boot rather than mix R2 writes with
     filesystem reads.

The guard is a Pydantic ``model_validator`` — it fires at
``Settings()`` instantiation, which on Render means fc-api's process
start. A ValidationError there aborts the deploy; the previous image
keeps serving. See ``_check_r2_configuration`` in
``app.core.config``.

Local dev / the rest of the test suite is unaffected: no R2 vars set
→ no ``present`` set → neither rule fires → filesystem fallback runs.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


# ---------------------------------------------------------------------------
# Fixture — start every test with a clean env so nothing from the
# outer .env leaks in and accidentally masks a "missing" case.
# ---------------------------------------------------------------------------


R2_VAR_NAMES = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_PRIVATE",
    "R2_BUCKET_PUBLIC",
    "R2_PUBLIC_BASE_URL",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in R2_VAR_NAMES:
        monkeypatch.delenv(name, raising=False)
    # APP_ENV comes from the dev .env; unset here so each test picks
    # what it wants explicitly.
    monkeypatch.delenv("APP_ENV", raising=False)
    return monkeypatch


def _mk_settings(**kwargs) -> Settings:
    """Instantiate Settings without reading any .env file so tests
    only see what's passed in. ``database_url`` and ``jwt_secret`` are
    required and have no default; every test provides throwaway
    values."""
    defaults = {
        "database_url": "postgresql://test-only",
        "jwt_secret": "test-only",
        "_env_file": None,
    }
    defaults.update(kwargs)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# Rule 1 — production requires the full set
# ---------------------------------------------------------------------------


class TestProductionRequiresFullR2:
    def test_production_with_zero_r2_vars_refuses_to_boot(
        self, clean_env,
    ) -> None:
        with pytest.raises(ValidationError) as exc:
            _mk_settings(app_env="production")
        # Every missing var name appears in the message so the operator
        # knows exactly what to set.
        msg = str(exc.value)
        for name in R2_VAR_NAMES:
            assert name in msg
        assert "required in production" in msg

    def test_production_with_five_of_six_refuses_to_boot(
        self, clean_env,
    ) -> None:
        with pytest.raises(ValidationError) as exc:
            _mk_settings(
                app_env="production",
                r2_account_id="0123456789abcdef0123456789abcdef",
                r2_access_key_id="key",
                r2_secret_access_key="sec",
                r2_bucket_private="fc-media",
                r2_bucket_public="fc-media-public",
                # r2_public_base_url deliberately missing
            )
        assert "R2_PUBLIC_BASE_URL" in str(exc.value)

    def test_production_with_full_r2_boots_cleanly(
        self, clean_env,
    ) -> None:
        s = _mk_settings(
            app_env="production",
            r2_account_id="0123456789abcdef0123456789abcdef",
            r2_access_key_id="key",
            r2_secret_access_key="sec",
            r2_bucket_private="fc-media",
            r2_bucket_public="fc-media-public",
            r2_public_base_url="https://pub-x.r2.dev",
        )
        assert s.is_r2_enabled is True


# ---------------------------------------------------------------------------
# Rule 2 — any env, partial config is always an error
# ---------------------------------------------------------------------------


class TestPartialConfigRefusesEverywhere:
    def test_dev_with_only_account_id_set_refuses_to_boot(
        self, clean_env,
    ) -> None:
        """Half-configured dev is a hazard — some code paths would use
        R2, others would use disk, and the confusion is hard to debug.
        The guard fires in dev too, forcing the operator to either
        finish the config or clear it."""
        with pytest.raises(ValidationError) as exc:
            _mk_settings(
                app_env="development",
                r2_account_id="0123456789abcdef0123456789abcdef",
            )
        msg = str(exc.value)
        assert "partially configured" in msg
        assert "R2_ACCOUNT_ID" in msg  # named as the one that's set
        # All missing vars named so the operator knows what to add.
        for missing in (
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET_PRIVATE",
            "R2_BUCKET_PUBLIC",
            "R2_PUBLIC_BASE_URL",
        ):
            assert missing in msg

    def test_dev_with_full_r2_boots_cleanly(self, clean_env) -> None:
        s = _mk_settings(
            app_env="development",
            r2_account_id="0123456789abcdef0123456789abcdef",
            r2_access_key_id="key",
            r2_secret_access_key="sec",
            r2_bucket_private="fc-media",
            r2_bucket_public="fc-media-public",
            r2_public_base_url="https://pub-x.r2.dev",
        )
        assert s.is_r2_enabled is True


# ---------------------------------------------------------------------------
# Silent-fallback baseline — dev with zero R2 vars must NOT raise
# ---------------------------------------------------------------------------


class TestZeroConfigDevIsAllowed:
    def test_dev_with_zero_r2_vars_boots_and_uses_filesystem(
        self, clean_env,
    ) -> None:
        s = _mk_settings(app_env="development")
        # No raise. is_r2_enabled is False so storage.py takes the
        # filesystem branch — the pre-Stage-B behaviour used by every
        # existing backend test.
        assert s.is_r2_enabled is False

    def test_default_env_is_development_and_permits_no_r2(
        self, clean_env,
    ) -> None:
        # Explicit env-var absence — the Settings default (`app_env
        # = "development"`) must permit no-R2 boot, otherwise the
        # thousands of existing tests without R2 credentials would
        # start failing.
        s = _mk_settings()
        assert s.app_env == "development"
        assert s.is_r2_enabled is False


# ---------------------------------------------------------------------------
# Rule 4 — R2_ACCOUNT_ID must be a 32-char hex string
# ---------------------------------------------------------------------------


_VALID_R2_KWARGS = dict(
    app_env="production",
    r2_account_id="0123456789abcdef0123456789abcdef",  # 32-char hex
    r2_access_key_id="key",
    r2_secret_access_key="sec",
    r2_bucket_private="fc-media",
    r2_bucket_public="fc-media-public",
    r2_public_base_url="https://pub-x.r2.dev",
)


class TestR2AccountIdFormat:
    def test_valid_32_hex_lowercase_accepted(self, clean_env) -> None:
        s = _mk_settings(**_VALID_R2_KWARGS)
        assert s.r2_account_id == "0123456789abcdef0123456789abcdef"

    def test_valid_32_hex_uppercase_accepted(self, clean_env) -> None:
        kwargs = {**_VALID_R2_KWARGS, "r2_account_id": "ABCDEF0123456789ABCDEF0123456789"}
        s = _mk_settings(**kwargs)
        assert s.r2_account_id == "ABCDEF0123456789ABCDEF0123456789"

    def test_placeholder_with_angle_brackets_rejected(self, clean_env) -> None:
        """The literal case that caused the production ``Invalid
        endpoint`` error: R2_ACCOUNT_ID set to the documentation
        placeholder ``<account>``. Must be rejected at boot with a
        clear message rather than surfacing as a boto3 hostname
        validation error at first upload."""
        kwargs = {**_VALID_R2_KWARGS, "r2_account_id": "<account>"}
        with pytest.raises(ValidationError) as exc:
            _mk_settings(**kwargs)
        msg = str(exc.value)
        assert "R2_ACCOUNT_ID" in msg
        assert "32-character hex" in msg

    def test_full_url_pasted_instead_of_id_rejected(self, clean_env) -> None:
        """Second common footgun: pasting the entire endpoint URL
        into R2_ACCOUNT_ID."""
        kwargs = {
            **_VALID_R2_KWARGS,
            "r2_account_id": "https://abc.r2.cloudflarestorage.com",
        }
        with pytest.raises(ValidationError) as exc:
            _mk_settings(**kwargs)
        assert "R2_ACCOUNT_ID" in str(exc.value)

    def test_wrong_length_rejected(self, clean_env) -> None:
        # 31 chars — one short.
        kwargs = {
            **_VALID_R2_KWARGS,
            "r2_account_id": "0123456789abcdef0123456789abcde",
        }
        with pytest.raises(ValidationError) as exc:
            _mk_settings(**kwargs)
        assert "R2_ACCOUNT_ID" in str(exc.value)

    def test_non_hex_char_rejected(self, clean_env) -> None:
        # 32 chars but contains a ``g``.
        kwargs = {
            **_VALID_R2_KWARGS,
            "r2_account_id": "g123456789abcdef0123456789abcdef",
        }
        with pytest.raises(ValidationError) as exc:
            _mk_settings(**kwargs)
        assert "R2_ACCOUNT_ID" in str(exc.value)


# ---------------------------------------------------------------------------
# Rule 1 — whitespace is stripped from every R2 var
# ---------------------------------------------------------------------------


class TestWhitespaceStripping:
    def test_trailing_newline_on_account_id_stripped(self, clean_env) -> None:
        # Common when copy-pasting from a terminal or dashboard: the
        # value carries a trailing newline. Must not turn into an
        # invalid hostname.
        kwargs = {
            **_VALID_R2_KWARGS,
            "r2_account_id": "0123456789abcdef0123456789abcdef\n",
        }
        s = _mk_settings(**kwargs)
        assert s.r2_account_id == "0123456789abcdef0123456789abcdef"

    def test_surrounding_spaces_stripped_on_public_url(self, clean_env) -> None:
        kwargs = {
            **_VALID_R2_KWARGS,
            "r2_public_base_url": "   https://pub-x.r2.dev   ",
        }
        s = _mk_settings(**kwargs)
        assert s.r2_public_base_url == "https://pub-x.r2.dev"

    def test_whitespace_only_treated_as_missing(self, clean_env) -> None:
        # R2_ACCOUNT_ID set to only whitespace → after trim, empty →
        # treated as missing. Under production this fires Rule 2
        # (production requires full R2), not Rule 4.
        kwargs = {**_VALID_R2_KWARGS, "r2_account_id": "   \n  "}
        with pytest.raises(ValidationError) as exc:
            _mk_settings(**kwargs)
        msg = str(exc.value)
        assert "R2_ACCOUNT_ID" in msg
        assert "Missing env vars" in msg
