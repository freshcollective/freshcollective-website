"""Shared vocabulary for Gatherings (the visible term; internal model
name is `Event`). Kept in one file so backend endpoints, permission
checks, and the frontend all agree on the terms and defaults.

Design rules
------------
- Icons are strictly type-driven. Creators pick a Gathering Type from
  a dropdown; the platform assigns the icon. Adding a new type is a
  single line in `GATHERING_TYPES`.
- Attendance format is separate from Gathering Type. "Live Online" is
  a Type; "Online" is a Format. They can be combined freely.
- Access type is separate from visibility. A paid Gathering may still
  be publicly discoverable; a free Gathering may be invite-only.
"""

from __future__ import annotations


# -----------------------------------------------------------------------------
# Gathering Type — what kind of moment this is.
# -----------------------------------------------------------------------------
# Ordered list; the UI renders in this order. Values are stable enum
# strings safe to write to disk; labels are the human-visible name.

GATHERING_TYPES: tuple[tuple[str, str, str], ...] = (
    # (value,           label,             icon)
    ("circle",          "Circle",          "⭕"),
    ("conversation",    "Conversation",    "💬"),
    ("workshop",        "Workshop",        "🛠️"),
    ("retreat",         "Retreat",         "🌿"),
    ("celebration",     "Celebration",     "✨"),
    ("practice",        "Practice",        "🧘"),
    ("live_online",     "Live Online",     "💻"),
    ("walk",            "Walk",            "🚶"),
    ("coffee_chat",     "Coffee Chat",     "☕"),
    ("book_club",       "Book Club",       "📚"),
    ("qa",              "Q&A",             "❓"),
    ("creative",        "Creative Session","🎨"),
    ("shared_meal",     "Shared Meal",     "🍽️"),
    ("other",           "Other",           "📅"),
)

GATHERING_TYPE_VALUES: tuple[str, ...] = tuple(t[0] for t in GATHERING_TYPES)
GATHERING_TYPE_LABEL: dict[str, str] = {t[0]: t[1] for t in GATHERING_TYPES}
GATHERING_TYPE_ICON:  dict[str, str] = {t[0]: t[2] for t in GATHERING_TYPES}

# A short human sentence describing what this Gathering type feels
# like. Used under the type dropdown in the creator form, and could
# power inline captions in listings. Keep each under ~90 chars.
GATHERING_TYPE_DESCRIPTION: dict[str, str] = {
    "circle":       "Reflect together in an open, supportive space.",
    "conversation": "Explore an idea together.",
    "workshop":     "Learn through guided practice.",
    "retreat":      "Step away from everyday life for deeper restoration.",
    "celebration":  "Mark a shared milestone together.",
    "practice":     "Move, breathe or meditate together.",
    "live_online":  "Come together over video.",
    "walk":         "Slow, moving conversation shared side by side.",
    "coffee_chat":  "Relaxed conversation and connection.",
    "book_club":    "Read together and share what you're noticing.",
    "qa":           "Ask questions and receive thoughtful answers.",
    "creative":     "Make something together in a shared session.",
    "shared_meal":  "Gather around a table and share a meal.",
    "other":        "A moment for people to come together.",
}

DEFAULT_GATHERING_TYPE = "other"


def gathering_icon(gathering_type: str | None) -> str:
    """Icon to display for a gathering. Unknown types fall back to
    the 'other' icon so a stale enum never crashes the UI."""
    return GATHERING_TYPE_ICON.get(gathering_type or DEFAULT_GATHERING_TYPE,
                                    GATHERING_TYPE_ICON[DEFAULT_GATHERING_TYPE])


def gathering_description(gathering_type: str | None) -> str:
    """Short human sentence for the type. Unknown types fall back to
    the 'other' copy so a stale row never breaks the UI."""
    return GATHERING_TYPE_DESCRIPTION.get(
        gathering_type or DEFAULT_GATHERING_TYPE,
        GATHERING_TYPE_DESCRIPTION[DEFAULT_GATHERING_TYPE],
    )


# -----------------------------------------------------------------------------
# Attendance Format — how people show up.
# -----------------------------------------------------------------------------

ATTENDANCE_FORMATS: tuple[tuple[str, str], ...] = (
    ("online",    "Online"),
    ("in_person", "In person"),
    ("hybrid",    "Hybrid"),
)

ATTENDANCE_FORMAT_VALUES: tuple[str, ...] = tuple(f[0] for f in ATTENDANCE_FORMATS)
ATTENDANCE_FORMAT_LABEL: dict[str, str] = {f[0]: f[1] for f in ATTENDANCE_FORMATS}

DEFAULT_ATTENDANCE_FORMAT = "online"


def infer_attendance_format(location_type: str | None) -> str:
    """Best-effort mapping used by the 079 backfill and by any legacy
    callers that still send `location_type`. `zoom` and
    `async_recorded` are best represented as online; `in_person`
    maps directly."""
    if location_type == "in_person":
        return "in_person"
    return "online"


# -----------------------------------------------------------------------------
# Access Type — who may register, and on what basis.
# -----------------------------------------------------------------------------
# Kept intentionally small. Visibility (who can *see* the Gathering)
# is a separate concept — see `EventVisibility` when it lands. Today
# the platform combines them via `is_public` + this field, but the
# UI treats them as distinct choices.

ACCESS_TYPES: tuple[tuple[str, str], ...] = (
    ("free",                    "Free"),
    ("included_with_collective","Included with Collective membership"),
    ("included_with_pathway",   "Included with a Pathway"),
    # A Gathering in this Series is bookable only with an active
    # AccessPass whose ``eligible_series_id`` matches. Distinct from
    # ``included_with_pathway`` because a Series is not a Pathway,
    # and distinct from mere ``series_id`` membership — an Event may
    # belong to a Series for grouping/presentation while remaining
    # ``free`` or ``included_with_collective``.
    ("included_with_series",    "Included with a term pass"),
    ("paid_separately",         "Paid separately"),
    ("invitation_only",         "Invitation only"),
)

ACCESS_TYPE_VALUES: tuple[str, ...] = tuple(a[0] for a in ACCESS_TYPES)
ACCESS_TYPE_LABEL: dict[str, str] = {a[0]: a[1] for a in ACCESS_TYPES}

DEFAULT_ACCESS_TYPE = "included_with_collective"


# Legacy string mapping. Migration 079 rewrites `booking_access_type`
# rows in the DB, but if anything in flight still uses the old value
# this helper lets us stay compatible without a cascade of changes.
LEGACY_ACCESS_MAP: dict[str, str] = {
    "all_members":      "included_with_collective",
    "pathway_required": "included_with_pathway",
}


def normalise_access_type(value: str | None) -> str:
    """Map any incoming value (new or legacy) to the current
    vocabulary. Unknown values fall back to the default so a stale
    row never breaks a caller."""
    if value is None:
        return DEFAULT_ACCESS_TYPE
    if value in ACCESS_TYPE_VALUES:
        return value
    return LEGACY_ACCESS_MAP.get(value, DEFAULT_ACCESS_TYPE)
