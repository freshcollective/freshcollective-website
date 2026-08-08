"""Tests for the M5b routing engine.

Coverage:
  * Provider map + supported_channels_for_category.
  * Pacing: priority resolution (silent / immediate / digest passthrough,
    rate-limit downgrade), quiet-hours evaluation.
  * Decision pipeline branches: silent, no-consent, address suppressed,
    dedupe collision, rate-limit downgrade to digest, quiet-hours
    reschedule, no-provider-configured, no-template-registered.
  * route_event orchestration: happy path (community.post), multiple
    recipients, delivery_mode='live' vs 'shadow' scoping.
  * Registry: resolver + template registration integrity.
"""

from __future__ import annotations

from datetime import UTC, datetime, time as dtime, timedelta

import pytest

from app.comms import emit
from app.comms.categories import (
    CATEGORY_ACCOUNT,
    CATEGORY_COMMUNITY,
    CATEGORY_CREATOR_UPDATES,
    CATEGORY_GATHERINGS,
    CATEGORY_MESSAGES,
    CATEGORY_PATHWAYS,
    CHANNEL_EMAIL_TRANSACTIONAL,
    CHANNEL_IN_APP,
    Priority,
    Source,
)
from app.comms.digest import CADENCE_DAILY
from app.comms.intents import (
    DELIVERY_MODE_LIVE,
    DELIVERY_MODE_SHADOW,
    STATE_QUEUED,
    STATE_RECORDED,
    STATE_SUPPRESSED,
    create_intent,
)
from app.comms.models import (
    CommunicationDigestItem,
    CommunicationIntent,
    CommunicationMemberSettings,
)
from app.comms.preferences import (
    grant_consent,
    revoke_consent,
    set_preference,
)
from app.comms.routing import (
    RoutingResult,
    get_provider_for,
    get_resolver_for,
    route_event,
    supported_channels_for_category,
)
from app.comms.routing.decision import DecisionOutcome, process_one
from app.comms.routing.pacing import (
    IMMEDIATE_EMAIL_CAP_PER_CATEGORY_PER_DAY,
    QuietHoursResult,
    evaluate_quiet_hours,
    resolve_priority,
)
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.suppressions import record_suppression
from app.comms.templates.registry import get_template_for


# ---------------------------------------------------------------------------
# Provider map
# ---------------------------------------------------------------------------


class TestProviderMap:
    def test_account_email_routed_to_resend(self):
        assert get_provider_for(CATEGORY_ACCOUNT, CHANNEL_EMAIL_TRANSACTIONAL) == "resend"

    def test_account_in_app_routed_to_in_app_provider(self):
        assert get_provider_for(CATEGORY_ACCOUNT, CHANNEL_IN_APP) == "in_app"

    def test_platform_updates_email_marketing_deferred(self):
        # Intentionally unrouted until M11; caller sees None and
        # treats as suppression.
        assert get_provider_for("platform_updates", "email_marketing") is None

    def test_supported_channels_order_stable(self):
        channels = supported_channels_for_category(CATEGORY_COMMUNITY)
        # in_app first, email_transactional second — decision pipeline
        # iterates this deterministically.
        assert channels == (CHANNEL_IN_APP, CHANNEL_EMAIL_TRANSACTIONAL)


# ---------------------------------------------------------------------------
# Pacing — priority resolution + quiet hours
# ---------------------------------------------------------------------------


