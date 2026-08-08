"""Digest items — the buffer between the routing pipeline and future digests.

Milestone 5a introduces the write path:
:func:`insert_digest_item` records one item per digest-eligible event
in ``communication_digest_items``. Multiple items accumulate over a
member's chosen daily or weekly window; the M13 digest worker will
group them, render one digest, create one delivery intent, and mark
the items consumed.

Design notes
------------

* The ordinary M4 delivery worker **never** touches this table.
  Digest items are structurally incapable of individual dispatch —
  they must be rolled into a digest intent first (M13). This
  mirrors the ``delivery_mode`` guarantee for shadow intents:
  safety by table separation, not by convention.
* :func:`compute_next_window` uses the member's timezone + digest
  arrival preferences (from ``communication_member_settings``) to
  place a new item into the correct upcoming window. When a member
  changes their digest arrival time or timezone, existing queued
  digest items **stay in their original window** — mid-window
  reassignment adds complexity for no meaningful user benefit and
  risks losing items across worker cycles. Only newly-inserted
  items reflect the new preferences.
* All timestamps stored in the DB are naive UTC; the member's
  timezone is applied only for the window computation and then
  discarded.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time as dtime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.comms.models import (
    CommunicationDigestItem,
    CommunicationMemberSettings,
)


CADENCE_DAILY = "daily"
CADENCE_WEEKLY = "weekly"
ALL_CADENCES = (CADENCE_DAILY, CADENCE_WEEKLY)

Cadence = Literal["daily", "weekly"]

# Platform defaults used when a member has no ``communication_member_settings``
# row or the relevant column is NULL.
_DEFAULT_TZ = "UTC"
_DEFAULT_DAILY_LOCAL_TIME = dtime(8, 0)         # 08:00 local
_DEFAULT_WEEKLY_LOCAL_WEEKDAY = 6                # 0=Mon..6=Sun → Sunday
_DEFAULT_WEEKLY_LOCAL_TIME = dtime(9, 0)         # 09:00 local


class UnknownCadenceError(ValueError):
    """The cadence is not a member of the digest cadence enum."""


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _naive_utc(dt_aware: datetime) -> datetime:
    """Convert a timezone-aware UTC datetime to a naive datetime for DB storage."""
    return dt_aware.astimezone(UTC).replace(tzinfo=None)


def _new_digest_item_id() -> str:
    return f"cdi_{uuid.uuid4().hex[:12]}"


def _load_member_prefs(
    db: Session, user_id: str,
) -> tuple[str, dtime, int, dtime]:
    """Load the member's timezone + digest arrival prefs, falling back to
    platform defaults for any NULL field. Returns
    ``(tz_name, daily_time_local, weekly_weekday, weekly_time_local)``.
    """
    row = db.get(CommunicationMemberSettings, user_id)
    tz_name = (row.timezone if row else None) or _DEFAULT_TZ
    daily_time = (row.daily_digest_send_local_time if row else None) or _DEFAULT_DAILY_LOCAL_TIME
    weekly_weekday = (
        row.weekly_digest_send_local_weekday
        if row and row.weekly_digest_send_local_weekday is not None
        else _DEFAULT_WEEKLY_LOCAL_WEEKDAY
    )
    weekly_time = (row.weekly_digest_send_local_time if row else None) or _DEFAULT_WEEKLY_LOCAL_TIME
    return tz_name, daily_time, weekly_weekday, weekly_time


def compute_next_window(
    db: Session,
    *,
    user_id: str,
    cadence: Cadence,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Compute the ``(scheduled_window_start, scheduled_window_end)``
    for a digest item created now.

    Returns naive UTC datetimes. ``window_end`` is when the digest
    worker will fire; ``window_start`` is the beginning of the
    aggregation range (the previous window's end, or the current
    moment if this is the first item in a window).

    Rules:

    * ``daily`` — window ends at the next occurrence of the member's
      chosen local send time. If the send time is later today, that's
      today; else tomorrow.
    * ``weekly`` — window ends at the next occurrence of
      ``(weekly_weekday, weekly_time)`` in the member's local timezone.
      If today matches the weekday and the send time is still ahead,
      that's today; otherwise the next matching weekday.
    * ``window_start`` is the previous same-cadence window's end (i.e.,
      one day earlier for daily, one week earlier for weekly). This
      guarantees adjacent windows tile without gap or overlap.
    """
    if cadence not in ALL_CADENCES:
        raise UnknownCadenceError(
            f"Unknown cadence: {cadence!r}. Expected one of {ALL_CADENCES}."
        )

    now_aware = now.astimezone(UTC) if now else _now_utc()
    tz_name, daily_time, weekly_weekday, weekly_time = _load_member_prefs(db, user_id)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        # A bad IANA string on the member row should not crash routing;
        # fall back to UTC and log-worthy but not fatal.
        tz = ZoneInfo(_DEFAULT_TZ)

    now_local = now_aware.astimezone(tz)

    if cadence == CADENCE_DAILY:
        target_local = datetime.combine(now_local.date(), daily_time, tzinfo=tz)
        if target_local <= now_local:
            target_local = target_local + timedelta(days=1)
        window_end_utc = _naive_utc(target_local)
        window_start_utc = _naive_utc(target_local - timedelta(days=1))
        return window_start_utc, window_end_utc

    # Weekly
    days_ahead = (weekly_weekday - now_local.weekday()) % 7
    candidate_local = datetime.combine(
        now_local.date() + timedelta(days=days_ahead), weekly_time, tzinfo=tz,
    )
    if candidate_local <= now_local:
        candidate_local = candidate_local + timedelta(days=7)
    window_end_utc = _naive_utc(candidate_local)
    window_start_utc = _naive_utc(candidate_local - timedelta(days=7))
    return window_start_utc, window_end_utc


def insert_digest_item(
    db: Session,
    *,
    user_id: str,
    category_key: str,
    cadence: Cadence,
    source_type: str,
    source_id: str | None,
    human_reason: str,
    item_payload: dict[str, Any] | None = None,
    event_id: str | None = None,
    now: datetime | None = None,
) -> CommunicationDigestItem:
    """Buffer a single digest-eligible piece of content for a member.

    Called by the M5b decision layer when priority resolves to
    ``daily_digest`` or ``weekly_digest``. Never creates an intent.

    The digest window is computed at insertion time and stored on
    the row so that subsequent preference changes do not disturb
    items already queued.
    """
    if not user_id:
        raise ValueError("user_id is required.")
    if not human_reason:
        raise ValueError("human_reason is required.")
    if cadence not in ALL_CADENCES:
        raise UnknownCadenceError(
            f"Unknown cadence: {cadence!r}. Expected one of {ALL_CADENCES}."
        )

    window_start, window_end = compute_next_window(
        db, user_id=user_id, cadence=cadence, now=now,
    )

    row = CommunicationDigestItem(
        id=_new_digest_item_id(),
        user_id=user_id,
        category_key=category_key,
        cadence=cadence,
        event_id=event_id,
        source_type=source_type,
        source_id=source_id,
        human_reason=human_reason,
        item_payload=item_payload or {},
        scheduled_window_start=window_start,
        scheduled_window_end=window_end,
    )
    db.add(row)
    db.flush()
    return row
