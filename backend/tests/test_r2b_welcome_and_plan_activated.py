"""R2B — welcome-after-signup + creator.plan_activated emit/dispatch.

R2B adds two new comms events:

* ``account.welcome_after_signup`` — fires once per new User row via
  ``auth.service.emit_welcome_after_signup``, called from the signup
  route and from ``purchases.routes.claim_with_signup``.
* ``creator.plan_activated`` — fires once per genuine
  inactive→active transition inside
  ``creator.plan_activation.activate_creator_plan``. Skipped when the
  same call is an idempotent no-op (already active on same plan) so
  Stripe replays and repeat admin actions do not produce duplicates.

Both events register under TOPIC_ACCOUNT (default-enabled +
locked-immediate) so they are never suppressed by preference gating —
they are transactional lifecycle emails.

Tests here mirror the R2A style: one focused test per contract, all
using the SAVEPOINT-scoped session + ``_run_route_event_bg`` helper
so InAppProvider and the routing wrapper both see the test User rows.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch, MagicMock

import pytest

# SQLAlchemy relationship registration bootstrap.
import app.models.community_care  # noqa: F401
import app.main  # noqa: F401 — bootstraps registries + providers

from app.comms.categories import (
    CHANNEL_EMAIL_TRANSACTIONAL,
    CHANNEL_IN_APP,
    SOURCE_FRESH_COLLECTIVE,
)
from app.comms.events import emit as comms_emit
from app.comms.models import CommunicationEvent, CommunicationIntent
from app.comms.rollout import _route_event_bg, is_event_live
from app.creator.plan_activation import ActivationSource, activate_creator_plan
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)


# ---------------------------------------------------------------------------
# Shared harness — mirrors backend/tests/test_r2a_legacy_to_comms_migration.py
# ---------------------------------------------------------------------------


def _run_route_event_bg(db, event_id: str) -> None:
    """Route + inline-dispatch against the test's SAVEPOINT session.

    Wraps the fixture session with a no-close shim so the routing
    wrapper's ``db.close()`` and InAppProvider's session-close do not
    tear the SAVEPOINT down.
    """
    class _NoClose:
        def __init__(self, real):
            self._real = real
        def __getattr__(self, name):
            return getattr(self._real, name)
        def close(self):
            pass

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
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict | None]] = []
        self.next_id = 1

    def __call__(self, params, options=None):
        self.calls.append((dict(params), dict(options) if options else None))
        msg_id = f"resend-r2b-{self.next_id}"
        self.next_id += 1
        return {"id": msg_id}


@pytest.fixture
def spy_and_legacy():
    """Mirror of R2A fixture: real Resend SDK stubbed, legacy sender
    watched. Neither new R2B event has a legacy send site, so we
    still assert ``legacy_spy.call_count == 0`` to future-proof
    against someone adding one."""
    sdk_spy = _SDKSpy()
    with patch("resend.Emails.send", side_effect=sdk_spy) as _sdk_patch, \
         patch("resend.api_key", create=True), \
         patch(
             "app.services.email_service.email_service.send",
             new_callable=MagicMock,
         ) as legacy_spy:
        yield sdk_spy, legacy_spy


@pytest.fixture
def _plans(db):
    """Seed the two Creator plan rows the activation service reads."""
    for slug, name, price, fee_bps, cap in (
        ("creator", "Creator", 1900, 800, 1),
        ("pro", "Creator Portfolio", 7900, 300, 5),
    ):
        if db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first() is None:
            db.add(CreatorPlan(
                id=f"cp_{slug}",
                name=name,
                slug=slug,
                monthly_price_cents=price,
                transaction_fee_basis_points=fee_bps,
                collective_limit=cap,
                is_active=True,
            ))
    db.flush()


def _sanity_topics_live():
    """R2B piggybacks on TOPIC_ACCOUNT / topic 'account' being live.
    Guard against drift that would silently make the tests trivial."""
    for ev_type in (
        "account.welcome_after_signup",
        "creator.plan_activated",
    ):
        assert is_event_live(ev_type), (
            f"R2B test suite requires {ev_type} to be live via "
            f"COMMS_LIVE_TOPICS; see backend/app/core/config.py."
        )


# ---------------------------------------------------------------------------
# account.welcome_after_signup
# ---------------------------------------------------------------------------


def test_welcome_after_signup_emits_and_dispatches_via_resend(
    db, make_user, spy_and_legacy,
):
    """Welcome flow: emit + route + dispatch through Resend (mocked).
    Legacy sender never called. Recipient is the just-signed-up user."""
    _sanity_topics_live()
    sdk_spy, legacy_spy = spy_and_legacy
    user = make_user(
        email=f"welcome-{uuid.uuid4().hex[:8]}@example.com",
        name="Ada Lovelace",
    )

    event = comms_emit(
        db,
        event_type="account.welcome_after_signup",
        source_type=SOURCE_FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="account",
        subject_id=user.id,
        payload={
            "first_name": "Ada",
            "next_url":   "https://example.com/dashboard",
        },
        dedupe_key=f"welcome:{user.id}",
    )
    db.commit()

    _run_route_event_bg(db, event.id)

    assert legacy_spy.call_count == 0
    assert len(sdk_spy.calls) == 1
    params, _ = sdk_spy.calls[0]
    assert params["to"] == [user.email]
    assert "Welcome to Fresh Collective" in params["subject"]
    assert "Hi Ada," in params["html"]
    assert "https://example.com/dashboard" in params["html"]

    email_intents = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event.id,
        CommunicationIntent.channel == CHANNEL_EMAIL_TRANSACTIONAL,
    ).all()
    assert len(email_intents) == 1
    assert email_intents[0].state == "sent"
    assert email_intents[0].recipient_address == user.email


def test_welcome_after_signup_in_app_recipient_is_user_id(
    db, make_user, spy_and_legacy,
):
    """In-app intent's ``recipient_address`` must be the User's id,
    matching the channel-aware fix in ``decision._resolve_address``
    the R2A cutover locked in."""
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    user = make_user(email=f"welcome-inapp-{uuid.uuid4().hex[:8]}@example.com")

    event = comms_emit(
        db,
        event_type="account.welcome_after_signup",
        source_type=SOURCE_FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="account",
        subject_id=user.id,
        payload={"first_name": "", "next_url": "https://example.com/dashboard"},
        dedupe_key=f"welcome:{user.id}",
    )
    db.commit()
    _run_route_event_bg(db, event.id)

    inapp = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event.id,
        CommunicationIntent.channel == CHANNEL_IN_APP,
    ).one()
    assert inapp.state == "sent"
    assert inapp.recipient_address == user.id


def test_signup_prevents_duplicate_welcome_via_user_uniqueness(
    db, make_user, spy_and_legacy,
):
    """The welcome emit doesn't use a dedupe_key — it doesn't need one
    because ``create_user`` sits behind an email-uniqueness check on
    ``users``. This test locks in the assumption: an attempted second
    signup for the same email raises before any second welcome could
    be emitted."""
    _sanity_topics_live()
    _, _ = spy_and_legacy
    email = f"unique-{uuid.uuid4().hex[:8]}@example.com"

    # First "signup" — direct model insert simulating create_user.
    from app.auth import service as auth_service
    user1 = auth_service.create_user(db, "First", email, "hunter22ok")
    assert user1.email == email

    # Second attempt with the same email — should raise. The route
    # layer's pre-check returns a 409 before reaching create_user, but
    # if a race got past that check the DB uniqueness constraint would
    # still fire. Either way, only one User row (→ only one welcome
    # emit possible) is ever created.
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        auth_service.create_user(db, "Second", email, "hunter22ok")


# ---------------------------------------------------------------------------
# creator.plan_activated
# ---------------------------------------------------------------------------


def test_creator_plan_activated_emits_and_dispatches_on_stripe_activation(
    db, make_user, _plans, spy_and_legacy,
):
    """Fresh Stripe-paid activation must produce exactly one
    ``creator.plan_activated`` event and one dispatched email."""
    _sanity_topics_live()
    sdk_spy, legacy_spy = spy_and_legacy
    user = make_user(
        email=f"creator-{uuid.uuid4().hex[:8]}@example.com",
        name="Grace Hopper",
    )

    result = activate_creator_plan(
        db, user, "creator",
        ActivationSource(
            source="stripe_paid",
            stripe_subscription_id="sub_test_r2b",
            stripe_customer_id="cus_test_r2b",
        ),
    )
    db.commit()

    assert not result.was_noop
    assert result.activation_event is not None
    event_id = result.activation_event.id

    _run_route_event_bg(db, event_id)

    assert legacy_spy.call_count == 0
    assert len(sdk_spy.calls) == 1
    params, _ = sdk_spy.calls[0]
    assert params["to"] == [user.email]
    assert "Creator plan is active" in params["subject"]
    assert "Hi Grace," in params["html"]


def test_creator_plan_activated_idempotent_noop_skips_emit(
    db, make_user, _plans, spy_and_legacy,
):
    """Second call for the same plan while already active is a
    ``was_noop=True`` no-op — no new event, no send."""
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    user = make_user(email=f"noop-{uuid.uuid4().hex[:8]}@example.com")

    first = activate_creator_plan(
        db, user, "creator",
        ActivationSource(source="stripe_paid",
                         stripe_subscription_id="sub_1",
                         stripe_customer_id="cus_1"),
    )
    db.commit()
    assert first.activation_event is not None

    # Route + dispatch the first activation so ``sdk_spy.calls`` has 1.
    _run_route_event_bg(db, first.activation_event.id)
    assert len(sdk_spy.calls) == 1

    # Replay — same plan, already active.
    second = activate_creator_plan(
        db, user, "creator",
        ActivationSource(source="stripe_paid",
                         stripe_subscription_id="sub_1",
                         stripe_customer_id="cus_1"),
    )
    db.commit()
    assert second.was_noop is True
    assert second.activation_event is None
    # No additional Resend send.
    assert len(sdk_spy.calls) == 1


def test_creator_plan_activated_reactivation_produces_new_event(
    db, make_user, _plans, spy_and_legacy,
):
    """Cancel then reactivate: the second activation is genuine and
    must emit a fresh event with a new dedupe key (new
    ``starts_at``)."""
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    user = make_user(email=f"reactivate-{uuid.uuid4().hex[:8]}@example.com")

    first = activate_creator_plan(
        db, user, "creator",
        ActivationSource(source="stripe_paid",
                         stripe_subscription_id="sub_x",
                         stripe_customer_id="cus_x"),
    )
    db.commit()
    assert first.activation_event is not None
    _run_route_event_bg(db, first.activation_event.id)
    assert len(sdk_spy.calls) == 1
    first_starts_at = first.subscription.starts_at

    # Cancel the subscription so a reactivation is possible.
    first.subscription.status = CreatorSubscriptionStatus.cancelled
    db.flush()
    db.commit()

    # Reactivate. Uses a distinct starts_at → distinct dedupe key.
    from datetime import timedelta
    later = first_starts_at + timedelta(days=30)
    second = activate_creator_plan(
        db, user, "creator",
        ActivationSource(source="stripe_paid",
                         stripe_subscription_id="sub_x",
                         stripe_customer_id="cus_x",
                         starts_at=later),
    )
    db.commit()
    assert second.was_reactivated is True
    assert not second.was_noop
    assert second.activation_event is not None
    assert second.activation_event.id != first.activation_event.id

    _run_route_event_bg(db, second.activation_event.id)
    # First send + second send = 2.
    assert len(sdk_spy.calls) == 2


def test_creator_plan_activated_admin_manual_grant_emits(
    db, make_user, _plans, spy_and_legacy,
):
    """Admin manual grant of a Creator plan sends the activation
    email too — per the R2B brief, transactional lifecycle emails do
    not assume out-of-band admin communication."""
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    admin = make_user(role="admin")
    user = make_user(email=f"manual-{uuid.uuid4().hex[:8]}@example.com")

    result = activate_creator_plan(
        db, user, "creator",
        ActivationSource(
            source="manual_grant",
            reason="comp",
            note="R2B manual-grant test",
            actor_user_id=admin.id,
        ),
    )
    db.commit()
    assert not result.was_noop
    assert result.activation_event is not None

    _run_route_event_bg(db, result.activation_event.id)
    assert len(sdk_spy.calls) == 1
    params, _ = sdk_spy.calls[0]
    assert params["to"] == [user.email]
    assert "Creator plan is active" in params["subject"]


def test_creator_plan_activated_uses_canonical_plan_name(
    db, make_user, _plans, spy_and_legacy,
):
    """Email must use ``CreatorPlan.name`` (source of truth) — R2B
    brief bans invented / product-marketing terminology like 'Pro'."""
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    user = make_user(email=f"portfolio-{uuid.uuid4().hex[:8]}@example.com")

    result = activate_creator_plan(
        db, user, "pro",
        ActivationSource(source="stripe_paid",
                         stripe_subscription_id="sub_p",
                         stripe_customer_id="cus_p"),
    )
    db.commit()
    assert result.activation_event is not None
    _run_route_event_bg(db, result.activation_event.id)

    assert len(sdk_spy.calls) == 1
    params, _ = sdk_spy.calls[0]
    # The seed row's ``name`` for slug='pro' is 'Creator Portfolio'.
    assert "Creator Portfolio" in params["html"]
    assert "Pro" not in params["html"]


# ---------------------------------------------------------------------------
# Provider failure
# ---------------------------------------------------------------------------


def test_creator_plan_activation_provider_failure_does_not_undo_activation(
    db, make_user, _plans, spy_and_legacy,
):
    """A Resend send failure must not roll back the CreatorSubscription
    row. Matches the R2A safety contract: comms failure is non-fatal."""
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    user = make_user(email=f"failsend-{uuid.uuid4().hex[:8]}@example.com")

    with patch("resend.Emails.send", side_effect=RuntimeError("resend down")):
        result = activate_creator_plan(
            db, user, "creator",
            ActivationSource(source="stripe_paid",
                             stripe_subscription_id="sub_fail",
                             stripe_customer_id="cus_fail"),
        )
        db.commit()
        assert result.activation_event is not None
        _run_route_event_bg(db, result.activation_event.id)

    # Subscription persisted.
    sub = db.query(CreatorSubscription).filter(
        CreatorSubscription.user_id == user.id
    ).one()
    assert sub.status == CreatorSubscriptionStatus.active

    # Email intent marked failed (not blocking the activation).
    email_intents = db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == result.activation_event.id,
        CommunicationIntent.channel == CHANNEL_EMAIL_TRANSACTIONAL,
    ).all()
    assert len(email_intents) == 1
    assert email_intents[0].state == "failed"


# ---------------------------------------------------------------------------
# State-aware activation destination
# ---------------------------------------------------------------------------
#
# The activation email's CTA + destination branch on
# ``user.creator_onboarded_at``:
#
#   * None      → /creator-onboarding + "Set up your Collective"
#   * timestamp → /creator-studio     + "Open Creator Studio"
#
# Sourced from the same persisted state ``purchases/routes.py::_resolve_next_url``
# uses for the Stripe-paid claim, so manual grants and paid activations
# always agree on where a Creator should land after activation.


def _email_html_for(sdk_spy) -> str:
    assert len(sdk_spy.calls) == 1, "expected exactly one Resend send"
    params, _ = sdk_spy.calls[0]
    return params["html"]


def test_fresh_creator_activation_targets_creator_onboarding(
    db, make_user, _plans, spy_and_legacy,
):
    """A never-onboarded Creator (``creator_onboarded_at is None``)
    is oriented toward setting up their first Collective. The email's
    CTA points at /creator-onboarding, which the product flows into
    /build-your-collective from."""
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    user = make_user(email=f"fresh-{uuid.uuid4().hex[:8]}@example.com")
    assert user.creator_onboarded_at is None

    result = activate_creator_plan(
        db, user, "creator",
        ActivationSource(source="stripe_paid",
                         stripe_subscription_id="sub_fresh",
                         stripe_customer_id="cus_fresh"),
    )
    db.commit()
    assert result.activation_event is not None
    assert result.activation_event.payload["is_fresh_creator"] is True
    assert result.activation_event.payload["next_url"].endswith("/creator-onboarding")

    _run_route_event_bg(db, result.activation_event.id)

    html = _email_html_for(sdk_spy)
    assert "Set up your Collective" in html
    assert "Open Creator Studio" not in html
    assert "/creator-onboarding" in html
    assert "/creator-studio" not in html


def test_onboarded_creator_activation_targets_creator_studio(
    db, make_user, _plans, spy_and_legacy,
):
    """A Creator who has already completed the creator-onboarding
    welcome (``creator_onboarded_at`` set) is pointed straight at
    Creator Studio — the empty welcome page would be a step
    backwards for someone who's already been through it."""
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    from datetime import datetime as _dt
    user = make_user(email=f"onboarded-{uuid.uuid4().hex[:8]}@example.com")
    user.creator_onboarded_at = _dt.utcnow()
    db.flush()

    result = activate_creator_plan(
        db, user, "creator",
        ActivationSource(source="stripe_paid",
                         stripe_subscription_id="sub_ob",
                         stripe_customer_id="cus_ob"),
    )
    db.commit()
    assert result.activation_event is not None
    assert result.activation_event.payload["is_fresh_creator"] is False
    assert result.activation_event.payload["next_url"].endswith("/creator-studio")

    _run_route_event_bg(db, result.activation_event.id)

    html = _email_html_for(sdk_spy)
    assert "Open Creator Studio" in html
    assert "Set up your Collective" not in html
    assert "/creator-studio" in html
    # Must not sneak /creator-onboarding into an already-onboarded user's link.
    assert "/creator-onboarding" not in html


