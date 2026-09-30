"""The creator-facing Connect endpoints, tested for behaviour not shape.

Stripe is patched at the adapter boundary — the module-level functions in
``stripe_connect_accounts`` — rather than at the SDK, so these tests
exercise the real route logic, the real projection and the real database
constraints while never touching the network.

The Stripe payloads reused here are the ones recorded from the live
test-mode probe, imported from ``test_connect_account_state`` so there is
one copy of the truth.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from app.models.creator_stripe_account import CreatorStripeAccount, OnboardingState
from app.services import stripe_connect_accounts as connect
from tests.test_connect_enablement import ACCT as CONNECT_ACCT
from tests.test_connect_enablement import _connect_txn
from tests.test_connect_account_state import (
    ACCT,
    V1_AFTER,
    V1_BEFORE,
    V2_AFTER_ONBOARDING,
    V2_BEFORE_ONBOARDING,
)

ADAPTER = "app.services.stripe_connect_accounts"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db):
    """A TestClient whose DB session is the test's own transaction."""
    from fastapi.testclient import TestClient
    from app.core.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def as_creator(client, make_user):
    """Authenticate as a creator, however this app does it."""
    from app.auth.dependencies import get_creator_user, get_current_user
    from app.main import app

    creator = make_user(role="creator")
    app.dependency_overrides[get_creator_user] = lambda: creator
    app.dependency_overrides[get_current_user] = lambda: creator
    yield creator
    app.dependency_overrides.pop(get_creator_user, None)
    app.dependency_overrides.pop(get_current_user, None)


def _row(db, creator_id, **overrides) -> CreatorStripeAccount:
    values = {
        "id": f"csa_{uuid.uuid4()}",
        "creator_user_id": creator_id,
        "stripe_mode": "test",
        "onboarding_state": OnboardingState.not_started.value,
    }
    values.update(overrides)
    row = CreatorStripeAccount(**values)
    db.add(row)
    db.commit()
    return row


def _created_account(account_id: str = ACCT) -> dict:
    return {**V2_BEFORE_ONBOARDING, "id": account_id}


# ---------------------------------------------------------------------------
# POST /account
# ---------------------------------------------------------------------------


class TestCreateAccount:
    def test_creates_once_and_persists_the_projection(self, client, as_creator, db):
        with patch(f"{ADAPTER}.create_recipient_account", return_value=_created_account()) as create, \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_BEFORE):
            r = client.post("/api/creator/stripe-connect/account")

        assert r.status_code == 200
        body = r.json()
        assert body["connected"] is True
        assert body["stripe_account_id"] == ACCT
        assert body["state"] == OnboardingState.onboarding.value
        assert body["transfers_status"] == "restricted"
        assert body["payout_interval"] == "daily"
        assert create.call_count == 1

        rows = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).all()
        assert len(rows) == 1
        assert rows[0].stripe_account_id == ACCT

    def test_second_call_returns_the_same_account_without_calling_stripe(
        self, client, as_creator, db,
    ):
        """Creating a duplicate connected account is not something FC could
        cleanly undo, and a creator double-clicking is the normal case."""
        with patch(f"{ADAPTER}.create_recipient_account", return_value=_created_account()), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_BEFORE):
            first = client.post("/api/creator/stripe-connect/account")

        with patch(f"{ADAPTER}.create_recipient_account") as create, \
             patch(f"{ADAPTER}.retrieve_legacy_account") as legacy:
            second = client.post("/api/creator/stripe-connect/account")

        assert create.call_count == 0
        assert legacy.call_count == 0
        assert second.json()["stripe_account_id"] == first.json()["stripe_account_id"]
        assert db.query(CreatorStripeAccount).filter_by(
            creator_user_id=as_creator.id,
        ).count() == 1

    def test_keeps_the_account_id_when_the_first_projection_read_fails(
        self, client, as_creator, db,
    ):
        """The account exists at Stripe. Losing its id would orphan it and
        then the unique constraint would block ever creating another."""
        with patch(f"{ADAPTER}.create_recipient_account", return_value=_created_account()), \
             patch(f"{ADAPTER}.retrieve_legacy_account",
                   side_effect=connect.ConnectUnavailable("timeout")):
            r = client.post("/api/creator/stripe-connect/account")

        assert r.status_code == 200
        row = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).one()
        assert row.stripe_account_id == ACCT
        assert "timeout" in (row.last_error_message or "")
        # Unprojected, not misprojected.
        assert row.transfers_status is None
        assert row.transfers_enabled is False

    def test_retryable_create_failure_is_503_and_creates_nothing(
        self, client, as_creator, db,
    ):
        with patch(f"{ADAPTER}.create_recipient_account",
                   side_effect=connect.ConnectUnavailable("Stripe unreachable")):
            r = client.post("/api/creator/stripe-connect/account")

        assert r.status_code == 503
        row = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).one()
        assert row.stripe_account_id is None
        assert row.last_error_message is not None

    def test_rejected_create_is_502(self, client, as_creator):
        with patch(f"{ADAPTER}.create_recipient_account",
                   side_effect=connect.ConnectRejected("bad config", code="url_invalid")):
            r = client.post("/api/creator/stripe-connect/account")
        assert r.status_code == 502

    def test_never_enables_routing(self, client, as_creator, db):
        with patch(f"{ADAPTER}.create_recipient_account", return_value=_created_account()), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            r = client.post("/api/creator/stripe-connect/account")

        assert r.json()["connect_routing_enabled"] is False
        row = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).one()
        assert row.connect_payouts_enabled_at is None


