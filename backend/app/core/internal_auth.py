"""SEC-007 — internal-endpoint authentication helper.

Centralises the ``X-Internal-Token`` check so all four
``/api/internal/*`` endpoints authenticate identically and cannot
drift into ad-hoc comparisons over time.

Trust model:

- The credential is a dedicated ``INTERNAL_COMMS_SECRET`` — distinct
  from ``JWT_SECRET`` (the session-signing key) and from
  ``INTERNAL_BFF_SECRET`` (the SEC-010 Step 2 BFF-to-API client-IP
  auth). Reusing any of the three across trust domains would defeat
  their independent rotation and blast-radius properties.
- Compared using ``secrets.compare_digest`` for constant-time
  equality — closes the timing-side-channel that the earlier
  ``!=`` pattern had.
- Fails closed when the credential is unconfigured. If
  ``settings.internal_comms_secret is None`` (local dev or an
  operator misconfiguration in production), every internal-endpoint
  call is rejected with 401. Better to reject a legitimate cron
  than silently fall back to a more-privileged credential.

Do NOT extend this module to accept alternate credentials or fall
back to other secrets. Any future internal-service auth requirement
should either use this helper directly or introduce its own
purpose-built helper with the same discipline.
"""

from __future__ import annotations

import secrets

from .config import settings


def verify_internal_token(presented: str | None) -> bool:
    """Return True iff ``presented`` matches the configured
    ``INTERNAL_COMMS_SECRET`` under constant-time comparison.

    Returns False whenever:

    * ``settings.internal_comms_secret`` is not configured (fail-closed);
    * ``presented`` is missing or empty;
    * the two values differ.
    """
    expected = settings.internal_comms_secret
    if not expected or not presented:
        return False
    return secrets.compare_digest(presented, expected)