class TestPriorityResolution:
    def test_silent_stays_silent(self, db, make_user):
        u = make_user()
        assert resolve_priority(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            preferred_priority=Priority.SILENT,
            delivery_mode=DELIVERY_MODE_LIVE,
        ) == Priority.SILENT

    def test_digest_passthrough(self, db, make_user):
        u = make_user()
        assert resolve_priority(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            preferred_priority=Priority.DAILY_DIGEST,
            delivery_mode=DELIVERY_MODE_LIVE,
        ) == Priority.DAILY_DIGEST

    def test_in_app_immediate_never_downgrades(self, db, make_user):
        u = make_user()
        # Even with dozens of prior in_app intents, immediate stays.
        for _ in range(IMMEDIATE_EMAIL_CAP_PER_CATEGORY_PER_DAY + 3):
            create_intent(
                db,
                recipient_user_id=u.id,
                recipient_address=u.email or f"{u.id}@e.test",
                source_type=Source.FRESH_COLLECTIVE,
                source_id=None,
                category_key=CATEGORY_COMMUNITY,
                topic_key="conversations",
                channel=CHANNEL_IN_APP,
                priority=Priority.IMMEDIATE,
                provider_key="in_app",
                human_reason="test",
                payload_subject="x",
                payload_body_text="x",
            )
        assert resolve_priority(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=CHANNEL_IN_APP,
            preferred_priority=Priority.IMMEDIATE,
            delivery_mode=DELIVERY_MODE_LIVE,
        ) == Priority.IMMEDIATE

    def test_immediate_email_downgrades_at_cap(self, db, make_user):
        u = make_user()
        # Create N immediate email intents at the cap.
        for _ in range(IMMEDIATE_EMAIL_CAP_PER_CATEGORY_PER_DAY):
            create_intent(
                db,
                recipient_user_id=u.id,
                recipient_address=u.email or f"{u.id}@e.test",
                source_type=Source.FRESH_COLLECTIVE,
                source_id=None,
                category_key=CATEGORY_COMMUNITY,
                topic_key="conversations",
                channel=CHANNEL_EMAIL_TRANSACTIONAL,
                priority=Priority.IMMEDIATE,
                provider_key="resend",
                human_reason="test",
                payload_subject="x",
                payload_body_text="x",
            )
        db.flush()
        assert resolve_priority(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            preferred_priority=Priority.IMMEDIATE,
            delivery_mode=DELIVERY_MODE_LIVE,
        ) == Priority.DAILY_DIGEST

    def test_rate_limit_scoped_to_delivery_mode(self, db, make_user):
        """Shadow intents don't count against live's cap and vice-versa."""
        u = make_user()
        for _ in range(IMMEDIATE_EMAIL_CAP_PER_CATEGORY_PER_DAY):
            create_intent(
                db,
                recipient_user_id=u.id,
                recipient_address=u.email or f"{u.id}@e.test",
                source_type=Source.FRESH_COLLECTIVE,
                source_id=None,
                category_key=CATEGORY_COMMUNITY,
                topic_key="conversations",
                channel=CHANNEL_EMAIL_TRANSACTIONAL,
                priority=Priority.IMMEDIATE,
                provider_key="resend",
                human_reason="test",
                payload_subject="x",
                payload_body_text="x",
                delivery_mode=DELIVERY_MODE_SHADOW,
            )
        db.flush()
        # Live cap not yet touched — resolves to immediate.
        assert resolve_priority(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            preferred_priority=Priority.IMMEDIATE,
            delivery_mode=DELIVERY_MODE_LIVE,
        ) == Priority.IMMEDIATE


class TestQuietHours:
    def test_no_settings_no_quiet_hours(self, db, make_user):
        u = make_user()
        result = evaluate_quiet_hours(
            db, user_id=u.id, channel=CHANNEL_EMAIL_TRANSACTIONAL,
        )
        assert result.in_quiet_hours is False

    def test_in_app_never_quieted(self, db, make_user):
        u = make_user()
        db.add(CommunicationMemberSettings(
            user_id=u.id,
            quiet_hours_start_local=dtime(0, 0),
            quiet_hours_end_local=dtime(23, 59),
        ))
        db.flush()
        result = evaluate_quiet_hours(
            db, user_id=u.id, channel=CHANNEL_IN_APP,
        )
        assert result.in_quiet_hours is False

    def test_overnight_window_defers_to_next_end(self, db, make_user):
        u = make_user()
        db.add(CommunicationMemberSettings(
            user_id=u.id,
            timezone="Australia/Sydney",
            quiet_hours_start_local=dtime(22, 0),
            quiet_hours_end_local=dtime(7, 0),
        ))
        db.flush()
        # 2026-08-08 15:00 UTC == 01:00 AEST 9 Aug → inside window.
        now = datetime(2026, 8, 8, 15, 0, tzinfo=UTC)
        result = evaluate_quiet_hours(
            db, user_id=u.id, channel=CHANNEL_EMAIL_TRANSACTIONAL, now=now,
        )
        assert result.in_quiet_hours is True
        # Next 07:00 AEST is 9 Aug 07:00 AEST = 8 Aug 21:00 UTC.
        assert result.scheduled_for_utc == datetime(2026, 8, 8, 21, 0)

    def test_outside_window_not_quieted(self, db, make_user):
        u = make_user()
        db.add(CommunicationMemberSettings(
            user_id=u.id,
            timezone="UTC",
            quiet_hours_start_local=dtime(22, 0),
            quiet_hours_end_local=dtime(7, 0),
        ))
        db.flush()
        now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
        result = evaluate_quiet_hours(
            db, user_id=u.id, channel=CHANNEL_EMAIL_TRANSACTIONAL, now=now,
        )
        assert result.in_quiet_hours is False

    def test_same_day_window(self, db, make_user):
        u = make_user()
        db.add(CommunicationMemberSettings(
            user_id=u.id,
            timezone="UTC",
            quiet_hours_start_local=dtime(13, 0),
            quiet_hours_end_local=dtime(15, 0),
        ))
        db.flush()
        # 14:00 UTC — inside 13:00-15:00.
        now = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)
        result = evaluate_quiet_hours(
            db, user_id=u.id, channel=CHANNEL_EMAIL_TRANSACTIONAL, now=now,
        )
        assert result.in_quiet_hours is True
        assert result.scheduled_for_utc == datetime(2026, 8, 8, 15, 0)


