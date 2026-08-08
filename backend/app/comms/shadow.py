"""Shadow parity — comparators, reconciler, and metrics (Milestone 5c).

The shadow reconciler is a periodic worker (invoked from
``/api/internal/comms/reconcile-shadow``) that walks recently-emitted
CommunicationEvents and, for each one that has a registered
comparator, records exactly one CommunicationShadowComparison row
capturing whether the new routing pipeline's shadow output matches
the authoritative legacy behaviour.

Comparators
-----------

One per event_type. Registered via :func:`register_comparator` /
``@comparator_for``. A comparator returns a :class:`ComparisonResult`
scoring the seven parity dimensions (see doc §5) and a
:class:`ShadowParityVerdict` summarising them.

  * ``NotificationBasedComparator`` — for events whose legacy path
    writes rows into the ``notifications`` table. Recipient parity
    is measured by matching user_id sets on notifications produced
    within ``event.occurred_at ± NOTIFICATION_WINDOW`` and the
    shadow intents' recipient_user_ids for the same event.
  * ``StructuralComparator`` — for events with no in-app notification
    trail (e.g. password reset — legacy sends an email only). The
    comparator asserts the shadow pipeline produced the expected
    structural output for the expected recipient set; the legacy
    side is unverifiable in the current infrastructure so the
    ``dim_no_orphan_legacy`` dimension is treated as vacuously
    True and recorded as such in ``discrepancy_detail``.

Idempotency
-----------

``CommunicationShadowComparison`` has a UNIQUE constraint on
``event_id``. A repeat reconciler run over the same window either
finds no new events to compare or trips the constraint on a race and
rolls back the individual insert (never the batch). Callers can run
the endpoint every few minutes without producing duplicates.

Parity metrics
--------------

:func:`compute_parity_report` reads comparison rows for a topic (or
category) across a rolling window of UTC days, computes the per-day
match/mismatch state, and returns a :class:`ParityReport` including
consecutive-day counting for cutover eligibility. A topic is
eligible only when the last three complete UTC days show 100% parity
across every dimension AND ``comparisons_recorded == events_observed``
for each qualifying day.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Protocol

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.comms.categories import TOPIC_TO_CATEGORY
from app.comms.intents import DELIVERY_MODE_SHADOW
from app.comms.models import (
    CommunicationEvent,
    CommunicationIntent,
    CommunicationShadowComparison,
)
from app.comms.registry import get_event_definition
from app.core.config import settings
from app.models.notification import Notification


logger = logging.getLogger(__name__)


# Time window on either side of event.occurred_at within which to
# consider a Notification row a candidate match for a legacy send.
NOTIFICATION_WINDOW = timedelta(minutes=5)


def _min_event_age() -> timedelta:
    """Read the reconciler's minimum event age from config at call time.

    Operators can adjust ``COMMS_RECONCILER_MIN_EVENT_AGE_SECONDS`` to
    match their cron cadence + BackgroundTasks latency without a
    code change.
    """
    return timedelta(seconds=int(settings.comms_reconciler_min_event_age_seconds))


# ---------------------------------------------------------------------------
# Parity verdict constants (mirror the enum shipped in migration 100)
# ---------------------------------------------------------------------------

VERDICT_MATCH = "match"
VERDICT_SHADOW_EXTRA = "shadow_extra"
VERDICT_LEGACY_EXTRA = "legacy_extra"
VERDICT_PAYLOAD_MISMATCH = "payload_mismatch"


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


@dataclass
class ComparisonResult:
    """Verdict + per-dimension breakdown for one event."""

    parity: str  # one of VERDICT_*
    shadow_intent_ids: list[str] = field(default_factory=list)
    legacy_notification_ids: list[str] = field(default_factory=list)
    discrepancy_detail: str | None = None

    # Seven parity dimensions.
    dim_recipient: bool = True
    dim_channel: bool = True
    dim_source: bool = True
    dim_category: bool = True
    dim_count: bool = True
    dim_no_orphan_legacy: bool = True
    dim_no_orphan_shadow: bool = True

    @property
    def all_dims_match(self) -> bool:
        return all([
            self.dim_recipient,
            self.dim_channel,
            self.dim_source,
            self.dim_category,
            self.dim_count,
            self.dim_no_orphan_legacy,
            self.dim_no_orphan_shadow,
        ])


# ---------------------------------------------------------------------------
# Comparator protocol + registry
# ---------------------------------------------------------------------------


class ShadowComparator(Protocol):
    event_type: str

    def compare(
        self, db: Session, event: CommunicationEvent,
    ) -> ComparisonResult: ...


_COMPARATORS: dict[str, ShadowComparator] = {}


def register_comparator(comparator: ShadowComparator) -> None:
    """Register a shadow comparator. Raises on duplicate."""
    if comparator.event_type in _COMPARATORS:
        raise ValueError(
            f"Shadow comparator for {comparator.event_type!r} already registered."
        )
    _COMPARATORS[comparator.event_type] = comparator


def get_comparator_for(event_type: str) -> ShadowComparator | None:
    return _COMPARATORS.get(event_type)


def registered_comparators() -> tuple[str, ...]:
    return tuple(sorted(_COMPARATORS.keys()))


def reset_comparator_registry() -> None:
    """For tests only."""
    _COMPARATORS.clear()


def comparator_for(event_type: str) -> Callable[[type], type]:
    def _wrap(cls: type) -> type:
        instance = cls()
        setattr(instance, "event_type", event_type)
        register_comparator(instance)  # type: ignore[arg-type]
        return cls
    return _wrap


# ---------------------------------------------------------------------------
# Concrete comparators
# ---------------------------------------------------------------------------


def _shadow_intents_for_event(
    db: Session, event_id: str,
) -> list[CommunicationIntent]:
    return db.execute(
        select(CommunicationIntent).where(
            CommunicationIntent.event_id == event_id,
            CommunicationIntent.delivery_mode == DELIVERY_MODE_SHADOW,
        )
    ).scalars().all()


def _notifications_in_window(
    db: Session,
    *,
    notification_type: str,
    center: datetime,
    window: timedelta = NOTIFICATION_WINDOW,
    recipient_ids: list[str] | None = None,
) -> list[Notification]:
    lo = center - window
    hi = center + window
    q = select(Notification).where(
        Notification.notification_type == notification_type,
        Notification.created_at >= lo,
        Notification.created_at <= hi,
    )
    if recipient_ids:
        q = q.where(Notification.user_id.in_(recipient_ids))
    return db.execute(q).scalars().all()


def _finalise(
    result: ComparisonResult,
    *,
    shadow_recipients: set[str],
    legacy_recipients: set[str],
) -> ComparisonResult:
    """Compute the aggregate verdict from the individual dimensions."""
    result.dim_no_orphan_shadow = shadow_recipients.issubset(legacy_recipients)
    result.dim_no_orphan_legacy = legacy_recipients.issubset(shadow_recipients)
    result.dim_recipient = (shadow_recipients == legacy_recipients)

    if result.all_dims_match:
        result.parity = VERDICT_MATCH
        result.discrepancy_detail = None
        return result

    # Pick the most descriptive verdict.
    if not result.dim_no_orphan_shadow and result.dim_no_orphan_legacy:
        result.parity = VERDICT_SHADOW_EXTRA
    elif not result.dim_no_orphan_legacy and result.dim_no_orphan_shadow:
        result.parity = VERDICT_LEGACY_EXTRA
    elif not (result.dim_channel and result.dim_source and result.dim_category and result.dim_count):
        result.parity = VERDICT_PAYLOAD_MISMATCH
    else:
        # Both directions have orphans, or subtler mismatch — call it payload_mismatch.
        result.parity = VERDICT_PAYLOAD_MISMATCH

    parts: list[str] = []
    extra_shadow = sorted(shadow_recipients - legacy_recipients)
    extra_legacy = sorted(legacy_recipients - shadow_recipients)
    if extra_shadow:
        parts.append(f"shadow-only recipients: {extra_shadow}")
    if extra_legacy:
        parts.append(f"legacy-only recipients: {extra_legacy}")
    if not result.dim_channel:
        parts.append("channel_mismatch")
    if not result.dim_source:
        parts.append("source_mismatch")
    if not result.dim_category:
        parts.append("category_mismatch")
    if not result.dim_count:
        parts.append("count_mismatch")
    result.discrepancy_detail = "; ".join(parts) if parts else None
    return result


class _NotificationBasedComparator:
    """Base class — subclasses set ``event_type`` and
    ``notification_type``.
    """

    event_type: str = ""
    notification_type: str = ""

    def compare(
        self, db: Session, event: CommunicationEvent,
    ) -> ComparisonResult:
        shadow_intents = _shadow_intents_for_event(db, event.id)
        shadow_recipients: set[str] = {
            i.recipient_user_id for i in shadow_intents
            if i.recipient_user_id is not None
        }
        notifs = _notifications_in_window(
            db,
            notification_type=self.notification_type,
            center=event.occurred_at,
        )
        legacy_recipients: set[str] = {n.user_id for n in notifs}

        # Category dimension: shadow intents' category_key must match the
        # event's declared category. This is deterministic — a mismatch
        # here is a routing bug.
        cat_mismatch = any(
            i.category_key != event.category_key for i in shadow_intents
        )

        # Source dimension: shadow intents' source_type + source_id must
        # match the event's.
        src_mismatch = any(
            i.source_type != event.source_type or i.source_id != event.source_id
            for i in shadow_intents
        )

        # Channel dimension (loose): if legacy wrote in_app notifications
        # we expect shadow to have produced in_app intents for the same
        # recipients. Full channel × recipient matching is deferred until
        # the legacy path itself exposes channel decisions.
        legacy_in_app_recipients = legacy_recipients  # every notification row is in_app
        shadow_in_app_recipients = {
            i.recipient_user_id for i in shadow_intents
            if i.channel == "in_app" and i.recipient_user_id
        }
        channel_ok = shadow_in_app_recipients.issuperset(legacy_in_app_recipients) or (
            not legacy_in_app_recipients and not shadow_in_app_recipients
        )

        # Count dimension: 1 shadow intent per legacy recipient (in_app).
        # Multiple shadow intents per recipient are expected (in_app +
        # email) and don't violate this — we count distinct recipients.
        count_ok = len(shadow_in_app_recipients) >= len(legacy_in_app_recipients)

        result = ComparisonResult(
            parity=VERDICT_MATCH,
            shadow_intent_ids=[i.id for i in shadow_intents],
            legacy_notification_ids=[n.id for n in notifs],
            dim_category=not cat_mismatch,
            dim_source=not src_mismatch,
            dim_channel=channel_ok,
            dim_count=count_ok,
        )
        return _finalise(
            result,
            shadow_recipients=shadow_recipients,
            legacy_recipients=legacy_recipients,
        )


@comparator_for("community.post.published")
class CommunityPostComparator(_NotificationBasedComparator):
    event_type = "community.post.published"
    notification_type = "new_post"


@comparator_for("dm.message.sent")
class DirectMessageComparator(_NotificationBasedComparator):
    event_type = "dm.message.sent"
    notification_type = "direct_message"


@comparator_for("gathering.booking.confirmed")
class BookingConfirmedComparator(_NotificationBasedComparator):
    event_type = "gathering.booking.confirmed"
    notification_type = "booking_confirmed"


@comparator_for("account.password_reset_requested")
class PasswordResetStructuralComparator:
    """Password reset legacy path sends an email but writes no
    notification row. We treat the legacy side as vacuously satisfied
    (dim_no_orphan_legacy = True by default) and verify only that
    the shadow pipeline produced the expected structural output.

    TODO(comms): transactional emails like password reset should
    eventually participate in full parity reporting once provider-
    level delivery observation or audit logging exists (e.g. a
    persistent email-send log fed by Resend webhooks, or a
    provider-agnostic dispatch record). Structural comparison is
    appropriate for now — it verifies the routing pipeline is
    producing what the legacy path is trying to send, without
    claiming to verify the legacy send actually left the building.
    Full parity would upgrade ``dim_no_orphan_legacy`` from
    vacuously-True to a real check against the delivery log.
    """

    event_type = "account.password_reset_requested"

    def compare(
        self, db: Session, event: CommunicationEvent,
    ) -> ComparisonResult:
        shadow_intents = _shadow_intents_for_event(db, event.id)
        expected_recipient = event.actor_user_id
        shadow_recipients: set[str] = {
            i.recipient_user_id for i in shadow_intents
            if i.recipient_user_id is not None
        }
        legacy_recipients: set[str] = (
            {expected_recipient} if expected_recipient else set()
        )
        # We can't observe the legacy email — treat legacy_recipients
        # as the expected structural target.
        result = ComparisonResult(
            parity=VERDICT_MATCH,
            shadow_intent_ids=[i.id for i in shadow_intents],
            legacy_notification_ids=[],
            dim_category=all(
                i.category_key == event.category_key for i in shadow_intents
            ),
            dim_source=all(
                i.source_type == event.source_type and i.source_id == event.source_id
                for i in shadow_intents
            ),
            dim_channel=True,  # not verifiable without an email log
            dim_count=len(shadow_intents) >= (1 if expected_recipient else 0),
        )
        finalised = _finalise(
            result,
            shadow_recipients=shadow_recipients,
            legacy_recipients=legacy_recipients,
        )
        if finalised.parity == VERDICT_MATCH:
            finalised.discrepancy_detail = (
                "structural comparison only — legacy email delivery not observable"
            )
        return finalised


# ---------------------------------------------------------------------------
# Reconciler
# ---------------------------------------------------------------------------


@dataclass
class ReconcilerResult:
    compared_event_ids: list[str] = field(default_factory=list)
    skipped_no_comparator: list[str] = field(default_factory=list)
    duplicate_skipped: int = 0


def _new_comparison_id() -> str:
    return f"csc_{uuid.uuid4().hex[:12]}"


def reconcile_shadow(
    db: Session,
    *,
    limit: int = 200,
    now: datetime | None = None,
) -> ReconcilerResult:
    """Walk events that don't yet have a comparison row and compare them.

    Only events at least ``COMMS_RECONCILER_MIN_EVENT_AGE_SECONDS``
    old are considered so both the legacy trigger (BackgroundTasks)
    and the shadow routing task have time to run. Idempotent — the
    UNIQUE constraint on ``communication_shadow_comparisons.event_id``
    catches concurrent inserts.
    """
    now_utc = (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)
    cutoff = now_utc - _min_event_age()

    subq = select(CommunicationShadowComparison.event_id)
    events = db.execute(
        select(CommunicationEvent)
        .where(
            CommunicationEvent.occurred_at <= cutoff,
            ~CommunicationEvent.id.in_(subq),
        )
        .order_by(CommunicationEvent.occurred_at)
        .limit(limit)
    ).scalars().all()

    result = ReconcilerResult()
    for event in events:
        comparator = get_comparator_for(event.event_type)
        if comparator is None:
            # Not-yet-comparable event type. Log once per event so
            # operators can see when the emit surface is running
            # ahead of the comparator registry (e.g. a resolver
            # landed without its comparator).
            logger.info(
                "shadow reconciler: no comparator for event_type=%s (event_id=%s)",
                event.event_type, event.id,
            )
            result.skipped_no_comparator.append(event.event_type)
            continue
        try:
            outcome = comparator.compare(db, event)
        except Exception:
            logger.exception(
                "shadow comparator raised for event %s (%s)",
                event.id, event.event_type,
            )
            continue

        row = CommunicationShadowComparison(
            id=_new_comparison_id(),
            event_id=event.id,
            topic_key=event.topic_key,
            category_key=event.category_key,
            shadow_intent_ids=list(outcome.shadow_intent_ids),
            legacy_notification_ids=list(outcome.legacy_notification_ids),
            parity=outcome.parity,
            discrepancy_detail=outcome.discrepancy_detail,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            result.duplicate_skipped += 1
            continue
        result.compared_event_ids.append(event.id)

    db.commit()
    return result


# ---------------------------------------------------------------------------
# Parity metrics + eligibility
# ---------------------------------------------------------------------------


REQUIRED_CONSECUTIVE_DAYS = 3


@dataclass
class ParityDayMetrics:
    day: date  # UTC calendar day
    events_observed: int
    comparisons_recorded: int
    matches: int
    mismatches_by_dim: dict[str, int]
    day_qualifies: bool


@dataclass
class ParityReport:
    scope_kind: str          # "topic" or "category" (which _key match won)
    scope_key: str
    window_days: int
    events_observed: int
    comparisons_recorded: int
    parity_pct: float
    days: list[ParityDayMetrics]
    consecutive_perfect_days: int
    eligible_for_live: bool
    recent_discrepancies: list[dict[str, Any]]


def _matches_scope(
    row_topic: str, row_category: str, scope_key: str,
) -> bool:
    """A comparison/event matches the requested scope key if either
    its topic or its category equals the key. Mirrors the
    ``COMMS_LIVE_TOPICS`` matching rule.
    """
    if scope_key == row_topic:
        return True
    if scope_key == row_category:
        return True
    return False


def _events_and_comparisons_in_range(
    db: Session,
    *,
    scope_key: str,
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[list[CommunicationEvent], list[CommunicationShadowComparison]]:
    """Load events and comparisons intersecting a UTC window and
    matching the scope (topic or category)."""
    events = db.execute(
        select(CommunicationEvent).where(
            CommunicationEvent.occurred_at >= start_utc,
            CommunicationEvent.occurred_at < end_utc,
            or_(
                CommunicationEvent.topic_key == scope_key,
                CommunicationEvent.category_key == scope_key,
            ),
        )
    ).scalars().all()
    comparisons = db.execute(
        select(CommunicationShadowComparison).where(
            CommunicationShadowComparison.compared_at >= start_utc,
            CommunicationShadowComparison.compared_at < end_utc,
            or_(
                CommunicationShadowComparison.topic_key == scope_key,
                CommunicationShadowComparison.category_key == scope_key,
            ),
        )
    ).scalars().all()
    return events, comparisons


def compute_parity_report(
    db: Session,
    *,
    scope_key: str,
    window_days: int = 7,
    now: datetime | None = None,
) -> ParityReport:
    """Compute per-day parity metrics + consecutive-day eligibility.

    Only fully-elapsed UTC days count toward the consecutive-day
    counter — the current UTC day is included in totals but never
    counts as a "qualifying day" because more events may still arrive.
    """
    now_utc = (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)
    today = now_utc.date()
    window_start_day = today - timedelta(days=window_days - 1)
    window_start_utc = datetime.combine(window_start_day, datetime.min.time())
    window_end_utc = datetime.combine(today, datetime.min.time()) + timedelta(days=1)

    events, comparisons = _events_and_comparisons_in_range(
        db,
        scope_key=scope_key,
        start_utc=window_start_utc,
        end_utc=window_end_utc,
    )

    # Identify the scope kind for readability in the report response.
    if any(e.topic_key == scope_key for e in events) or any(
        c.topic_key == scope_key for c in comparisons
    ):
        scope_kind = "topic"
    else:
        # If not seen as a topic, treat as category. When there's no
        # data at all, default to "topic" for stable response shape.
        scope_kind = "category" if any(
            e.category_key == scope_key or c.category_key == scope_key
            for e in events for c in comparisons
        ) else "topic"

    per_day: list[ParityDayMetrics] = []
    for offset in range(window_days):
        day = window_start_day + timedelta(days=offset)
        day_start = datetime.combine(day, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        day_events = [e for e in events if day_start <= e.occurred_at < day_end]
        day_comparisons = [c for c in comparisons if day_start <= c.compared_at < day_end]

        matches = sum(1 for c in day_comparisons if c.parity == VERDICT_MATCH)
        mismatches_by_dim = {
            "recipient_or_orphan": sum(
                1 for c in day_comparisons
                if c.parity in (VERDICT_SHADOW_EXTRA, VERDICT_LEGACY_EXTRA)
            ),
            "payload": sum(
                1 for c in day_comparisons if c.parity == VERDICT_PAYLOAD_MISMATCH
            ),
        }
        is_complete_day = day < today
        day_qualifies = (
            is_complete_day
            and len(day_comparisons) == len(day_events)
            and matches == len(day_comparisons)
            and len(day_events) > 0
        )
        per_day.append(ParityDayMetrics(
            day=day,
            events_observed=len(day_events),
            comparisons_recorded=len(day_comparisons),
            matches=matches,
            mismatches_by_dim=mismatches_by_dim,
            day_qualifies=day_qualifies,
        ))

    # Consecutive-day streak, counting backward from yesterday
    # (today is deliberately never a qualifying day — see above).
    consecutive = 0
    for metrics in reversed(per_day):
        if metrics.day == today:
            continue
        if metrics.day_qualifies:
            consecutive += 1
        else:
            break

    total_events = sum(d.events_observed for d in per_day)
    total_comparisons = sum(d.comparisons_recorded for d in per_day)
    total_matches = sum(d.matches for d in per_day)
    parity_pct = (100.0 * total_matches / total_comparisons) if total_comparisons else 0.0

    recent_discrepancies = [
        {
            "event_id": c.event_id,
            "parity": c.parity,
            "detail": c.discrepancy_detail,
            "compared_at": c.compared_at.isoformat(),
        }
        for c in sorted(
            (c for c in comparisons if c.parity != VERDICT_MATCH),
            key=lambda c: c.compared_at, reverse=True,
        )[:20]
    ]

    return ParityReport(
        scope_kind=scope_kind,
        scope_key=scope_key,
        window_days=window_days,
        events_observed=total_events,
        comparisons_recorded=total_comparisons,
        parity_pct=round(parity_pct, 2),
        days=per_day,
        consecutive_perfect_days=consecutive,
        eligible_for_live=(consecutive >= REQUIRED_CONSECUTIVE_DAYS),
        recent_discrepancies=recent_discrepancies,
    )