class TestBusinessUrl:
    def _create(self, client):
        with patch(f"{ADAPTER}.create_recipient_account",
                   return_value=_created_account()) as create, \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_BEFORE):
            client.post("/api/creator/stripe-connect/account")
        return create.call_args.kwargs

    def test_included_when_the_creator_has_a_collective_on_a_public_host(
        self, client, as_creator, make_space, monkeypatch,
    ):
        from app.core.config import settings
        space = make_space(creator=as_creator)
        monkeypatch.setattr(settings, "public_app_url", "https://freshcollective.com.au")

        kwargs = self._create(client)
        assert kwargs["business_url"] == (
            f"https://freshcollective.com.au/spaces/{space.slug}"
        )

    def test_omitted_when_the_creator_has_no_collective(
        self, client, as_creator, monkeypatch,
    ):
        from app.core.config import settings
        monkeypatch.setattr(settings, "public_app_url", "https://freshcollective.com.au")
        assert self._create(client)["business_url"] is None

    def test_omitted_on_a_local_host_rather_than_invented(
        self, client, as_creator, make_space, monkeypatch,
    ):
        """Stripe validates this field — it refuses ``example.com`` as
        ``url_invalid`` — so a placeholder would turn a helpful prefill into
        a failed account create."""
        from app.core.config import settings
        make_space(creator=as_creator)
        monkeypatch.setattr(settings, "public_app_url", "http://localhost:3000")
        assert self._create(client)["business_url"] is None

    def test_omitted_for_example_com(self, client, as_creator, make_space, monkeypatch):
        from app.core.config import settings
        make_space(creator=as_creator)
        monkeypatch.setattr(settings, "public_app_url", "https://example.com")
        assert self._create(client)["business_url"] is None


class TestAccountConfiguration:
    def test_uses_the_verified_configuration(self, client, as_creator):
        """recipient + express + application/application is one decision,
        not three: Stripe rejects any other combination with an express
        dashboard."""
        captured = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return _created_account()

        with patch(f"{ADAPTER}.create_recipient_account", side_effect=fake_create), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_BEFORE):
            client.post("/api/creator/stripe-connect/account")

        assert captured["country"] == "AU"
        assert captured["contact_email"] == as_creator.email

    def test_adapter_builds_the_verified_params(self):
        """Asserted against the adapter itself, since the configuration is
        the thing Stripe validates."""
        sent = {}

        class _Accounts:
            def create(self, params):
                sent.update(params)
                return _created_account()

        class _Core:
            accounts = _Accounts()

        class _V2:
            core = _Core()

        class _Client:
            v2 = _V2()

        with patch(f"{ADAPTER}.get_stripe_client", return_value=_Client()):
            connect.create_recipient_account(
                display_name="A Creator", contact_email="c@example.com",
                country="AU", business_url="https://freshcollective.com.au/spaces/x",
            )

        assert sent["dashboard"] == "express"
        assert sent["defaults"]["responsibilities"] == {
            "fees_collector": "application",
            "losses_collector": "application",
        }
        # Left to Stripe on purpose — express implies it, and setting it
        # would claim a responsibility FC has not acknowledged.
        assert "requirements_collector" not in sent["defaults"]["responsibilities"]
        assert sent["configuration"]["recipient"]["capabilities"] == {
            "stripe_balance": {"stripe_transfers": {"requested": True}},
        }
        assert sent["defaults"]["profile"]["business_url"].startswith("https://")
        assert "configuration.recipient" in sent["include"]
        assert "requirements" in sent["include"]

    def test_adapter_omits_the_profile_when_there_is_no_url(self):
        sent = {}

        class _Accounts:
            def create(self, params):
                sent.update(params)
                return _created_account()

        class _Core:
            accounts = _Accounts()

        class _V2:
            core = _Core()

        class _Client:
            v2 = _V2()

        with patch(f"{ADAPTER}.get_stripe_client", return_value=_Client()):
            connect.create_recipient_account(
                display_name="A Creator", contact_email=None,
                country="AU", business_url=None,
            )
        assert "profile" not in sent["defaults"]
        assert "contact_email" not in sent


# ---------------------------------------------------------------------------
# Serialising what the SDK actually returns
# ---------------------------------------------------------------------------


def _as_stripe_object(payload: dict, cls=None):
    """The recorded payload as the SDK would hand it back.

    Every other test in this file stubs Stripe with plain dicts, which is
    why a serialisation bug could reach production: ``_to_dict`` was only
    ever given values that were already dicts. These tests give it the
    real thing.
    """
    from stripe.v2.core._account import Account

    cls = cls or Account
    return cls._construct_from(values=payload, requestor=None, api_mode="V2")


