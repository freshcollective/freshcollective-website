"""R2A — legacy → comms migration proof.

One test per migrated flow proving:

* the comms event is emitted exactly once
* the comms routing pipeline produces at least one live intent
* the intent dispatches through Resend (the SDK call is intercepted;
  no real send)
* the legacy ``app.services.email_service.email_service.send`` is
  NEVER called for the same business action
* the recipient + rendered payload match the flow's contract

Every test flips COMMS_LIVE_TOPICS via the config default (already
set for the four migrated topics) — no per-test env manipulation
required.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch, MagicMock

import pytest

# SQLAlchemy relationship registration bootstrap.
import app.models.community_care  # noqa: F401
import app.main  # noqa: F401 — bootstraps registries + providers

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, SOURCE_FRESH_COLLECTIVE, SOURCE_CREATOR
from app.comms.events import emit as comms_emit
from app.comms.models import CommunicationDelivery, CommunicationEvent, CommunicationIntent
from app.comms.rollout import _route_event_bg, is_event_live


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------


def _run_route_event_bg(db, event_id: str) -> None:
    """Run ``_route_event_bg`` against the test's session without
    letting the production function close it.

    Two production surfaces open their own sessions via
    ``SessionLocal`` and would not see the test's SAVEPOINT-only
    User rows:

    * ``app/comms/rollout.py`` — the routing wrapper that closes
      its session at the end.
    * ``app/comms/providers/inapp.py::InAppProvider`` — opens a
      fresh session per send so its ``create_notification`` FK
      against ``users.id`` needs a session that can see the test
      user.

    Wrapping the fixture session with a shim whose ``close()`` is
    a no-op lets both call sites operate on the test session
    (visible SAVEPOINT state) without tearing it down.
    """
    class _NoClose:
        def __init__(self, real):
            self._real = real
        def __getattr__(self, name):
            return getattr(self._real, name)
        def close(self):
            pass

    # Swap the InAppProvider instance's stored session_factory to a
    # closure that hands the test session out. The provider was
    # instantiated at bootstrap and captured ``SessionLocal`` by
    # reference then, so patching the module-level import doesn't
    # affect the already-bound attribute.
    from app.comms.providers import get as _get_provider
    inapp = _get_provider("in_app")
    original_factory = inapp._session_factory  # type: ignore[attr-defined]
    inapp._session_factory = lambda: _NoClose(db)  # type: ignore[attr-defined]
    try:
        with patch("app.comms.rollout.SessionLocal", return_value=_NoClose(db)):
            _route_event_bg(event_id, "live")
    finally:
        inapp._session_factory = original_factory  # type: ignore[attr-defined]


class _SDKSpy:
    """Wraps a fake ``resend.Emails.send`` and records every call.

    Returns a well-formed response so ``ResendProvider.send`` reports
    accepted=True and populates the delivery's ``provider_message_id``.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict | None]] = []
        self.next_id = 1

    def __call__(self, params, options=None):
        self.calls.append((dict(params), dict(options) if options else None))
        msg_id = f"resend-mock-{self.next_id}"
        self.next_id += 1
        return {"id": msg_id}


@pytest.fixture
def spy_and_legacy():
    """Patch resend.Emails.send with a spy AND spy on the legacy
    ``email_service.send`` so tests can assert it was never called.
    """
    sdk_spy = _SDKSpy()
    with patch("resend.Emails.send", side_effect=sdk_spy) as _sdk_patch, \
         patch("resend.api_key", create=True), \
         patch(
             "app.services.email_service.email_service.send",
             new_callable=MagicMock,
         ) as legacy_spy:
        yield sdk_spy, legacy_spy


def _sanity_topics_live():
    """Every migrated topic must actually be live for R2A tests to
    exercise the comms path. This is a guard against a config drift
    that would silently make the tests trivial."""
    for ev_type in (
        "account.password_reset_requested",
        "collective.invitation.sent",
        "gathering.booking.confirmed",
        "community.post.published",
        "community.comment.created",
    ):
        assert is_event_live(ev_type), (
            f"R2A test suite requires {ev_type} to be live via "
            f"COMMS_LIVE_TOPICS; see backend/app/core/config.py."
        )