# ---------------------------------------------------------------------------
# Decision pipeline — process_one branches
# ---------------------------------------------------------------------------


def _fresh_event(db, make_user, *, event_type="community.post.published"):
    """Emit + return a persisted CommunicationEvent for tests."""
    actor = make_user()
    ev = emit(
        db,
        event_type=event_type,
        source_type=Source.CREATOR,
        source_id=actor.id,
        actor_user_id=actor.id,
        subject_type="post",
        subject_id="p_test",
        context={"space_id": "s_test", "collective_name": "Test Collective"},
        payload={"post_id": "p_test", "excerpt": "hello"},
    )
    return actor, ev


def _recipient(user, *, template_context: dict | None = None) -> ResolvedRecipient:
    return ResolvedRecipient(
        user_id=user.id,
        role_in_event="member_of_collective",
        human_reason="You're a member of Test Collective.",
        template_context=template_context or {
            "collective_name": "Test Collective",
            "space_id": "s_test",
            "post_id": "p_test",
            "excerpt": "hello",
        },
    )


class TestDecisionPipeline:
    def test_happy_path_creates_intent(self, db, make_user):
        _, ev = _fresh_event(db, make_user)
        recipient_user = make_user()
        db.flush()
        outcome = process_one(
            db, event=ev, recipient=_recipient(recipient_user),
            channel=CHANNEL_IN_APP, delivery_mode=DELIVERY_MODE_SHADOW,
        )
        assert outcome.intent_id is not None
        assert outcome.digest_item_id is None
        assert outcome.suppression_reason is None

        intent = db.get(CommunicationIntent, outcome.intent_id)
        assert intent is not None
        assert intent.delivery_mode == DELIVERY_MODE_SHADOW
        assert intent.state == STATE_QUEUED
        assert intent.template_key == "community.post.published.in_app"
        assert intent.template_version == "v1"

    def test_silent_preference_produces_recorded_intent(self, db, make_user):
        _, ev = _fresh_event(db, make_user)
        recipient_user = make_user()
        set_preference(
            db, user_id=recipient_user.id,
            category_key=CATEGORY_COMMUNITY,
            channel=CHANNEL_IN_APP,
            priority=Priority.SILENT,
        )
        db.flush()
        outcome = process_one(
            db, event=ev, recipient=_recipient(recipient_user),
            channel=CHANNEL_IN_APP, delivery_mode=DELIVERY_MODE_SHADOW,
        )
        assert outcome.intent_id is not None
        intent = db.get(CommunicationIntent, outcome.intent_id)
        assert intent.state == STATE_RECORDED

    def test_missing_consent_produces_suppressed_intent(self, db, make_user):
        # Creator Updates is consent-gated (creator_broadcast).
        actor = make_user()
        ev = emit(
            db,
            event_type="creator.update.sent",  # exists in registry from M1
            source_type=Source.CREATOR,
            source_id=actor.id,
            actor_user_id=actor.id,
        )
        recipient_user = make_user()
        db.flush()
        # Deliberately do not grant creator_broadcast consent.
        outcome = process_one(
            db, event=ev,
            recipient=ResolvedRecipient(
                user_id=recipient_user.id,
                role_in_event="member_of_collective",
                human_reason="You're a member.",
                template_context={},
            ),
            channel=CHANNEL_IN_APP, delivery_mode=DELIVERY_MODE_SHADOW,
        )
        assert outcome.suppression_reason == "no_consent"

    def test_granted_consent_permits_creation(self, db, make_user):
        actor = make_user()
        ev = emit(
            db,
            event_type="creator.update.sent",
            source_type=Source.CREATOR,
            source_id=actor.id,
            actor_user_id=actor.id,
        )
        recipient_user = make_user()
        grant_consent(
            db, user_id=recipient_user.id,
            consent_kind="creator_broadcast", source="test",
        )
        db.flush()
        outcome = process_one(
            db, event=ev,
            recipient=ResolvedRecipient(
                user_id=recipient_user.id,
                role_in_event="member_of_collective",
                human_reason="You're a member.",
                template_context={},
            ),
            channel=CHANNEL_IN_APP, delivery_mode=DELIVERY_MODE_SHADOW,
        )
        # No template registered for creator.update.sent × in_app in
        # M5b (that ships with M10 broadcasts) — pipeline reports the
        # skip cleanly rather than creating an unrenderable intent.
        assert outcome.intent_id is None
        assert outcome.skipped_reason == "no_template_registered"

    def test_address_suppressed_produces_suppressed_intent(self, db, make_user):
        _, ev = _fresh_event(db, make_user)
        recipient_user = make_user()
        # Community × email defaults to silent — set an explicit
        # immediate preference so the pipeline reaches the
        # suppression check.
        set_preference(
            db, user_id=recipient_user.id,
            category_key=CATEGORY_COMMUNITY,
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            priority=Priority.IMMEDIATE,
        )
        record_suppression(
            db, address_type="email", address=recipient_user.email,
            reason="bounced", source_provider="resend",
        )
        db.flush()
        outcome = process_one(
            db, event=ev, recipient=_recipient(recipient_user),
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            delivery_mode=DELIVERY_MODE_SHADOW,
        )
        assert outcome.suppression_reason == "bounced"
        intent = db.get(CommunicationIntent, outcome.intent_id)
        assert intent.state == STATE_SUPPRESSED

    def test_rate_limit_downgrades_to_digest(self, db, make_user):
        _, ev = _fresh_event(db, make_user)
        recipient_user = make_user()
        set_preference(
            db, user_id=recipient_user.id,
            category_key=CATEGORY_COMMUNITY,
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            priority=Priority.IMMEDIATE,
        )
        for _ in range(IMMEDIATE_EMAIL_CAP_PER_CATEGORY_PER_DAY):
            create_intent(
                db,
                recipient_user_id=recipient_user.id,
                recipient_address=recipient_user.email,
                source_type=Source.FRESH_COLLECTIVE,
                source_id=None,
                category_key=CATEGORY_COMMUNITY,
                topic_key="conversations",
                channel=CHANNEL_EMAIL_TRANSACTIONAL,
                priority=Priority.IMMEDIATE,
                provider_key="resend",
                human_reason="test",
                payload_subject="x",
                payload_body_text="x",
                delivery_mode=DELIVERY_MODE_SHADOW,
            )
        db.flush()
        outcome = process_one(
            db, event=ev, recipient=_recipient(recipient_user),
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            delivery_mode=DELIVERY_MODE_SHADOW,
        )
        assert outcome.digest_item_id is not None
        item = db.get(CommunicationDigestItem, outcome.digest_item_id)
        assert item.cadence == CADENCE_DAILY
        assert item.category_key == CATEGORY_COMMUNITY

    def test_dedupe_collision_returns_skip(self, db, make_user):
        _, ev = _fresh_event(db, make_user)
        recipient_user = make_user()
        db.flush()
        # First creation succeeds.
        first = process_one(
            db, event=ev, recipient=_recipient(recipient_user),
            channel=CHANNEL_IN_APP, delivery_mode=DELIVERY_MODE_SHADOW,
        )
        assert first.intent_id is not None
        # Second attempt collides on (event_id, recipient, channel).
        second = process_one(
            db, event=ev, recipient=_recipient(recipient_user),
            channel=CHANNEL_IN_APP, delivery_mode=DELIVERY_MODE_SHADOW,
        )
        assert second.intent_id is None
        assert second.skipped_reason == "duplicate_intent"


