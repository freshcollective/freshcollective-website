"""SEC-010 Step 2 — tests for the ``client_ip_for_rate_limit`` key
function.

Uses a minimal stand-in ``Request`` object rather than TestClient
because the function only reads ``request.client`` and
``request.headers`` — a real ASGI request is unnecessary overhead
for pure branch coverage.

Every test locks in exactly one of the invariants captured in the
module docstring for ``app.core.rate_limit``:

- Authenticated BFF branch trusts ``X-Fc-Client-IP`` iff (a) the
  credential is configured, (b) the presented value matches under
  constant-time compare, and (c) the header value passes strict
  single-public-IP format validation.
- An invalid/absent BFF credential never lets ``X-Fc-Client-IP``
  influence the returned key.
- Authenticated-but-malformed requests fall back to the private
  peer, not the public branch.
- Public path uses ``CF-Connecting-IP`` when valid; falls back to
  the peer or ``"unknown"``.
- Strict single-public-IP validator rejects comma-lists, whitespace,
  malformed input, and every non-public IP range.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# Ensure User's community_care FKs resolve in isolation.
import app.models.community_care  # noqa: F401
from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import (
    _looks_like_single_public_ip,
    client_ip_for_rate_limit,
)


# ---------------------------------------------------------------------------
# Test-only Request stand-in
# ---------------------------------------------------------------------------

class _FakeHeaders:
    def __init__(self, mapping: dict[str, str]) -> None:
        # Case-insensitive lookup, matches Starlette Headers semantics.
        self._lower = {k.lower(): v for k, v in mapping.items()}

    def get(self, name: str, default=None):
        return self._lower.get(name.lower(), default)


def _req(*, peer: str | None = None, **headers: str):
    """Build a minimal object with the two attributes
    ``client_ip_for_rate_limit`` reads. Any keyword arg becomes an
    HTTP header. Peer ``None`` mimics missing ``scope["client"]``."""
    return SimpleNamespace(
        client=SimpleNamespace(host=peer) if peer is not None else None,
        headers=_FakeHeaders(headers),
    )


@pytest.fixture
def secret_set(monkeypatch):
    """Configure a known credential for the authenticated branch."""
    monkeypatch.setattr(settings, "internal_bff_secret", "correct-horse-battery-staple-shared-bff-secret")
    return "correct-horse-battery-staple-shared-bff-secret"


@pytest.fixture
def secret_unset(monkeypatch):
    """Confirm the authenticated branch is skipped entirely when the
    credential is not configured (local dev, or a production
    misconfiguration)."""
    monkeypatch.setattr(settings, "internal_bff_secret", None)


# ---------------------------------------------------------------------------
# Group A — Authenticated BFF branch
# ---------------------------------------------------------------------------

class TestAuthenticatedBffBranch:
    def test_A1_correct_secret_valid_ipv4_returns_forwarded(self, secret_set):
        req = _req(
            peer="10.28.154.55",
            **{"x-fc-bff-auth": secret_set, "x-fc-client-ip": "1.2.3.4"},
        )
        assert client_ip_for_rate_limit(req) == "1.2.3.4"

    def test_A2_correct_secret_valid_ipv6_returns_forwarded(self, secret_set):
        req = _req(
            peer="10.28.154.55",
            **{"x-fc-bff-auth": secret_set, "x-fc-client-ip": "2606:4700:4700::1111"},
        )
        assert client_ip_for_rate_limit(req) == "2606:4700:4700::1111"

    def test_A3_correct_secret_garbage_ip_falls_back_to_peer(self, secret_set):
        req = _req(
            peer="10.28.154.55",
            **{"x-fc-bff-auth": secret_set, "x-fc-client-ip": "not-an-ip"},
        )
        assert client_ip_for_rate_limit(req) == "10.28.154.55"

    def test_A4_correct_secret_empty_header_falls_back_to_peer(self, secret_set):
        req = _req(
            peer="10.28.154.55",
            **{"x-fc-bff-auth": secret_set, "x-fc-client-ip": ""},
        )
        assert client_ip_for_rate_limit(req) == "10.28.154.55"

    def test_A5_correct_secret_whitespace_only_falls_back(self, secret_set):
        req = _req(
            peer="10.28.154.55",
            **{"x-fc-bff-auth": secret_set, "x-fc-client-ip": "   "},
        )
        assert client_ip_for_rate_limit(req) == "10.28.154.55"

    def test_A6_correct_secret_padded_value_rejected(self, secret_set):
        """Strict format: no leading/trailing whitespace tolerated."""
        req = _req(
            peer="10.28.154.55",
            **{"x-fc-bff-auth": secret_set, "x-fc-client-ip": " 1.2.3.4 "},
        )
        assert client_ip_for_rate_limit(req) == "10.28.154.55"

    def test_A7_correct_secret_comma_list_rejected(self, secret_set):
        """X-Fc-Client-IP is our own single-value protocol, NOT XFF."""
        req = _req(
            peer="10.28.154.55",
            **{"x-fc-bff-auth": secret_set, "x-fc-client-ip": "1.2.3.4, 5.6.7.8"},
        )
        assert client_ip_for_rate_limit(req) == "10.28.154.55"

    @pytest.mark.parametrize("bad_ip", [
        "10.0.0.1",         # RFC1918
        "192.168.1.1",      # RFC1918
        "172.16.0.1",       # RFC1918
        "100.64.0.1",       # CGNAT
        "127.0.0.1",        # loopback IPv4
        "::1",              # loopback IPv6
        "169.254.0.1",      # link-local IPv4
        "fe80::1",          # link-local IPv6
        "224.0.0.1",        # multicast IPv4
        "ff02::1",          # multicast IPv6
        "0.0.0.0",          # unspecified IPv4
        "::",               # unspecified IPv6
        "240.0.0.1",        # reserved
    ])
    def test_A8_correct_secret_non_public_ip_rejected(self, secret_set, bad_ip):
        req = _req(
            peer="10.28.154.55",
            **{"x-fc-bff-auth": secret_set, "x-fc-client-ip": bad_ip},
        )
        assert client_ip_for_rate_limit(req) == "10.28.154.55"

    def test_A9_correct_secret_missing_client_ip_falls_back_to_peer(
        self, secret_set,
    ):
        """Authenticated but no claim → private-peer fallback, NOT the
        public branch. This prevents a compromised BFF from bypassing
        validation by omitting X-Fc-Client-IP."""
        req = _req(
            peer="10.28.154.55",
            **{"x-fc-bff-auth": secret_set,
               "cf-connecting-ip": "8.8.8.8"},   # tempting but must be ignored
        )
        assert client_ip_for_rate_limit(req) == "10.28.154.55"


# ---------------------------------------------------------------------------
# Group B — Unauthenticated / public branch — X-Fc-Client-IP MUST be ignored
# ---------------------------------------------------------------------------

class TestPublicBranch:
    def test_B1_wrong_secret_with_spoofed_xfcip_uses_cf_ignoring_spoof(
        self, secret_set,
    ):
        """Attacker forwards a wrong credential plus a spoofed
        X-Fc-Client-IP. The header must be entirely ignored; the
        limiter keys on CF-Connecting-IP (attacker's real IP)."""
        req = _req(
            peer="162.158.3.120",  # Cloudflare edge
            **{"x-fc-bff-auth": "wrong",
               "x-fc-client-ip": "9.9.9.9",  # spoofed
               "cf-connecting-ip": "8.8.8.8"},
        )
        assert client_ip_for_rate_limit(req) == "8.8.8.8"

    def test_B2_missing_secret_with_spoofed_xfcip_ignores_spoof(
        self, secret_set,
    ):
        req = _req(
            peer="162.158.3.120",
            **{"x-fc-client-ip": "9.9.9.9",
               "cf-connecting-ip": "8.8.8.8"},
        )
        assert client_ip_for_rate_limit(req) == "8.8.8.8"

    def test_B3_valid_cf_connecting_ip_no_bff_auth_returns_cf(
        self, secret_set,
    ):
        req = _req(
            peer="162.158.3.120",
            **{"cf-connecting-ip": "8.8.8.8"},
        )
        assert client_ip_for_rate_limit(req) == "8.8.8.8"

    def test_B4_no_cf_no_bff_returns_peer(self, secret_set):
        req = _req(peer="162.158.3.120")
        assert client_ip_for_rate_limit(req) == "162.158.3.120"

    def test_B5_missing_peer_returns_unknown(self, secret_set):
        req = _req(peer=None)
        assert client_ip_for_rate_limit(req) == "unknown"

    def test_B6_malformed_cf_connecting_ip_falls_back_to_peer(self, secret_set):
        req = _req(peer="162.158.3.120", **{"cf-connecting-ip": "garbage"})
        assert client_ip_for_rate_limit(req) == "162.158.3.120"


# ---------------------------------------------------------------------------
# Group C — Configuration edge cases
# ---------------------------------------------------------------------------

class TestConfigEdgeCases:
    def test_C1_unset_secret_all_headers_absent_returns_peer(self, secret_unset):
        req = _req(peer="127.0.0.1")
        assert client_ip_for_rate_limit(req) == "127.0.0.1"

    def test_C2_unset_secret_ignores_authenticated_headers(self, secret_unset):
        """When the credential is not configured, the authenticated
        branch must NEVER run — even if an attacker sends valid-looking
        auth+claim headers."""
        req = _req(
            peer="162.158.3.120",
            **{"x-fc-bff-auth": "anything",
               "x-fc-client-ip": "9.9.9.9",
               "cf-connecting-ip": "8.8.8.8"},
        )
        assert client_ip_for_rate_limit(req) == "8.8.8.8"

    def test_C3_off_by_one_secret_rejected(self, secret_set):
        """Constant-time compare guarantees this by construction; assert
        anyway to catch a future refactor that swapped to ``==``."""
        req = _req(
            peer="10.28.154.55",
            **{"x-fc-bff-auth": secret_set[:-1] + "X",
               "x-fc-client-ip": "1.2.3.4",
               "cf-connecting-ip": "8.8.8.8"},
        )
        # Authenticated branch skipped → public branch → CF value.
        assert client_ip_for_rate_limit(req) == "8.8.8.8"

    def test_C4_uses_constant_time_compare(self, monkeypatch, secret_set):
        """Assert that ``secrets.compare_digest`` is the comparator —
        detects a refactor to ``==`` (timing side-channel regression)."""
        calls = []
        real_compare = rate_limit.secrets.compare_digest

        def spy(a, b):
            calls.append(True)
            return real_compare(a, b)

        monkeypatch.setattr(rate_limit.secrets, "compare_digest", spy)
        req = _req(
            peer="10.28.154.55",
            **{"x-fc-bff-auth": secret_set,
               "x-fc-client-ip": "1.2.3.4"},
        )
        client_ip_for_rate_limit(req)
        assert calls, "expected secrets.compare_digest to be invoked"


# ---------------------------------------------------------------------------
# Group D — Public-IP validator (locks the shape rules)
# ---------------------------------------------------------------------------

class TestLooksLikeSinglePublicIp:
    @pytest.mark.parametrize("value", [
        "1.2.3.4",
        "8.8.8.8",
        "2606:4700:4700::1111",
        "2606:4700:4700::1111",
    ])
    def test_D1_valid_public_ips_accepted(self, value):
        assert _looks_like_single_public_ip(value) is True

    @pytest.mark.parametrize("value", [
        "",
        " ",
        "   ",
        " 1.2.3.4",
        "1.2.3.4 ",
        "1.2.3.4, 5.6.7.8",
        "1.2.3.4,5.6.7.8",
        "not-an-ip",
        "1.2.3",
        "1.2.3.256",
        "10.0.0.1",
        "192.168.0.1",
        "172.16.0.1",
        "100.64.0.1",
        "127.0.0.1",
        "::1",
        "169.254.1.1",
        "fe80::1",
        "224.0.0.1",
        "ff02::1",
        "0.0.0.0",
        "::",
    ])
    def test_D2_invalid_or_non_public_rejected(self, value):
        assert _looks_like_single_public_ip(value) is False