class TestStripeObjectSerialisation:
    """A creator clicking Connect Stripe got a 500: ``dict(account)`` on a
    v2 ``StripeObject`` raises ``KeyError: 0``, because the object is not a
    mapping and ``dict()`` falls back to indexing it as a sequence."""

    def test_create_returns_a_plain_dict_from_a_stripe_object(self):
        account_object = _as_stripe_object(_created_account())

        class _Accounts:
            def create(self, params):
                return account_object

        class _Core:
            accounts = _Accounts()

        class _V2:
            core = _Core()

        class _Client:
            v2 = _V2()

        with patch(f"{ADAPTER}.get_stripe_client", return_value=_Client()):
            result = connect.create_recipient_account(
                display_name="A Creator", contact_email="c@example.com",
                country="AU", business_url=None,
            )

        assert type(result) is dict
        assert result["id"] == ACCT
        assert result == _created_account()

    def test_conversion_reaches_the_nested_objects_too(self):
        """A shallow copy would leave StripeObjects one level down, and the
        projection reads capability statuses and requirement entries."""
        converted = connect._to_dict(_as_stripe_object(_created_account()))

        def assert_plain(value, path):
            assert not hasattr(value, "_data"), f"StripeObject survived at {path}"
            if isinstance(value, dict):
                for key, item in value.items():
                    assert_plain(item, f"{path}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    assert_plain(item, f"{path}[{index}]")

        assert_plain(converted, "account")
        recipient = converted["configuration"]["recipient"]
        assert type(recipient["capabilities"]) is dict

    def test_the_whole_create_endpoint_survives_a_real_stripe_object(
        self, client, as_creator, db,
    ):
        """The production path end to end: the adapter is not patched, so
        the account the route projects is the one the SDK would return."""
        account_object = _as_stripe_object(_created_account())

        class _Accounts:
            def create(self, params):
                return account_object

        class _Core:
            accounts = _Accounts()

        class _V2:
            core = _Core()

        class _Client:
            v2 = _V2()

        with patch(f"{ADAPTER}.get_stripe_client", return_value=_Client()), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_BEFORE):
            r = client.post("/api/creator/stripe-connect/account")

        assert r.status_code == 200, r.text
        assert r.json()["stripe_account_id"] == ACCT
        assert r.json()["transfers_status"] == "restricted"

        rows = db.query(CreatorStripeAccount).filter_by(
            creator_user_id=as_creator.id,
        ).all()
        assert len(rows) == 1
        assert rows[0].stripe_account_id == ACCT

    def test_an_ordinary_dict_is_returned_unchanged(self):
        """Every existing caller and fixture passes a plain dict."""
        payload = _created_account()
        assert connect._to_dict(payload) is payload

    def test_none_is_an_empty_dict(self):
        assert connect._to_dict(None) == {}

    def test_something_unreadable_is_a_connect_failure_not_a_key_error(self):
        """The old guard caught TypeError and ValueError only, so the
        KeyError went straight out as a 500."""

        class _Opaque:
            def __getitem__(self, key):
                raise KeyError(key)

        with pytest.raises(connect.ConnectUnavailable):
            connect._to_dict(_Opaque())


# ---------------------------------------------------------------------------
# POST /onboarding-link
# ---------------------------------------------------------------------------