def test_reactivation_of_onboarded_creator_still_targets_creator_studio(
    db, make_user, _plans, spy_and_legacy,
):
    """A previously-onboarded Creator whose subscription was cancelled
    and later reactivated must NOT be sent through /creator-onboarding
    again. The signal is ``creator_onboarded_at`` (persisted, permanent
    once set), not ``was_reactivated`` (which describes Stripe
    lifecycle)."""
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    from datetime import datetime as _dt, timedelta as _td
    user = make_user(email=f"reonb-{uuid.uuid4().hex[:8]}@example.com")
    user.creator_onboarded_at = _dt.utcnow() - _td(days=90)
    db.flush()

    first = activate_creator_plan(
        db, user, "creator",
        ActivationSource(source="stripe_paid",
                         stripe_subscription_id="sub_r1",
                         stripe_customer_id="cus_r1"),
    )
    db.commit()
    _run_route_event_bg(db, first.activation_event.id)
    assert len(sdk_spy.calls) == 1
    first.subscription.status = CreatorSubscriptionStatus.cancelled
    db.flush()
    db.commit()

    later = first.subscription.starts_at + _td(days=30)
    second = activate_creator_plan(
        db, user, "creator",
        ActivationSource(source="stripe_paid",
                         stripe_subscription_id="sub_r1",
                         stripe_customer_id="cus_r1",
                         starts_at=later),
    )
    db.commit()
    assert second.was_reactivated is True
    assert second.activation_event is not None
    # was_reactivated=True but persisted onboarding is complete → CS path.
    assert second.activation_event.payload["is_fresh_creator"] is False
    assert second.activation_event.payload["next_url"].endswith("/creator-studio")

    _run_route_event_bg(db, second.activation_event.id)
    # Two sends across both activations. Inspect the second's HTML.
    assert len(sdk_spy.calls) == 2
    second_html = sdk_spy.calls[1][0]["html"]
    assert "Open Creator Studio" in second_html
    assert "Set up your Collective" not in second_html


