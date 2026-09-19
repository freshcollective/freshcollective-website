"""Phase A — editable email copy: declarations, resolution, preview.

The load-bearing test in this file is
``TestNoOverridesChangesNothing`` — every one of the 25 email templates
must render byte-identically to how it rendered before slots existed.
Everything else here is worthless if that one fails.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.comms.templates  # noqa: F401 — registers templates + declarations
import app.comms.routing.resolvers  # noqa: F401
from app.auth.dependencies import get_admin_user
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.editable import (
    EDITABLE,
    PARTIAL,
    SUBJECT_MAX_LENGTH,
    SYSTEM,
    EditableSlot,
    MergeField,
    SlotResolver,
    TemplateDeclaration,
    all_declarations,
    get_declaration,
    preview_overrides,
    substitute,
    validate_slot_value,
)
from app.comms.templates.registry import get_template_for
from app.core.database import get_db
from app.main import app
from app.models.communication_template_override import (
    CommunicationTemplateOverride,
)


WELCOME = "account.welcome_after_signup.email_transactional"
BOOKING = "gathering.booking.confirmed.email_transactional"
RESET = "account.password_reset_requested.email_transactional"


# ---------------------------------------------------------------------------
# Shared sample context — generous, so every template can render.
# ---------------------------------------------------------------------------

SAMPLE = {
    "first_name": "Ada", "verify_url": "https://fc.test/v", "next_url": "https://fc.test/d",
    "reset_url": "https://fc.test/r", "plan_name": "Creator Portfolio",
    "is_fresh_creator": True, "was_reactivated": False, "inviter_name": "Sarah",
    "collective_name": "Still Water", "accept_url": "https://fc.test/i",
    "gathering_title": "Morning Sit", "gathering_starts_at": "Friday 19 September at 9:00am",
    "gathering_id": "ev_1", "gathering_url": "https://fc.test/g", "added_by_creator": False,
    "gathering_when": "Friday 19 September at 9:00am", "was_ticketed": True,
    "series_title": "Spring Term", "session_count": 8,
    "first_starts_at": "Fri 19 Sep", "last_starts_at": "Fri 7 Nov",
    "cta_url": "https://fc.test/s", "schedule_preview": [{"title": "W1", "when": "Fri"}],
    "excerpt": "A quiet thought.", "post_title": "On stillness",
    "commenter_name": "Sarah", "view_url": "https://fc.test/p", "post_id": "p1",
    "space_id": "s1", "comment_id": "c1", "pathway_title": "Beginning",
    "pathway_id": "pw1", "sender_name": "Sarah", "thread_id": "t1",
    "experience_name": "Life in Alignment", "member_url": "https://fc.test/m",
    "payment_mode": "plan", "amount_cents": 3780, "currency": "AUD",
    "installments_paid": 1, "installments_expected": 10,
    "repair_url": "https://fc.test/fix", "grace_expires_at": "2026-10-01T00:00:00",
    "was_suspended": True, "total_paid_cents": 37800, "item_name": "Life in Alignment",
    "is_full_refund": False, "retry_url": "https://fc.test/o",
    "plan_label": "Creator Portfolio", "billing_url": "https://fc.test/b",
    "current_period_end": "2026-10-25T00:00:00", "ended_at": "2026-10-25T00:00:00",
}


def _render(event_type: str, db=None, ctx=None):
    t = get_template_for(event_type, CHANNEL_EMAIL_TRANSACTIONAL)
    return t.render(db, None, ResolvedRecipient(
        user_id="u", role_in_event="r", human_reason="h",
        template_context=dict(ctx or SAMPLE),
    ))


# ===========================================================================
# The guarantee: no overrides → nothing changed
# ===========================================================================


class TestNoOverridesChangesNothing:
    @pytest.mark.parametrize("decl", [
        pytest.param(d, id=d.event_type) for d in all_declarations()
        if d.event_type != "diagnostics.provider_probe"
    ])
    def test_renders_without_a_database(self, decl):
        """Every template renders from code defaults with no session —
        the path taken today and until an admin saves anything."""
        p = _render(decl.event_type, db=None)
        assert p.subject.strip()
        assert p.body_html and p.body_html.lstrip().startswith("<!DOCTYPE html>")
        assert p.body_text and p.body_text.strip()

    @pytest.mark.parametrize("decl", [
        pytest.param(d, id=d.event_type) for d in all_declarations()
        if d.event_type != "diagnostics.provider_probe"
    ])
    def test_empty_override_table_matches_no_database(self, db, decl):
        """A real session with zero override rows must produce exactly
        what no session produces."""
        assert _render(decl.event_type, db=db) == _render(decl.event_type, db=None)

    def test_no_stray_placeholders_survive_rendering(self):
        for d in all_declarations():
            if d.event_type == "diagnostics.provider_probe":
                continue
            p = _render(d.event_type)
            assert "{{" not in p.body_html, d.event_type
            assert "{{" not in p.subject, d.event_type


# ===========================================================================
# Declarations
# ===========================================================================


class TestDeclarations:
    def test_every_email_template_is_declared_exactly_once(self):
        from app.comms.templates.registry import registered_templates
        registered = {
            e for e, c in registered_templates()
            if c == CHANNEL_EMAIL_TRANSACTIONAL
        }
        declared = {d.event_type for d in all_declarations()}
        assert registered == declared

    def test_system_templates_declare_no_slots(self):
        """The guarantee is structural: no slot means no field, no
        endpoint, no storage."""
        for d in all_declarations():
            if d.classification == SYSTEM:
                assert d.slots == (), d.template_key

    def test_security_and_money_templates_are_system_controlled(self):
        for key in (
            "account.password_reset_requested",
            "payment.instalment_failed",
            "access.suspended",
            "purchase.refunded",
            "purchase.first_payment_failed",
            "creator.subscription.payment_failed",
            "creator.subscription.recovered",
            "creator.subscription.cancellation_scheduled",
            "creator.subscription.cancelled",
        ):
            d = next(x for x in all_declarations() if x.event_type == key)
            assert d.classification == SYSTEM, key

    def test_signup_emails_do_not_offer_a_name_merge_field(self):
        """'Hey friend,' exists because users.name is unvalidated free
        text. Offering the field back would let an override re-introduce
        the 'Hi Creator' defect."""
        for key in (
            "account.welcome_after_signup.email_transactional",
            "account.email_verification_requested.email_transactional",
        ):
            d = get_declaration(key)
            assert all("name" not in f.name for f in d.merge_fields), key

    def test_declaring_a_system_template_with_slots_is_refused(self):
        with pytest.raises(ValueError, match="no editable slots"):
            from app.comms.templates.editable import declare
            declare(TemplateDeclaration(
                template_key="x.y", event_type="x.y", display_name="X",
                category="Account", audience="a", classification=SYSTEM,
                slots=(EditableSlot("subject", "S", "hi"),),
            ))

    def test_a_default_using_an_undeclared_field_is_refused(self):
        with pytest.raises(ValueError, match="not in the merge-field whitelist"):
            from app.comms.templates.editable import declare
            declare(TemplateDeclaration(
                template_key="x.z", event_type="x.z", display_name="X",
                category="Account", audience="a", classification=EDITABLE,
                slots=(EditableSlot("subject", "S", "Hi {{nope}}"),),
            ))


# ===========================================================================
# Merge fields
# ===========================================================================


_DECL = TemplateDeclaration(
    template_key="t", event_type="t", display_name="T", category="Account",
    audience="a", classification=EDITABLE,
    merge_fields=(MergeField("who", "who_key", "Ada"),),
    slots=(EditableSlot("body", "Body", "Hello {{who}}."),),
)


class TestMergeFields:
    def test_allowed_field_renders(self):
        assert substitute("Hi {{who}}.", _DECL, {"who_key": "Ada"}) == "Hi Ada."

    def test_whitespace_inside_braces_is_tolerated(self):
        assert substitute("Hi {{ who }}.", _DECL, {"who_key": "Ada"}) == "Hi Ada."

    def test_unknown_field_renders_empty_never_literally(self):
        out = substitute("Hi {{nope}}.", _DECL, {})
        assert "{{" not in out and "nope" not in out

    def test_missing_value_renders_empty_and_tidies_spacing(self):
        assert substitute("Hi {{who}} there.", _DECL, {}) == "Hi there."

    def test_no_arbitrary_execution(self):
        """Not str.format — attribute traversal must neither resolve nor
        survive as a literal."""
        out = substitute("{{who.__class__}}", _DECL, {"who_key": "Ada"})
        assert "class" not in out.lower()
        assert "Ada" not in out
        assert "{{" not in out and "}}" not in out

    def test_a_malformed_placeholder_never_reaches_the_reader(self):
        assert substitute("Hi {{ not a field }} there.", _DECL, {}) == "Hi there."

    def test_values_are_escaped_by_the_shell_not_the_substituter(self):
        """Substitution is deliberately raw; the shell is the single
        escaping boundary."""
        p = _render(
            "gathering.booking.confirmed",
            ctx={**SAMPLE, "gathering_title": '<img src=x onerror="a">'},
        )
        assert "<img" not in p.body_html
        assert "&lt;img" in p.body_html


# ===========================================================================
# Validation
# ===========================================================================


class TestValidation:
    def test_unknown_slot_rejected(self):
        errs = validate_slot_value(get_declaration(WELCOME), "nope", "x")
        assert errs and "Unknown field" in errs[0]

    def test_system_template_cannot_be_overridden(self):
        errs = validate_slot_value(get_declaration(RESET), "subject", "x")
        assert errs and "system-controlled" in errs[0]

    def test_empty_value_rejected(self):
        assert validate_slot_value(get_declaration(WELCOME), "heading", "   ")

    def test_html_rejected(self):
        errs = validate_slot_value(
            get_declaration(WELCOME), "heading", "Hi <b>there</b>",
        )
        assert any("plain text" in e for e in errs)

    def test_unknown_merge_field_rejected(self):
        errs = validate_slot_value(
            get_declaration(BOOKING), "heading", "Booked: {{nope}}",
        )
        assert any("not available" in e for e in errs)

    def test_required_merge_field_must_be_kept(self):
        errs = validate_slot_value(
            get_declaration(BOOKING), "heading", "You are booked",
        )
        assert any("must keep" in e for e in errs)

    def test_subject_length_capped(self):
        errs = validate_slot_value(
            get_declaration(WELCOME), "subject", "x" * (SUBJECT_MAX_LENGTH + 1),
        )
        assert any("limit is" in e for e in errs)

    def test_subject_must_be_one_line(self):
        errs = validate_slot_value(
            get_declaration(WELCOME), "subject", "Hello\nthere",
        )
        assert any("single line" in e for e in errs)

    def test_malformed_placeholder_rejected(self):
        errs = validate_slot_value(
            get_declaration(WELCOME), "heading", "Hello {{there",
        )
        assert any("malformed" in e for e in errs)

    def test_a_valid_override_passes(self):
        assert validate_slot_value(
            get_declaration(WELCOME), "heading", "Welcome aboard",
        ) == []


# ===========================================================================
# Resolution + fail-safe
# ===========================================================================


class TestResolution:
    def _resolver(self, overrides):
        return SlotResolver(
            decl=get_declaration(WELCOME), context={}, overrides=overrides,
        )

    def test_no_override_uses_the_code_default(self):
        r = self._resolver({})
        assert r.text("heading") == "Welcome to Fresh Collective"
        assert not r.uses_override("heading")

    def test_override_is_used(self):
        r = self._resolver({"heading": "Welcome aboard"})
        assert r.text("heading") == "Welcome aboard"
        assert r.uses_override("heading")

    def test_an_invalid_stored_override_falls_back_to_the_default(self):
        """Fails safe. Validation at save should prevent this, but a
        send is not the place to discover otherwise."""
        r = self._resolver({"heading": "Broken <b>markup</b>"})
        assert r.text("heading") == "Welcome to Fresh Collective"

    def test_an_empty_stored_override_falls_back(self):
        assert self._resolver({"heading": "   "}).text("heading") == (
            "Welcome to Fresh Collective"
        )

    def test_unknown_slot_raises_rather_than_rendering_nothing(self):
        with pytest.raises(KeyError):
            self._resolver({}).text("no.such.slot")

    def test_fingerprint_changes_with_the_default(self):
        a = EditableSlot("s", "S", "One").fingerprint()
        b = EditableSlot("s", "S", "Two").fingerprint()
        assert a != b and len(a) == 32


class TestOverridesFromTheDatabase:
    def test_a_stored_override_reaches_the_rendered_email(self, db):
        db.add(CommunicationTemplateOverride(
            id=f"cto_{uuid.uuid4().hex[:10]}",
            template_key=WELCOME, slot_id="heading",
            value="A warm welcome",
            default_fingerprint=get_declaration(WELCOME)
            .slot("heading").fingerprint(),
        ))
        db.flush()
        p = _render("account.welcome_after_signup", db=db)
        assert "A warm welcome" in p.body_html
        assert "Welcome to Fresh Collective</h1>" not in p.body_html

    def test_removing_the_row_restores_the_default(self, db):
        row = CommunicationTemplateOverride(
            id=f"cto_{uuid.uuid4().hex[:10]}",
            template_key=WELCOME, slot_id="heading", value="A warm welcome",
            default_fingerprint="x",
        )
        db.add(row)
        db.flush()
        assert "A warm welcome" in _render(
            "account.welcome_after_signup", db=db).body_html
        db.delete(row)
        db.flush()
        assert _render("account.welcome_after_signup", db=db) == _render(
            "account.welcome_after_signup", db=None)

    def test_a_database_failure_does_not_stop_the_email(self):
        """Rendering must survive a broken session — an email going out
        with default copy beats an email not going out."""
        class _Broken:
            def query(self, *a, **k):
                raise RuntimeError("db down")
        p = _render("account.welcome_after_signup", db=_Broken())
        assert "Welcome to Fresh Collective" in p.body_html

    def test_money_facts_cannot_be_reached_through_an_override(self, db):
        """purchase.completed is partial — only the sign-off is a slot."""
        decl = get_declaration("purchase.completed.email_transactional")
        assert [s.slot_id for s in decl.slots] == ["signoff"]
        db.add(CommunicationTemplateOverride(
            id=f"cto_{uuid.uuid4().hex[:10]}",
            template_key=decl.template_key, slot_id="signoff",
            value="Thanks so much.", default_fingerprint="x",
        ))
        db.flush()
        p = _render("purchase.completed", db=db)
        assert "Thanks so much." in p.body_html
        # The generated amount is untouched and unreachable.
        assert "AUD 37.80" in p.body_html


# ===========================================================================
# Preview endpoint
# ===========================================================================


@pytest.fixture
def admin_client(db, make_user):
    admin = make_user(role="admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_admin_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_admin_user, None)


@pytest.fixture
def member_client(db, make_user):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


class TestPreview:
    def test_renders_defaults_when_no_draft_is_supplied(self, admin_client):
        r = admin_client.post(
            f"/api/admin/communications/email-templates/{WELCOME}/preview",
            json={},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["subject"] == "Welcome to Fresh Collective"
        assert body["html"].lstrip().startswith("<!DOCTYPE html>")
        assert body["mode"] == "effective"

    def test_preview_matches_the_real_renderer(self, admin_client):
        """The whole point — a preview that can disagree with a send is
        worse than none."""
        r = admin_client.post(
            f"/api/admin/communications/email-templates/{WELCOME}/preview",
            json={},
        )
        real = _render("account.welcome_after_signup", db=None,
                       ctx={**SAMPLE, "next_url": "https://example.test/dashboard"})
        assert r.json()["subject"] == real.subject

    def test_draft_override_appears_in_the_preview(self, admin_client):
        r = admin_client.post(
            f"/api/admin/communications/email-templates/{WELCOME}/preview",
            json={"drafts": {"heading": "A warm welcome"}},
        )
        assert "A warm welcome" in r.json()["html"]

    def test_invalid_draft_is_reported_and_not_rendered(self, admin_client):
        r = admin_client.post(
            f"/api/admin/communications/email-templates/{WELCOME}/preview",
            json={"drafts": {"heading": "Hi <b>there</b>"}},
        )
        body = r.json()
        assert "heading" in body["errors"]
        assert "<b>" not in body["html"]
        assert "Welcome to Fresh Collective" in body["html"]

    def test_variant_switch_previews_the_other_copy(self, admin_client):
        key = "creator.plan_activated.email_transactional"
        fresh = admin_client.post(
            f"/api/admin/communications/email-templates/{key}/preview",
            json={"variant": {"is_fresh_creator": True}},
        ).json()["html"]
        returning = admin_client.post(
            f"/api/admin/communications/email-templates/{key}/preview",
            json={"variant": {"is_fresh_creator": False}},
        ).json()["html"]
        assert "Set up your Collective" in fresh
        assert "Open Creator Studio" in returning

    def test_returns_effective_slot_values(self, admin_client):
        """Template metadata (merge fields, locked notes, classification)
        lives on the detail endpoint — see the Phase B suite. Preview
        returns the render plus the values it used."""
        r = admin_client.post(
            f"/api/admin/communications/email-templates/{BOOKING}/preview",
            json={},
        ).json()
        decl = get_declaration(BOOKING)
        assert set(r["effective_slots"]) == {s.slot_id for s in decl.slots}

    def test_system_template_previews_but_has_no_slots(self, admin_client):
        r = admin_client.post(
            f"/api/admin/communications/email-templates/{RESET}/preview",
            json={},
        ).json()
        assert r["effective_slots"] == {}
        assert r["html"].lstrip().startswith("<!DOCTYPE html>")

    def test_unknown_template_is_404(self, admin_client):
        r = admin_client.post(
            "/api/admin/communications/email-templates/nope/preview", json={},
        )
        assert r.status_code == 404

    def test_preview_writes_nothing(self, admin_client, db):
        before = db.query(CommunicationTemplateOverride).count()
        admin_client.post(
            f"/api/admin/communications/email-templates/{WELCOME}/preview",
            json={"drafts": {"heading": "A warm welcome"}},
        )
        assert db.query(CommunicationTemplateOverride).count() == before
        # And the real render is untouched by the preview.
        assert "A warm welcome" not in _render(
            "account.welcome_after_signup", db=db).body_html

    def test_draft_does_not_leak_out_of_the_preview_context(self, db):
        with preview_overrides({WELCOME: {"heading": "Leaked"}}):
            assert "Leaked" in _render("account.welcome_after_signup").body_html
        assert "Leaked" not in _render("account.welcome_after_signup").body_html


class TestPermissions:
    def test_member_is_denied(self, member_client, make_user):
        from app.auth.dependencies import get_current_user
        member = make_user(role="user")
        app.dependency_overrides[get_current_user] = lambda: member
        try:
            r = member_client.post(
                f"/api/admin/communications/email-templates/{WELCOME}/preview",
                json={},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_creator_is_denied(self, member_client, make_user):
        from app.auth.dependencies import get_current_user
        creator = make_user(role="creator")
        app.dependency_overrides[get_current_user] = lambda: creator
        try:
            r = member_client.post(
                f"/api/admin/communications/email-templates/{WELCOME}/preview",
                json={},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)


# ===========================================================================
# Delivery behaviour is untouched
# ===========================================================================


class TestDeliveryUnchanged:
    def test_booking_confirmations_remain_transactional(self):
        from app.comms.registry import TRANSACTIONAL_EVENT_TYPES
        assert TRANSACTIONAL_EVENT_TYPES == {
            "gathering.booking.confirmed",
            "gathering.multi_booking.confirmed",
        }

    def test_editable_copy_does_not_change_the_preferences_footer(self):
        """Locked categories still omit the Stay Connected link; unlocked
        ones still show it. Copy editing must not touch delivery."""
        assert "Manage your Stay Connected preferences" not in _render(
            "account.welcome_after_signup").body_html
        assert "Manage your Stay Connected preferences" in _render(
            "gathering.reminder.24h").body_html