# ---------------------------------------------------------------------------
# 1. Password reset
# ---------------------------------------------------------------------------


def test_password_reset_emits_one_event_and_dispatches_via_resend(db, make_user, spy_and_legacy):
    """Password reset flow: emit account.password_reset_requested,
    route inline, dispatch through Resend (mocked). Legacy sender
    never called."""
    _sanity_topics_live()
    sdk_spy, legacy_spy = spy_and_legacy
    user = make_user(email=f"pw-{uuid.uuid4().hex[:8]}@example.com")

    event = comms_emit(
        db,
        event_type="account.password_reset_requested",
        source_type=SOURCE_FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="password_reset",
        payload={"reset_url": "https://example.com/reset?token=abc"},
    )
    db.commit()

    _run_route_event_bg(db, event.id)

    assert legacy_spy.call_count == 0, "legacy email_service.send must not fire"
    assert len(sdk_spy.calls) == 1, "exactly one Resend send"
    params, _options = sdk_spy.calls[0]
    assert params["to"] == [user.email]
    assert "Reset your Fresh Collective password" in params["subject"]
    assert "example.com/reset?token=abc" in params["html"]

    intents = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event.id
    ).all()
    email_intents = [i for i in intents if i.channel == CHANNEL_EMAIL_TRANSACTIONAL]
    assert len(email_intents) == 1
    assert email_intents[0].state == "sent"
    assert email_intents[0].recipient_address == user.email


# ---------------------------------------------------------------------------
# 2. Invitation
# ---------------------------------------------------------------------------


def test_invitation_emits_and_dispatches_to_prospective_member(db, make_user, spy_and_legacy):
    """The invitee usually has no User row. Verify the resolver
    still delivers via recipient_address_override."""
    _sanity_topics_live()
    sdk_spy, legacy_spy = spy_and_legacy
    inviter = make_user(role="creator")
    target_email = f"prospect-{uuid.uuid4().hex[:8]}@example.com"

    event = comms_emit(
        db,
        event_type="collective.invitation.sent",
        source_type=SOURCE_CREATOR,
        source_id=inviter.id,
        actor_user_id=inviter.id,
        subject_type="invitation",
        subject_id="inv_test_123",
        context={"space_id": "space_test", "collective_name": "The Grove"},
        payload={
            "recipient_email": target_email,
            "inviter_name":    "Alex",
            "collective_name": "The Grove",
            "accept_url":      "https://example.com/invites/token123",
        },
    )
    db.commit()

    _run_route_event_bg(db, event.id)

    assert legacy_spy.call_count == 0
    assert len(sdk_spy.calls) == 1
    params, _ = sdk_spy.calls[0]
    assert params["to"] == [target_email]
    assert "Alex invited you to The Grove" in params["subject"]
    assert "https://example.com/invites/token123" in params["html"]

    intents = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event.id
    ).all()
    assert len(intents) == 1
    assert intents[0].state == "sent"
    assert intents[0].recipient_address == target_email


# ---------------------------------------------------------------------------
# 3. Gathering booking confirmation
# ---------------------------------------------------------------------------