class TestOnboardingLink:
    def test_mints_a_fresh_link_every_call_and_stores_none_of_it(
        self, client, as_creator, db,
    ):
        _row(db, as_creator.id, stripe_account_id=ACCT)
        urls = iter(["https://connect.stripe.com/setup/e/one",
                     "https://connect.stripe.com/setup/e/two"])

        with patch(f"{ADAPTER}.create_onboarding_link",
                   side_effect=lambda **_: next(urls)) as mint:
            first = client.post("/api/creator/stripe-connect/onboarding-link")
            second = client.post("/api/creator/stripe-connect/onboarding-link")

        assert mint.call_count == 2
        assert first.json()["url"] != second.json()["url"]
        assert first.json()["expires_in_seconds"] == 300

        row = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).one()
        assert row.account_link_count == 2
        assert row.last_account_link_created_at is not None
        # The URL appears nowhere on the row — a cached link is dead within
        # five minutes, and a dead link is worse than asking again.
        stored = {
            c.name: getattr(row, c.name) for c in row.__table__.columns
        }
        assert not any(
            isinstance(v, str) and "connect.stripe.com" in v for v in stored.values()
        )

    def test_uses_the_update_link_once_details_are_submitted(
        self, client, as_creator, db,
    ):
        """A creator who already submitted needs re-collection, which is a
        different Stripe use case."""
        _row(
            db, as_creator.id, stripe_account_id=ACCT, details_submitted=True,
            onboarding_state=OnboardingState.action_required.value,
        )
        with patch(f"{ADAPTER}.create_update_link", return_value="https://x/update") as update, \
             patch(f"{ADAPTER}.create_onboarding_link") as onboarding:
            r = client.post("/api/creator/stripe-connect/onboarding-link")

        assert r.status_code == 200
        assert update.call_count == 1
        assert onboarding.call_count == 0

    def test_refuses_before_an_account_exists(self, client, as_creator):
        r = client.post("/api/creator/stripe-connect/onboarding-link")
        assert r.status_code == 409

    def test_refuses_for_a_closed_account(self, client, as_creator, db):
        _row(
            db, as_creator.id, stripe_account_id=ACCT,
            onboarding_state=OnboardingState.closed.value,
        )
        with patch(f"{ADAPTER}.create_onboarding_link") as mint:
            r = client.post("/api/creator/stripe-connect/onboarding-link")
        assert r.status_code == 409
        assert mint.call_count == 0

    def test_a_closed_account_reported_by_stripe_is_409(self, client, as_creator, db):
        _row(db, as_creator.id, stripe_account_id=ACCT)
        with patch(f"{ADAPTER}.create_onboarding_link",
                   side_effect=connect.ConnectAccountClosed("closed")):
            r = client.post("/api/creator/stripe-connect/onboarding-link")
        assert r.status_code == 409

    def test_a_link_failure_does_not_count_an_attempt(self, client, as_creator, db):
        _row(db, as_creator.id, stripe_account_id=ACCT)
        with patch(f"{ADAPTER}.create_onboarding_link",
                   side_effect=connect.ConnectUnavailable("down")):
            r = client.post("/api/creator/stripe-connect/onboarding-link")
        assert r.status_code == 503
        row = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).one()
        assert row.account_link_count == 0
        assert row.last_account_link_created_at is None


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_is_database_only(self, client, as_creator, db):
        """A page view must not fail because Stripe is slow, and must not
        rewrite state as a side effect."""
        _row(
            db, as_creator.id, stripe_account_id=ACCT,
            onboarding_state=OnboardingState.ready.value,
            transfers_status="active", transfers_enabled=True,
            payouts_status="active", payouts_enabled=True,
            external_account_count=1,
        )
        with patch(f"{ADAPTER}.retrieve_account") as v2, \
             patch(f"{ADAPTER}.retrieve_legacy_account") as v1:
            r = client.get("/api/creator/stripe-connect/status")

        assert v2.call_count == 0 and v1.call_count == 0
        body = r.json()
        assert body["state"] == OnboardingState.ready.value
        assert body["transfers_enabled"] is True
        assert body["payouts_enabled"] is True
        assert body["connect_routing_enabled"] is False

    def test_reports_not_started_without_a_row(self, client, as_creator):
        r = client.get("/api/creator/stripe-connect/status")
        assert r.status_code == 200
        body = r.json()
        assert body["connected"] is False
        assert body["state"] == OnboardingState.not_started.value
        assert body["stripe_account_id"] is None

    def test_surfaces_action_required_from_the_stored_entries(
        self, client, as_creator, db,
    ):
        _row(
            db, as_creator.id, stripe_account_id=ACCT,
            onboarding_state=OnboardingState.action_required.value,
            details_submitted=True,
            currently_due_json=[{
                "description": "identity.individual.address.line1",
                "awaiting_action_from": "user",
                "restricts_capabilities": ["stripe_balance.stripe_transfers"],
                "errors": [],
            }],
        )
        body = client.get("/api/creator/stripe-connect/status").json()
        assert body["action_required"] is True
        assert body["requirements"][0]["awaiting_action_from"] == "user"

    def test_verifying_is_not_reported_as_action_required(self, client, as_creator, db):
        _row(
            db, as_creator.id, stripe_account_id=ACCT,
            onboarding_state=OnboardingState.verifying.value,
            details_submitted=True,
            currently_due_json=[{
                "description": "identity.individual.verification.document",
                "awaiting_action_from": "stripe",
                "restricts_capabilities": ["stripe_balance.stripe_transfers"],
                "errors": [],
            }],
        )
        body = client.get("/api/creator/stripe-connect/status").json()
        assert body["action_required"] is False


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_reprojects_and_stamps_the_diagnostics(self, client, as_creator, db):
        _row(
            db, as_creator.id, stripe_account_id=ACCT,
            onboarding_state=OnboardingState.onboarding.value,
        )
        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING) as v2, \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER) as v1:
            r = client.post("/api/creator/stripe-connect/refresh")

        assert v2.call_count == 1 and v1.call_count == 1
        body = r.json()
        assert body["state"] == OnboardingState.ready.value
        assert body["external_account_count"] == 1
        assert body["last_sync_source"] == "manual"
        assert body["last_synced_at"] is not None
        assert body["last_error_message"] is None

        row = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).one()
        assert row.onboarding_state == OnboardingState.ready.value
        assert row.payouts_enabled is True
        assert row.connect_payouts_enabled_at is None

    def test_observes_the_recorded_transition_in_both_directions(
        self, client, as_creator, db,
    ):
        _row(db, as_creator.id, stripe_account_id=ACCT)
        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_BEFORE_ONBOARDING), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_BEFORE):
            before = client.post("/api/creator/stripe-connect/refresh").json()
        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            after = client.post("/api/creator/stripe-connect/refresh").json()

        assert before["state"] == OnboardingState.onboarding.value
        assert len(before["requirements"]) == 13
        assert after["state"] == OnboardingState.ready.value
        assert after["requirements"] == []

    def test_retryable_failure_preserves_a_good_stored_state(
        self, client, as_creator, db,
    ):
        """An unanswered question is not evidence. A creator who was ready a
        minute ago must not be demoted because Stripe timed out."""
        _row(
            db, as_creator.id, stripe_account_id=ACCT,
            onboarding_state=OnboardingState.ready.value,
            transfers_status="active", transfers_enabled=True,
            payouts_status="active", payouts_enabled=True,
            details_submitted=True, external_account_count=1,
            payout_interval="daily", payout_delay_days=2,
        )
        with patch(f"{ADAPTER}.retrieve_account",
                   side_effect=connect.ConnectUnavailable("504 from Stripe")):
            r = client.post("/api/creator/stripe-connect/refresh")

        assert r.status_code == 503
        row = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).one()
        assert row.onboarding_state == OnboardingState.ready.value
        assert row.transfers_enabled is True
        assert row.payouts_enabled is True
        assert row.external_account_count == 1
        assert "504 from Stripe" in (row.last_error_message or "")

    def test_a_half_finished_sync_never_lands(self, client, as_creator, db):
        """v2 answered and v1 did not. The row must describe one moment or
        none of it — not a mixture."""
        _row(
            db, as_creator.id, stripe_account_id=ACCT,
            onboarding_state=OnboardingState.onboarding.value,
        )
        with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING), \
             patch(f"{ADAPTER}.retrieve_legacy_account",
                   side_effect=connect.ConnectUnavailable("v1 timeout")):
            r = client.post("/api/creator/stripe-connect/refresh")

        assert r.status_code == 503
        row = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).one()
        assert row.onboarding_state == OnboardingState.onboarding.value
        assert row.transfers_status is None

    def test_account_not_found_keeps_what_was_known(self, client, as_creator, db):
        """``resource_missing`` is also what a mode mismatch looks like, so
        it is never grounds for wiping a projection."""
        _row(
            db, as_creator.id, stripe_account_id=ACCT,
            onboarding_state=OnboardingState.ready.value,
            transfers_status="active", transfers_enabled=True,
            payouts_status="active", payouts_enabled=True,
        )
        with patch(f"{ADAPTER}.retrieve_account",
                   side_effect=connect.ConnectAccountNotFound("No such account")):
            r = client.post("/api/creator/stripe-connect/refresh")

        assert r.status_code == 409
        row = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).one()
        assert row.onboarding_state == OnboardingState.ready.value
        assert row.transfers_enabled is True

    def test_a_closed_account_projects_to_closed(self, client, as_creator, db):
        """Stripe answers for a closed account, so this is an observation
        rather than a failure."""
        _row(
            db, as_creator.id, stripe_account_id=ACCT,
            onboarding_state=OnboardingState.ready.value,
            transfers_status="active", transfers_enabled=True,
            payouts_status="active", payouts_enabled=True,
        )
        closed = {**V2_AFTER_ONBOARDING, "closed": True}
        with patch(f"{ADAPTER}.retrieve_account", return_value=closed), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
            body = client.post("/api/creator/stripe-connect/refresh").json()

        assert body["state"] == OnboardingState.closed.value
        row = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).one()
        assert row.onboarding_state == OnboardingState.closed.value

    def test_refuses_without_an_account(self, client, as_creator):
        r = client.post("/api/creator/stripe-connect/refresh")
        assert r.status_code == 409

    def test_transfers_only_is_reached_through_the_route(self, client, as_creator, db):
        """The state that would otherwise strand a creator's money."""
        _row(db, as_creator.id, stripe_account_id=ACCT)
        v2 = {
            **V2_AFTER_ONBOARDING,
            "configuration": {
                "recipient": {
                    "applied": True,
                    "capabilities": {
                        "stripe_balance": {
                            "stripe_transfers": {"status": "active", "status_details": []},
                            "payouts": {
                                "status": "restricted",
                                "status_details": [
                                    {"code": "requirements_past_due",
                                     "resolution": "provide_info"},
                                ],
                            },
                        },
                    },
                },
            },
        }
        v1 = {**V1_AFTER, "payouts_enabled": False,
              "external_accounts": {"total_count": 0, "data": []}}
        with patch(f"{ADAPTER}.retrieve_account", return_value=v2), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=v1):
            body = client.post("/api/creator/stripe-connect/refresh").json()

        assert body["state"] == OnboardingState.transfers_only.value
        assert body["transfers_enabled"] is True
        assert body["payouts_enabled"] is False
        assert body["external_account_count"] == 0
        # Even here — especially here — routing stays off.
        assert body["connect_routing_enabled"] is False


