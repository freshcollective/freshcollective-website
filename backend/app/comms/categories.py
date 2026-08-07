"""Constants + light types used across the Communications Layer.

Kept as string constants rather than Python enums so migrations and
raw SQL can reference the same values without additional imports. The
:class:`Source`, :class:`Priority`, and :class:`Channel` helpers are
just typed façades — value equality is what matters.
"""

from __future__ import annotations

from typing import Literal


# ---------------------------------------------------------------------------
# Source — who the communication is from (Refinement 3, first-class alongside
# Category and Reason).
# ---------------------------------------------------------------------------

SOURCE_FRESH_COLLECTIVE = "fresh_collective"
SOURCE_COLLECTIVE = "collective"
SOURCE_CREATOR = "creator"

ALL_SOURCES = (
    SOURCE_FRESH_COLLECTIVE,
    SOURCE_COLLECTIVE,
    SOURCE_CREATOR,
)

SourceType = Literal["fresh_collective", "collective", "creator"]


class Source:
    """Typed façade for source constants.

    Usage::

        Source.FRESH_COLLECTIVE  # "fresh_collective"
        Source.CREATOR           # "creator"
    """

    FRESH_COLLECTIVE = SOURCE_FRESH_COLLECTIVE
    COLLECTIVE = SOURCE_COLLECTIVE
    CREATOR = SOURCE_CREATOR


# ---------------------------------------------------------------------------
# Priority — the pacing hint attached at emit time.
# ---------------------------------------------------------------------------

PRIORITY_IMMEDIATE = "immediate"
PRIORITY_SCHEDULED = "scheduled"
PRIORITY_DAILY_DIGEST = "daily_digest"
PRIORITY_WEEKLY_DIGEST = "weekly_digest"
PRIORITY_SILENT = "silent"

ALL_PRIORITIES = (
    PRIORITY_IMMEDIATE,
    PRIORITY_SCHEDULED,
    PRIORITY_DAILY_DIGEST,
    PRIORITY_WEEKLY_DIGEST,
    PRIORITY_SILENT,
)

PriorityType = Literal[
    "immediate", "scheduled", "daily_digest", "weekly_digest", "silent"
]


class Priority:
    IMMEDIATE = PRIORITY_IMMEDIATE
    SCHEDULED = PRIORITY_SCHEDULED
    DAILY_DIGEST = PRIORITY_DAILY_DIGEST
    WEEKLY_DIGEST = PRIORITY_WEEKLY_DIGEST
    SILENT = PRIORITY_SILENT


# ---------------------------------------------------------------------------
# Channel — the delivery medium. Every event × topic combination declares
# which channels are eligible; per-user preferences narrow further.
# ---------------------------------------------------------------------------

CHANNEL_IN_APP = "in_app"
CHANNEL_EMAIL_TRANSACTIONAL = "email_transactional"
CHANNEL_EMAIL_MARKETING = "email_marketing"
CHANNEL_PUSH = "push"
CHANNEL_WEBHOOK_OUTBOUND = "webhook_outbound"

ALL_CHANNELS = (
    CHANNEL_IN_APP,
    CHANNEL_EMAIL_TRANSACTIONAL,
    CHANNEL_EMAIL_MARKETING,
    CHANNEL_PUSH,
    CHANNEL_WEBHOOK_OUTBOUND,
)

ChannelType = Literal[
    "in_app",
    "email_transactional",
    "email_marketing",
    "push",
    "webhook_outbound",
]


class Channel:
    IN_APP = CHANNEL_IN_APP
    EMAIL_TRANSACTIONAL = CHANNEL_EMAIL_TRANSACTIONAL
    EMAIL_MARKETING = CHANNEL_EMAIL_MARKETING
    PUSH = CHANNEL_PUSH
    WEBHOOK_OUTBOUND = CHANNEL_WEBHOOK_OUTBOUND


# ---------------------------------------------------------------------------
# Member-facing categories — nine of them. Mirrors the seed in migration 097.
# The keys match ``communication_categories.key`` rows.
# ---------------------------------------------------------------------------

