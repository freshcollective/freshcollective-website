"""Phase B — the admin API for editable email copy.

Covers list / detail / save / reset / preview / test-send, the
permission boundary, and the regression guarantees that matter more
than any of them: with no overrides saved, production rendering is
unchanged, and no override can reach a money, security or access fact.

No real email is sent anywhere in this file — the provider is stubbed
at its own boundary, so there is no code path from these tests to the
network.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.comms.templates  # noqa: F401
import app.comms.routing.resolvers  # noqa: F401
from app.auth.dependencies import get_admin_user, get_current_user
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.providers.base import ProviderResult
from app.comms.providers.resend import ResendProvider
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.editable import get_declaration
from app.comms.templates.registry import get_template_for
from app.core.database import get_db
from app.main import app
from app.models.communication_template_override import (
    CommunicationTemplateOverride,
)

BASE = "/api/admin/communications/email-templates"
WELCOME = "account.welcome_after_signup.email_transactional"
VERIFY = "account.email_verification_requested.email_transactional"
BOOKING = "gathering.booking.confirmed.email_transactional"
PURCHASE = "purchase.completed.email_transactional"
RESET_TPL = "account.password_reset_requested.email_transactional"
DARK = "dm.message.sent.email_transactional"


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


@pytest.fixture
def sent():
    """Stub the provider at its own boundary — no network path exists
    from these tests."""
    calls: list = []

    def _send(self, payload):
        calls.append(payload)
        return ProviderResult(accepted=True, provider_message_id="msg_test")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ResendProvider, "send", _send)
        yield calls


def _render_real(event_type: str, db):
    t = get_template_for(event_type, CHANNEL_EMAIL_TRANSACTIONAL)
    return t.render(db, None, ResolvedRecipient(
        user_id="u", role_in_event="r", human_reason="h",
        template_context={
            "first_name": "Ada", "next_url": "https://fc.test/d",
            "verify_url": "https://fc.test/v",
            "experience_name": "Life in Alignment",
            "member_url": "https://fc.test/m", "payment_mode": "single",
            "amount_cents": 3780, "currency": "AUD",
        },
    ))


# ===========================================================================
# 1. List
# ===========================================================================


class TestList:
    def test_lists_only_live_templates(self, client):
        keys = {t["template_key"] for t in client.get(BASE).json()}
        assert WELCOME in keys
        assert RESET_TPL in keys          # system, but listed read-only
        assert DARK not in keys           # topic not live — excluded
        assert "pathway.published.email_transactional" not in keys

    def test_classifications_are_reported(self, client):
        by_key = {t["template_key"]: t for t in client.get(BASE).json()}
        assert by_key[WELCOME]["classification"] == "editable"
        assert by_key[WELCOME]["editable"] is True
        assert by_key[PURCHASE]["classification"] == "partial"
        assert by_key[RESET_TPL]["classification"] == "system"
        assert by_key[RESET_TPL]["editable"] is False

    def test_transactional_delivery_is_reported_as_information(self, client):
        by_key = {t["template_key"]: t for t in client.get(BASE).json()}
        assert by_key[BOOKING]["is_transactional"] is True
        assert by_key[WELCOME]["is_transactional"] is False
        # Delivery lock and content editability are independent.
        assert by_key[BOOKING]["editable"] is True

    def test_customised_state_and_count(self, client, db, admin):
        assert all(not t["customised"] for t in client.get(BASE).json())
        client.put(f"{BASE}/{WELCOME}", json={
            "overrides": {"heading": "A warm welcome", "signoff": "So glad."},
        })
        item = next(t for t in client.get(BASE).json()
                    if t["template_key"] == WELCOME)
        assert item["customised"] is True
        assert item["overridden_slot_count"] == 2

    def test_stale_fingerprint_is_surfaced(self, client, db):
        db.add(CommunicationTemplateOverride(
            id=f"cto_{uuid.uuid4().hex[:10]}", template_key=WELCOME,
            slot_id="heading", value="Custom",
            default_fingerprint="stale-hash-from-an-older-deploy",
        ))
        db.flush()
        item = next(t for t in client.get(BASE).json()
                    if t["template_key"] == WELCOME)
        assert item["has_stale_default"] is True


# ===========================================================================
# 2. Detail
# ===========================================================================


class TestDetail:
    def test_returns_slots_defaults_and_effective_values(self, client):
        d = client.get(f"{BASE}/{WELCOME}").json()
        heading = next(s for s in d["slots"] if s["slot_id"] == "heading")
        assert heading["default"] == "Welcome to Fresh Collective"
        assert heading["effective"] == heading["default"]
        assert heading["override"] is None
        assert heading["customised"] is False

    def test_exposes_merge_fields_and_locked_notes(self, client):
        d = client.get(f"{BASE}/{BOOKING}").json()
        names = {f["name"] for f in d["merge_fields"]}
        assert {"gathering_name", "collective_name", "gathering_when"} <= names
        assert all(f["sample"] for f in d["merge_fields"])
        assert any("generated" in n for n in d["locked_notes"])

    def test_system_template_exposes_no_editable_slots(self, client):
        d = client.get(f"{BASE}/{RESET_TPL}").json()
        assert d["classification"] == "system"
        assert d["slots"] == []
        assert d["editable"] is False

    def test_partial_template_exposes_only_its_declared_slots(self, client):
        d = client.get(f"{BASE}/{PURCHASE}").json()
        assert [s["slot_id"] for s in d["slots"]] == ["signoff"]

    def test_default_changed_flag(self, client, db):
        db.add(CommunicationTemplateOverride(
            id=f"cto_{uuid.uuid4().hex[:10]}", template_key=WELCOME,
            slot_id="heading", value="Custom", default_fingerprint="stale",
        ))
        db.flush()
        heading = next(s for s in client.get(f"{BASE}/{WELCOME}").json()["slots"]
                       if s["slot_id"] == "heading")
        assert heading["default_changed"] is True
        # The admin's copy is untouched — the flag is informational.
        assert heading["effective"] == "Custom"

    def test_unknown_template_404(self, client):
        assert client.get(f"{BASE}/nope").status_code == 404


# ===========================================================================
# 3. Save
# ===========================================================================


class TestSave:
    def test_valid_override_persists_and_changes_rendering(self, client, db):
        r = client.put(f"{BASE}/{WELCOME}",
                       json={"overrides": {"heading": "A warm welcome"}})
        assert r.status_code == 200
        heading = next(s for s in r.json()["slots"] if s["slot_id"] == "heading")
        assert heading["effective"] == "A warm welcome"
        assert "A warm welcome" in _render_real(
            "account.welcome_after_signup", db).body_html

    def test_records_who_edited_and_when(self, client, db, admin):
        client.put(f"{BASE}/{WELCOME}",
                   json={"overrides": {"heading": "A warm welcome"}})
        row = db.query(CommunicationTemplateOverride).filter(
            CommunicationTemplateOverride.template_key == WELCOME).one()
        assert row.updated_by_user_id == admin.id
        assert row.updated_at is not None
        assert row.default_fingerprint == get_declaration(WELCOME).slot(
            "heading").fingerprint()

    def test_a_value_equal_to_the_default_stores_nothing(self, client, db):
        """Customised should mean 'differs'. Typing the original back
        must genuinely return to default, so future improvements to it
        still reach the member."""
        default = get_declaration(WELCOME).slot("heading").default
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {"heading": default}})
        assert db.query(CommunicationTemplateOverride).filter(
            CommunicationTemplateOverride.template_key == WELCOME).count() == 0

    def test_retyping_the_default_removes_an_existing_override(self, client, db):
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {"heading": "Custom"}})
        default = get_declaration(WELCOME).slot("heading").default
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {"heading": default}})
        assert db.query(CommunicationTemplateOverride).filter(
            CommunicationTemplateOverride.template_key == WELCOME).count() == 0

    def test_saving_twice_updates_rather_than_duplicating(self, client, db):
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {"heading": "One"}})
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {"heading": "Two"}})
        rows = db.query(CommunicationTemplateOverride).filter(
            CommunicationTemplateOverride.template_key == WELCOME).all()
        assert len(rows) == 1 and rows[0].value == "Two"

    @pytest.mark.parametrize("slot_id,value,fragment", [
        ("nope", "x", "Unknown field"),
        ("heading", "Hi <b>there</b>", "plain text"),
        ("heading", "Hello {{nope}}", "not available"),
        ("heading", "Hello {{there", "malformed"),
        ("subject", "x" * 200, "limit is"),
        ("heading", "   ", "cannot be empty"),
    ])
    def test_invalid_values_are_rejected(self, client, db, slot_id, value, fragment):
        r = client.put(f"{BASE}/{WELCOME}",
                       json={"overrides": {slot_id: value}})
        assert r.status_code == 422
        assert fragment in str(r.json()["detail"])
        assert db.query(CommunicationTemplateOverride).count() == 0

    def test_required_merge_field_must_be_kept(self, client):
        r = client.put(f"{BASE}/{BOOKING}",
                       json={"overrides": {"heading": "You are booked"}})
        assert r.status_code == 422
        assert "must keep" in str(r.json()["detail"])

    def test_system_template_is_rejected(self, client, db):
        r = client.put(f"{BASE}/{RESET_TPL}",
                       json={"overrides": {"heading": "x"}})
        assert r.status_code == 400
        assert "system-controlled" in r.json()["detail"]
        assert db.query(CommunicationTemplateOverride).count() == 0

    def test_a_slot_the_partial_template_does_not_declare_is_rejected(self, client):
        """purchase.completed exposes only its sign-off — the amount and
        the access statement have no slot and therefore no route in."""
        r = client.put(f"{BASE}/{PURCHASE}",
                       json={"overrides": {"body.opening": "Free!"}})
        assert r.status_code == 422
        assert "Unknown field" in str(r.json()["detail"])

    def test_a_batch_with_one_bad_slot_saves_nothing(self, client, db):
        r = client.put(f"{BASE}/{WELCOME}", json={"overrides": {
            "heading": "Fine", "signoff": "Hi <b>no</b>",
        }})
        assert r.status_code == 422
        assert db.query(CommunicationTemplateOverride).count() == 0


# ===========================================================================
# 4 & 5. Reset
# ===========================================================================


class TestReset:
    def test_single_slot_reset_restores_the_default(self, client, db):
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {
            "heading": "Custom", "signoff": "Custom too",
        }})
        r = client.delete(f"{BASE}/{WELCOME}/slots/heading")
        assert r.status_code == 200
        slots = {s["slot_id"]: s for s in r.json()["slots"]}
        assert slots["heading"]["effective"] == "Welcome to Fresh Collective"
        assert slots["heading"]["customised"] is False
        assert slots["signoff"]["customised"] is True

    def test_full_reset_removes_every_override(self, client, db):
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {
            "heading": "Custom", "signoff": "Custom too",
        }})
        r = client.delete(f"{BASE}/{WELCOME}")
        assert r.status_code == 200
        assert r.json()["customised"] is False
        assert db.query(CommunicationTemplateOverride).filter(
            CommunicationTemplateOverride.template_key == WELCOME).count() == 0

    def test_reset_restores_byte_identical_rendering(self, client, db):
        before = _render_real("account.welcome_after_signup", db)
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {"heading": "Custom"}})
        client.delete(f"{BASE}/{WELCOME}")
        assert _render_real("account.welcome_after_signup", db) == before

    def test_reset_of_an_unknown_slot_is_404(self, client):
        assert client.delete(f"{BASE}/{WELCOME}/slots/nope").status_code == 404

    def test_reset_on_a_system_template_is_refused(self, client):
        assert client.delete(f"{BASE}/{RESET_TPL}").status_code == 400

    def test_reset_with_nothing_saved_is_harmless(self, client):
        assert client.delete(f"{BASE}/{WELCOME}").status_code == 200


# ===========================================================================
# 6. Preview
# ===========================================================================


class TestPreview:
    def test_effective_mode_includes_saved_overrides(self, client):
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {"heading": "Saved"}})
        r = client.post(f"{BASE}/{WELCOME}/preview",
                        json={"mode": "effective"}).json()
        assert "Saved" in r["html"]
        assert r["effective_slots"]["heading"] == "Saved"

    def test_drafts_layer_over_saved_overrides(self, client):
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {
            "heading": "Stored heading", "signoff": "Stored signoff",
        }})
        r = client.post(f"{BASE}/{WELCOME}/preview", json={
            "mode": "effective", "drafts": {"heading": "Drafted heading"},
        }).json()
        assert "Drafted heading" in r["html"]
        assert "Stored heading" not in r["html"]      # draft wins
        assert "Stored signoff" in r["html"]          # untouched slot persists
        assert r["effective_slots"]["heading"] == "Drafted heading"
        assert r["effective_slots"]["signoff"] == "Stored signoff"

    def test_default_mode_ignores_everything_stored(self, client):
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {"heading": "Saved"}})
        r = client.post(f"{BASE}/{WELCOME}/preview",
                        json={"mode": "default"}).json()
        assert "Saved" not in r["html"]
        assert "Welcome to Fresh Collective" in r["html"]

    def test_invalid_draft_is_reported_and_dropped(self, client):
        r = client.post(f"{BASE}/{WELCOME}/preview", json={
            "drafts": {"heading": "Hi <b>there</b>"},
        }).json()
        assert "heading" in r["errors"]
        assert "<b>" not in r["html"]

    def test_preheader_is_returned_where_the_template_has_one(self, client):
        r = client.post(f"{BASE}/{VERIFY}/preview", json={}).json()
        assert r["preheader"] == (
            "Confirm your email address so we know we can reach you when it "
            "matters."
        )
        assert client.post(f"{BASE}/{BOOKING}/preview",
                           json={}).json()["preheader"] is None

    def test_editing_the_preheader_changes_the_rendered_document(self, client):
        client.put(f"{BASE}/{VERIFY}",
                   json={"overrides": {"preheader": "Just one quick step."}})
        r = client.post(f"{BASE}/{VERIFY}/preview", json={}).json()
        assert r["preheader"] == "Just one quick step."
        assert "Just one quick step." in r["html"]

    def test_variant_switch(self, client):
        key = "creator.plan_activated.email_transactional"
        fresh = client.post(f"{BASE}/{key}/preview",
                            json={"variant": {"is_fresh_creator": True}}).json()
        ret = client.post(f"{BASE}/{key}/preview",
                          json={"variant": {"is_fresh_creator": False}}).json()
        assert "Set up your Collective" in fresh["html"]
        assert "Open Creator Studio" in ret["html"]

    def test_preview_writes_nothing(self, client, db):
        before = db.query(CommunicationTemplateOverride).count()
        client.post(f"{BASE}/{WELCOME}/preview",
                    json={"drafts": {"heading": "Draft only"}})
        assert db.query(CommunicationTemplateOverride).count() == before
        assert "Draft only" not in _render_real(
            "account.welcome_after_signup", db).body_html


# ===========================================================================
# 7. Test send
# ===========================================================================


class TestTestSend:
    def test_sends_to_the_admins_own_address_with_a_test_prefix(
        self, client, admin, sent,
    ):
        r = client.post(f"{BASE}/{WELCOME}/test-send", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["sent_to"] == admin.email
        assert body["subject"].startswith("[TEST] ")
        assert body["accepted"] is True
        assert len(sent) == 1
        assert sent[0].to == admin.email

    def test_the_email_identifies_itself_as_a_test(self, client, sent):
        client.post(f"{BASE}/{WELCOME}/test-send", json={})
        payload = sent[0]
        assert "TEST EMAIL" in payload.body_html
        assert payload.body_text.startswith("[TEST]")

    def test_recipient_cannot_be_supplied_by_the_caller(self, client, admin, sent):
        """Not a parameter — an extra field is ignored, never honoured."""
        client.post(f"{BASE}/{WELCOME}/test-send",
                    json={"to": "member@example.test",
                          "recipient": "member@example.test"})
        assert sent[0].to == admin.email

    def test_an_unverified_admin_cannot_test_send(self, db, make_user, sent):
        unverified = make_user(role="admin", email_verified_at=None)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_admin_user] = lambda: unverified
        try:
            r = TestClient(app).post(f"{BASE}/{WELCOME}/test-send", json={})
            assert r.status_code == 400
            assert "Verify your own email" in r.json()["detail"]
            assert sent == []
        finally:
            app.dependency_overrides.clear()

    def test_uses_saved_overrides_and_drafts(self, client, sent):
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {"heading": "Saved"}})
        client.post(f"{BASE}/{WELCOME}/test-send", json={})
        assert "Saved" in sent[0].body_html
        client.post(f"{BASE}/{WELCOME}/test-send",
                    json={"drafts": {"heading": "Draft"}})
        assert "Draft" in sent[1].body_html

    def test_invalid_draft_refuses_to_send(self, client, sent):
        r = client.post(f"{BASE}/{WELCOME}/test-send",
                        json={"drafts": {"heading": "Hi <b>x</b>"}})
        assert r.status_code == 422
        assert sent == []

    def test_creates_no_communication_event_intent_or_delivery(
        self, client, db, sent,
    ):
        """The ledger records member communications. A test is not one,
        and writing to it would consume dedupe keys and distort
        preference and lifecycle reporting."""
        from app.comms.models import (
            CommunicationDelivery, CommunicationEvent, CommunicationIntent,
        )
        before = (
            db.query(CommunicationEvent).count(),
            db.query(CommunicationIntent).count(),
            db.query(CommunicationDelivery).count(),
        )
        client.post(f"{BASE}/{WELCOME}/test-send", json={})
        after = (
            db.query(CommunicationEvent).count(),
            db.query(CommunicationIntent).count(),
            db.query(CommunicationDelivery).count(),
        )
        assert before == after
        assert len(sent) == 1        # but it really did reach the provider

    def test_creates_no_business_state(self, client, db, sent):
        from app.models.platform import EventBooking
        from app.models.payment import PaymentTransaction
        before = (
            db.query(EventBooking).count(),
            db.query(PaymentTransaction).count(),
        )
        for key in (WELCOME, BOOKING, PURCHASE):
            client.post(f"{BASE}/{key}/test-send", json={})
        assert (
            db.query(EventBooking).count(),
            db.query(PaymentTransaction).count(),
        ) == before

    def test_does_not_alter_stored_copy_or_defaults(self, client, db, sent):
        client.post(f"{BASE}/{WELCOME}/test-send", json={})
        assert db.query(CommunicationTemplateOverride).count() == 0
        assert get_declaration(WELCOME).slot("subject").default == (
            "Welcome to Fresh Collective"
        )
        # A real render is unprefixed.
        assert not _render_real(
            "account.welcome_after_signup", db).subject.startswith("[TEST]")


# ===========================================================================
# Permissions
# ===========================================================================


@pytest.mark.parametrize("role", ["user", "creator"])
class TestPermissions:
    def _client(self, db, make_user, role):
        u = make_user(role=role)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: u
        return TestClient(app)

    def test_every_endpoint_is_denied(self, db, make_user, role):
        c = self._client(db, make_user, role)
        try:
            for call in (
                lambda: c.get(BASE),
                lambda: c.get(f"{BASE}/{WELCOME}"),
                lambda: c.put(f"{BASE}/{WELCOME}", json={"overrides": {}}),
                lambda: c.delete(f"{BASE}/{WELCOME}"),
                lambda: c.delete(f"{BASE}/{WELCOME}/slots/heading"),
                lambda: c.post(f"{BASE}/{WELCOME}/preview", json={}),
                lambda: c.post(f"{BASE}/{WELCOME}/test-send", json={}),
            ):
                assert call().status_code == 403
        finally:
            app.dependency_overrides.clear()


# ===========================================================================
# Regression
# ===========================================================================


class TestRegression:
    def test_no_overrides_renders_identically_to_no_database(self, db):
        from app.comms.templates.editable import all_declarations
        for d in all_declarations():
            if d.event_type == "diagnostics.provider_probe":
                continue
            assert _render_real(d.event_type, db) == _render_real(
                d.event_type, None), d.event_type

    def test_money_facts_survive_an_override_of_the_editable_slot(
        self, client, db,
    ):
        client.put(f"{BASE}/{PURCHASE}",
                   json={"overrides": {"signoff": "Thanks so much."}})
        p = _render_real("purchase.completed", db)
        assert "Thanks so much." in p.body_html
        assert "AUD 37.80" in p.body_html          # generated, unreachable

    def test_transactional_lock_unchanged(self):
        from app.comms.registry import TRANSACTIONAL_EVENT_TYPES
        assert TRANSACTIONAL_EVENT_TYPES == {
            "gathering.booking.confirmed",
            "gathering.multi_booking.confirmed",
        }

    def test_preference_footer_policy_unchanged_by_editing(self, client, db):
        client.put(f"{BASE}/{WELCOME}", json={"overrides": {"heading": "X"}})
        assert "Manage your Stay Connected preferences" not in _render_real(
            "account.welcome_after_signup", db).body_html
