"""Shared channel-type constants + helpers.

Kept in one place so backend endpoints, permission checks, and the
frontend response layer all agree on the vocabulary and the derived
icon per type. Adding a new type is a single-line change here plus a
matching entry on the frontend.

Design rule: creators never choose icons manually. Every response
returns the type-derived icon (or an existing stored override, which
is not user-editable today).
"""

from __future__ import annotations


# Types the API accepts on create/update. `start_here` and `general`
# are reserved for system channels and cannot be created through the
# creator endpoints.
ALL_CHANNEL_TYPES: tuple[str, ...] = (
    "start_here",
    "general",
    "open",
    "private",
    "pathway",
    "gathering",
)

# Types a creator may choose when authoring a new Channel through the
# UI. System types (`start_here`, `general`) are provisioned by the
# 077 migration and by the creator-studio-space setup helpers.
CREATOR_ASSIGNABLE_TYPES: tuple[str, ...] = (
    "open",
    "private",
    "pathway",
    "gathering",
)

# Types that require a linked entity (validated on create).
LINKED_TYPES = {"pathway": "pathway_id", "gathering": "gathering_id"}

# Type → default emoji icon. Icons are strictly type-driven; creators
# do not pick icons in the UI. Every channel type must be represented.
CHANNEL_TYPE_ICONS: dict[str, str] = {
    "start_here": "🌱",
    "general": "🏡",
    "open": "💬",
    "private": "🔒",
    "pathway": "🛤",
    "gathering": "📅",
}

# Human-friendly group heading for the member selector + manage view.
# `None` means the channel is rendered in the un-headed system row
# at the very top of the navigation.
GROUP_LABEL_BY_TYPE: dict[str, str | None] = {
    "start_here": None,
    "general":    None,
    "pathway":    "PATHWAYS",
    "gathering":  "GATHERINGS",
    "private":    "PRIVATE",
    "open":       "OPEN DISCUSSIONS",
}


def icon_for(channel_type: str, stored: str | None = None) -> str:
    """Return the icon to display for a channel.

    Preference order: a non-empty stored `icon_emoji` override wins so
    legacy channels keep their existing icon; otherwise the type-driven
    default is used. Unknown types fall back to the 'open' icon.
    """
    if stored:
        return stored
    return CHANNEL_TYPE_ICONS.get(channel_type, CHANNEL_TYPE_ICONS["open"])
