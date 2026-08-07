"""Preference, consent and member-settings resolution helpers.

Pure Python read/write helpers used by:

  * ``/api/comms/preferences/me`` and ``/api/comms/consents/me`` (this
    milestone), and
  * the eligibility decision layer (Milestone 5) when routing events
    to intents.

The helpers do not perform any I/O beyond the passed-in Session.
Callers manage transactions; helpers just add / flush.

Effective-preference resolution
-------------------------------

For any (user, category, channel):

  1. If a row exists in ``communication_preferences`` for that triple,
     its ``priority`` value is effective.
  2. Else, the ``communication_channel_defaults`` row for
     (category, channel) provides:
       * ``default_enabled=True``  →  effective priority = ``immediate``
       * ``default_enabled=False`` →  effective priority = ``silent``
  3. If no channel-default row exists for the pair, the channel is not
     supported for that category and the resolver returns ``None``.

Locked defaults
---------------

If the channel default has ``is_locked=True``, the member cannot
override — ``set_preference`` raises :class:`LockedPreferenceError`.
This preserves the platform's non-negotiable duty of care for
Account, Purchases and Safety in-app and email notifications.

Consent
-------

Consent is append-only. ``grant_consent`` and ``revoke_consent``
always insert a new row rather than mutating history.
``get_consent_state`` returns the most recent row for the pair (or
``None`` if the user has never interacted with that consent kind).

Member settings
---------------

Global settings (timezone, quiet hours, digest times) sit in a
single row per user, lazily created. ``get_member_settings`` returns
the row or ``None``; ``update_member_settings`` upserts with the
provided fields, leaving unspecified fields untouched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.comms.categories import (
    ALL_CATEGORIES,
    ALL_CHANNELS,
    ALL_PRIORITIES,
    PRIORITY_IMMEDIATE,
    PRIORITY_SILENT,
    ChannelType,
    PriorityType,
)
from app.comms.models import (
    CommunicationCategory,
    CommunicationChannelDefault,
    CommunicationConsent,
    CommunicationMemberSettings,
    CommunicationPreference,
)


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class UnknownCategoryError(ValueError):
    """The category key is not registered in ``communication_categories``."""


class UnknownChannelError(ValueError):
    """The channel is not a member of ``communication_channel_enum``."""


class UnknownPriorityError(ValueError):
    """The priority is not a member of ``communication_priority_enum``."""


class UnsupportedChannelError(ValueError):
    """The channel is not offered for this category (no default row)."""


class LockedPreferenceError(PermissionError):
    """The category × channel is locked; members cannot override it."""


# ---------------------------------------------------------------------------
# Effective preference
# ---------------------------------------------------------------------------


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _new_preference_id() -> str:
    return f"cpr_{uuid.uuid4().hex[:12]}"


def _new_consent_id() -> str:
    return f"cco_{uuid.uuid4().hex[:12]}"


def _load_channel_default(
    db: Session, category_key: str, channel: str,
) -> CommunicationChannelDefault | None:
    return db.execute(
        select(CommunicationChannelDefault)
        .where(
            CommunicationChannelDefault.category_key == category_key,
            CommunicationChannelDefault.channel == channel,
        )
    ).scalar_one_or_none()


def get_effective_preference(
    db: Session,
    *,
    user_id: str,
    category_key: str,
    channel: ChannelType,
) -> tuple[str, bool, str]:
    """Resolve the effective priority for the pair, plus its origin.

    Returns
    -------
    (priority, is_locked, origin)
        ``priority``  — one of ``ALL_PRIORITIES``.
        ``is_locked`` — True if the member cannot override.
        ``origin``    — ``"override"`` if a preference row wins,
                         ``"default"`` if the channel default wins.

    Raises
    ------
    UnknownCategoryError, UnknownChannelError, UnsupportedChannelError
    """
    if category_key not in ALL_CATEGORIES:
        raise UnknownCategoryError(f"Unknown category: {category_key!r}")
    if channel not in ALL_CHANNELS:
        raise UnknownChannelError(f"Unknown channel: {channel!r}")

    default = _load_channel_default(db, category_key, channel)
    if default is None:
        raise UnsupportedChannelError(
            f"Channel {channel!r} is not offered for category {category_key!r}."
        )

    override = db.execute(
        select(CommunicationPreference).where(
            CommunicationPreference.user_id == user_id,
            CommunicationPreference.category_key == category_key,
            CommunicationPreference.channel == channel,
        )
    ).scalar_one_or_none()

    if override is not None:
        return override.priority, default.is_locked, "override"

    default_priority = PRIORITY_IMMEDIATE if default.default_enabled else PRIORITY_SILENT
    return default_priority, default.is_locked, "default"


def set_preference(
    db: Session,
    *,
    user_id: str,
    category_key: str,
    channel: ChannelType,
    priority: PriorityType,
) -> CommunicationPreference:
    """Upsert a preference row. Refuses to write when the channel
    default is locked.

    Raises
    ------
    UnknownCategoryError, UnknownChannelError, UnknownPriorityError,
    UnsupportedChannelError, LockedPreferenceError
    """
    if category_key not in ALL_CATEGORIES:
        raise UnknownCategoryError(f"Unknown category: {category_key!r}")
    if channel not in ALL_CHANNELS:
        raise UnknownChannelError(f"Unknown channel: {channel!r}")
    if priority not in ALL_PRIORITIES:
        raise UnknownPriorityError(f"Unknown priority: {priority!r}")

    default = _load_channel_default(db, category_key, channel)
    if default is None:
        raise UnsupportedChannelError(
            f"Channel {channel!r} is not offered for category {category_key!r}."
        )
    if default.is_locked:
        raise LockedPreferenceError(
            f"({category_key}, {channel}) is locked and cannot be overridden."
        )

    existing = db.execute(
        select(CommunicationPreference).where(
            CommunicationPreference.user_id == user_id,
            CommunicationPreference.category_key == category_key,
            CommunicationPreference.channel == channel,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.priority = priority
        existing.updated_at = _now_naive()
        db.flush()
        return existing

    pref = CommunicationPreference(
        id=_new_preference_id(),
        user_id=user_id,
        category_key=category_key,
        channel=channel,
        priority=priority,
    )
    db.add(pref)
    db.flush()
    return pref


def clear_preference(
    db: Session,
    *,
    user_id: str,
    category_key: str,
    channel: ChannelType,
) -> bool:
    """Remove an override row so the default applies. Returns True if
    a row existed and was removed, False if there was nothing to clear.
    """
    row = db.execute(
        select(CommunicationPreference).where(
            CommunicationPreference.user_id == user_id,
            CommunicationPreference.category_key == category_key,
            CommunicationPreference.channel == channel,
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def get_preference_matrix(
    db: Session,
    *,
    user_id: str,
) -> list[dict[str, Any]]:
    """Return the full category × channel matrix as a list of dicts:

        [
          {
            "category_key": "community",
            "category_label": "Community",
            "category_description": "...",
            "sort_order": 70,
            "is_critical": False,
            "cells": [
              {"channel": "in_app", "priority": "immediate",
               "is_locked": False, "origin": "default"},
              ...
            ],
          },
          ...
        ]

    Ordered by category ``sort_order``; cells ordered by the seed
    channel order for that category.
    """
    categories = db.execute(
        select(CommunicationCategory).order_by(CommunicationCategory.sort_order)
    ).scalars().all()

    defaults = db.execute(select(CommunicationChannelDefault)).scalars().all()
    defaults_by_cat: dict[str, list[CommunicationChannelDefault]] = {}
    for d in defaults:
        defaults_by_cat.setdefault(d.category_key, []).append(d)

    overrides = db.execute(
        select(CommunicationPreference).where(
            CommunicationPreference.user_id == user_id,
        )
    ).scalars().all()
    overrides_by_pair: dict[tuple[str, str], CommunicationPreference] = {
        (o.category_key, o.channel): o for o in overrides
    }

    out: list[dict[str, Any]] = []
    for cat in categories:
        cells = []
        # Deterministic channel ordering — matches the channel enum
        # declaration order so the UI shows in_app → email → push.
        cat_defaults = sorted(
            defaults_by_cat.get(cat.key, []),
            key=lambda d: (
                # In-app first, transactional email second, marketing
                # third, push last, webhook_outbound after.
                {
                    "in_app": 0,
                    "email_transactional": 1,
                    "email_marketing": 2,
                    "push": 3,
                    "webhook_outbound": 4,
                }.get(d.channel, 99)
            ),
        )
        for d in cat_defaults:
            override = overrides_by_pair.get((cat.key, d.channel))
            if override is not None:
                priority = override.priority
                origin = "override"
            else:
                priority = PRIORITY_IMMEDIATE if d.default_enabled else PRIORITY_SILENT
                origin = "default"
            cells.append({
                "channel": d.channel,
                "priority": priority,
                "is_locked": d.is_locked,
                "origin": origin,
            })
        out.append({
            "category_key": cat.key,
            "category_label": cat.label,
            "category_description": cat.description,
            "sort_order": cat.sort_order,
            "is_critical": cat.is_critical,
            "cells": cells,
        })
    return out


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


def get_consent_state(
    db: Session,
    *,
    user_id: str,
    consent_kind: str,
) -> CommunicationConsent | None:
    """Return the most recent consent row for the pair, or None if the
    user has never interacted with this consent kind.
    """
    # ``id`` acts as a deterministic tiebreaker when two consent
    # transitions share a microsecond timestamp (tests + rapid grant/
    # revoke pairs). Newer id sorts higher because ``_new_consent_id``
    # embeds a fresh UUID prefix; combined with occurred_at DESC this
    # guarantees stable ordering.
    return db.execute(
        select(CommunicationConsent)
        .where(
            CommunicationConsent.user_id == user_id,
            CommunicationConsent.consent_kind == consent_kind,
        )
        .order_by(
            desc(CommunicationConsent.occurred_at),
            desc(CommunicationConsent.id),
        )
        .limit(1)
    ).scalar_one_or_none()


def _append_consent(
    db: Session,
    *,
    user_id: str,
    consent_kind: str,
    state: str,
    source: str,
    policy_version: str | None,
    evidence_ip_hash: str | None,
    evidence_ua_hash: str | None,
) -> CommunicationConsent:
    # occurred_at is set explicitly (rather than relying on the
    # server_default NOW()) because inside a single transaction
    # Postgres returns the same NOW() for every statement — grant
    # then revoke in the same test/request would tie on timestamp.
    row = CommunicationConsent(
        id=_new_consent_id(),
        user_id=user_id,
        consent_kind=consent_kind,
        state=state,
        source=source,
        policy_version=policy_version,
        evidence_ip_hash=evidence_ip_hash,
        evidence_ua_hash=evidence_ua_hash,
        occurred_at=_now_naive(),
    )
    db.add(row)
    db.flush()
    return row


def grant_consent(
    db: Session,
    *,
    user_id: str,
    consent_kind: str,
    source: str,
    policy_version: str | None = None,
    evidence_ip_hash: str | None = None,
    evidence_ua_hash: str | None = None,
) -> CommunicationConsent:
    """Append a granted consent record. Always inserts — repeat calls
    create a new row (audit trail preserves every state transition).
    """
    return _append_consent(
        db,
        user_id=user_id,
        consent_kind=consent_kind,
        state="granted",
        source=source,
        policy_version=policy_version,
        evidence_ip_hash=evidence_ip_hash,
        evidence_ua_hash=evidence_ua_hash,
    )


def revoke_consent(
    db: Session,
    *,
    user_id: str,
    consent_kind: str,
    source: str,
    evidence_ip_hash: str | None = None,
    evidence_ua_hash: str | None = None,
) -> CommunicationConsent:
    """Append a revoked consent record. Same append semantics as grant."""
    return _append_consent(
        db,
        user_id=user_id,
        consent_kind=consent_kind,
        state="revoked",
        source=source,
        policy_version=None,
        evidence_ip_hash=evidence_ip_hash,
        evidence_ua_hash=evidence_ua_hash,
    )


# ---------------------------------------------------------------------------
# Member settings
# ---------------------------------------------------------------------------


def get_member_settings(
    db: Session, *, user_id: str,
) -> CommunicationMemberSettings | None:
    return db.get(CommunicationMemberSettings, user_id)


# Sentinel used by ``update_member_settings`` to distinguish "not
# provided in this call" from "explicitly set to NULL". Callers pass
# an actual value (including ``None``) to change a field.
_UNSET: Any = object()


def update_member_settings(
    db: Session,
    *,
    user_id: str,
    timezone: Any = _UNSET,
    quiet_hours_start_local: Any = _UNSET,
    quiet_hours_end_local: Any = _UNSET,
    daily_digest_send_local_time: Any = _UNSET,
    weekly_digest_send_local_weekday: Any = _UNSET,
    weekly_digest_send_local_time: Any = _UNSET,
) -> CommunicationMemberSettings:
    """Upsert the settings row for a member. Only fields explicitly
    passed are touched; unpassed fields retain their existing value.
    Pass ``None`` for a field to reset it to the platform default.
    """
    row = db.get(CommunicationMemberSettings, user_id)
    if row is None:
        row = CommunicationMemberSettings(user_id=user_id)
        db.add(row)

    if timezone is not _UNSET:
        row.timezone = timezone
    if quiet_hours_start_local is not _UNSET:
        row.quiet_hours_start_local = quiet_hours_start_local
    if quiet_hours_end_local is not _UNSET:
        row.quiet_hours_end_local = quiet_hours_end_local
    if daily_digest_send_local_time is not _UNSET:
        row.daily_digest_send_local_time = daily_digest_send_local_time
    if weekly_digest_send_local_weekday is not _UNSET:
        if weekly_digest_send_local_weekday is not None and not (
            0 <= weekly_digest_send_local_weekday <= 6
        ):
            raise ValueError(
                "weekly_digest_send_local_weekday must be 0..6 (Mon..Sun)."
            )
        row.weekly_digest_send_local_weekday = weekly_digest_send_local_weekday
    if weekly_digest_send_local_time is not _UNSET:
        row.weekly_digest_send_local_time = weekly_digest_send_local_time

    row.updated_at = _now_naive()
    db.flush()
    return row