# ---------------------------------------------------------------------------
# Mode separation
# ---------------------------------------------------------------------------


class TestModeSeparation:
    def test_a_live_row_is_invisible_to_a_test_mode_environment(
        self, client, as_creator, db,
    ):
        """Lookups are keyed on the current mode, so a live account id can
        never be handed to a test key."""
        _row(
            db, as_creator.id, stripe_mode="live", stripe_account_id="acct_LIVEONLY",
            onboarding_state=OnboardingState.ready.value,
            transfers_status="active", transfers_enabled=True,
            payouts_status="active", payouts_enabled=True,
        )
        body = client.get("/api/creator/stripe-connect/status").json()
        assert body["stripe_mode"] == "test"
        assert body["connected"] is False
        assert body["state"] == OnboardingState.not_started.value

    def test_creating_in_test_mode_leaves_the_live_row_untouched(
        self, client, as_creator, db,
    ):
        live = _row(
            db, as_creator.id, stripe_mode="live", stripe_account_id="acct_LIVEONLY",
        )
        with patch(f"{ADAPTER}.create_recipient_account", return_value=_created_account()), \
             patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_BEFORE):
            r = client.post("/api/creator/stripe-connect/account")

        assert r.json()["stripe_account_id"] == ACCT
        rows = db.query(CreatorStripeAccount).filter_by(
            creator_user_id=as_creator.id,
        ).all()
        assert len(rows) == 2
        assert {r_.stripe_mode for r_ in rows} == {"test", "live"}
        db.refresh(live)
        assert live.stripe_account_id == "acct_LIVEONLY"

    def test_a_refresh_never_reaches_across_modes(self, client, as_creator, db):
        _row(db, as_creator.id, stripe_mode="live", stripe_account_id="acct_LIVEONLY")
        with patch(f"{ADAPTER}.retrieve_account") as v2:
            r = client.post("/api/creator/stripe-connect/refresh")
        assert r.status_code == 409
        assert v2.call_count == 0


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_no_route_ever_sets_connect_payouts_enabled_at(client, as_creator, db):
    """The one field that changes payment behaviour. Every endpoint is
    exercised here, including the fully-ready path where it would be most
    tempting."""
    with patch(f"{ADAPTER}.create_recipient_account", return_value=_created_account()), \
         patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
        client.post("/api/creator/stripe-connect/account")
    with patch(f"{ADAPTER}.create_onboarding_link", return_value="https://x/1"), \
         patch(f"{ADAPTER}.create_update_link", return_value="https://x/2"):
        client.post("/api/creator/stripe-connect/onboarding-link")
    with patch(f"{ADAPTER}.retrieve_account", return_value=V2_AFTER_ONBOARDING), \
         patch(f"{ADAPTER}.retrieve_legacy_account", return_value=V1_AFTER):
        client.post("/api/creator/stripe-connect/refresh")
    client.get("/api/creator/stripe-connect/status")

    row = db.query(CreatorStripeAccount).filter_by(creator_user_id=as_creator.id).one()
    assert row.onboarding_state == OnboardingState.ready.value
    assert row.connect_payouts_enabled_at is None


