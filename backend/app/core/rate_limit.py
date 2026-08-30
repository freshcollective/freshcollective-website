"""SEC-010 Step 2 — client-IP identification for SlowAPI rate limiting.

Two independent identity branches, chosen per request:

1. **Authenticated BFF branch.** When ``X-Fc-Bff-Auth`` matches the
   configured ``INTERNAL_BFF_SECRET`` (constant-time compare), the
   caller-supplied ``X-Fc-Client-IP`` is trusted after strict format
   validation. The credential is the sole authentication mechanism;
   the SEC-010 Step 1 Render-private-network transport remains as
   isolation but is deliberately NOT re-encoded as an application-
   level trust check (undocumented CIDR guarantees would be fragile).

2. **Public path.** ``X-Fc-Client-IP`` is IGNORED regardless of value.
   ``CF-Connecting-IP`` is used when it validates as a public IP;
   otherwise the raw TCP peer or ``"unknown"`` is used as a
   fail-safe fallback. Cloudflare rejects inbound copies of its own
   ``CF-Connecting-IP`` header at the edge (403), so a value reaching
   us in this header was set by Cloudflare and reflects the real
   caller.

Invariants (enforced by structure + covered by
``tests/test_rate_limit_client_ip.py``):

  * An invalid or absent BFF credential NEVER lets ``X-Fc-Client-IP``
    influence the returned key.
  * An authenticated request with a missing or malformed
    ``X-Fc-Client-IP`` falls back to the private peer address (safe,
    non-attacker-controlled). It does NOT fall through to the public
    branch — that would let a compromised BFF bypass validation by
    omitting the header.
  * ``X-Fc-Client-IP`` is our own internal protocol, not X-Forwarded-
    For. Exactly one syntactically valid *public* IPv4 or IPv6
    address is accepted; private/loopback/link-local/reserved/
    multicast/unspecified addresses, comma-lists, whitespace, and
    malformed input are rejected.
"""

from __future__ import annotations

import ipaddress
import secrets

from fastapi import Request

from .config import settings

# 100.64.0.0/10 is Carrier-Grade NAT (RFC 6598) — a shared address
# space that ISPs use behind their own NAT. Not a real public client
# IP; two different subscribers can appear at the same 100.64/10
# address. Python's ``ipaddress.is_private`` does NOT cover this
# range in every stdlib version, so check explicitly.
_CGNAT_RANGE = ipaddress.ip_network("100.64.0.0/10")


def client_ip_for_rate_limit(request: Request) -> str:
    """SlowAPI ``key_func`` for every ``Limiter`` in the app. Returns
    a stable string identifying the caller for rate-limiting purposes.
    """
    expected = settings.internal_bff_secret
    presented = request.headers.get("x-fc-bff-auth")

    # Authenticated BFF branch — only entered when the credential is
    # configured AND matches. ``compare_digest`` is constant-time.
    if (
        expected is not None
        and presented is not None
        and secrets.compare_digest(presented, expected)
    ):
        claimed = request.headers.get("x-fc-client-ip")
        if claimed is not None and _looks_like_single_public_ip(claimed):
            return claimed
        # Authenticated but the forwarded claim is missing or unusable:
        # fall back to the private TCP peer (fc-web's Render-internal
        # address). Deliberately does NOT fall through to the public
        # branch — that would let a compromised BFF bypass validation
        # by simply omitting X-Fc-Client-IP.
        return request.client.host if request.client else "unknown"

    # Public / unauthenticated branch. X-Fc-Client-IP is IGNORED
    # regardless of value.
    cf = request.headers.get("cf-connecting-ip")
    if cf is not None and _looks_like_single_public_ip(cf):
        return cf

    # Last-resort fallback — local dev (127.0.0.1), or a caller that
    # reached us without Cloudflare metadata.
    return request.client.host if request.client else "unknown"


def _looks_like_single_public_ip(value: str) -> bool:
    """Strict format check for our own ``X-Fc-Client-IP`` protocol.

    Accepts exactly one syntactically valid public IPv4 or IPv6
    address. Rejects comma-lists (we are not X-Forwarded-For),
    whitespace around the value (would indicate proxy re-formatting),
    empty strings, malformed input, and any address in a private,
    loopback, link-local, reserved, multicast, or unspecified range.
    """
    if not value:
        return False
    if "," in value:
        return False
    if value != value.strip():
        return False
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    ):
        return False
    # CGNAT — explicitly rejected; see ``_CGNAT_RANGE`` above.
    if isinstance(addr, ipaddress.IPv4Address) and addr in _CGNAT_RANGE:
        return False
    return True