def test_manual_grant_uses_same_state_aware_destination(
    db, make_user, _plans, spy_and_legacy,
):
    """Admin manual grant and Stripe-paid activation must agree on
    destination — both are just callers of ``activate_creator_plan``,
    which reads the persisted ``creator_onboarded_at`` once. Grant
    to a fresh Creator via ``manual_grant`` → /creator-onboarding;
    grant to an onboarded Creator via ``manual_grant`` → /creator-studio."""
    _sanity_topics_live()
    sdk_spy, _ = spy_and_legacy
    admin = make_user(role="admin")

    # Fresh Creator, manual grant → /creator-onboarding
    fresh_user = make_user(email=f"mg-fresh-{uuid.uuid4().hex[:8]}@example.com")
    fresh_result = activate_creator_plan(
        db, fresh_user, "creator",
        ActivationSource(source="manual_grant", reason="comp",
                         note="fresh manual-grant test", actor_user_id=admin.id),
    )
    db.commit()
    assert fresh_result.activation_event.payload["is_fresh_creator"] is True
    assert fresh_result.activation_event.payload["next_url"].endswith("/creator-onboarding")
    _run_route_event_bg(db, fresh_result.activation_event.id)
    fresh_html = sdk_spy.calls[0][0]["html"]
    assert "Set up your Collective" in fresh_html
    assert "/creator-onboarding" in fresh_html

    # Onboarded Creator, manual grant → /creator-studio
    from datetime import datetime as _dt
    onb_user = make_user(email=f"mg-onb-{uuid.uuid4().hex[:8]}@example.com")
    onb_user.creator_onboarded_at = _dt.utcnow()
    db.flush()
    onb_result = activate_creator_plan(
        db, onb_user, "creator",
        ActivationSource(source="manual_grant", reason="comp",
                         note="onboarded manual-grant test", actor_user_id=admin.id),
    )
    db.commit()
    assert onb_result.activation_event.payload["is_fresh_creator"] is False
    assert onb_result.activation_event.payload["next_url"].endswith("/creator-studio")
    _run_route_event_bg(db, onb_result.activation_event.id)
    onb_html = sdk_spy.calls[1][0]["html"]
    assert "Open Creator Studio" in onb_html
    assert "/creator-onboarding" not in onb_html