# ---------------------------------------------------------------------------
# Adapter failure translation
# ---------------------------------------------------------------------------


class TestFailureTranslation:
    @pytest.mark.parametrize("exc, expected", [
        (lambda: __import__("stripe").APIConnectionError("no route"), connect.ConnectUnavailable),
        (lambda: __import__("stripe").RateLimitError("slow down"), connect.ConnectUnavailable),
        (lambda: __import__("stripe").APIError("500"), connect.ConnectUnavailable),
    ])
    def test_transport_failures_are_retryable(self, exc, expected):
        assert isinstance(connect._translate(exc(), what="x"), expected)

    def test_resource_missing_is_not_found(self):
        import stripe
        err = stripe.InvalidRequestError("No such account", param=None, code="resource_missing")
        assert isinstance(connect._translate(err, what="x"), connect.ConnectAccountNotFound)

    def test_other_invalid_requests_are_rejections_carrying_the_code(self):
        import stripe
        err = stripe.InvalidRequestError("Not a valid URL", param="url", code="url_invalid")
        translated = connect._translate(err, what="x")
        assert isinstance(translated, connect.ConnectRejected)
        assert translated.code == "url_invalid"

    def test_permission_errors_are_rejections_not_retries(self):
        """Retrying a 403 gets the same 403 — what needs fixing is the
        environment, not the timing."""
        import stripe
        err = stripe.PermissionError("no permission for parameter 'individual'")
        translated = connect._translate(err, what="x")
        assert isinstance(translated, connect.ConnectRejected)
        assert not isinstance(translated, connect.ConnectUnavailable)

    def test_a_link_without_a_url_is_unavailable_not_success(self):
        class _Links:
            def create(self, params):
                return {"object": "v2.core.account_link", "url": None}

        class _Core:
            account_links = _Links()

        class _V2:
            core = _Core()

        class _Client:
            v2 = _V2()

        with patch(f"{ADAPTER}.get_stripe_client", return_value=_Client()):
            with pytest.raises(connect.ConnectUnavailable):
                connect.create_onboarding_link(
                    account_id=ACCT, return_url="https://x/r", refresh_url="https://x/f",
                )

    def test_adapter_requests_the_recipient_configuration_on_links(self):
        sent = {}

        class _Links:
            def create(self, params):
                sent.update(params)
                return {"url": "https://connect.stripe.com/setup/e/x"}

        class _Core:
            account_links = _Links()

        class _V2:
            core = _Core()

        class _Client:
            v2 = _V2()

        with patch(f"{ADAPTER}.get_stripe_client", return_value=_Client()):
            connect.create_onboarding_link(
                account_id=ACCT, return_url="https://x/r", refresh_url="https://x/f",
            )
        assert sent["use_case"]["type"] == "account_onboarding"
        options = sent["use_case"]["account_onboarding"]
        assert options["configurations"] == ["recipient"]
        assert options["collection_options"] == {"fields": "currently_due"}
        assert options["return_url"] == "https://x/r"
        assert options["refresh_url"] == "https://x/f"

    def test_update_links_use_the_account_update_use_case(self):
        sent = {}

        class _Links:
            def create(self, params):
                sent.update(params)
                return {"url": "https://connect.stripe.com/setup/u/x"}

        class _Core:
            account_links = _Links()

        class _V2:
            core = _Core()

        class _Client:
            v2 = _V2()

        with patch(f"{ADAPTER}.get_stripe_client", return_value=_Client()):
            connect.create_update_link(
                account_id=ACCT, return_url="https://x/r", refresh_url="https://x/f",
            )
        assert sent["use_case"]["type"] == "account_update"
        assert sent["use_case"]["account_update"]["configurations"] == ["recipient"]