# ---------------------------------------------------------------------------
# route_event orchestration
# ---------------------------------------------------------------------------


class TestRouteEvent:
    def test_no_resolver_returns_empty_with_reason(self, db, make_user):
        actor = make_user()
        ev = emit(
            db,
            event_type="account.created",  # registered in event registry, no resolver in M5b
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=actor.id,
        )
        db.flush()
        result = route_event(db, ev)
        assert isinstance(result, RoutingResult)
        assert result.intent_ids == []
        assert result.had_resolver is False

    def test_shadow_mode_creates_shadow_intents(self, db, make_user):
        # community.post.published — need a real space + membership.
        from app.models.platform import Space, SpaceMembership
        creator = make_user(role="creator")
        member = make_user()
        space = Space(
            id="s_route", slug="route-test", name="Route Test",
            creator_id=creator.id, status="active",
        )
        db.add(space)
        db.flush()
        db.add(SpaceMembership(
            id="m_1", space_id=space.id, user_id=member.id,
            role="learner", status="active",
        ))
        db.flush()

        ev = emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=creator.id,
            actor_user_id=creator.id,
            subject_type="post", subject_id="p_route",
            context={"space_id": space.id, "collective_name": space.name},
            payload={"post_id": "p_route", "excerpt": "hi"},
        )
        db.flush()

        result = route_event(db, ev, delivery_mode=DELIVERY_MODE_SHADOW)
        assert result.had_resolver is True
        assert len(result.intent_ids) >= 1
        for intent_id in result.intent_ids:
            intent = db.get(CommunicationIntent, intent_id)
            assert intent.delivery_mode == DELIVERY_MODE_SHADOW

    def test_author_excluded_from_recipients(self, db, make_user):
        from app.models.platform import Space, SpaceMembership
        creator = make_user(role="creator")
        space = Space(
            id="s_author", slug="author-test", name="Author Test",
            creator_id=creator.id, status="active",
        )
        db.add(space)
        db.add(SpaceMembership(
            id="m_c1", space_id=space.id, user_id=creator.id,
            role="creator", status="active",
        ))
        db.flush()
        ev = emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=creator.id,
            actor_user_id=creator.id,
            subject_type="post", subject_id="p_a",
            context={"space_id": space.id, "collective_name": space.name},
            payload={"post_id": "p_a", "excerpt": ""},
        )
        db.flush()
        result = route_event(db, ev)
        # Only the creator is in the space; author-exclusion means no
        # recipients → no intents.
        assert result.intent_ids == []
        assert result.digest_item_ids == []

    def test_live_mode_creates_live_intents(self, db, make_user):
        from app.models.platform import Space, SpaceMembership
        creator = make_user(role="creator")
        member = make_user()
        space = Space(
            id="s_live", slug="live-test", name="Live Test",
            creator_id=creator.id, status="active",
        )
        db.add(space)
        db.flush()
        db.add(SpaceMembership(
            id="m_live", space_id=space.id, user_id=member.id,
            role="learner", status="active",
        ))
        db.flush()
        ev = emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=creator.id,
            actor_user_id=creator.id,
            subject_type="post", subject_id="p_live",
            context={"space_id": space.id, "collective_name": space.name},
            payload={"post_id": "p_live", "excerpt": ""},
        )
        db.flush()
        result = route_event(db, ev, delivery_mode=DELIVERY_MODE_LIVE)
        assert len(result.intent_ids) >= 1
        for intent_id in result.intent_ids:
            intent = db.get(CommunicationIntent, intent_id)
            assert intent.delivery_mode == DELIVERY_MODE_LIVE

    def test_dm_resolver_addresses_recipient(self, db, make_user):
        sender = make_user()
        recipient_user = make_user()
        ev = emit(
            db,
            event_type="dm.message.sent",
            source_type=Source.CREATOR,
            source_id=sender.id,
            actor_user_id=sender.id,
            subject_type="thread", subject_id="t_1",
            payload={
                "recipient_id": recipient_user.id,
                "sender_name": "Sender",
                "thread_id": "t_1",
                "excerpt": "hi",
            },
        )
        db.flush()
        result = route_event(db, ev)
        assert len(result.intent_ids) >= 1
        for intent_id in result.intent_ids:
            intent = db.get(CommunicationIntent, intent_id)
            assert intent.recipient_user_id == recipient_user.id


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


class TestRegistries:
    def test_all_registered_resolvers_have_matching_templates(self):
        """Every resolver's event_type has at least one template
        registered — otherwise the pipeline would silently skip
        every recipient. If this fails, either add the template or
        de-register the resolver.
        """
        from app.comms.routing.resolver import registered_event_types
        from app.comms.templates.registry import registered_templates

        resolver_types = set(registered_event_types())
        template_types = {et for (et, _ch) in registered_templates()}
        missing = resolver_types - template_types
        assert not missing, (
            f"Registered resolvers without any template: {sorted(missing)}"
        )

    def test_expected_resolvers_present(self):
        from app.comms.routing.resolver import registered_event_types
        expected = {
            "account.password_reset_requested",
            "community.post.published",
            "dm.message.sent",
            "gathering.booking.confirmed",
            "pathway.published",
        }
        assert expected.issubset(set(registered_event_types()))

    def test_get_template_for_returns_registered(self):
        t = get_template_for("community.post.published", CHANNEL_IN_APP)
        assert t is not None
        assert t.key == "community.post.published.in_app"
        assert t.version == "v1"

    def test_get_template_for_unregistered_returns_none(self):
        assert get_template_for("nonexistent.event", CHANNEL_IN_APP) is None