def test_gathering_booking_confirmation_emits_and_dispatches(db, make_user, make_space, spy_and_legacy):
    _sanity_topics_live()
    sdk_spy, legacy_spy = spy_and_legacy
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    booker = make_user(email=f"booker-{uuid.uuid4().hex[:8]}@example.com")

    event = comms_emit(
        db,
        event_type="gathering.booking.confirmed",
        source_type=SOURCE_CREATOR,
        source_id=creator.id,
        actor_user_id=booker.id,
        subject_type="gathering",
        subject_id="event_test_x",
        context={"space_id": space.id, "collective_name": space.name},
        payload={
            "booker_id": booker.id,
            "gathering_title": "Sunday Circle",
            "gathering_starts_at": "2026-09-01T18:00:00+10:00",
        },
    )
    db.commit()

    _run_route_event_bg(db, event.id)

    assert legacy_spy.call_count == 0
    # Booking may produce both in-app and email intents. Filter to email.
    email_calls = [c for c in sdk_spy.calls]
    assert len(email_calls) == 1
    params, _ = email_calls[0]
    assert params["to"] == [booker.email]
    assert "Sunday Circle" in params["subject"] or "booking" in params["subject"].lower()

    email_intents = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event.id,
        CommunicationIntent.channel == CHANNEL_EMAIL_TRANSACTIONAL,
    ).all()
    assert len(email_intents) == 1
    assert email_intents[0].state == "sent"
    assert email_intents[0].recipient_address == booker.email


# ---------------------------------------------------------------------------
# 4. Community post/reply
# ---------------------------------------------------------------------------


def test_community_comment_created_emits_and_dispatches_to_post_author(
    db, make_user, make_space, spy_and_legacy,
):
    _sanity_topics_live()
    sdk_spy, legacy_spy = spy_and_legacy
    author = make_user(email=f"author-{uuid.uuid4().hex[:8]}@example.com")
    commenter = make_user(email=f"commenter-{uuid.uuid4().hex[:8]}@example.com")
    space = make_space(creator=author)

    # The community category's email channel default is opt-in
    # (default_enabled=False, is_locked=False). To exercise the send
    # path the author needs an explicit IMMEDIATE preference — which
    # mirrors the pre-migration reality where members had to enable
    # the ``comment_reply_email`` preference for the legacy path to
    # fire.
    from app.comms.categories import CATEGORY_COMMUNITY, PRIORITY_IMMEDIATE
    from app.comms.preferences import set_preference
    set_preference(
        db, user_id=author.id,
        category_key=CATEGORY_COMMUNITY,
        channel=CHANNEL_EMAIL_TRANSACTIONAL,
        priority=PRIORITY_IMMEDIATE,
    )
    db.commit()

    event = comms_emit(
        db,
        event_type="community.comment.created",
        source_type=SOURCE_CREATOR,
        source_id=commenter.id,
        actor_user_id=commenter.id,
        subject_type="post_comment",
        subject_id="cmt_test_x",
        context={"space_id": space.id},
        payload={
            "post_id":        "post_test_x",
            "post_author_id": author.id,
            "post_title":     "First reflection",
            "comment_id":     "cmt_test_x",
            "commenter_name": commenter.name or "Someone",
            "view_url":       f"https://example.com/spaces/{space.slug}/community/post_test_x",
        },
    )
    db.commit()

    _run_route_event_bg(db, event.id)

    assert legacy_spy.call_count == 0, "legacy trigger email must be guarded off"
    assert len(sdk_spy.calls) == 1, "exactly one Resend send — to the post author"
    params, _ = sdk_spy.calls[0]
    assert params["to"] == [author.email]
    assert "reply" in params["subject"].lower()

    email_intents = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event.id,
        CommunicationIntent.channel == CHANNEL_EMAIL_TRANSACTIONAL,
    ).all()
    assert len(email_intents) == 1
    assert email_intents[0].state == "sent"
    assert email_intents[0].recipient_address == author.email


# ---------------------------------------------------------------------------
# Self-notification safety
# ---------------------------------------------------------------------------