# ---------------------------------------------------------------------------
# POST /acknowledge-fees
# ---------------------------------------------------------------------------


READY_FIELDS = dict(
    stripe_account_id=ACCT,
    onboarding_state=OnboardingState.ready.value,
    transfers_status="active", transfers_enabled=True,
    payouts_status="active", payouts_enabled=True,
    details_submitted=True, external_account_count=1,
)


class TestAcknowledgeFees:
    def test_it_records_the_acknowledgement_and_returns_the_status(
        self, client, as_creator, db,
    ):
        row = _row(db, as_creator.id, **READY_FIELDS)

        res = client.post("/api/creator/stripe-connect/acknowledge-fees")

        assert res.status_code == 200
        assert res.json()["fee_disclosure_acknowledged"] is True
        assert res.json()["fee_disclosure_version"]
        db.refresh(row)
        assert row.fee_disclosure_acknowledged_at is not None

    def test_acknowledging_does_not_switch_routing_on(
        self, client, as_creator, db,
    ):
        """The whole reason this is a separate endpoint from enablement."""
        row = _row(db, as_creator.id, **READY_FIELDS)

        res = client.post("/api/creator/stripe-connect/acknowledge-fees")

        assert res.json()["connect_routing_enabled"] is False
        db.refresh(row)
        assert row.connect_payouts_enabled_at is None

    def test_a_creator_with_no_stripe_account_gets_a_clear_refusal(
        self, client, as_creator,
    ):
        res = client.post("/api/creator/stripe-connect/acknowledge-fees")
        assert res.status_code == 409

    def test_it_makes_no_stripe_call(self, client, as_creator, db):
        """A creator agreeing to the fee model is a local fact."""
        _row(db, as_creator.id, **READY_FIELDS)

        with patch(f"{ADAPTER}.retrieve_account") as retrieve, \
             patch(f"{ADAPTER}.get_stripe_client") as get_client:
            res = client.post("/api/creator/stripe-connect/acknowledge-fees")

        assert res.status_code == 200
        retrieve.assert_not_called()
        get_client.assert_not_called()


# ---------------------------------------------------------------------------
# GET /earnings
# ---------------------------------------------------------------------------


class TestEarningsEndpoint:
    def test_it_returns_only_this_creators_connect_sales(
        self, client, as_creator, db, make_user,
    ):
        other = make_user(role="creator")
        mine = _connect_txn(db, as_creator.id)
        theirs = _connect_txn(db, other.id)

        res = client.get("/api/creator/stripe-connect/earnings")

        assert res.status_code == 200
        ids = [r["payment_transaction_id"] for r in res.json()["rows"]]
        assert mine.id in ids
        assert theirs.id not in ids

    def test_it_exposes_no_stripe_ids_or_recovery_internals(
        self, client, as_creator, db,
    ):
        _connect_txn(
            db, as_creator.id,
            provider_transfer_id="tr_leaky",
            connect_destination_account_id=CONNECT_ACCT,
            connect_unrecovered_amount_cents=500,
        )

        body = client.get("/api/creator/stripe-connect/earnings").text

        assert "tr_leaky" not in body
        assert CONNECT_ACCT not in body
        assert "unrecovered" not in body

    def test_a_creator_with_no_account_gets_an_empty_list_not_an_error(
        self, client, as_creator,
    ):
        """Nothing to show is a normal state, not a failure."""
        res = client.get("/api/creator/stripe-connect/earnings")
        assert res.status_code == 200
        assert res.json()["rows"] == []
        assert res.json()["row_count"] == 0

    def test_it_makes_no_stripe_call(self, client, as_creator, db):
        with patch(f"{ADAPTER}.get_stripe_client") as get_client:
            res = client.get("/api/creator/stripe-connect/earnings")
        assert res.status_code == 200
        get_client.assert_not_called()


