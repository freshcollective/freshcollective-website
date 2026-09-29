"""The Accounts v2 webhook intake.

Signatures are generated for real — HMAC-SHA256 over ``<timestamp>.<body>``
with the v2 secret — so the tests exercise Stripe's own verification code
rather than a bypass. Only the two Stripe *re-fetches* are patched, which
is the boundary that would otherwise need a network.

The Stripe account payloads are the ones recorded from the live test-mode
probe, imported from ``test_connect_account_state`` so there is one copy of
the truth.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from app.models.creator_stripe_account import CreatorStripeAccount, OnboardingState
from app.models.webhook_event import WebhookEvent, WebhookEventOutcome
from app.services import stripe_connect_accounts as connect
from app.webhooks.connect_routes import (
    ACCOUNT_CLOSED,
    ACCOUNT_LINK_RETURNED,
    CAPABILITY_STATUS_UPDATED,
    PROVIDER,
    RECIPIENT_UPDATED,
    REQUIREMENTS_UPDATED,
)
from tests.test_connect_account_state import (
    ACCT,
    V1_AFTER,
    V1_BEFORE,
    V2_AFTER_ONBOARDING,
    V2_BEFORE_ONBOARDING,
)

ADAPTER = "app.services.stripe_connect_accounts"
SECRET = "whsec_test_v2_secret_for_unit_tests"
ENDPOINT = "/api/webhooks/stripe/v2"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _v2_secret(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "stripe_v2_webhook_secret", SECRET)
    # Mode is asserted against the event's livemode flag, so pin it.
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy_for_tests")


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from app.core.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _thin(
    event_type: str,
    *,
    account_id: str | None = ACCT,
    event_id: str | None = None,
    livemode: bool = False,
) -> dict:
    """A thin event notification in Stripe's delivered shape.

    Note what is *not* here: any account state. That is the contract — the
    notification names an object and FC goes and reads it.
    """
    body: dict = {
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "object": "v2.core.event",
        "type": event_type,
        "created": "2026-09-29T07:30:00.000Z",
        "livemode": livemode,
        "context": None,
    }
    if event_type != ACCOUNT_LINK_RETURNED and account_id:
        body["related_object"] = {
            "id": account_id,
            "type": "v2.core.account",
            "url": f"/v2/core/accounts/{account_id}",
        }
    return body


def _sign(body: str, *, secret: str = SECRET, timestamp: int | None = None) -> str:
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.{body}"
    signature = hmac.new(
        secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256,
    ).hexdigest()
    return f"t={ts},v1={signature}"


def _post(client, body: dict, *, secret: str = SECRET, header: str | None = None):
    raw = json.dumps(body)
    return client.post(
        ENDPOINT,
        content=raw,
        headers={
            "stripe-signature": header if header is not None else _sign(raw, secret=secret),
            "content-type": "application/json",
        },
    )


def _row(db, creator_id, **overrides) -> CreatorStripeAccount:
    values = {
        "id": f"csa_{uuid.uuid4()}",
        "creator_user_id": creator_id,
        "stripe_mode": "test",
        "stripe_account_id": ACCT,
        "onboarding_state": OnboardingState.onboarding.value,
    }
    values.update(overrides)
    row = CreatorStripeAccount(**values)
    db.add(row)
    db.commit()
    return row


def _ready_row(db, creator_id, **overrides) -> CreatorStripeAccount:
    return _row(
        db, creator_id,
        onboarding_state=OnboardingState.ready.value,
        transfers_status="active", transfers_enabled=True,
        payouts_status="active", payouts_enabled=True,
        details_submitted=True, external_account_count=1,
        payout_interval="daily", payout_delay_days=2,
        **overrides,
    )


def _event_rows(db, event_id: str):
    return (
        db.query(WebhookEvent)
        .filter(
            WebhookEvent.provider == PROVIDER,
            WebhookEvent.provider_event_id == event_id,
        )
        .all()
    )


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


class TestSignature:
    def test_a_valid_signature_is_accepted(self, client, db, make_user):
        _row(db, make_user(role="creator").id)
        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_BEFORE_ONBOARDING), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_BEFORE):
            r = _post(client, _thin(REQUIREMENTS_UPDATED))
        assert r.status_code == 200
        assert r.json()["received"] is True

    def test_a_wrong_secret_is_rejected(self, client):
        r = _post(client, _thin(REQUIREMENTS_UPDATED), secret="whsec_the_wrong_one")
        assert r.status_code == 400
        assert "signature" in r.json()["detail"].lower()

    def test_a_missing_signature_header_is_rejected(self, client):
        r = _post(client, _thin(REQUIREMENTS_UPDATED), header="")
        assert r.status_code == 400

    def test_a_tampered_body_is_rejected(self, client):
        body = _thin(REQUIREMENTS_UPDATED)
        raw = json.dumps(body)
        header = _sign(raw)
        tampered = json.dumps({**body, "livemode": True})
        r = client.post(
            ENDPOINT, content=tampered,
            headers={"stripe-signature": header, "content-type": "application/json"},
        )
        assert r.status_code == 400

    def test_an_expired_timestamp_is_rejected(self, client):
        body = _thin(REQUIREMENTS_UPDATED)
        raw = json.dumps(body)
        old = int(time.time()) - 60 * 60 * 24
        r = client.post(
            ENDPOINT, content=raw,
            headers={
                "stripe-signature": _sign(raw, timestamp=old),
                "content-type": "application/json",
            },
        )
        assert r.status_code == 400

    def test_a_v1_webhook_payload_sent_here_is_refused(self, client, db, make_user):
        """Guards against the two endpoints being crossed in configuration:
        a v1 body has ``object: "event"``, and the SDK refuses it."""
        _row(db, make_user(role="creator").id)
        v1_body = {
            "id": "evt_v1_shaped",
            "object": "event",
            "type": "checkout.session.completed",
            "created": 1790000000,
            "livemode": False,
            "data": {"object": {"id": "cs_123"}},
        }
        r = _post(client, v1_body)
        assert r.status_code == 400

    def test_the_intake_refuses_when_its_own_secret_is_unset(
        self, client, monkeypatch,
    ):
        """503, not 200: an unconfigured environment must not look like a
        working one in Stripe's delivery log."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "stripe_v2_webhook_secret", None)
        r = _post(client, _thin(REQUIREMENTS_UPDATED))
        assert r.status_code == 503

    def test_the_v1_secret_does_not_work_on_the_v2_endpoint(
        self, client, monkeypatch,
    ):
        """The two secrets are separate so a rotation on either side cannot
        silently break the other."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_v1_only")
        r = _post(client, _thin(REQUIREMENTS_UPDATED), secret="whsec_v1_only")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# The thin payload is a doorbell, not a status report
# ---------------------------------------------------------------------------


class TestThinPayloadIsNotState:
    def test_both_objects_are_refetched_before_anything_is_written(
        self, client, db, make_user,
    ):
        row = _row(db, make_user(role="creator").id)
        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING) as v2, \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER) as v1:
            r = _post(client, _thin(CAPABILITY_STATUS_UPDATED))

        assert r.status_code == 200
        assert v2.call_count == 1
        assert v1.call_count == 1
        assert v2.call_args.args[0] == ACCT
        assert v1.call_args.args[0] == ACCT

        db.refresh(row)
        assert row.onboarding_state == OnboardingState.ready.value
        assert row.last_sync_source == "webhook"
        assert row.last_synced_at is not None

    def test_state_embedded_in_the_payload_is_ignored(self, client, db, make_user):
        """A notification claiming everything is fine must not be able to
        make FC believe it — the fetched objects decide."""
        row = _row(db, make_user(role="creator").id)
        body = _thin(CAPABILITY_STATUS_UPDATED)
        body["data"] = {
            "updated_capability": "stripe_balance.stripe_transfers",
            # Deliberately contradicting what Stripe will actually return.
            "status": "active",
            "payouts_enabled": True,
        }
        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_BEFORE_ONBOARDING), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_BEFORE):
            r = _post(client, body)

        assert r.status_code == 200
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.onboarding.value
        assert row.transfers_enabled is False
        assert row.payouts_enabled is False


# ---------------------------------------------------------------------------
# Event coverage
# ---------------------------------------------------------------------------


class TestEventTypes:
    @pytest.mark.parametrize("event_type", [
        CAPABILITY_STATUS_UPDATED, REQUIREMENTS_UPDATED, RECIPIENT_UPDATED,
    ])
    def test_account_events_carry_the_id_on_the_thin_notification(
        self, client, db, make_user, event_type,
    ):
        row = _row(db, make_user(role="creator").id)
        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            r = _post(client, _thin(event_type))
        assert r.status_code == 200
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.ready.value

    def test_capability_event_moves_onboarding_to_ready(self, client, db, make_user):
        row = _row(
            db, make_user(role="creator").id,
            onboarding_state=OnboardingState.onboarding.value,
        )
        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            _post(client, _thin(CAPABILITY_STATUS_UPDATED))
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.ready.value
        assert row.transfers_enabled is True
        assert row.payouts_enabled is True
        assert row.external_account_count == 1

    def test_capability_event_moves_restricted_to_ready(self, client, db, make_user):
        row = _row(
            db, make_user(role="creator").id,
            onboarding_state=OnboardingState.restricted.value,
            transfers_status="restricted", payouts_status="restricted",
        )
        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            _post(client, _thin(CAPABILITY_STATUS_UPDATED))
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.ready.value

    def test_requirements_event_moves_ready_back_to_action_required(
        self, client, db, make_user,
    ):
        """Stripe coming back for more after a creator was live."""
        row = _ready_row(db, make_user(role="creator").id)
        regressed = {
            **V2_AFTER_ONBOARDING,
            "configuration": {
                "recipient": {
                    "applied": True,
                    "capabilities": {
                        "stripe_balance": {
                            "stripe_transfers": {
                                "status": "restricted",
                                "status_details": [{
                                    "code": "requirements_past_due",
                                    "resolution": "provide_info",
                                }],
                            },
                            "payouts": {
                                "status": "restricted",
                                "status_details": [{
                                    "code": "requirements_past_due",
                                    "resolution": "provide_info",
                                }],
                            },
                        },
                    },
                },
            },
            "requirements": {
                "entries": [{
                    "description": "identity.individual.verification.document",
                    "awaiting_action_from": "user",
                    "errors": [],
                    "impact": {"restricts_capabilities": [
                        {"capability": "stripe_balance.stripe_transfers",
                         "configuration": "recipient",
                         "deadline": {"status": "currently_due"}},
                    ]},
                    "minimum_deadline": {"status": "currently_due"},
                }],
                "summary": {"minimum_deadline": {"status": "currently_due", "time": None}},
            },
        }
        with patch(f"{ADAPTER}.retrieve_account", return_value=regressed), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            _post(client, _thin(REQUIREMENTS_UPDATED))

        db.refresh(row)
        assert row.onboarding_state == OnboardingState.action_required.value
        assert row.transfers_enabled is False

    def test_requirements_event_can_move_ready_to_verifying(
        self, client, db, make_user,
    ):
        row = _ready_row(db, make_user(role="creator").id)
        verifying = {
            **V2_AFTER_ONBOARDING,
            "configuration": {
                "recipient": {
                    "applied": True,
                    "capabilities": {
                        "stripe_balance": {
                            "stripe_transfers": {
                                "status": "restricted",
                                "status_details": [{
                                    "code": "requirements_pending_verification",
                                    "resolution": "provide_info",
                                }],
                            },
                            "payouts": {"status": "pending", "status_details": []},
                        },
                    },
                },
            },
            "requirements": {"entries": [], "summary": None},
        }
        with patch(f"{ADAPTER}.retrieve_account", return_value=verifying), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            _post(client, _thin(REQUIREMENTS_UPDATED))
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.verifying.value

    def test_closure_event_projects_closed(self, client, db, make_user):
        row = _ready_row(db, make_user(role="creator").id)
        with patch(f"{ADAPTER}.retrieve_account",
                   return_value={**V2_AFTER_ONBOARDING, "closed": True}), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            r = _post(client, _thin(ACCOUNT_CLOSED))
        assert r.status_code == 200
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.closed.value

    def test_account_link_returned_fetches_the_event_for_its_account_id(
        self, client, db, make_user,
    ):
        """This notification has no ``related_object`` — the account id lives
        on the full event as ``data.account_id``, so it costs a fetch."""
        row = _row(db, make_user(role="creator").id)

        class _Data:
            account_id = ACCT

        class _Event:
            data = _Data()

        with patch("stripe.v2.core.EventNotification.fetch_event", return_value=_Event()), \
             patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            r = _post(client, _thin(ACCOUNT_LINK_RETURNED))

        assert r.status_code == 200
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.ready.value

    def test_account_link_returned_is_retryable_when_the_event_fetch_fails(
        self, client, db, make_user,
    ):
        import stripe
        row = _ready_row(db, make_user(role="creator").id)
        with patch("stripe.v2.core.EventNotification.fetch_event",
                   side_effect=stripe.APIConnectionError("no route")):
            r = _post(client, _thin(ACCOUNT_LINK_RETURNED))
        assert r.status_code == 503
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.ready.value

    def test_an_unsupported_event_type_is_recorded_and_acknowledged(
        self, client, db, make_user,
    ):
        _row(db, make_user(role="creator").id)
        event = _thin("v2.core.account[identity].updated")
        with patch(f"{ADAPTER}.retrieve_account") as v2:
            r = _post(client, event)
        assert r.status_code == 200
        assert r.json()["handled"] is False
        assert v2.call_count == 0
        rows = _event_rows(db, event["id"])
        assert len(rows) == 1
        assert rows[0].outcome == WebhookEventOutcome.skipped


# ---------------------------------------------------------------------------
# Unknown accounts and mode safety
# ---------------------------------------------------------------------------


class TestUnknownAndMode:
    def test_an_unknown_account_is_skipped_deliberately(self, client, db):
        """Terminal on purpose: retrying for days cannot make FC aware of an
        account it never created."""
        event = _thin(CAPABILITY_STATUS_UPDATED, account_id="acct_neverSeen")
        with patch(f"{ADAPTER}.retrieve_account") as v2, \
             patch(f"{ADAPTER}.retrieve_legacy_account") as v1:
            r = _post(client, event)

        assert r.status_code == 200
        assert v2.call_count == 0 and v1.call_count == 0
        rows = _event_rows(db, event["id"])
        assert len(rows) == 1
        assert rows[0].outcome == WebhookEventOutcome.skipped
        assert "acct_neverSeen" in (rows[0].error_message or "")

    def test_a_livemode_event_is_skipped_in_a_test_environment(
        self, client, db, make_user,
    ):
        row = _ready_row(db, make_user(role="creator").id)
        event = _thin(CAPABILITY_STATUS_UPDATED, livemode=True)
        with patch(f"{ADAPTER}.retrieve_account") as v2:
            r = _post(client, event)
        assert r.status_code == 200
        assert v2.call_count == 0
        assert _event_rows(db, event["id"])[0].outcome == WebhookEventOutcome.skipped
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.ready.value

    def test_a_live_mode_row_is_not_matched_by_a_test_mode_event(self, client, db, make_user):
        _row(
            db, make_user(role="creator").id, stripe_mode="live",
            stripe_account_id="acct_liveOnly",
        )
        event = _thin(CAPABILITY_STATUS_UPDATED, account_id="acct_liveOnly")
        with patch(f"{ADAPTER}.retrieve_account") as v2:
            r = _post(client, event)
        assert r.status_code == 200
        assert v2.call_count == 0
        assert _event_rows(db, event["id"])[0].outcome == WebhookEventOutcome.skipped


# ---------------------------------------------------------------------------
# Retryable failures
# ---------------------------------------------------------------------------


class TestRetryable:
    """How "nothing was written" is asserted here.

    ``process_webhook_event`` calls ``db.rollback()`` before marking a row
    ``failed``, which is right in production — the row it protects was
    committed in an earlier transaction — but in these tests every write
    lives inside the fixture's SAVEPOINT, so that rollback also discards
    the seeded row. Reading it back afterwards would therefore prove
    nothing either way.

    So the invariant is asserted at its source instead: if the projection
    service was never invoked, no projected field can have been written.
    That is a stronger claim than an unchanged row, and it holds regardless
    of transaction scoping. The row-level "a good state survives a
    retryable failure" assertion lives in ``test_connect_routes.py``, where
    no rollback intervenes.
    """

    def test_a_v2_fetch_failure_is_non_2xx_and_writes_nothing(
        self, client, db, make_user,
    ):
        _ready_row(db, make_user(role="creator").id)
        event = _thin(CAPABILITY_STATUS_UPDATED)
        with patch("app.services.connect_account_state.project") as project, \
             patch(f"{ADAPTER}.retrieve_legacy_account") as v1, \
             patch(f"{ADAPTER}.retrieve_account",
                   side_effect=connect.ConnectUnavailable("v2 timed out")):
            r = _post(client, event)

        assert r.status_code == 503
        # Nothing further was attempted, and nothing was projected.
        assert v1.call_count == 0
        assert project.call_count == 0

    def test_a_v1_fetch_failure_is_non_2xx_and_writes_nothing(
        self, client, db, make_user,
    ):
        """v2 answered and v1 did not. The row must describe one moment or
        none of it — so the projection must not run on half the evidence."""
        _row(
            db, make_user(role="creator").id,
            onboarding_state=OnboardingState.onboarding.value,
        )
        event = _thin(CAPABILITY_STATUS_UPDATED)
        with patch("app.services.connect_account_state.project") as project, \
             patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING), \
             patch(f"{ADAPTER}.retrieve_legacy_account",
                   side_effect=connect.ConnectUnavailable("v1 timed out")):
            r = _post(client, event)

        assert r.status_code == 503
        assert project.call_count == 0

    def test_a_refused_refetch_is_terminal_not_retried(self, client, db, make_user):
        """Stripe decided. The identical request gets the identical answer,
        so redelivering for days achieves nothing."""
        row = _ready_row(db, make_user(role="creator").id)
        event = _thin(CAPABILITY_STATUS_UPDATED)
        with patch(f"{ADAPTER}.retrieve_account",
                   side_effect=connect.ConnectRejected("refused", code="x")):
            r = _post(client, event)

        assert r.status_code == 200
        assert _event_rows(db, event["id"])[0].outcome == WebhookEventOutcome.skipped
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.ready.value
        assert "refused" in (row.last_error_message or "")

    def test_account_not_found_on_refetch_keeps_the_projection(
        self, client, db, make_user,
    ):
        row = _ready_row(db, make_user(role="creator").id)
        event = _thin(CAPABILITY_STATUS_UPDATED)
        with patch(f"{ADAPTER}.retrieve_account",
                   side_effect=connect.ConnectAccountNotFound("No such account")):
            r = _post(client, event)

        assert r.status_code == 200
        assert _event_rows(db, event["id"])[0].outcome == WebhookEventOutcome.skipped
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.ready.value
        assert row.transfers_enabled is True


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_a_duplicate_event_id_processes_once(self, client, db, make_user):
        row = _row(db, make_user(role="creator").id)
        event = _thin(CAPABILITY_STATUS_UPDATED)

        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING) as v2, \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            first = _post(client, event)
            second = _post(client, event)

        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["handled"] is True
        assert second.json()["handled"] is False
        assert v2.call_count == 1

        rows = _event_rows(db, event["id"])
        assert len(rows) == 1
        assert rows[0].outcome == WebhookEventOutcome.succeeded
        db.refresh(row)
        assert row.onboarding_state == OnboardingState.ready.value

    def test_distinct_event_ids_both_process(self, client, db, make_user):
        _row(db, make_user(role="creator").id)
        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING) as v2, \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            _post(client, _thin(CAPABILITY_STATUS_UPDATED))
            _post(client, _thin(REQUIREMENTS_UPDATED))
        assert v2.call_count == 2

    def test_the_provider_is_stripe_v2_so_ids_cannot_collide_with_v1(
        self, client, db, make_user,
    ):
        _row(db, make_user(role="creator").id)
        shared_id = f"evt_{uuid.uuid4().hex}"
        db.add(WebhookEvent(
            id=f"whe_{uuid.uuid4()}",
            provider="stripe",
            provider_event_id=shared_id,
            event_type="checkout.session.completed",
            outcome=WebhookEventOutcome.succeeded,
            received_at=datetime.utcnow(),
        ))
        db.commit()

        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING) as v2, \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            r = _post(client, _thin(CAPABILITY_STATUS_UPDATED, event_id=shared_id))

        # The v1 row with the same id must not make this look handled.
        assert r.status_code == 200
        assert v2.call_count == 1
        assert len(_event_rows(db, shared_id)) == 1


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_the_webhook_never_changes_connect_payouts_enabled_at(
    client, db, make_user,
):
    """Including on the event that takes a creator all the way to ready."""
    row = _row(db, make_user(role="creator").id)
    assert row.connect_payouts_enabled_at is None

    with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING), \
         patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
        _post(client, _thin(CAPABILITY_STATUS_UPDATED))
        _post(client, _thin(REQUIREMENTS_UPDATED))
        _post(client, _thin(RECIPIENT_UPDATED))

    db.refresh(row)
    assert row.onboarding_state == OnboardingState.ready.value
    assert row.payouts_enabled is True
    assert row.connect_payouts_enabled_at is None


def test_an_already_enabled_creator_is_not_disturbed_by_a_sync(
    client, db, make_user,
):
    """If routing were ever on, a webhook must not switch it off either."""
    enabled_at = datetime(2026, 9, 29, 12, 0, 0)
    row = _ready_row(db, make_user(role="creator").id)
    row.connect_payouts_enabled_at = enabled_at
    db.commit()

    with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING), \
         patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
        _post(client, _thin(RECIPIENT_UPDATED))

    db.refresh(row)
    assert row.connect_payouts_enabled_at == enabled_at


# ---------------------------------------------------------------------------
# Event names, against the SDK rather than this module
# ---------------------------------------------------------------------------


def test_every_subscribed_event_name_exists_in_the_sdk():
    """If Stripe renames one, this fails rather than FC silently
    subscribing to nothing."""
    from stripe.events._event_classes import get_v2_event_notification_class
    from stripe.v2.core._event import UnknownEventNotification

    from app.webhooks.connect_routes import SUPPORTED_EVENTS

    for name in SUPPORTED_EVENTS:
        klass = get_v2_event_notification_class(name)
        assert klass is not UnknownEventNotification, f"SDK does not know {name}"
        assert klass.LOOKUP_TYPE == name
