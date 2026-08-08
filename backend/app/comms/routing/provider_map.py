"""Provider selection map.

Keyed by ``(category_key, channel)`` — providers align with the
member-facing groupings, not the engineering-internal topic taxonomy.
Rationale in the M5 design proposal (Refinement 4): several topics
share a category, and members experience the category as the unit;
provider treatment should mirror that.

Version-controlled code, not a DB table. Per-tenant / per-creator
provider overrides can be introduced later without disrupting the
default routing (a lookup helper is the single seam).
"""

from __future__ import annotations

from app.comms.categories import (
    CATEGORY_ACCOUNT,
    CATEGORY_COMMUNITY,
    CATEGORY_CREATOR_UPDATES,
    CATEGORY_GATHERINGS,
    CATEGORY_MESSAGES,
    CATEGORY_PATHWAYS,
    CATEGORY_PLATFORM_UPDATES,
    CATEGORY_PURCHASES,
    CATEGORY_SAFETY,
    CHANNEL_EMAIL_TRANSACTIONAL,
    CHANNEL_IN_APP,
)


# (category_key, channel) → provider_key
#
# M5 lights up in_app + email_transactional across every category. The
# remaining channels stay unrouted (missing entries → suppressed intent
# with reason=no_provider_configured):
#   * email_marketing  → M11 (MailerLite)
#   * push             → M14
#   * webhook_outbound → M12
PROVIDER_MAP: dict[tuple[str, str], str] = {
    (CATEGORY_ACCOUNT,          CHANNEL_IN_APP):              "in_app",
    (CATEGORY_ACCOUNT,          CHANNEL_EMAIL_TRANSACTIONAL): "resend",
    (CATEGORY_SAFETY,           CHANNEL_IN_APP):              "in_app",
    (CATEGORY_SAFETY,           CHANNEL_EMAIL_TRANSACTIONAL): "resend",
    (CATEGORY_PURCHASES,        CHANNEL_IN_APP):              "in_app",
    (CATEGORY_PURCHASES,        CHANNEL_EMAIL_TRANSACTIONAL): "resend",
    (CATEGORY_MESSAGES,         CHANNEL_IN_APP):              "in_app",
    (CATEGORY_MESSAGES,         CHANNEL_EMAIL_TRANSACTIONAL): "resend",
    (CATEGORY_GATHERINGS,       CHANNEL_IN_APP):              "in_app",
    (CATEGORY_GATHERINGS,       CHANNEL_EMAIL_TRANSACTIONAL): "resend",
    (CATEGORY_PATHWAYS,         CHANNEL_IN_APP):              "in_app",
    (CATEGORY_PATHWAYS,         CHANNEL_EMAIL_TRANSACTIONAL): "resend",
    (CATEGORY_COMMUNITY,        CHANNEL_IN_APP):              "in_app",
    (CATEGORY_COMMUNITY,        CHANNEL_EMAIL_TRANSACTIONAL): "resend",
    (CATEGORY_CREATOR_UPDATES,  CHANNEL_IN_APP):              "in_app",
    (CATEGORY_CREATOR_UPDATES,  CHANNEL_EMAIL_TRANSACTIONAL): "resend",
    (CATEGORY_PLATFORM_UPDATES, CHANNEL_IN_APP):              "in_app",
    # (platform_updates, email_marketing) intentionally deferred to M11.
}


def get_provider_for(category_key: str, channel: str) -> str | None:
    """Return the provider_key for a (category, channel) pair, or
    ``None`` when the pair is not routed. Callers treat ``None`` as
    a suppression signal (``reason=no_provider_configured``).
    """
    return PROVIDER_MAP.get((category_key, channel))


def supported_channels_for_category(category_key: str) -> tuple[str, ...]:
    """Every channel currently routed for a category, in deterministic
    order. Used by ``route_event`` to iterate the recipient × channel
    grid without hard-coding channel lists.
    """
    out = [ch for (cat, ch) in PROVIDER_MAP.keys() if cat == category_key]
    # Stable ordering — in_app first, email_transactional second,
    # everything else alphabetical. Deterministic across CPython runs.
    order = {
        CHANNEL_IN_APP: 0,
        CHANNEL_EMAIL_TRANSACTIONAL: 1,
    }
    out.sort(key=lambda ch: (order.get(ch, 99), ch))
    return tuple(out)
