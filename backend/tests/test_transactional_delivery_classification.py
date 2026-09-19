"""Delivery classification — which emails a member can switch off.

Content editability and delivery reach are two different questions and
this file only asks the second one:

    Can the recipient opt out of this email without losing a security
    message, a receipt, a money- or access-state notification, or a
    material change to something they booked or bought?

Where the answer is no, the event is listed in
``TRANSACTIONAL_EVENT_TYPES`` and its delivery stops depending on a
preference. Where the answer is yes — reminders, community
notifications, the welcome note — the member stays in charge.

:data:`AUDITED` below is the whole decision, one line per email, and
the first test fails if a template is ever declared without one. That
is the point of writing it out: a new email should not be able to
arrive in World Management having quietly inherited a delivery policy
nobody chose for it.

Three things the lock deliberately does not do, each pinned here:
hard-bounce and complaint suppression still win, consent gates still
run, and an unlocked category's preferences still govern every other
event in that category.

No email is sent anywhere in this file — the decision pipeline stops
at an intent row, and no provider is invoked.
"""

from __future__ import annotations

import uuid
from datetime import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.comms.templates  # noqa: F401 — registers templates
import app.comms.routing.resolvers  # noqa: F401 — registers resolvers
from app.auth.dependencies import get_admin_user
from app.comms.categories import (
    CHANNEL_EMAIL_TRANSACTIONAL,
    Priority,
    Source,
)
from app.comms.intents import DELIVERY_MODE_LIVE, STATE_RECORDED
from app.comms.models import (
    CommunicationChannelDefault,
    CommunicationEvent,
    CommunicationIntent,
)
from app.comms.preferences import (
    LockedPreferenceError,
    set_preference,
    update_member_settings,
)
from app.comms.registry import (
    TRANSACTIONAL_EVENT_TYPES,
    category_for_topic,
    get_event_definition,
    is_transactional_event,
)
from app.comms.routing.decision import CONSENT_GATES, process_one
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.suppressions import record_suppression
from app.comms.templates.editable import (
    admin_declarations,
    all_declarations,
)
from app.core.database import get_db
from app.main import app


BASE = "/api/admin/communications/email-templates"
PROBE = "diagnostics.provider_probe.email_transactional"

LOCKED = "locked"                      # a member cannot switch it off
PREFERENCE = "preference_controlled"   # a member can


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------
#
# Every declared email, and the reason it lands where it does. Read the
# second column as the answer to the question at the top of this file.

AUDITED: dict[str, str] = {
    # ── Security and account entry ───────────────────────────────────
    # Someone mid-flow, waiting. A preference must not strand a person
    # outside their own account.
    "account.email_verification_requested":          LOCKED,
    "account.password_reset_requested":              LOCKED,
    # The recipient is usually not a member yet and has no preferences
    # at all; the preference the pipeline consults belongs to the
    # inviter. See the note in ``registry.py``.
    "collective.invitation.sent":                    LOCKED,
    # Not a receipt and not a security message — a greeting. The
    # member could safely miss it, so the event itself is not locked.
    # (It is nonetheless undroppable today because the Account
    # category default is locked; the admin list reports that truth.)
    "account.welcome_after_signup":                  PREFERENCE,

    # ── Gatherings ───────────────────────────────────────────────────
    "gathering.booking.confirmed":                   LOCKED,
    "gathering.multi_booking.confirmed":             LOCKED,
    # A thing they booked is not happening. Material, and it arrives
    # whether or not they wanted gathering chatter.
    "gathering.cancelled":                           LOCKED,
    # The canonical optional message: useful, repeatable, skippable.
    "gathering.reminder.24h":                        PREFERENCE,

    # ── Member money and access ──────────────────────────────────────
    "purchase.completed":                            LOCKED,
    "purchase.refunded":                             LOCKED,
    "purchase.first_payment_failed":                 LOCKED,
    "purchase.plan_completed":                       LOCKED,
    "payment.instalment_failed":                     LOCKED,
    "payment.recovered":                             LOCKED,
    "access.suspended":                              LOCKED,

    # ── Creator plan billing ─────────────────────────────────────────
    "creator.plan_activated":                        LOCKED,
    "creator.subscription.payment_failed":           LOCKED,
    "creator.subscription.recovered":                LOCKED,
    "creator.subscription.cancellation_scheduled":   LOCKED,
    "creator.subscription.cancelled":                LOCKED,

    # ── Community and messages ───────────────────────────────────────
    # Conversation, not consequence. Exactly what preferences are for.
    "community.post.published":                      PREFERENCE,
    "community.comment.created":                     PREFERENCE,
    "dm.message.sent":                               PREFERENCE,
    "pathway.published":                             PREFERENCE,
}

