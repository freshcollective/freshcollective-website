"""Preview variants — explicit declaration metadata, not inference.

A template that branches declares its branches. The admin UI reads that
declaration and never infers a control from a slot name, which is what
an earlier draft did and what these tests exist to prevent returning.

Three properties are load-bearing:

* the metadata is **complete** — every real branch in a template's
  ``render`` has a declared control, checked against the templates
  rather than against a list someone maintained by hand;
* the metadata is **closed** — a request names a declared option, so no
  caller can inject a context key of its own;
* the metadata is **inert** — selecting a variant renders differently
  and changes nothing else, in the database or in a real send.
"""

from __future__ import annotations

import inspect
import re

import pytest
from fastapi.testclient import TestClient

import app.comms.templates  # noqa: F401
import app.comms.routing.resolvers  # noqa: F401
from app.admin.email_templates import _NON_MERGE_SAMPLES
from app.auth.dependencies import get_admin_user
from app.comms.templates.editable import (
    PreviewVariant,
    PreviewVariantOption,
    TemplateDeclaration,
    all_declarations,
    get_declaration,
)
from app.comms.templates.registry import get_template_for
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.core.database import get_db
from app.main import app
from app.models.communication_template_override import (
    CommunicationTemplateOverride,
)

BASE = "/api/admin/communications/email-templates"
BOOKING = "gathering.booking.confirmed.email_transactional"
PLAN = "creator.plan_activated.email_transactional"
PURCHASE = "purchase.completed.email_transactional"
CANCELLED = "gathering.cancelled.email_transactional"
MULTI = "gathering.multi_booking.confirmed.email_transactional"
REFUND = "purchase.refunded.email_transactional"
RECOVERED = "payment.recovered.email_transactional"
WELCOME = "account.welcome_after_signup.email_transactional"


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


# ---------------------------------------------------------------------------
# The metadata is explicit
# ---------------------------------------------------------------------------


class TestNoInference:
    def test_no_slot_name_inference_remains_in_the_codebase(self):
        """The inferred implementation is gone, not merely unused.

        ``variant_flags`` was derived by substring-matching slot ids,
        so renaming ``body.fresh_creator`` silently removed a control.
        """
        import app.admin.email_templates as mod
        src = inspect.getsource(mod)
        assert "variant_flags" not in src
        # The overlay comes from the declaration, not from the request.
        assert "decl.variant_context(" in src
        # And no branch flag is named anywhere except in the sample
        # context it belongs to.
        after_samples = src.split("def sample_context", 1)[1]
        for flag in ("is_fresh_creator", "was_ticketed", "was_suspended",
                     "is_full_refund"):
            assert flag not in after_samples, flag

    def test_detail_exposes_variants_as_product_controls(self, client):
        r = client.get(f"{BASE}/{BOOKING}").json()
        [v] = r["preview_variants"]
        assert v["variant_id"] == "booking_source"
        assert v["label"] == "Booking source"
        assert [o["label"] for o in v["options"]] == [
            "Member booked", "Added by creator",
        ]

    def test_the_response_carries_no_context_payload(self, client):
        """The UI renders labels. Shipping the overlay would invite a
        client to start reasoning about internal flag names."""
        for v in client.get(f"{BASE}/{PLAN}").json()["preview_variants"]:
            for o in v["options"]:
                assert set(o) == {"value", "label", "is_default"}
            assert "is_fresh_creator" not in str(v)

    def test_exactly_one_default_option_per_variant(self, client):
        for decl in all_declarations():
            for v in decl.preview_variants:
                defaults = [o for o in v.options if o.is_default]
                assert len(defaults) == 1, f"{decl.template_key}.{v.variant_id}"
        # …and the API agrees about which one it is.
        [v] = client.get(f"{BASE}/{BOOKING}").json()["preview_variants"]
        assert [o["is_default"] for o in v["options"]] == [True, False]


# ---------------------------------------------------------------------------
# The metadata matches the templates
# ---------------------------------------------------------------------------


# Every ``bool(ctx.get(...))`` / ``payment_mode`` branch found in the
# email templates, and the control that must cover it.
_EXPECTED = {
    PLAN:       ("creator_state", {"returning", "fresh"}),
    BOOKING:    ("booking_source", {"self_booked", "added_by_creator"}),
    MULTI:      ("booking_source", {"self_booked", "added_by_creator"}),
    CANCELLED:  ("ticketing", {"paid", "free"}),
    PURCHASE:   ("payment_mode", {"plan", "single"}),
    RECOVERED:  ("access_state", {"still_active", "was_paused"}),
    REFUND:     ("refund_scope", {"partial", "full"}),
}