def test_comment_by_post_author_does_not_notify_themselves(
    db, make_user, make_space, spy_and_legacy,
):
    """Defence in depth for the resolver — even if an event is
    emitted where commenter == post author (something the community
    routes emit site prevents, but a future emit site or admin
    tooling might not), no intent is created and no send happens.
    """
    _sanity_topics_live()
    sdk_spy, legacy_spy = spy_and_legacy
    author = make_user(email=f"solo-{uuid.uuid4().hex[:8]}@example.com")
    space = make_space(creator=author)

    # Enable the community email preference so this test would send
    # if the resolver weren't filtering self-notifications out.
    from app.comms.categories import CATEGORY_COMMUNITY, PRIORITY_IMMEDIATE
    from app.comms.preferences import set_preference
    set_preference(
        db, user_id=author.id,
        category_key=CATEGORY_COMMUNITY,
        channel=CHANNEL_EMAIL_TRANSACTIONAL,
        priority=PRIORITY_IMMEDIATE,
    )
    db.commit()

    event = comms_emit(
        db,
        event_type="community.comment.created",
        source_type=SOURCE_CREATOR,
        source_id=author.id,
        actor_user_id=author.id,               # <- same as post_author_id
        subject_type="post_comment",
        subject_id="cmt_solo_x",
        context={"space_id": space.id},
        payload={
            "post_id":        "post_solo_x",
            "post_author_id": author.id,        # <- self
            "post_title":     "Just thinking aloud",
            "comment_id":     "cmt_solo_x",
            "commenter_name": author.name or "Author",
            "view_url":       f"https://example.com/spaces/{space.slug}/community/post_solo_x",
        },
    )
    db.commit()
    _run_route_event_bg(db, event.id)

    assert len(sdk_spy.calls) == 0, "resolver must not return the commenter as a recipient of their own comment"
    assert legacy_spy.call_count == 0


# ---------------------------------------------------------------------------
# In-app routing regression — channel-aware _resolve_address
# ---------------------------------------------------------------------------
#
# The R2A cutover promoted four topics to live for the first time.
# Prior to this promotion, the routing pipeline had never dispatched
# an in-app intent in production, and a latent bug in
# ``decision._resolve_address`` (always returning ``user.email``,
# ignoring channel) was masked. Promotion surfaced it: the InAppProvider
# hands ``payload.to`` to ``create_notification`` as ``recipient_id``,
# which FK-references ``users.id`` — a raw email string violates the
# constraint at insert time and every in-app intent transitioned to
# ``failed``. These tests lock in the channel-aware fix.


def test_inapp_intent_recipient_is_user_id_not_email(
    db, make_user, spy_and_legacy,
):
    """The in-app intent's ``recipient_address`` must be the User's
    id, not their email — so InAppProvider's ``create_notification``
    can pass it as ``recipient_id`` without an FK violation.

    Uses password reset because its category (``account``) supports
    both in-app and email channels and is preference-locked
    immediate — no fixture setup required."""
    _sanity_topics_live()
    sdk_spy, legacy_spy = spy_and_legacy
    user = make_user(email=f"inapp-{uuid.uuid4().hex[:8]}@example.com")

    event = comms_emit(
        db,
        event_type="account.password_reset_requested",
        source_type=SOURCE_FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="password_reset",
        payload={"reset_url": "https://example.com/reset?token=abc"},
    )
    db.commit()
    _run_route_event_bg(db, event.id)

    intents = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event.id
    ).all()
    by_channel = {i.channel: i for i in intents}

    inapp = by_channel.get("in_app")
    assert inapp is not None, "expected an in-app intent for the account category"
    assert inapp.state == "sent", (
        f"in-app intent should reach 'sent' — got {inapp.state!r} "
        "(likely a channel-aware resolution bug in _resolve_address)"
    )
    assert inapp.recipient_address == user.id, (
        "in-app recipient must be user.id — the InAppProvider passes "
        "it as recipient_id to create_notification which FKs users.id"
    )

    email = by_channel.get(CHANNEL_EMAIL_TRANSACTIONAL)
    assert email is not None and email.state == "sent"
    assert email.recipient_address == user.email
    assert len(sdk_spy.calls) == 1
    assert legacy_spy.call_count == 0