LOCKED_EVENTS = sorted(k for k, v in AUDITED.items() if v == LOCKED)
OPTIONAL_EVENTS = sorted(k for k, v in AUDITED.items() if v == PREFERENCE)


# A context wide enough for any template in the inventory to render.
# The decision pipeline renders before it creates an intent, so these
# tests need real copy out the other end.
CONTEXT = {
    "first_name": "Ada",
    "collective_name": "Still Water",
    "gathering_title": "Morning Sit",
    "gathering_starts_at": "Friday 19 September at 9:00am",
    "gathering_name": "Morning Sit",
    "next_url": "https://fc.test/d",
    "verify_url": "https://fc.test/v",
    "reset_url": "https://fc.test/r",
    "accept_url": "https://fc.test/a",
    "inviter_name": "Sarah",
    "experience_name": "Life in Alignment",
    "purchase_name": "Life in Alignment",
    "member_url": "https://fc.test/m",
    "billing_url": "https://fc.test/b",
    "plan_name": "Creator Portfolio",
    "plan_label": "Creator Portfolio",
    "payment_mode": "single",
    "amount_cents": 3780,
    "currency": "AUD",
    "grace_expires_at": "26 September",
    "current_period_end": "26 September",
    "commenter_name": "Sarah",
    "post_title": "On stillness",
    "excerpt": "A quiet thought.",
    "sender_name": "Sarah",
    "pathway_title": "Beginning",
    "schedule": [],
    "cancellation_reason": None,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _category_of(event_type: str) -> str:
    definition = get_event_definition(event_type)
    assert definition is not None, f"{event_type} is not registered"
    return category_for_topic(definition.topic)


def _unlock_category(db, category_key: str) -> None:
    """Drop the category-level lock for the email channel.

    Several of the events below live in Account or Purchases, which are
    locked categories. Leaving that lock in place would let these tests
    pass without the event-level lock doing anything at all. Removing
    it inside the test transaction is what makes the assertion about
    the mechanism under test rather than about a seed row.
    """
    row = db.execute(
        select(CommunicationChannelDefault).where(
            CommunicationChannelDefault.category_key == category_key,
            CommunicationChannelDefault.channel == CHANNEL_EMAIL_TRANSACTIONAL,
        )
    ).scalar_one()
    row.is_locked = False
    db.flush()


def _silence(db, user, category_key: str) -> None:
    _unlock_category(db, category_key)
    set_preference(
        db, user_id=user.id, category_key=category_key,
        channel=CHANNEL_EMAIL_TRANSACTIONAL, priority=Priority.SILENT,
    )
    db.flush()


def _event(db, user, event_type: str) -> CommunicationEvent:
    from app.comms import emit as comms_emit

    ev = comms_emit(
        db,
        event_type=event_type,
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="test",
        subject_id=f"sub_{uuid.uuid4().hex[:8]}",
        context={"collective_name": "Still Water"},
        payload=dict(CONTEXT),
    )
    db.flush()
    return ev


def _recipient(user) -> ResolvedRecipient:
    return ResolvedRecipient(
        user_id=user.id, role_in_event="recipient",
        human_reason="A test recipient.",
        template_context=dict(CONTEXT),
    )


def _decide(db, user, event_type: str, **kw):
    return process_one(
        db, event=_event(db, user, event_type), recipient=_recipient(user),
        channel=CHANNEL_EMAIL_TRANSACTIONAL,
        delivery_mode=DELIVERY_MODE_LIVE, **kw,
    )


def _was_delivered(db, outcome) -> bool:
    """True when the decision produced a real, sendable intent."""
    if outcome.intent_id is None or outcome.suppression_reason is not None:
        return False
    intent = db.get(CommunicationIntent, outcome.intent_id)
    return intent is not None and intent.state != STATE_RECORDED


@pytest.fixture(autouse=True)
def _no_dispatch():
    with patch("app.comms.rollout.schedule_routing_if_needed", return_value=None):
        yield


@pytest.fixture
def admin(make_user):
    from datetime import datetime
    return make_user(role="admin", email_verified_at=datetime.utcnow())


@pytest.fixture
def client(db, admin):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_admin_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


# ===========================================================================
# 1. The audit is complete and is what the code implements
# ===========================================================================


class TestTheAudit:
    def test_every_declared_email_has_a_decision(self):
        """A new template must not inherit a delivery policy by
        accident. Declaring one without a line in AUDITED fails here."""
        declared = {d.event_type for d in admin_declarations()}
        assert declared - set(AUDITED) == set(), (
            "these emails are in World Management with no audited "
            "delivery classification"
        )
        assert set(AUDITED) - declared == set(), (
            "AUDITED names emails that are no longer declared"
        )

    @pytest.mark.parametrize("event_type", LOCKED_EVENTS)
    def test_locked_events_are_locked(self, event_type):
        assert is_transactional_event(event_type)

    @pytest.mark.parametrize("event_type", OPTIONAL_EVENTS)
    def test_optional_events_are_not_locked(self, event_type):
        assert not is_transactional_event(event_type)

    def test_the_registry_holds_nothing_the_audit_has_not_seen(self):
        """The lock list and the audit are the same list."""
        assert set(TRANSACTIONAL_EVENT_TYPES) == set(LOCKED_EVENTS)


# ===========================================================================
# 2. Locked emails reach the member whatever their preferences say
# ===========================================================================


class TestLockedEmailsAreDelivered:
    @pytest.mark.parametrize("event_type", LOCKED_EVENTS)
    def test_a_silenced_category_cannot_suppress_it(
        self, db, make_user, event_type,
    ):
        user = make_user()
        _silence(db, user, _category_of(event_type))
        assert _was_delivered(db, _decide(db, user, event_type)), event_type

    def test_verification_survives_silenced_account_email(self, db, make_user):
        """Named explicitly because the failure is the worst one in the
        set: a new account that can never confirm itself."""
        user = make_user(email_verified_at=None)
        _silence(db, user, _category_of("account.email_verification_requested"))
        assert _was_delivered(
            db, _decide(db, user, "account.email_verification_requested"),
        )

    def test_password_reset_survives_silenced_account_email(self, db, make_user):
        """The other one: locked out, and the way back in is silenced."""
        user = make_user()
        _silence(db, user, _category_of("account.password_reset_requested"))
        assert _was_delivered(
            db, _decide(db, user, "account.password_reset_requested"),
        )

    @pytest.mark.parametrize("event_type", LOCKED_EVENTS)
    def test_a_digest_cadence_cannot_defer_it(
        self, db, make_user, event_type,
    ):
        """A receipt in tomorrow's digest is not a receipt."""
        user = make_user()
        category = _category_of(event_type)
        _unlock_category(db, category)
        set_preference(
            db, user_id=user.id, category_key=category,
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            priority=Priority.DAILY_DIGEST,
        )
        db.flush()
        outcome = _decide(db, user, event_type)
        assert outcome.digest_item_id is None, event_type
        assert _was_delivered(db, outcome), event_type

    def test_the_daily_email_cap_does_not_downgrade_a_receipt(
        self, db, make_user,
    ):
        """The cap protects an inbox from optional notifications. A
        member who has had a busy day still gets their refund."""
        user = make_user()
        with patch(
            "app.comms.routing.pacing."
            "IMMEDIATE_EMAIL_CAP_PER_CATEGORY_PER_DAY", 0,
        ):
            locked = _decide(db, user, "purchase.refunded")
            optional = _decide(db, user, "gathering.reminder.24h")
        assert locked.digest_item_id is None
        assert _was_delivered(db, locked)
        assert optional.digest_item_id is not None, (
            "the cap must still apply to everything else"
        )

    def test_quiet_hours_do_not_defer_a_password_reset(self, db, make_user):
        """A reset held until morning is a reset the member cannot use.
        A reminder held until morning is the feature working."""
        user = make_user()
        update_member_settings(
            db, user_id=user.id, timezone="UTC",
            quiet_hours_start_local=time(0, 0),
            quiet_hours_end_local=time(23, 59),
        )
        db.flush()
        locked = _decide(db, user, "account.password_reset_requested")
        optional = _decide(db, user, "gathering.reminder.24h")

        assert db.get(CommunicationIntent, locked.intent_id).scheduled_for is None
        assert db.get(
            CommunicationIntent, optional.intent_id,
        ).scheduled_for is not None, (
            "quiet hours must still hold an optional notification"
        )


# ===========================================================================
# 3. Optional emails stay optional
# ===========================================================================


class TestOptionalEmailsStayOptional:
    @pytest.mark.parametrize("event_type", [
        "gathering.reminder.24h",
        "community.post.published",
        "community.comment.created",
    ])
    def test_a_silenced_category_still_suppresses_it(
        self, db, make_user, event_type,
    ):
        user = make_user()
        _silence(db, user, _category_of(event_type))
        outcome = _decide(db, user, event_type)
        intent = db.get(CommunicationIntent, outcome.intent_id)
        assert intent is not None and intent.state == STATE_RECORDED, event_type

    def test_silencing_gatherings_is_still_allowed(self, db, make_user):
        """Locking the cancellation notice must not have locked the
        category it lives in."""
        user = make_user()
        set_preference(
            db, user_id=user.id, category_key=_category_of("gathering.cancelled"),
            channel=CHANNEL_EMAIL_TRANSACTIONAL, priority=Priority.SILENT,
        )
        db.flush()
        outcome = _decide(db, user, "gathering.reminder.24h")
        assert db.get(
            CommunicationIntent, outcome.intent_id,
        ).state == STATE_RECORDED
        assert _was_delivered(db, _decide(db, user, "gathering.cancelled"))

    def test_locked_categories_still_refuse_a_member_override(
        self, db, make_user,
    ):
        """Unchanged by this work: Account and Purchases were locked
        categories before it and still are."""
        user = make_user()
        for category in ("account", "purchases"):
            with pytest.raises(LockedPreferenceError):
                set_preference(
                    db, user_id=user.id, category_key=category,
                    channel=CHANNEL_EMAIL_TRANSACTIONAL,
                    priority=Priority.SILENT,
                )


# ===========================================================================
# 4. What the lock must never override
# ===========================================================================


class TestSafetyStillWins:
    @pytest.mark.parametrize("reason", ["bounced", "complained"])
    @pytest.mark.parametrize("event_type", LOCKED_EVENTS)
    def test_hard_bounce_and_complaint_still_suppress(
        self, db, make_user, event_type, reason,
    ):
        """Deliverability safety runs after the preference gate and
        wins. A locked email is not a licence to keep mailing an
        address the provider has told us to stop using."""
        user = make_user()
        record_suppression(
            db, address_type="email", address=user.email,
            reason=reason, source_provider="resend",
        )
        db.flush()
        outcome = _decide(db, user, event_type)
        assert outcome.suppression_reason == reason, event_type
        assert not _was_delivered(db, outcome), event_type

    def test_no_locked_event_sits_behind_a_consent_gate(self):
        """Consent is checked after the lock, so a consent-gated
        category would still be gated — but nothing in the locked list
        belongs to one, and that is worth knowing if a future event
        does."""
        gated = {category for category, _channel in CONSENT_GATES}
        for event_type in LOCKED_EVENTS:
            assert _category_of(event_type) not in gated, event_type


# ===========================================================================
# 5. The internal diagnostic is not part of World Management
# ===========================================================================


class TestProviderProbeIsHidden:
    def test_it_is_absent_from_the_list(self, client):
        keys = {t["template_key"] for t in client.get(BASE).json()}
        assert PROBE not in keys
        assert keys, "the list must not be empty — that would pass vacuously"

    @pytest.mark.parametrize("call", [
        lambda c: c.get(f"{BASE}/{PROBE}"),
        lambda c: c.put(f"{BASE}/{PROBE}", json={"overrides": {"heading": "x"}}),
        lambda c: c.post(f"{BASE}/{PROBE}/preview", json={}),
        lambda c: c.delete(f"{BASE}/{PROBE}"),
    ])
    def test_it_is_unreachable_by_key(self, client, call):
        """Hiding it from the list alone would leave it reachable by
        anyone who typed the key."""
        assert call(client).status_code == 404

    def test_the_diagnostic_itself_is_untouched(self):
        """Excluded from the admin inventory, still a registered,
        renderable template with its own declaration."""
        from app.comms.templates.registry import get_template_for
        assert get_template_for(
            "diagnostics.provider_probe", CHANNEL_EMAIL_TRANSACTIONAL,
        ) is not None
        probe = next(
            d for d in all_declarations()
            if d.event_type == "diagnostics.provider_probe"
        )
        assert probe.internal is True
        assert probe.classification == "system"
        assert probe.slots == ()


# ===========================================================================
# 6. Content editability is untouched by any of this
# ===========================================================================


# Pinned as it stood before the delivery audit. Delivery reach changed;
# not one template gained or lost an editable field.
CONTENT_CLASSIFICATION: dict[str, str] = {
    "account.email_verification_requested":        "partial",
    "account.password_reset_requested":            "system",
    "account.welcome_after_signup":                "editable",
    "collective.invitation.sent":                  "editable",
    "creator.plan_activated":                      "editable",
    "creator.subscription.cancellation_scheduled": "system",
    "creator.subscription.cancelled":              "system",
    "creator.subscription.payment_failed":         "system",
    "creator.subscription.recovered":              "system",
    "community.comment.created":                   "editable",
    "community.post.published":                    "editable",
    "dm.message.sent":                             "editable",
    "pathway.published":                           "editable",
    "gathering.booking.confirmed":                 "editable",
    "gathering.cancelled":                         "editable",
    "gathering.multi_booking.confirmed":           "partial",
    "gathering.reminder.24h":                      "editable",
    "access.suspended":                            "system",
    "payment.instalment_failed":                   "system",
    "payment.recovered":                           "system",
    "purchase.completed":                          "partial",
    "purchase.first_payment_failed":               "system",
    "purchase.plan_completed":                     "system",
    "purchase.refunded":                           "system",
}


class TestContentEditabilityUnchanged:
    def test_classifications_are_exactly_as_before(self):
        actual = {
            d.event_type: d.classification for d in admin_declarations()
        }
        assert actual == CONTENT_CLASSIFICATION

    def test_no_locked_email_lost_its_editable_copy(self):
        """The two questions are independent. A cancellation notice is
        locked for delivery and still fully editable."""
        by_event = {d.event_type: d for d in admin_declarations()}
        assert by_event["gathering.cancelled"].is_editable
        assert by_event["gathering.booking.confirmed"].is_editable
        assert not by_event["account.password_reset_requested"].is_editable

    def test_system_templates_still_declare_no_slots(self):
        for d in admin_declarations():
            if d.classification == "system":
                assert d.slots == (), d.template_key