class TestCoverage:
    @pytest.mark.parametrize("key,expected", list(_EXPECTED.items()))
    def test_branching_template_declares_its_variant(self, key, expected):
        variant_id, values = expected
        decl = get_declaration(key)
        v = decl.variant(variant_id)
        assert v is not None, f"{key} lost its {variant_id} control"
        assert {o.value for o in v.options} == values

    def test_templates_without_branches_expose_no_controls(self):
        for decl in all_declarations():
            if decl.template_key in _EXPECTED:
                continue
            assert decl.preview_variants == (), decl.template_key

    def test_every_branching_email_template_is_covered(self):
        """Read the templates, not a hand-kept list.

        A new ``bool(ctx.get("some_flag"))`` in a render method fails
        this until it is either declared or explained here.
        """
        import app.comms.templates.account as account
        import app.comms.templates.gatherings as gatherings
        import app.comms.templates.purchases as purchases
        import app.comms.templates.creator_billing as billing
        import app.comms.templates.collective as collective
        import app.comms.templates.community as community
        import app.comms.templates.messages as messages
        import app.comms.templates.pathways as pathways

        flag_re = re.compile(r'bool\(ctx\.get\("([a-z_]+)"\)\)')
        declared: set[str] = set()
        for decl in all_declarations():
            for v in decl.preview_variants:
                for o in v.options:
                    declared.update(o.context)

        found: set[str] = set()
        for mod in (account, gatherings, purchases, billing, collective,
                    community, messages, pathways):
            for cls_name, cls in vars(mod).items():
                if not (inspect.isclass(cls) and hasattr(cls, "key")):
                    continue
                if not str(getattr(cls, "key", "")).endswith(
                    "email_transactional"
                ):
                    continue
                found.update(flag_re.findall(inspect.getsource(cls)))

        assert found, "the scan found no branches — it has stopped working"
        assert found <= declared, (
            f"email templates branch on {sorted(found - declared)} with no "
            "declared preview variant"
        )


# ---------------------------------------------------------------------------
# The metadata is closed
# ---------------------------------------------------------------------------


class TestClosedEnumeration:
    def test_unknown_variant_id_is_refused(self, client):
        r = client.post(f"{BASE}/{BOOKING}/preview",
                        json={"variant": {"made_up": "yes"}})
        assert r.status_code == 400

    def test_unknown_option_is_refused(self, client):
        r = client.post(f"{BASE}/{BOOKING}/preview",
                        json={"variant": {"booking_source": "telepathy"}})
        assert r.status_code == 400

    def test_a_caller_cannot_inject_a_context_key(self, client):
        """The old contract took ``{context_key: bool}``. It does not
        any more, and the key it used to accept is now just unknown."""
        r = client.post(f"{BASE}/{PLAN}/preview",
                        json={"variant": {"is_fresh_creator": "true"}})
        assert r.status_code == 400

    def test_a_template_with_no_variants_accepts_no_selection(self, client):
        r = client.post(f"{BASE}/{WELCOME}/preview",
                        json={"variant": {"booking_source": "self_booked"}})
        assert r.status_code == 400

    def test_declaration_refuses_a_variant_that_writes_a_merge_source(self):
        """A variant that rewrote a merge value would make the preview
        disagree with the field list the admin is reading beside it."""
        from app.comms.templates.editable import MergeField, declare
        with pytest.raises(ValueError, match="merge field's source"):
            declare(TemplateDeclaration(
                template_key="x.test", event_type="x.test", display_name="X",
                category="Account", audience="nobody",
                classification="system",
                merge_fields=(MergeField("c", "collective_name", "Sample"),),
                preview_variants=(PreviewVariant(
                    "v", "V", (
                        PreviewVariantOption("a", "A",
                                             {"collective_name": "x"}),
                        PreviewVariantOption("b", "B",
                                             {"collective_name": "y"}),
                    ),
                ),),
            ))

    def test_declaration_refuses_a_single_option_variant(self):
        from app.comms.templates.editable import declare
        with pytest.raises(ValueError, match="not a choice"):
            declare(TemplateDeclaration(
                template_key="x.test2", event_type="x.test2", display_name="X",
                category="Account", audience="nobody",
                classification="system",
                preview_variants=(PreviewVariant(
                    "v", "V",
                    (PreviewVariantOption("a", "A", {"flag": True}),),
                ),),
            ))