# ---------------------------------------------------------------------------
# Admin enablement
# ---------------------------------------------------------------------------
#
# Called as functions, matching ``test_physical_locations_routes.py`` — that
# exercises the real guard and the real DB effects without booting the auth
# stack. Admin-only access is asserted two ways below: the dependency itself
# rejects a creator, and every route in the module declares it.


class TestAdminEnablement:
    def _ready_acknowledged(self, db, creator_id):
        return _row(
            db, creator_id, **READY_FIELDS,
            fee_disclosure_acknowledged_at=datetime(2026, 9, 1, 8, 0, 0),
            fee_disclosure_version="2026-09-connect-v1",
        )

    def test_enable_routes_the_creators_future_sales(self, db, make_user):
        from app.admin.connect_routes import enable_connect_routing

        admin = make_user(role="admin")
        creator = make_user(role="creator")
        row = self._ready_acknowledged(db, creator.id)

        out = enable_connect_routing(
            creator_user_id=creator.id, admin=admin, db=db,
        )

        assert out.routing_enabled_at is not None
        assert out.ready_to_enable is True
        db.refresh(row)
        assert row.connect_payouts_enabled_at is not None

    def test_enable_refuses_an_unacknowledged_creator(self, db, make_user):
        from fastapi import HTTPException
        from app.admin.connect_routes import enable_connect_routing

        admin = make_user(role="admin")
        creator = make_user(role="creator")
        row = _row(db, creator.id, **READY_FIELDS)

        with pytest.raises(HTTPException) as ex:
            enable_connect_routing(
                creator_user_id=creator.id, admin=admin, db=db,
            )
        assert ex.value.status_code == 409
        assert ex.value.detail["reason"] == "fee_disclosure_not_acknowledged"
        db.refresh(row)
        assert row.connect_payouts_enabled_at is None

    def test_readiness_names_every_missing_condition(self, db, make_user):
        from app.admin.connect_routes import get_connect_readiness

        admin = make_user(role="admin")
        creator = make_user(role="creator")
        _row(db, creator.id)   # no account id, no payouts, no acknowledgement

        out = get_connect_readiness(
            creator_user_id=creator.id, admin=admin, db=db,
        )

        assert out.ready_to_enable is False
        assert "no_stripe_account_id" in out.blockers
        assert "payouts_not_enabled" in out.blockers
        assert "fee_disclosure_not_acknowledged" in out.blockers

    def test_readiness_for_an_unknown_creator_is_a_blocker_not_a_crash(
        self, db, make_user,
    ):
        from app.admin.connect_routes import get_connect_readiness

        admin = make_user(role="admin")
        out = get_connect_readiness(
            creator_user_id="usr_nobody", admin=admin, db=db,
        )
        assert out.ready_to_enable is False
        assert "no_account_for_current_mode" in out.blockers

    def test_disable_stops_future_routing_and_leaves_the_row_intact(
        self, db, make_user,
    ):
        from app.admin.connect_routes import (
            disable_connect_routing, enable_connect_routing,
        )

        admin = make_user(role="admin")
        creator = make_user(role="creator")
        row = self._ready_acknowledged(db, creator.id)
        enable_connect_routing(creator_user_id=creator.id, admin=admin, db=db)

        out = disable_connect_routing(
            creator_user_id=creator.id, admin=admin, db=db,
        )

        assert out.routing_enabled_at is None
        db.refresh(row)
        assert row.connect_payouts_enabled_at is None
        # The acknowledgement is a historical fact and survives.
        assert row.fee_disclosure_acknowledged_at is not None

    def test_the_dependency_rejects_a_creator_and_a_member(self, db, make_user):
        from fastapi import HTTPException
        from app.auth.dependencies import get_admin_user

        for role in ("user", "creator"):
            with pytest.raises(HTTPException) as ex:
                get_admin_user(current_user=make_user(role=role))
            assert ex.value.status_code == 403

    def test_every_admin_connect_route_requires_an_admin(self):
        """The guard cannot be dropped from one route without failing here."""
        from app.admin import connect_routes as admin_connect
        from app.auth.dependencies import get_admin_user

        assert admin_connect.router.routes
        for route in admin_connect.router.routes:
            guards = [d.call for d in route.dependant.dependencies]
            assert get_admin_user in guards, route.path