def test_booking_confirmation_in_app_row_persisted(
    db, make_user, make_space, spy_and_legacy,
):
    """Booking confirmation must produce a real notifications row
    for the booker via the InAppProvider, replacing the legacy
    trigger's in-app write that R2A's guard now no-ops.
    """
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    booker = make_user(email=f"bk-{uuid.uuid4().hex[:8]}@example.com")

    event = comms_emit(
        db,
        event_type="gathering.booking.confirmed",
        source_type=SOURCE_CREATOR,
        source_id=creator.id,
        actor_user_id=booker.id,
        subject_type="gathering",
        subject_id="event_x",
        context={"space_id": space.id, "collective_name": space.name},
        payload={
            "booker_id": booker.id,
            "gathering_title": "Sunday Circle",
            "gathering_starts_at": "2026-09-01T18:00:00+10:00",
        },
    )
    db.commit()
    _run_route_event_bg(db, event.id)

    from app.models.notification import Notification
    notif_rows = db.query(Notification).filter(
        Notification.user_id == booker.id,
        Notification.notification_type == "booking_confirmed",
    ).all()
    assert len(notif_rows) == 1, (
        "InAppProvider should have written exactly one notifications "
        "row for the booker"
    )

    # In-app intent state
    inapp_intents = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event.id,
        CommunicationIntent.channel == "in_app",
    ).all()
    assert len(inapp_intents) == 1
    assert inapp_intents[0].state == "sent"
    assert inapp_intents[0].recipient_address == booker.id


def test_comment_reply_in_app_row_persisted(
    db, make_user, make_space, spy_and_legacy,
):
    """Comment reply must produce a notifications row for the post
    author, matching the legacy trigger's row shape."""
    _sanity_topics_live()
    from app.comms.categories import CATEGORY_COMMUNITY, PRIORITY_IMMEDIATE
    from app.comms.preferences import set_preference

    sdk_spy, _ = spy_and_legacy
    author = make_user(email=f"a-{uuid.uuid4().hex[:8]}@example.com")
    commenter = make_user(email=f"c-{uuid.uuid4().hex[:8]}@example.com")
    space = make_space(creator=author)

    set_preference(
        db, user_id=author.id,
        category_key=CATEGORY_COMMUNITY,
        channel=CHANNEL_EMAIL_TRANSACTIONAL,
        priority=PRIORITY_IMMEDIATE,
    )
    db.commit()

    event = comms_emit(
        db,
        event_type="community.comment.created",
        source_type=SOURCE_CREATOR,
        source_id=commenter.id,
        actor_user_id=commenter.id,
        subject_type="post_comment",
        subject_id="cmt_x",
        context={"space_id": space.id},
        payload={
            "post_id":        "post_x",
            "post_author_id": author.id,
            "post_title":     "First thoughts",
            "comment_id":     "cmt_x",
            "commenter_name": commenter.name or "Someone",
            "view_url":       f"https://example.com/spaces/{space.slug}/community/post_x",
        },
    )
    db.commit()
    _run_route_event_bg(db, event.id)

    from app.models.notification import Notification
    notif_rows = db.query(Notification).filter(
        Notification.user_id == author.id,
        Notification.notification_type == "comment_reply",
    ).all()
    assert len(notif_rows) == 1, (
        "InAppProvider should have written exactly one 'comment_reply' "
        "notifications row for the post author"
    )

    inapp_intents = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event.id,
        CommunicationIntent.channel == "in_app",
    ).all()
    assert len(inapp_intents) == 1
    assert inapp_intents[0].state == "sent"
    assert inapp_intents[0].recipient_address == author.id


def test_invitation_to_external_recipient_does_not_create_in_app_intent(
    db, make_user, spy_and_legacy,
):
    """Invitations to a prospective member (no User row) must not
    produce an in-app intent — there is no account to notify. The
    resolver hands ``recipient_address_override`` for email; the
    absence of an in-app template for ``collective.invitation.sent``
    causes process_one to skip that channel entirely.
    """
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    inviter = make_user(role="creator")

    event = comms_emit(
        db,
        event_type="collective.invitation.sent",
        source_type=SOURCE_CREATOR,
        source_id=inviter.id,
        actor_user_id=inviter.id,
        subject_type="invitation",
        subject_id="inv_x",
        context={"space_id": "s_x", "collective_name": "Grove"},
        payload={
            "recipient_email": f"prospect-{uuid.uuid4().hex[:8]}@example.com",
            "inviter_name":    "Alex",
            "collective_name": "Grove",
            "accept_url":      "https://ex.com/i/abc",
        },
    )
    db.commit()
    _run_route_event_bg(db, event.id)

    intents = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event.id
    ).all()
    channels = {i.channel for i in intents}
    assert CHANNEL_EMAIL_TRANSACTIONAL in channels, (
        "invitation must still produce its transactional email intent"
    )
    assert "in_app" not in channels, (
        "invitation must not create an in-app intent for an external "
        "recipient — no in-app template registered, process_one skips"
    )
    # And of course exactly one email send fires.
    assert len(sdk_spy.calls) == 1


