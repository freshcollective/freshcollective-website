"""Phase 2 — the transactional emails the audit found missing.

Three families:

* **Creator billing** — payment failed / recovered / cancellation
  scheduled / ended, emitted from the Stripe webhook handlers at the
  genuine state transitions only.
* **Refunds** — emitted from ``charge.refunded``, which Stripe fires
  only after a refund settles.
* **Gathering cancellation** — emitted when a creator cancels a whole
  gathering and attendees' bookings are released.

Both layers are covered: the webhook/domain layer (does the right
transition emit exactly one event?) and the template layer (does the
copy say something true, in the branded shell, without leaking
internal vocabulary?).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import app.comms.templates  # noqa: F401 — registers every template
import app.comms.routing.resolvers  # noqa: F401 — registers every resolver
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.registry import get_template_for
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.services.creator_plan_labels import creator_facing_plan_label


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

XSS = '<img src=x onerror="alert(1)">'


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _recipient(**ctx) -> ResolvedRecipient:
    return ResolvedRecipient(
        user_id="u_1", role_in_event="r", human_reason="h",
        template_context=ctx,
    )


def _render(event_type: str, **ctx):
    t = get_template_for(event_type, CHANNEL_EMAIL_TRANSACTIONAL)
    assert t is not None, f"no email template for {event_type!r}"
    return t.render(None, None, _recipient(**ctx))


def _paragraphs(html: str) -> list[str]:
    return [
        p.strip() for p in re.findall(
            r'<p style="margin:0;font-size:15\.5px[^"]*">\s*(.*?)\s*</p>',
            html, re.S,
        )
    ]


def _cta(html: str):
    m = re.search(
        r'<a href="([^"]+)"\s+style="[^"]*border-radius:999px[^"]*">'
        r'\s*(.*?)\s*</a>', html, re.S,
    )
    return (m.group(2).strip(), m.group(1)) if m else None


def _assert_shell(html: str) -> None:
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "Fresh Collective" in html
    assert "#F5F0E8" in html
    assert "text-transform:uppercase" not in html   # no eyebrows


def _ensure_plan(db, *, slug: str, name: str) -> CreatorPlan:
    plan = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
    if plan:
        return plan
    plan = CreatorPlan(
        id=_uid("cp"), name=name, slug=slug, monthly_price_cents=1900,
        transaction_fee_basis_points=800, collective_limit=1, is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


def _grant_sub(
    db, user, plan, *,
    status: CreatorSubscriptionStatus = CreatorSubscriptionStatus.active,
    stripe_subscription_id: str,
    grace_expires_at: datetime | None = None,
    cancel_at_period_end: bool = False,
    current_period_end: datetime | None = None,
) -> CreatorSubscription:
    sub = CreatorSubscription(
        id=_uid("sub"), user_id=user.id, creator_plan_id=plan.id,
        status=status, starts_at=datetime.utcnow(), source="stripe_paid",
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id="cus_test",
        grace_expires_at=grace_expires_at,
        cancel_at_period_end=cancel_at_period_end,
        current_period_end=current_period_end,
    )
    db.add(sub)
    db.flush()
    return sub


def _stripe_sub(sub_id: str, creator, *, slug="creator",
                cancel_at_period_end=False, period_end=None, status="active"):
    return {
        "id": sub_id,
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "current_period_end": period_end or int(
            (datetime.utcnow() + timedelta(days=30)).timestamp()
        ),
        "customer": "cus_test",
        "metadata": {
            "purchase_type": "creator_subscription",
            "creator_user_id": creator.id,
            "creator_plan_slug": slug,
        },
    }


def _events(db, event_type: str, subject_id: str) -> list[CommunicationEvent]:
    return (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.event_type == event_type,
            CommunicationEvent.subject_id == subject_id,
        )
        .all()
    )


@pytest.fixture(autouse=True)
def _no_dispatch():
    """Phase 2 tests assert on emitted events, never on delivery. Routing
    is stubbed so nothing reaches a provider."""
    with patch("app.comms.rollout.schedule_routing_if_needed", return_value=None):
        yield


# ===========================================================================
# 1. Creator billing — transitions
# ===========================================================================


class TestCreatorBillingPaymentFailed:
    def test_opening_a_grace_window_emits_once(self, db, make_user):
        from app.webhooks.creator_billing_handlers import (
            handle_invoice_payment_failed,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", name="Creator")
        sub = _grant_sub(db, creator, plan, stripe_subscription_id="sub_pf1")
        db.commit()

        with patch(
            "app.webhooks.creator_billing_handlers.scb.retrieve_subscription",
            return_value=_stripe_sub("sub_pf1", creator),
        ):
            handle_invoice_payment_failed(
                {"id": "in_1", "subscription": "sub_pf1"}, db,
                event_id="evt_pf_1", event_type="invoice.payment_failed",
            )
        db.expire_all()
        evs = _events(db, "creator.subscription.payment_failed", sub.id)
        assert len(evs) == 1
        # The grace deadline the copy will quote is carried on the event.
        assert evs[0].payload["grace_expires_at"]

    def test_retries_inside_one_grace_window_emit_nothing_further(
        self, db, make_user,
    ):
        """Stripe retries a failing invoice several times inside our
        7-day window. Only the failure that OPENS the window emails."""
        from app.webhooks.creator_billing_handlers import (
            handle_invoice_payment_failed,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", name="Creator")
        sub = _grant_sub(db, creator, plan, stripe_subscription_id="sub_pf2")
        db.commit()

        with patch(
            "app.webhooks.creator_billing_handlers.scb.retrieve_subscription",
            return_value=_stripe_sub("sub_pf2", creator),
        ):
            for n in range(3):
                handle_invoice_payment_failed(
                    {"id": f"in_{n}", "subscription": "sub_pf2"}, db,
                    event_id=f"evt_pf2_{n}",
                    event_type="invoice.payment_failed",
                )
        db.expire_all()
        assert len(_events(db, "creator.subscription.payment_failed", sub.id)) == 1

    def test_grace_window_is_seven_days(self, db, make_user):
        from app.webhooks.creator_billing_handlers import (
            handle_invoice_payment_failed,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", name="Creator")
        sub = _grant_sub(db, creator, plan, stripe_subscription_id="sub_pf3")
        db.commit()
        before = datetime.utcnow()
        with patch(
            "app.webhooks.creator_billing_handlers.scb.retrieve_subscription",
            return_value=_stripe_sub("sub_pf3", creator),
        ):
            handle_invoice_payment_failed(
                {"id": "in_x", "subscription": "sub_pf3"}, db,
                event_id="evt_pf_3", event_type="invoice.payment_failed",
            )
        db.expire_all()
        row = db.query(CreatorSubscription).filter(
            CreatorSubscription.id == sub.id).one()
        assert row.status == CreatorSubscriptionStatus.past_due
        delta = row.grace_expires_at - before
        assert timedelta(days=6, hours=23) <= delta <= timedelta(days=7, minutes=5)

    def test_duplicate_webhook_delivery_emits_nothing_further(
        self, db, make_user,
    ):
        from app.webhooks.creator_billing_handlers import (
            handle_invoice_payment_failed,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", name="Creator")
        sub = _grant_sub(db, creator, plan, stripe_subscription_id="sub_pf4")
        db.commit()
        with patch(
            "app.webhooks.creator_billing_handlers.scb.retrieve_subscription",
            return_value=_stripe_sub("sub_pf4", creator),
        ):
            for _ in range(3):          # same Stripe event id each time
                handle_invoice_payment_failed(
                    {"id": "in_dup", "subscription": "sub_pf4"}, db,
                    event_id="evt_same", event_type="invoice.payment_failed",
                )
        db.expire_all()
        assert len(_events(db, "creator.subscription.payment_failed", sub.id)) == 1


class TestCreatorBillingRecovered:
    def test_recovery_from_past_due_emits_once(self, db, make_user):
        from app.webhooks.creator_billing_handlers import handle_invoice_paid
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", name="Creator")
        sub = _grant_sub(
            db, creator, plan, stripe_subscription_id="sub_rec1",
            status=CreatorSubscriptionStatus.past_due,
            grace_expires_at=datetime.utcnow() + timedelta(days=3),
        )
        db.commit()
        with patch(
            "app.webhooks.creator_billing_handlers.scb.retrieve_subscription",
            return_value=_stripe_sub("sub_rec1", creator),
        ):
            handle_invoice_paid(
                {"id": "in_r1", "subscription": "sub_rec1"}, db,
                event_id="evt_rec_1", event_type="invoice.paid",
            )
        db.expire_all()
        assert len(_events(db, "creator.subscription.recovered", sub.id)) == 1
        row = db.query(CreatorSubscription).filter(
            CreatorSubscription.id == sub.id).one()
        assert row.status == CreatorSubscriptionStatus.active
        assert row.grace_expires_at is None

    def test_ordinary_renewal_while_active_emits_nothing(self, db, make_user):
        """An invoice.paid for an already-active subscription is the
        monthly renewal, not a recovery. No email."""
        from app.webhooks.creator_billing_handlers import handle_invoice_paid
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", name="Creator")
        sub = _grant_sub(
            db, creator, plan, stripe_subscription_id="sub_rec2",
            status=CreatorSubscriptionStatus.active,
        )
        db.commit()
        with patch(
            "app.webhooks.creator_billing_handlers.scb.retrieve_subscription",
            return_value=_stripe_sub("sub_rec2", creator),
        ):
            handle_invoice_paid(
                {"id": "in_r2", "subscription": "sub_rec2"}, db,
                event_id="evt_rec_2", event_type="invoice.paid",
            )
        db.expire_all()
        assert _events(db, "creator.subscription.recovered", sub.id) == []


class TestCreatorBillingCancellation:
    def test_scheduling_a_cancellation_emits_scheduled_not_ended(
        self, db, make_user,
    ):
        from app.webhooks.creator_billing_handlers import (
            handle_subscription_updated,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", name="Creator")
        sub = _grant_sub(
            db, creator, plan, stripe_subscription_id="sub_cs1",
            cancel_at_period_end=False,
        )
        db.commit()
        handle_subscription_updated(
            _stripe_sub("sub_cs1", creator, cancel_at_period_end=True), db,
            event_id="evt_cs_1", event_type="customer.subscription.updated",
        )
        db.expire_all()
        assert len(
            _events(db, "creator.subscription.cancellation_scheduled", sub.id)
        ) == 1
        # Distinct states — nothing has ended yet.
        assert _events(db, "creator.subscription.cancelled", sub.id) == []

    def test_restating_an_already_scheduled_cancellation_is_silent(
        self, db, make_user,
    ):
        from app.webhooks.creator_billing_handlers import (
            handle_subscription_updated,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", name="Creator")
        sub = _grant_sub(
            db, creator, plan, stripe_subscription_id="sub_cs2",
            cancel_at_period_end=True,
        )
        db.commit()
        handle_subscription_updated(
            _stripe_sub("sub_cs2", creator, cancel_at_period_end=True), db,
            event_id="evt_cs_2", event_type="customer.subscription.updated",
        )
        db.expire_all()
        assert _events(
            db, "creator.subscription.cancellation_scheduled", sub.id) == []

    def test_subscription_deleted_emits_cancelled_once(self, db, make_user):
        from app.webhooks.creator_billing_handlers import (
            handle_subscription_deleted,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", name="Creator")
        sub = _grant_sub(db, creator, plan, stripe_subscription_id="sub_del1")
        db.commit()
        handle_subscription_deleted(
            _stripe_sub("sub_del1", creator, status="canceled"), db,
            event_id="evt_del_1", event_type="customer.subscription.deleted",
        )
        db.expire_all()
        assert len(_events(db, "creator.subscription.cancelled", sub.id)) == 1
        row = db.query(CreatorSubscription).filter(
            CreatorSubscription.id == sub.id).one()
        assert row.status == CreatorSubscriptionStatus.cancelled

    def test_deleted_replay_emits_nothing_further(self, db, make_user):
        from app.webhooks.creator_billing_handlers import (
            handle_subscription_deleted,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", name="Creator")
        sub = _grant_sub(db, creator, plan, stripe_subscription_id="sub_del2")
        db.commit()
        for n in range(3):
            handle_subscription_deleted(
                _stripe_sub("sub_del2", creator, status="canceled"), db,
                event_id=f"evt_del2_{n}",
                event_type="customer.subscription.deleted",
            )
        db.expire_all()
        assert len(_events(db, "creator.subscription.cancelled", sub.id)) == 1


# ===========================================================================
# 2. Creator billing — copy
# ===========================================================================


CREATOR_BILLING_EMAILS = [
    ("creator.subscription.payment_failed",
     {"first_name": "Grace", "plan_label": "Creator Portfolio",
      "billing_url": "https://fc.test/b",
      "grace_expires_at": "2026-09-25T00:00:00"}),
    ("creator.subscription.recovered",
     {"first_name": "Grace", "plan_label": "Creator Portfolio",
      "billing_url": "https://fc.test/b",
      "current_period_end": "2026-10-25T00:00:00"}),
    ("creator.subscription.cancellation_scheduled",
     {"first_name": "Grace", "plan_label": "Creator Portfolio",
      "billing_url": "https://fc.test/b",
      "current_period_end": "2026-10-25T00:00:00"}),
    ("creator.subscription.cancelled",
     {"first_name": "Grace", "plan_label": "Creator Portfolio",
      "billing_url": "https://fc.test/b"}),
]


class TestCreatorBillingCopy:
    @pytest.mark.parametrize("event_type,ctx", CREATOR_BILLING_EMAILS)
    def test_uses_shared_branded_shell(self, event_type, ctx):
        _assert_shell(_render(event_type, **ctx).body_html)

    @pytest.mark.parametrize("event_type,ctx", CREATOR_BILLING_EMAILS)
    def test_has_a_billing_cta(self, event_type, ctx):
        label, url = _cta(_render(event_type, **ctx).body_html)
        assert label
        assert url == "https://fc.test/b"

    def test_payment_failed_says_plan_is_still_active(self):
        p = _render(
            "creator.subscription.payment_failed",
            first_name="Grace", plan_label="Creator Portfolio",
            billing_url="https://fc.test/b",
            grace_expires_at="2026-09-25T00:00:00",
        )
        html = p.body_html
        assert "still active" in html
        # Must NOT claim suspension has already happened.
        for forbidden in ("has been paused", "is suspended", "access has been"):
            assert forbidden not in html
        # The grace deadline is quoted.
        assert "25 September 2026" in html

    def test_payment_failed_without_deadline_falls_back_to_seven_days(self):
        html = _render(
            "creator.subscription.payment_failed",
            first_name="Grace", plan_label="Creator",
            billing_url="https://fc.test/b", grace_expires_at=None,
        ).body_html
        assert "7-day grace period" in html

    def test_recovered_is_not_alarmist(self):
        html = _render(
            "creator.subscription.recovered",
            first_name="Grace", plan_label="Creator Portfolio",
            billing_url="https://fc.test/b",
            current_period_end="2026-10-25T00:00:00",
        ).body_html
        assert "gone through" in html
        assert "active" in html
        for alarm in ("problem", "failed", "overdue", "urgent", "suspend"):
            assert alarm not in html.lower()

    def test_cancellation_scheduled_states_end_date_and_keeps_access(self):
        html = _render(
            "creator.subscription.cancellation_scheduled",
            first_name="Grace", plan_label="Creator Portfolio",
            billing_url="https://fc.test/b",
            current_period_end="2026-10-25T00:00:00",
        ).body_html
        assert "25 October 2026" in html
        assert "active" in html
        assert "has ended" not in html      # distinct from the ended email

    def test_ended_does_not_imply_member_purchases_were_removed(self):
        html = _render(
            "creator.subscription.cancelled",
            first_name="Grace", plan_label="Creator Portfolio",
            billing_url="https://fc.test/b",
        ).body_html
        assert "has now ended" in html
        assert "new paid offers" in html
        # The critical reassurance.
        assert "Nothing has been cancelled or refunded." in html
        assert "continue exactly as before" in html

    @pytest.mark.parametrize("event_type,ctx", CREATOR_BILLING_EMAILS)
    def test_never_exposes_the_internal_pro_label(self, event_type, ctx):
        """Whatever the plan row is called internally, creator-facing
        copy must read Creator Portfolio."""
        ctx = dict(ctx)
        ctx["plan_label"] = creator_facing_plan_label(slug="pro", name="Pro")
        p = _render(event_type, **ctx)
        assert "Creator Portfolio" in p.body_text
        assert "Pro" not in p.body_text


class TestCreatorPlanLabels:
    def test_pro_slug_maps_to_creator_portfolio(self):
        assert creator_facing_plan_label(slug="pro") == "Creator Portfolio"

    def test_pro_name_maps_even_without_a_slug(self):
        assert creator_facing_plan_label(name="Pro") == "Creator Portfolio"
        assert creator_facing_plan_label(name="pro") == "Creator Portfolio"

    def test_other_plans_pass_through(self):
        assert creator_facing_plan_label(slug="creator", name="Creator") == "Creator"
        assert creator_facing_plan_label(name="Organisation") == "Organisation"

    def test_empty_falls_back_to_creator(self):
        assert creator_facing_plan_label() == "Creator"
        assert creator_facing_plan_label(slug="", name="  ") == "Creator"

    def test_activation_email_translates_the_internal_name(self):
        """The already-live activation email rendered "Pro" before P2."""
        html = _render(
            "creator.plan_activated",
            first_name="Grace", plan_name="Pro",
            next_url="https://fc.test/s", is_fresh_creator=False,
        ).body_html
        assert "Creator Portfolio" in html
        assert ">Pro<" not in html
        assert "Fresh Collective <strong>Pro</strong>" not in html


# ===========================================================================
# 3. Refunds
# ===========================================================================


class TestRefundEmail:
    @staticmethod
    def _txn(**overrides):
        """Minimal stand-in. ``emit_purchase_refunded`` only reads
        attributes, and these guard-path tests return before any query
        runs, so a namespace keeps the test honest without dragging in
        the full PaymentTransaction column set."""
        from types import SimpleNamespace
        fields = {
            "id": "txn_1", "payer_user_id": "u_1", "currency": "aud",
            "space_id": None, "pathway_id": None, "status": None,
        }
        fields.update(overrides)
        return SimpleNamespace(**fields)

    def test_only_a_real_increase_emits(self, db):
        """A refund that was merely requested, or a same-value webhook
        re-delivery, must not produce an email."""
        from app.services.refund_emit import emit_purchase_refunded
        txn = self._txn()
        # Zero and negative deltas emit nothing at all.
        assert emit_purchase_refunded(
            db, txn=txn, refund_amount_cents=0,
            cumulative_refunded_cents=1000,
        ) is None
        assert emit_purchase_refunded(
            db, txn=txn, refund_amount_cents=-500,
            cumulative_refunded_cents=1000,
        ) is None

    def test_no_payer_means_nobody_to_notify(self, db):
        from app.services.refund_emit import emit_purchase_refunded
        assert emit_purchase_refunded(
            db, txn=self._txn(id="txn_2", payer_user_id=None),
            refund_amount_cents=500, cumulative_refunded_cents=500,
        ) is None

    def test_partial_and_full_read_differently(self):
        partial = _render(
            "purchase.refunded", first_name="Ada", amount_cents=1000,
            currency="AUD", item_name="Life in Alignment",
            collective_name="Still Water", is_full_refund=False,
        ).body_html
        full = _render(
            "purchase.refunded", first_name="Ada", amount_cents=2000,
            currency="AUD", item_name="Life in Alignment",
            collective_name="Still Water", is_full_refund=True,
        ).body_html
        assert "partial refund" in partial
        assert "full amount" in full
        assert "partial refund" not in full

    def test_states_amount_item_and_collective(self):
        html = _render(
            "purchase.refunded", first_name="Ada", amount_cents=2000,
            currency="AUD", item_name="Life in Alignment",
            collective_name="Still Water", is_full_refund=True,
        ).body_html
        assert "AUD 20.00" in html
        assert "Life in Alignment" in html
        assert "Still Water" in html

    def test_settlement_timing_is_attributed_to_the_bank(self):
        html = _render(
            "purchase.refunded", first_name="Ada", amount_cents=2000,
            currency="AUD", item_name="X", is_full_refund=True,
        ).body_html
        assert "bank or card provider" in html
        # Never promise a Fresh Collective-controlled timeframe.
        for overclaim in ("within 24 hours", "immediately", "instantly"):
            assert overclaim not in html.lower()

    def test_never_exposes_creator_payout_accounting(self):
        html = _render(
            "purchase.refunded", first_name="Ada", amount_cents=2000,
            currency="AUD", item_name="X", collective_name="Y",
            is_full_refund=True,
        ).body_html
        for internal in ("platform fee", "payout", "net", "basis point"):
            assert internal not in html.lower()

    def test_falls_back_through_item_then_collective(self):
        assert "Still Water" in _render(
            "purchase.refunded", amount_cents=100, currency="AUD",
            collective_name="Still Water", item_name="",
        ).subject
        assert "your purchase" in _render(
            "purchase.refunded", amount_cents=100, currency="AUD",
        ).subject

    def test_uses_shared_branded_shell(self):
        _assert_shell(_render(
            "purchase.refunded", first_name="Ada", amount_cents=100,
            currency="AUD", item_name="X",
        ).body_html)


# ===========================================================================
# 4. Gathering cancellation
# ===========================================================================


class TestGatheringCancelledCopy:
    def test_uses_shared_branded_shell(self):
        _assert_shell(_render(
            "gathering.cancelled", gathering_title="Morning Sit",
            gathering_starts_at="20 September 2026 at 9:00am",
            collective_name="Still Water",
        ).body_html)

    def test_names_the_gathering_and_releases_the_place(self):
        p = _render(
            "gathering.cancelled", gathering_title="Morning Sit",
            gathering_starts_at="20 September 2026 at 9:00am",
            collective_name="Still Water",
        )
        assert p.subject == "Cancelled: Morning Sit"
        assert "has been cancelled" in p.body_html
        assert "released" in p.body_html
        assert "20 September 2026" in p.body_html

    def test_mentions_refund_only_for_ticketed_bookings(self):
        ticketed = _render(
            "gathering.cancelled", gathering_title="G",
            was_ticketed=True,
        ).body_html
        free = _render(
            "gathering.cancelled", gathering_title="G",
            was_ticketed=False,
        ).body_html
        assert "refund will be confirmed" in ticketed
        assert "refund" not in free

    def test_resolver_fans_out_to_captured_attendees_only(self):
        from app.comms.routing.resolver import get_resolver_for
        resolver = get_resolver_for("gathering.cancelled")
        assert resolver is not None
        event = CommunicationEvent(
            id="ce_1", event_type="gathering.cancelled",
            payload={
                "recipient_user_ids": ["u_a", "u_b", None, ""],
                "gathering_title": "Morning Sit",
                "collective_name": "Still Water",
            },
        )
        recipients = resolver.resolve(None, event)
        assert [r.user_id for r in recipients] == ["u_a", "u_b"]

    def test_no_attendees_resolves_to_nobody(self):
        from app.comms.routing.resolver import get_resolver_for
        resolver = get_resolver_for("gathering.cancelled")
        event = CommunicationEvent(
            id="ce_2", event_type="gathering.cancelled",
            payload={"recipient_user_ids": []},
        )
        assert resolver.resolve(None, event) == []


# ===========================================================================
# 5. Escaping — user-generated content across every new template
# ===========================================================================


class TestNewTemplatesEscapeUserContent:
    @pytest.mark.parametrize("event_type,ctx,field", [
        ("purchase.refunded",
         {"item_name": XSS, "amount_cents": 100, "currency": "AUD"},
         "item_name"),
        ("purchase.refunded",
         {"collective_name": XSS, "item_name": "", "amount_cents": 100,
          "currency": "AUD"}, "collective_name"),
        ("gathering.cancelled",
         {"gathering_title": XSS}, "gathering_title"),
        ("gathering.cancelled",
         {"gathering_title": "G", "collective_name": XSS}, "collective_name"),
        ("creator.subscription.payment_failed",
         {"plan_label": XSS, "billing_url": "https://fc.test/b"},
         "plan_label"),
        ("creator.subscription.cancelled",
         {"plan_label": XSS, "billing_url": "https://fc.test/b"},
         "plan_label"),
    ])
    def test_markup_cannot_be_injected(self, event_type, ctx, field):
        html = _render(event_type, **ctx).body_html
        # One <img> in the document: the brand logo in the shell header.
        assert "<img src=x" not in html, f"{event_type}.{field} not escaped"
        assert html.count("<img") == 1, f"{event_type}.{field} added an image"
        assert "&lt;img src=x" in html, f"{event_type}.{field} lost its value"

    def test_ampersands_are_not_double_escaped(self):
        html = _render(
            "gathering.cancelled", gathering_title="Tea & Quiet",
        ).body_html
        assert "Tea &amp; Quiet" in html
        assert "&amp;amp;" not in html