# ---------------------------------------------------------------------------
# The metadata is inert
# ---------------------------------------------------------------------------


class TestPreviewOnly:
    def test_default_selection_renders_what_no_selection_renders(self, client):
        for key in _EXPECTED:
            variant_id, _ = _EXPECTED[key]
            default = get_declaration(key).variant(variant_id).default_option
            a = client.post(f"{BASE}/{key}/preview", json={}).json()["html"]
            b = client.post(
                f"{BASE}/{key}/preview",
                json={"variant": {variant_id: default.value}},
            ).json()["html"]
            assert a == b, key

    def test_each_option_renders_materially_different_copy(self, client):
        """A control that changes nothing is a control that lies."""
        for key, (variant_id, _) in _EXPECTED.items():
            v = get_declaration(key).variant(variant_id)
            rendered = {
                o.value: client.post(
                    f"{BASE}/{key}/preview",
                    json={"variant": {variant_id: o.value}},
                ).json()["html"]
                for o in v.options
            }
            assert len(set(rendered.values())) == len(v.options), key

    def test_selecting_a_variant_writes_nothing(self, client, db):
        before = db.query(CommunicationTemplateOverride).count()
        for key, (variant_id, _) in _EXPECTED.items():
            for o in get_declaration(key).variant(variant_id).options:
                client.post(f"{BASE}/{key}/preview",
                            json={"variant": {variant_id: o.value}})
        assert db.query(CommunicationTemplateOverride).count() == before

    def test_a_variant_cannot_reach_a_real_send(self, db):
        """The overlay lands on fabricated sample context only. A real
        render reads its own event payload and never sees a variant."""
        template = get_template_for(
            "gathering.booking.confirmed", CHANNEL_EMAIL_TRANSACTIONAL,
        )
        from app.comms.routing.resolver import ResolvedRecipient
        payload = template.render(db, None, ResolvedRecipient(
            user_id="u", role_in_event="attendee", human_reason="test",
            template_context={
                "gathering_title": "Morning Sit",
                "collective_name": "Still Water",
                "gathering_starts_at": "Friday at 9:00am",
                # The real context decides. There is no variant here and
                # no way to supply one.
                "added_by_creator": True,
            },
        ))
        assert "You've been added to" in payload.body_text
        assert "booking_source" not in payload.body_html

    def test_variant_is_not_an_editable_field(self, client):
        detail = client.get(f"{BASE}/{BOOKING}").json()
        slot_ids = {s["slot_id"] for s in detail["slots"]}
        assert "booking_source" not in slot_ids
        r = client.put(f"{BASE}/{BOOKING}",
                       json={"overrides": {"booking_source": "self_booked"}})
        assert r.status_code == 422  # unknown slot — same refusal as any other
        assert "booking_source" in str(r.json()["detail"]["errors"])

    def test_variant_context_keys_are_all_real_sample_keys(self):
        """An overlay key the sample context does not already carry
        would mean the default preview renders a different branch from
        the one the default option claims."""
        for decl in all_declarations():
            for v in decl.preview_variants:
                for o in v.options:
                    for key in o.context:
                        assert key in _NON_MERGE_SAMPLES, (
                            f"{decl.template_key}.{v.variant_id}: {key}"
                        )

    def test_the_default_option_agrees_with_the_standing_sample(self):
        for decl in all_declarations():
            for v in decl.preview_variants:
                for key, value in v.default_option.context.items():
                    assert _NON_MERGE_SAMPLES[key] == value, (
                        f"{decl.template_key}.{v.variant_id}"
                    )


class TestTestSendUsesVariants:
    def test_test_send_accepts_the_same_selection(self, client, monkeypatch):
        from app.comms.providers.base import ProviderResult
        from app.comms.providers.resend import ResendProvider
        calls: list = []
        monkeypatch.setattr(
            ResendProvider, "send",
            lambda self, p: (calls.append(p),
                             ProviderResult(accepted=True,
                                            provider_message_id="m"))[1],
        )
        r = client.post(f"{BASE}/{BOOKING}/test-send",
                        json={"variant": {"booking_source": "added_by_creator"}})
        assert r.status_code == 200
        assert "You've been added to" in calls[0].body_text