# ---------------------------------------------------------------------------
# Retry / idempotency
# ---------------------------------------------------------------------------


def test_second_route_of_same_event_does_not_double_send(db, make_user, spy_and_legacy):
    """Routing the same event twice must not send twice — the intent's
    dedupe index on (event × recipient × channel) prevents a second
    intent from being created; the DB uniqueness is the durable
    dedupe surface, not Resend's Idempotency-Key window."""
    _sanity_topics_live()
    sdk_spy, legacy_spy = spy_and_legacy
    user = make_user(email=f"idempotent-{uuid.uuid4().hex[:8]}@example.com")

    event = comms_emit(
        db,
        event_type="account.password_reset_requested",
        source_type=SOURCE_FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="password_reset",
        payload={"reset_url": "https://example.com/reset?token=xyz"},
    )
    # Capture the id up-front. process_one performs a `db.rollback()`
    # on the second route's IntegrityError (duplicate-intent), which
    # invalidates the ORM identity map for `event` — attribute access
    # after that raises ObjectDeletedError. Freezing the id here
    # dodges that entirely; the DB row itself is unaffected.
    event_id = event.id
    db.commit()

    _run_route_event_bg(db, event_id)
    assert len(sdk_spy.calls) == 1, "first route: exactly one send"

    _run_route_event_bg(db, event_id)
    # Second route: ``create_intent`` inside ``process_one`` hits the
    # partial unique index on (event × recipient × channel), the
    # IntegrityError is caught, no new intent is created, and no new
    # dispatch fires. The invariant is "one business action ⇒ one
    # email"; asserting on the Resend spy is the direct check.
    assert len(sdk_spy.calls) == 1, "second route: no additional send"
    assert legacy_spy.call_count == 0, "legacy sender must never fire"


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


def test_provider_failure_does_not_prevent_intent_from_being_recorded(
    db, make_user, spy_and_legacy,
):
    """If Resend rejects the send, the intent is marked ``failed``
    and a delivery row records the failure. The domain event and
    intent still exist so operators can inspect and retry — no
    exception escapes the routing/dispatch loop."""
    _sanity_topics_live()
    sdk_spy, legacy_spy = spy_and_legacy
    user = make_user(email=f"fail-{uuid.uuid4().hex[:8]}@example.com")

    with patch("resend.Emails.send", side_effect=RuntimeError("simulated Resend outage")), \
         patch("resend.api_key", create=True):
        event = comms_emit(
            db,
            event_type="account.password_reset_requested",
            source_type=SOURCE_FRESH_COLLECTIVE,
            actor_user_id=user.id,
            subject_type="password_reset",
            payload={"reset_url": "https://example.com/reset?token=fail"},
        )
        db.commit()
        _run_route_event_bg(db, event.id)

    intents = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event.id
    ).all()
    email_intents = [i for i in intents if i.channel == CHANNEL_EMAIL_TRANSACTIONAL]
    assert len(email_intents) == 1
    assert email_intents[0].state == "failed"

    deliveries = db.query(CommunicationDelivery).filter(
        CommunicationDelivery.intent_id == email_intents[0].id
    ).all()
    assert len(deliveries) == 1
    assert deliveries[0].status == "failed"
    assert deliveries[0].error_class == "RuntimeError"
