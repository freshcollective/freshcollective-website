"""SEC-007 — tests for ``verify_internal_token``.

Locks in the invariants captured in the module docstring for
``app.core.internal_auth``:

  * Fail-closed when the credential is unconfigured.
  * Constant-time equality via ``secrets.compare_digest``.
  * Missing / empty presented value → False.
  * Explicit regression: the JWT signing key is NOT accepted (they
    must remain independent credentials — the whole point of
    SEC-007).
  * The internal-endpoint route in ``comms/routes.py`` invokes this
    helper (structural check — catches a future refactor that
    swapped back to an ad-hoc comparison).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Ensure User's community_care FKs resolve in isolation.
import app.models.community_care  # noqa: F401
from app.core import internal_auth
from app.core.config import settings
from app.core.internal_auth import verify_internal_token


# ---------------------------------------------------------------------------
# Configuration-branch behaviour
# ---------------------------------------------------------------------------

class TestFailClosedWhenUnconfigured:
    def test_unset_secret_rejects_none(self, monkeypatch):
        monkeypatch.setattr(settings, "internal_comms_secret", None, raising=False)
        assert verify_internal_token(None) is False

    def test_unset_secret_rejects_empty(self, monkeypatch):
        monkeypatch.setattr(settings, "internal_comms_secret", None, raising=False)
        assert verify_internal_token("") is False

    def test_unset_secret_rejects_any_value(self, monkeypatch):
        """Even a would-be-correct value must not authenticate when
        the server hasn't been given the credential to compare against.
        Fail-closed is the intended posture — better to reject a
        legitimate cron than silently succeed against a nil expected."""
        monkeypatch.setattr(settings, "internal_comms_secret", None, raising=False)
        assert verify_internal_token("anything-at-all") is False


# ---------------------------------------------------------------------------
# Configured-secret behaviour
# ---------------------------------------------------------------------------

class TestConfiguredSecret:
    _SECRET = "test-only-internal-comms-secret-value"

    @pytest.fixture(autouse=True)
    def _set_secret(self, monkeypatch):
        monkeypatch.setattr(
            settings, "internal_comms_secret", self._SECRET, raising=False,
        )

    def test_correct_value_accepted(self):
        assert verify_internal_token(self._SECRET) is True

    def test_none_rejected(self):
        assert verify_internal_token(None) is False

    def test_empty_string_rejected(self):
        assert verify_internal_token("") is False

    def test_off_by_one_rejected(self):
        assert verify_internal_token(self._SECRET[:-1] + "X") is False

    def test_prefix_of_secret_rejected(self):
        assert verify_internal_token(self._SECRET[:-3]) is False

    def test_longer_than_secret_rejected(self):
        assert verify_internal_token(self._SECRET + "extra") is False

    def test_completely_different_rejected(self):
        assert verify_internal_token("completely-unrelated-value") is False

    def test_uses_constant_time_compare(self, monkeypatch):
        """SEC-007 wart-fix: the earlier ``!=`` comparison had a
        (practically irrelevant) timing side-channel. Assert that
        ``secrets.compare_digest`` is invoked so a future refactor
        that swapped back to ``==`` would fail this test."""
        calls = []
        real_compare = internal_auth.secrets.compare_digest

        def spy(a, b):
            calls.append(True)
            return real_compare(a, b)

        monkeypatch.setattr(internal_auth.secrets, "compare_digest", spy)
        verify_internal_token(self._SECRET)
        assert calls, "expected secrets.compare_digest to be invoked"


# ---------------------------------------------------------------------------
# Independence from JWT_SECRET — the point of SEC-007
# ---------------------------------------------------------------------------

class TestIndependentFromJwtSecret:
    def test_jwt_secret_value_does_not_authenticate_internal_endpoint(
        self, monkeypatch,
    ):
        """The two credentials MUST be independent. If an operator
        accidentally set both to the same value in production, the
        rotation-independence property would silently degrade — but
        this test locks in that the *code* never treats ``jwt_secret``
        as a valid internal-endpoint credential regardless of the
        configured value of ``internal_comms_secret``."""
        monkeypatch.setattr(settings, "jwt_secret", "session-signing-key", raising=False)
        monkeypatch.setattr(
            settings, "internal_comms_secret",
            "distinct-internal-comms-secret",
            raising=False,
        )
        assert verify_internal_token("session-signing-key") is False
        assert verify_internal_token("distinct-internal-comms-secret") is True


# ---------------------------------------------------------------------------
# Structural regression — helper is used at every internal-endpoint site
# ---------------------------------------------------------------------------

class TestHelperUsedAtEveryCallSite:
    """Grep the source of the two files that declare ``/api/internal/*``
    endpoints and confirm no lingering ``!= settings.jwt_secret``
    comparison remains, and that ``verify_internal_token`` is
    imported/used.

    Detects a future refactor that reintroduced ad-hoc token checks
    or reverted one endpoint to the old scheme."""

    _BACKEND = Path(__file__).resolve().parent.parent / "app"
    _INTERNAL_FILES = [
        _BACKEND / "comms" / "routes.py",
        _BACKEND / "notifications" / "routes.py",
    ]

    def test_no_jwt_secret_comparison_remains(self):
        for path in self._INTERNAL_FILES:
            src = path.read_text()
            assert "x_internal_token != settings.jwt_secret" not in src, (
                f"stale JWT_SECRET-based token comparison found in {path.name}"
            )
            assert "x_internal_token == settings.jwt_secret" not in src, (
                f"stale JWT_SECRET-based token comparison found in {path.name}"
            )

    def test_verify_internal_token_imported_and_used(self):
        for path in self._INTERNAL_FILES:
            src = path.read_text()
            assert "from app.core.internal_auth import verify_internal_token" in src, (
                f"{path.name} does not import the SEC-007 helper"
            )
            assert "verify_internal_token(" in src, (
                f"{path.name} does not invoke verify_internal_token"
            )
