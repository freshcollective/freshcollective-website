"""Tests for the M5a delivery_mode guarantee.

The core invariant: an intent with ``delivery_mode='shadow'`` is
structurally invisible to the dispatch worker, no matter its state or
scheduled_for. Flipping topics to live in some future config cannot
make previously-shadow intents eligible.
"""

from __future__ import annotations

import pytest

from app.comms.categories import (
    CATEGORY_COMMUNITY,
    Channel,
    Priority,
    Source,
    TOPIC_CONVERSATIONS,
)
from app.comms.intents import (
    ALL_DELIVERY_MODES,
    DELIVERY_MODE_LIVE,
    DELIVERY_MODE_SHADOW,
    InvalidIntentError,
    STATE_QUEUED,
    STATE_RECORDED,
    claim_next_batch,
    create_intent,
)
from app.comms.models import CommunicationIntent
from app.comms.providers import (
    ProviderHealth,
    ProviderResult,
    RenderedPayload,
    _bootstrap,
    register,
    reset_registry,
)
from app.comms.providers.base import HealthStatus, now_utc
from app.comms.worker import dispatch_due


def _base_kwargs(u) -> dict:
    return dict(
        recipient_user_id=u.id,
        recipient_address=u.email or f"{u.id}@example.test",
        source_type=Source.CREATOR,
        source_id=u.id,
        category_key=CATEGORY_COMMUNITY,
        topic_key=TOPIC_CONVERSATIONS,
        channel=Channel.EMAIL_TRANSACTIONAL,
        priority=Priority.IMMEDIATE,
        provider_key="mock",
        human_reason="You subscribed to Updates from this collective.",
        payload_subject="Test",
        payload_body_html="<p>hi</p>",
    )


class _CollectingProvider:
    def __init__(self, key: str):
        self.key = key
        self.capabilities = frozenset({"email_transactional"})
        self.production_eligible = True
        self.sent: list[RenderedPayload] = []

    def send(self, payload):
        self.sent.append(payload)
        return ProviderResult(accepted=True, provider_message_id=f"{self.key}-{len(self.sent)}")

    def health(self):
        return ProviderHealth(status=HealthStatus.HEALTHY, checked_at=now_utc())


class TestDeliveryModeCreation:
    def test_default_delivery_mode_is_live(self, db, make_user):
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        assert intent.delivery_mode == DELIVERY_MODE_LIVE

    def test_can_create_shadow_intent(self, db, make_user):
        u = make_user()
        intent = create_intent(
            db, **{**_base_kwargs(u), "delivery_mode": DELIVERY_MODE_SHADOW},
        )
        assert intent.delivery_mode == DELIVERY_MODE_SHADOW
        # Shadow intents still enter the queued state — they just
        # aren't claimable.
        assert intent.state == STATE_QUEUED

    def test_rejects_unknown_delivery_mode(self, db, make_user):
        u = make_user()
        with pytest.raises(InvalidIntentError):
            create_intent(
                db, **{**_base_kwargs(u), "delivery_mode": "test_mode"},
            )

    def test_all_delivery_modes_advertises_both(self):
        assert set(ALL_DELIVERY_MODES) == {DELIVERY_MODE_SHADOW, DELIVERY_MODE_LIVE}


class TestWorkerClaimIgnoresShadow:
    @pytest.fixture(autouse=True)
    def _isolated_registry(self):
        reset_registry()
        register(_CollectingProvider("mock"))
        yield
        reset_registry()
        _bootstrap()

    def test_shadow_intent_not_claimed(self, db, make_user):
        u = make_user()
        shadow = create_intent(
            db, **{**_base_kwargs(u), "delivery_mode": DELIVERY_MODE_SHADOW},
        )
        db.flush()
        assert claim_next_batch(db, limit=10) == []
        db.refresh(shadow)
        # Still queued — nothing touched it.
        assert shadow.state == STATE_QUEUED

    def test_only_live_intent_claimed_when_both_exist(self, db, make_user):
        u = make_user()
        shadow = create_intent(
            db, **{**_base_kwargs(u), "delivery_mode": DELIVERY_MODE_SHADOW},
        )
        live = create_intent(db, **_base_kwargs(u))
        db.flush()
        ids = claim_next_batch(db, limit=10)
        assert live.id in ids
        assert shadow.id not in ids

    def test_dispatch_due_never_delivers_shadow(self, db, make_user):
        u = make_user()
        shadow = create_intent(
            db, **{**_base_kwargs(u), "delivery_mode": DELIVERY_MODE_SHADOW},
        )
        db.flush()
        processed = dispatch_due(db, limit=10)
        assert processed == []
        # Assert nothing sent via provider
        from app.comms.providers import get
        mock = get("mock")
        assert mock.sent == []  # type: ignore[attr-defined]

    def test_shadow_intent_survives_worker_run_on_same_topic(self, db, make_user):
        """A shadow intent stays queued forever until someone deletes
        it — no worker cycle promotes it to sent regardless of state,
        scheduled_for, or the presence of live siblings.
        """
        u = make_user()
        shadow = create_intent(
            db, **{**_base_kwargs(u), "delivery_mode": DELIVERY_MODE_SHADOW},
        )
        live = create_intent(db, **_base_kwargs(u))
        db.flush()
        dispatch_due(db, limit=10)
        db.refresh(shadow)
        db.refresh(live)
        assert shadow.state == STATE_QUEUED
        assert live.state != STATE_QUEUED  # was dispatched

    def test_shadow_silent_intent_stays_recorded(self, db, make_user):
        """A shadow silent intent enters ``recorded`` at creation and
        stays there — same as live silent. The worker guard applies
        regardless of state, so this is a belt-and-braces check.
        """
        u = make_user()
        intent = create_intent(
            db,
            **{
                **_base_kwargs(u),
                "delivery_mode": DELIVERY_MODE_SHADOW,
                "priority": Priority.SILENT,
            },
        )
        db.flush()
        dispatch_due(db, limit=10)
        db.refresh(intent)
        assert intent.state == STATE_RECORDED
