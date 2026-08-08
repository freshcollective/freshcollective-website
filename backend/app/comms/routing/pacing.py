"""Priority resolution, rate limits, quiet hours.

Three helpers used by the decision pipeline:

* :func:`resolve_priority` — starts from the effective preference,
  applies per-day immediate-email rate limits (downgrading to
  ``daily_digest`` when over cap), and returns the priority the
  intent should carry.
* :func:`evaluate_quiet_hours` — for immediate email/push, computes
  a ``scheduled_for`` timestamp if the current moment falls inside
  the member's quiet-hours window; otherwise returns ``None``.
* :func:`should_route_to_digest` — small classifier the decision
  pipeline uses to branch into the digest buffer.

Rate limits (per member per category per day)
---------------------------------------------

Immediate-email cap: 5 per day per category. When exceeded the
new intent downgrades to ``daily_digest``. Rate-limit counting is
scoped to the intent's ``delivery_mode`` so shadow mode observes
what live routing would produce (rather than being skewed by live
traffic or vice-versa).

Quiet hours
-----------

Read the member's ``communication_member_settings`` (timezone +
quiet_hours_start_local + quiet_hours_end_local). When both bounds
are set, an immediate email/push falling inside the window has its
``scheduled_for`` bumped to the next ``quiet_hours_end`` in UTC.
Handles the midnight-wrap case (start > end means "overnight").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.comms.categories import (
    CHANNEL_EMAIL_MARKETING,
    CHANNEL_EMAIL_TRANSACTIONAL,
    CHANNEL_PUSH,
    PRIORITY_DAILY_DIGEST,
    PRIORITY_IMMEDIATE,
    PRIORITY_SILENT,
    PRIORITY_WEEKLY_DIGEST,
)
from app.comms.models import (
    CommunicationIntent,
    CommunicationMemberSettings,
)


# Rate limits — see design doc §2.15
IMMEDIATE_EMAIL_CAP_PER_CATEGORY_PER_DAY = 5


DIGEST_PRIORITIES = frozenset({PRIORITY_DAILY_DIGEST, PRIORITY_WEEKLY_DIGEST})


@dataclass(frozen=True)
class QuietHoursResult:
    """Outcome of a quiet-hours evaluation."""

    in_quiet_hours: bool
    scheduled_for_utc: datetime | None   # naive UTC; set only when in_quiet_hours


def _now_utc_aware() -> datetime:
    return datetime.now(UTC)


def _naive_utc(dt_aware: datetime) -> datetime:
    return dt_aware.astimezone(UTC).replace(tzinfo=None)


def should_route_to_digest(priority: str) -> bool:
    """True if the intent should be buffered as a digest item rather
    than turned into a queued intent.
    """
    return priority in DIGEST_PRIORITIES


def _immediate_email_count_today(
    db: Session,
    *,
    user_id: str,
    category_key: str,
    channel: str,
    delivery_mode: str,
    now: datetime,
) -> int:
    """Count immediate-priority intents for this member/category/channel
    already created today (UTC calendar day), scoped to the same
    delivery_mode. Excludes ``recorded`` and ``suppressed`` states so
    silent/blocked intents don't count against the cap.
    """
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    result = db.execute(
        select(func.count()).select_from(CommunicationIntent).where(
            CommunicationIntent.recipient_user_id == user_id,
            CommunicationIntent.category_key == category_key,
            CommunicationIntent.channel == channel,
            CommunicationIntent.priority == PRIORITY_IMMEDIATE,
            CommunicationIntent.delivery_mode == delivery_mode,
            CommunicationIntent.state.notin_(["recorded", "suppressed"]),
            CommunicationIntent.created_at >= day_start,
            CommunicationIntent.created_at < day_end,
        )
    ).scalar_one()
    return int(result or 0)


def resolve_priority(
    db: Session,
    *,
    user_id: str,
    category_key: str,
    channel: str,
    preferred_priority: str,
    delivery_mode: str,
    now: datetime | None = None,
) -> str:
    """Return the final priority for a would-be intent.

    Starts from the member's effective preference (``preferred_priority``)
    and applies rate-limit downgrades:

    * ``silent`` stays ``silent``.
    * ``immediate`` on an email channel gets downgraded to
      ``daily_digest`` if the member has already received
      :data:`IMMEDIATE_EMAIL_CAP_PER_CATEGORY_PER_DAY` immediate
      emails today in this category.
    * Digest priorities stay as-is.
    """
    if preferred_priority == PRIORITY_SILENT:
        return PRIORITY_SILENT
    if preferred_priority in DIGEST_PRIORITIES:
        return preferred_priority
    if preferred_priority != PRIORITY_IMMEDIATE:
        # scheduled / any future priorities pass through unchanged
        return preferred_priority

    # Immediate — apply rate limit only to email channels (rate limits
    # exist to prevent inbox flood; in-app has no equivalent stress).
    if channel not in (CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_EMAIL_MARKETING):
        return PRIORITY_IMMEDIATE

    when = (now or _now_utc_aware()).astimezone(UTC).replace(tzinfo=None)
    count = _immediate_email_count_today(
        db,
        user_id=user_id,
        category_key=category_key,
        channel=channel,
        delivery_mode=delivery_mode,
        now=when,
    )
    if count >= IMMEDIATE_EMAIL_CAP_PER_CATEGORY_PER_DAY:
        return PRIORITY_DAILY_DIGEST
    return PRIORITY_IMMEDIATE


def evaluate_quiet_hours(
    db: Session,
    *,
    user_id: str,
    channel: str,
    now: datetime | None = None,
) -> QuietHoursResult:
    """If the member is currently inside their quiet-hours window,
    return the UTC ``scheduled_for`` to defer delivery to the window
    end. Otherwise return an empty result (deliver now).

    Applies only to email/push channels — in-app is never quiet-hour-
    gated (it doesn't wake the member up).
    """
    if channel not in (CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_EMAIL_MARKETING, CHANNEL_PUSH):
        return QuietHoursResult(in_quiet_hours=False, scheduled_for_utc=None)

    settings_row = db.get(CommunicationMemberSettings, user_id)
    if settings_row is None:
        return QuietHoursResult(in_quiet_hours=False, scheduled_for_utc=None)
    if (
        settings_row.quiet_hours_start_local is None
        or settings_row.quiet_hours_end_local is None
    ):
        return QuietHoursResult(in_quiet_hours=False, scheduled_for_utc=None)

    tz_name = settings_row.timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    now_aware = (now or _now_utc_aware()).astimezone(UTC)
    now_local = now_aware.astimezone(tz)
    start_t = settings_row.quiet_hours_start_local
    end_t = settings_row.quiet_hours_end_local

    now_t = now_local.time()
    # Two window shapes:
    #   * start < end     → same-day window (e.g. 13:00 to 15:00)
    #   * start > end     → overnight window (e.g. 22:00 to 07:00)
    #   * start == end    → the window is empty; never quiet
    if start_t == end_t:
        return QuietHoursResult(in_quiet_hours=False, scheduled_for_utc=None)

    if start_t < end_t:
        in_window = start_t <= now_t < end_t
    else:
        in_window = now_t >= start_t or now_t < end_t

    if not in_window:
        return QuietHoursResult(in_quiet_hours=False, scheduled_for_utc=None)

    # Compute the next occurrence of end_t in local time.
    end_today_local = datetime.combine(now_local.date(), end_t, tzinfo=tz)
    if end_today_local > now_local:
        target_local = end_today_local
    else:
        target_local = end_today_local + timedelta(days=1)
    scheduled_utc = _naive_utc(target_local)
    return QuietHoursResult(in_quiet_hours=True, scheduled_for_utc=scheduled_utc)