CATEGORY_ACCOUNT = "account"
CATEGORY_SAFETY = "safety"
CATEGORY_PURCHASES = "purchases"
CATEGORY_MESSAGES = "messages"
CATEGORY_GATHERINGS = "gatherings"
CATEGORY_PATHWAYS = "pathways"
CATEGORY_COMMUNITY = "community"
CATEGORY_CREATOR_UPDATES = "creator_updates"
CATEGORY_PLATFORM_UPDATES = "platform_updates"

ALL_CATEGORIES = (
    CATEGORY_ACCOUNT,
    CATEGORY_SAFETY,
    CATEGORY_PURCHASES,
    CATEGORY_MESSAGES,
    CATEGORY_GATHERINGS,
    CATEGORY_PATHWAYS,
    CATEGORY_COMMUNITY,
    CATEGORY_CREATOR_UPDATES,
    CATEGORY_PLATFORM_UPDATES,
)


# ---------------------------------------------------------------------------
# Internal topics — mirrors the seed in migration 097. Domain code doesn't
# usually reference these directly; the event registry resolves an event_type
# to its topic (and category) automatically.
# ---------------------------------------------------------------------------

TOPIC_ACCOUNT = "account"
TOPIC_SECURITY = "security"
TOPIC_CONVERSATIONS = "conversations"
TOPIC_COLLECTIVE_UPDATES = "collective_updates"
TOPIC_PATHWAYS = "pathways"
TOPIC_GATHERINGS = "gatherings"
TOPIC_DIRECT_MESSAGES = "direct_messages"
TOPIC_PURCHASES = "purchases"
TOPIC_SUBSCRIPTIONS = "subscriptions"
TOPIC_CREATOR_BROADCASTS = "creator_broadcasts"
TOPIC_PRODUCT_UPDATES = "product_updates"
TOPIC_MARKETING = "marketing"
TOPIC_MODERATION = "moderation"
TOPIC_COMMUNITY_CARE = "community_care"

ALL_TOPICS = (
    TOPIC_ACCOUNT,
    TOPIC_SECURITY,
    TOPIC_CONVERSATIONS,
    TOPIC_COLLECTIVE_UPDATES,
    TOPIC_PATHWAYS,
    TOPIC_GATHERINGS,
    TOPIC_DIRECT_MESSAGES,
    TOPIC_PURCHASES,
    TOPIC_SUBSCRIPTIONS,
    TOPIC_CREATOR_BROADCASTS,
    TOPIC_PRODUCT_UPDATES,
    TOPIC_MARKETING,
    TOPIC_COMMUNITY_CARE,
    TOPIC_MODERATION,
)


# ---------------------------------------------------------------------------
# Topic → Category mapping. Engineering-owned: adding a new topic and a new
# category should always ship with a migration seeding both plus an entry
# here.
# ---------------------------------------------------------------------------

TOPIC_TO_CATEGORY: dict[str, str] = {
    TOPIC_ACCOUNT:            CATEGORY_ACCOUNT,
    TOPIC_SECURITY:           CATEGORY_ACCOUNT,
    TOPIC_CONVERSATIONS:      CATEGORY_COMMUNITY,
    TOPIC_COLLECTIVE_UPDATES: CATEGORY_COMMUNITY,
    TOPIC_PATHWAYS:           CATEGORY_PATHWAYS,
    TOPIC_GATHERINGS:         CATEGORY_GATHERINGS,
    TOPIC_DIRECT_MESSAGES:    CATEGORY_MESSAGES,
    TOPIC_PURCHASES:          CATEGORY_PURCHASES,
    TOPIC_SUBSCRIPTIONS:      CATEGORY_PURCHASES,
    TOPIC_CREATOR_BROADCASTS: CATEGORY_CREATOR_UPDATES,
    TOPIC_PRODUCT_UPDATES:    CATEGORY_PLATFORM_UPDATES,
    TOPIC_MARKETING:          CATEGORY_PLATFORM_UPDATES,
    TOPIC_MODERATION:         CATEGORY_SAFETY,
    TOPIC_COMMUNITY_CARE:     CATEGORY_SAFETY,
}
