"""Tests for M5c rollout wiring — config parsing, live detection,
schedule_routing_if_needed, and the reconciler + parity report.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.comms import Source, emit
from app.comms.categories import Source as SourceEnum
from app.comms.intents import DELIVERY_MODE_LIVE, DELIVERY_MODE_SHADOW
from app.comms.models import (
    CommunicationEvent,
    CommunicationIntent,
    CommunicationShadowComparison,
)
from app.comms.rollout import (
    _route_event_bg,
    is_event_live,
    parsed_live_topics,
    resolve_delivery_mode,
    schedule_routing_if_needed,
)
from app.comms.shadow import (
    REQUIRED_CONSECUTIVE_DAYS,
    VERDICT_MATCH,
    VERDICT_SHADOW_EXTRA,
    compute_parity_report,
    get_comparator_for,
    reconcile_shadow,
    registered_comparators,
)


# ---------------------------------------------------------------------------
# Config parsing + live detection
# ---------------------------------------------------------------------------


class TestConfigParsing:
    def test_default_off(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "comms_shadow", False, raising=False)
        monkeypatch.setattr(settings, "comms_live_topics", "", raising=False)
        assert parsed_live_topics() == frozenset()
        assert resolve_delivery_mode("community.post.published") is None

    def test_shadow_only(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "comms_shadow", True, raising=False)
        monkeypatch.setattr(settings, "comms_live_topics", "", raising=False)
        assert resolve_delivery_mode("community.post.published") == DELIVERY_MODE_SHADOW

    def test_live_topic_wins_over_shadow(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "comms_shadow", True, raising=False)
        monkeypatch.setattr(
            settings, "comms_live_topics",
            "conversations", raising=False,
        )
        # community.post.published's topic is 'conversations' → live.
        assert is_event_live("community.post.published") is True
        assert resolve_delivery_mode("community.post.published") == DELIVERY_MODE_LIVE

    def test_category_key_also_matches(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "comms_live_topics", "community", raising=False)
        # community.post.published's category is 'community' → live via category.
        assert is_event_live("community.post.published") is True

    def test_whitespace_tolerant(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(
            settings, "comms_live_topics",
            "  direct_messages , conversations ", raising=False,
        )
        assert parsed_live_topics() == {"direct_messages", "conversations"}

    def test_unregistered_event_never_live(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "comms_live_topics", "conversations", raising=False)
        assert is_event_live("not.a.real.event") is False


# ---------------------------------------------------------------------------
# schedule_routing_if_needed
# ---------------------------------------------------------------------------


class TestScheduleRouting:
    def test_none_event_is_noop(self, monkeypatch):
        # Emitting a duplicate returns None. schedule_routing_if_needed
        # must handle it silently.
        from app.core.config import settings
        monkeypatch.setattr(settings, "comms_shadow", True, raising=False)
        schedule_routing_if_needed(None, None, "community.post.published")
        # No exception, no side effects.

    def test_no_mode_no_routing(self, db, make_user, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "comms_shadow", False, raising=False)
        monkeypatch.setattr(settings, "comms_live_topics", "", raising=False)
        actor = make_user()
        ev = emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=actor.id,
            actor_user_id=actor.id,
            subject_type="post", subject_id="p_x",
            context={"space_id": "s_x"},
            payload={"post_id": "p_x", "excerpt": ""},
        )
        db.commit()
        schedule_routing_if_needed(None, ev, "community.post.published")
        # No shadow intents should have been created.
        from sqlalchemy import select
        intents = db.execute(
            select(CommunicationIntent).where(
                CommunicationIntent.event_id == ev.id,
            )
        ).scalars().all()
        assert intents == []

    def test_shadow_creates_shadow_intents(self, db, make_user, monkeypatch):
        """When shadow is on and the topic is not live, routing
        produces shadow intents. Uses route_event directly (rather
        than schedule_routing_if_needed with a fresh session) so the
        test's SAVEPOINT-scoped writes are visible to the routing.
        """
        from app.comms.routing import route_event
        from app.core.config import settings
        from app.models.platform import Space, SpaceMembership
        monkeypatch.setattr(settings, "comms_shadow", True, raising=False)
        monkeypatch.setattr(settings, "comms_live_topics", "", raising=False)

        creator = make_user(role="creator")
        member = make_user()
        space = Space(
            id="s_shadow", slug="shadow", name="Shadow",
            creator_id=creator.id, status="active",
        )
        db.add(space)
        db.add(SpaceMembership(
            id="m_s", space_id=space.id, user_id=member.id,
            role="learner", status="active",
        ))
        db.flush()
        ev = emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=creator.id,
            actor_user_id=creator.id,
            subject_type="post", subject_id="p_s",
            context={"space_id": space.id, "collective_name": space.name},
            payload={"post_id": "p_s", "excerpt": "hi"},
        )
        db.flush()

        # Confirm resolve_delivery_mode says shadow, then invoke
        # route_event with that mode — same code path production takes
        # in the background task.
        assert resolve_delivery_mode("community.post.published") == DELIVERY_MODE_SHADOW
        route_event(db, ev, delivery_mode=DELIVERY_MODE_SHADOW)

        from sqlalchemy import select
        intents = db.execute(
            select(CommunicationIntent).where(
                CommunicationIntent.event_id == ev.id,
            )
        ).scalars().all()
        assert len(intents) >= 1
        for intent in intents:
            assert intent.delivery_mode == DELIVERY_MODE_SHADOW

    def test_live_creates_live_intents(self, db, make_user, monkeypatch):
        from app.comms.routing import route_event
        from app.core.config import settings
        from app.models.platform import Space, SpaceMembership
        monkeypatch.setattr(settings, "comms_shadow", False, raising=False)
        monkeypatch.setattr(settings, "comms_live_topics", "conversations", raising=False)

        creator = make_user(role="creator")
        member = make_user()
        space = Space(
            id="s_live_r", slug="live-r", name="Live R",
            creator_id=creator.id, status="active",
        )
        db.add(space)
        db.add(SpaceMembership(
            id="m_lr", space_id=space.id, user_id=member.id,
            role="learner", status="active",
        ))
        db.flush()
        ev = emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=creator.id,
            actor_user_id=creator.id,
            subject_type="post", subject_id="p_lr",
            context={"space_id": space.id, "collective_name": space.name},
            payload={"post_id": "p_lr"},
        )
        db.flush()

        assert resolve_delivery_mode("community.post.published") == DELIVERY_MODE_LIVE
        route_event(db, ev, delivery_mode=DELIVERY_MODE_LIVE)

        from sqlalchemy import select
        intents = db.execute(
            select(CommunicationIntent).where(
                CommunicationIntent.event_id == ev.id,
            )
        ).scalars().all()
        assert len(intents) >= 1
        for intent in intents:
            assert intent.delivery_mode == DELIVERY_MODE_LIVE


# ---------------------------------------------------------------------------
# Shadow intents never dispatch
# ---------------------------------------------------------------------------


class TestShadowNeverDispatches:
    def test_shadow_intent_not_claimed_by_worker(self, db, make_user, monkeypatch):
        """Regression — even after routing creates a shadow intent,
        the worker refuses to pick it up.
        """
        from app.comms.intents import claim_next_batch
        from app.comms.routing import route_event
        from app.core.config import settings
        from app.models.platform import Space, SpaceMembership
        monkeypatch.setattr(settings, "comms_shadow", True, raising=False)

        creator = make_user(role="creator")
        member = make_user()
        space = Space(
            id="s_ns", slug="ns", name="NS",
            creator_id=creator.id, status="active",
        )
        db.add(space)
        db.add(SpaceMembership(
            id="m_ns", space_id=space.id, user_id=member.id,
            role="learner", status="active",
        ))
        db.flush()
        ev = emit(
            db, event_type="community.post.published",
            source_type=Source.CREATOR, source_id=creator.id,
            actor_user_id=creator.id, subject_type="post", subject_id="p_ns",
            context={"space_id": space.id, "collective_name": space.name},
            payload={"post_id": "p_ns"},
        )
        db.flush()
        route_event(db, ev, delivery_mode=DELIVERY_MODE_SHADOW)

        assert claim_next_batch(db, limit=100) == []


# ---------------------------------------------------------------------------
# Legacy trigger guards — no duplicate send when live
# ---------------------------------------------------------------------------


class TestLegacyCutoverGuards:
    def test_new_post_trigger_noops_when_live(self, monkeypatch):
        from app.core.config import settings
        from app.services import notification_service
        monkeypatch.setattr(
            settings, "comms_live_topics", "conversations", raising=False,
        )
        # If the guard works, trigger_new_post returns immediately
        # without loading the post — a nonexistent post_id would
        # otherwise blow up somewhere. The absence of exception is
        # the assertion.
        notification_service.trigger_new_post(
            post_id="does-not-exist",
            space_id="does-not-exist",
            author_id="does-not-exist",
        )

    def test_dm_notify_noops_when_live(self, monkeypatch):
        from app.core.config import settings
        from app.messages.routes import _notify_direct_message
        monkeypatch.setattr(
            settings, "comms_live_topics", "direct_messages", raising=False,
        )
        _notify_direct_message(
            recipient_id="ghost",
            sender_name="Nobody",
            space_id="ghost-space",
            thread_url=None,
            preview="",
        )
        # No exception; no side effect. Guard passed.

    def test_booking_confirmed_noops_when_live(self, monkeypatch):
        from app.core.config import settings
        from app.services import notification_service
        monkeypatch.setattr(
            settings, "comms_live_topics", "gatherings", raising=False,
        )
        notification_service.trigger_booking_confirmed(
            event_id="ghost", user_id="ghost",
        )


# ---------------------------------------------------------------------------
# Reconciler + parity report
# ---------------------------------------------------------------------------


class TestComparatorsRegistered:
    def test_all_four_registered(self):
        registered = set(registered_comparators())
        assert {
            "community.post.published",
            "dm.message.sent",
            "gathering.booking.confirmed",
            "account.password_reset_requested",
        }.issubset(registered)


class TestReconciler:
    def test_no_events_no_rows(self, db):
        r = reconcile_shadow(db)
        assert r.compared_event_ids == []
        assert r.duplicate_skipped == 0

    def test_min_age_excludes_very_recent(self, db, make_user, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "comms_shadow", True, raising=False)
        actor = make_user()
        ev = emit(
            db,
            event_type="dm.message.sent",
            source_type=Source.CREATOR,
            source_id=actor.id,
            actor_user_id=actor.id,
            payload={"recipient_id": actor.id, "sender_name": "X",
                     "thread_id": "t1", "excerpt": ""},
        )
        db.commit()
        # Event is brand-new; reconciler skips events younger than MIN_EVENT_AGE.
        r = reconcile_shadow(db)
        assert ev.id not in r.compared_event_ids

    def test_records_one_row_per_event_and_is_idempotent(
        self, db, make_user, monkeypatch,
    ):
        from app.core.config import settings
        monkeypatch.setattr(settings, "comms_shadow", True, raising=False)
        actor = make_user()
        recipient = make_user()
        # Emit an old event by explicitly setting occurred_at.
        old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
        ev = emit(
            db,
            event_type="dm.message.sent",
            source_type=Source.CREATOR,
            source_id=actor.id,
            actor_user_id=actor.id,
            payload={
                "recipient_id": recipient.id,
                "sender_name": "X",
                "thread_id": "t2",
                "excerpt": "",
            },
            occurred_at=old_time,
        )
        db.commit()
        # Run once.
        r1 = reconcile_shadow(db)
        assert ev.id in r1.compared_event_ids
        # Run again — no new rows, event is now compared.
        r2 = reconcile_shadow(db)
        assert r2.compared_event_ids == []

        from sqlalchemy import select
        rows = db.execute(
            select(CommunicationShadowComparison).where(
                CommunicationShadowComparison.event_id == ev.id,
            )
        ).scalars().all()
        assert len(rows) == 1


class TestParityReport:
    def _make_comparison(
        self, db, *, topic_key, category_key, event, parity, when,
    ):
        row = CommunicationShadowComparison(
            id=f"csc_{event.id}",
            event_id=event.id,
            topic_key=topic_key,
            category_key=category_key,
            shadow_intent_ids=[],
            legacy_notification_ids=[],
            parity=parity,
            compared_at=when,
        )
        db.add(row)
        db.flush()

    def _make_event(self, db, make_user, *, when, event_type="dm.message.sent"):
        actor = make_user()
        return emit(
            db,
            event_type=event_type,
            source_type=Source.CREATOR,
            source_id=actor.id,
            actor_user_id=actor.id,
            payload={"recipient_id": actor.id, "sender_name": "X",
                     "thread_id": "t", "excerpt": ""},
            occurred_at=when,
            dedupe_key=f"parity-{when.isoformat()}",
        )

    def test_perfect_three_days_becomes_eligible(self, db, make_user):
        now = datetime(2026, 8, 8, 12, 0)  # noon UTC
        # Three prior complete days — 5, 6, 7 August — each with one
        # matching event.
        for day_offset in (3, 2, 1):
            when = datetime(2026, 8, 8 - day_offset, 12, 0)
            ev = self._make_event(db, make_user, when=when)
            self._make_comparison(
                db,
                topic_key="direct_messages", category_key="messages",
                event=ev, parity=VERDICT_MATCH, when=when + timedelta(minutes=2),
            )
        report = compute_parity_report(
            db, scope_key="direct_messages", window_days=7, now=now,
        )
        assert report.consecutive_perfect_days == 3
        assert report.eligible_for_live is True

    def test_mismatch_breaks_streak(self, db, make_user):
        now = datetime(2026, 8, 8, 12, 0)
        for day_offset, verdict in [(3, VERDICT_MATCH), (2, VERDICT_SHADOW_EXTRA), (1, VERDICT_MATCH)]:
            when = datetime(2026, 8, 8 - day_offset, 12, 0)
            ev = self._make_event(db, make_user, when=when)
            self._make_comparison(
                db, topic_key="direct_messages", category_key="messages",
                event=ev, parity=verdict, when=when + timedelta(minutes=2),
            )
        report = compute_parity_report(
            db, scope_key="direct_messages", window_days=7, now=now,
        )
        # Yesterday (day -1) was perfect, but 2 days back had a
        # mismatch → streak resets at yesterday to 1.
        assert report.consecutive_perfect_days == 1
        assert report.eligible_for_live is False

    def test_incomplete_day_cannot_qualify(self, db, make_user):
        now = datetime(2026, 8, 8, 12, 0)
        # Event on TODAY (Aug 8) is a match — but today is incomplete,
        # so it can't count toward the streak even at 100%.
        when_today = datetime(2026, 8, 8, 10, 0)
        ev = self._make_event(db, make_user, when=when_today)
        self._make_comparison(
            db, topic_key="direct_messages", category_key="messages",
            event=ev, parity=VERDICT_MATCH, when=when_today + timedelta(minutes=2),
        )
        report = compute_parity_report(
            db, scope_key="direct_messages", window_days=7, now=now,
        )
        assert report.consecutive_perfect_days == 0
        assert report.eligible_for_live is False

    def test_missing_comparison_disqualifies_day(self, db, make_user):
        """Integrity invariant — comparisons_recorded must equal
        events_observed for a day to qualify.
        """
        now = datetime(2026, 8, 8, 12, 0)
        # Yesterday: two events, only one comparison.
        for i in range(2):
            when = datetime(2026, 8, 7, 10 + i, 0)
            ev = self._make_event(db, make_user, when=when)
            if i == 0:
                self._make_comparison(
                    db, topic_key="direct_messages", category_key="messages",
                    event=ev, parity=VERDICT_MATCH,
                    when=when + timedelta(minutes=2),
                )
        report = compute_parity_report(
            db, scope_key="direct_messages", window_days=7, now=now,
        )
        assert report.consecutive_perfect_days == 0

    def test_scope_matches_category_as_well(self, db, make_user):
        """COMMS_LIVE_TOPICS can name a category — report should match
        by category too, mirroring the promotion rule.
        """
        now = datetime(2026, 8, 8, 12, 0)
        when = datetime(2026, 8, 7, 10, 0)
        ev = self._make_event(db, make_user, when=when)
        self._make_comparison(
            db, topic_key="direct_messages", category_key="messages",
            event=ev, parity=VERDICT_MATCH, when=when + timedelta(minutes=2),
        )
        # Ask for the "messages" category instead of the topic.
        report = compute_parity_report(
            db, scope_key="messages", window_days=7, now=now,
        )
        assert report.events_observed >= 1
        assert report.comparisons_recorded >= 1

    def test_parity_pct_calculation(self, db, make_user):
        now = datetime(2026, 8, 8, 12, 0)
        # 3 matches + 1 mismatch = 75% parity.
        for i, verdict in enumerate(
            [VERDICT_MATCH, VERDICT_MATCH, VERDICT_MATCH, VERDICT_SHADOW_EXTRA],
        ):
            when = datetime(2026, 8, 7, 10 + i, 0)
            ev = self._make_event(db, make_user, when=when)
            self._make_comparison(
                db, topic_key="direct_messages", category_key="messages",
                event=ev, parity=verdict,
                when=when + timedelta(minutes=2),
            )
        report = compute_parity_report(
            db, scope_key="direct_messages", window_days=7, now=now,
        )
        assert report.parity_pct == 75.0
