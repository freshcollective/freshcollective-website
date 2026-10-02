"""Regression: the creator-billing invoice handlers must normalise the
Subscription they fetch from Stripe before reading it.

The production failure, in order:

  1. A member bought a finite payment plan. Stripe collected the first
     $2 instalment and fired both ``invoice.paid`` and
     ``invoice.payment_succeeded``.
  2. The dispatcher routes BOTH of those event types through
     ``creator_billing_handlers.handle_invoice_paid`` first, because an
     Invoice carries no metadata of its own — the creator/member
     discrimination needs the underlying Subscription.
  3. ``scb.retrieve_subscription`` returned a raw ``stripe.Subscription``
     by design: the service layer hands back Stripe resources and lets
     callers own conversion.
  4. ``is_creator_subscription(sub)`` then called ``sub.get("metadata")``.
     A ``StripeObject`` in stripe-python 15.x has no ``.get()``, so that
     raised ``AttributeError: get`` — chained from ``KeyError: 'get'``,
     which is the line that surfaced first in the Render traceback.
  5. Nothing caught it (the ``except`` there is scoped to
     ``stripe.error.StripeError``), so FC returned 500 for a payment
     Stripe had already taken.

The damage was not confined to creator billing. The crash happened
*before* the discriminator returned a verdict, so a finite-plan invoice
500'd on a code path that was never meant to claim it.

Why the existing coverage missed it: every test of these handlers
patches ``retrieve_subscription`` with a plain ``dict``, which has
``.get()``. A dict can never reproduce this bug. Every test here builds
a real ``stripe.Subscription`` via ``_construct_from`` — the same type
the live SDK returns — so the fixture is hostile in exactly the way
production was.

The fix is one call to the shared
``app.checkout.stripe_client.to_plain_dict`` at each point a
Subscription enters the handler, on both the invoice.paid and the
invoice.payment_failed path.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import stripe
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.services import stripe_creator_billing as scb


# The live subscription from the incident, and the plan id its metadata
# carried. Kept verbatim so a future reader can tie the test back to the
# Stripe dashboard record.
LIVE_SUB_ID = "sub_1UM4kjIHWmUObCoGIZiOy1z3"
LIVE_PURCHASE_PLAN_ID = "pplan_063c986728054f36a8e1abfa"

_RETRIEVE = "app.webhooks.creator_billing_handlers.scb.retrieve_subscription"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# The hostile fixture — a real StripeObject, not a dict
# ---------------------------------------------------------------------------


def _real_subscription(**overrides) -> stripe.Subscription:
    """A ``stripe.Subscription`` of the type the SDK actually returns.

    ``_construct_from`` is how the SDK itself materialises a resource
    from an API response, so this is the production object shape and
    not an approximation of it. Deliberately NOT a dict and NOT a
    SimpleNamespace: a test double that happens to implement ``.get()``
    is what let this bug reach live.
    """
    period_end = int((datetime.utcnow() + timedelta(days=30)).timestamp())
    values = {
        "id": LIVE_SUB_ID,
        "object": "subscription",
        "status": "active",
        "customer": "cus_live_x",
        "current_period_start": period_end - 30 * 86_400,
        "current_period_end": period_end,
        "cancel_at_period_end": False,
        # Nested StripeObjects on purpose — a shallow conversion would
        # leave these to fail later and further away.
        "items": {
            "object": "list",
            "has_more": False,
            "data": [{"id": "si_live_x", "price": {"id": "price_live_x"}}],
        },
        "metadata": {"purchase_plan_id": LIVE_PURCHASE_PLAN_ID},
    }
    values.update(overrides)
    return stripe.Subscription._construct_from(
        values=values, requestor=None, api_mode="V1",
    )


def _finite_plan_subscription() -> stripe.Subscription:
    """The incident's subscription: a member finite plan, carrying
    ``purchase_plan_id`` and no creator-billing discriminator."""
    return _real_subscription()


def _creator_subscription(*, creator_user_id: str, plan_slug: str = "creator",
                          sub_id: str = "sub_creator_live") -> stripe.Subscription:
    return _real_subscription(
        id=sub_id,
        metadata={
            "purchase_type": "creator_subscription",
            "creator_user_id": creator_user_id,
            "creator_plan_slug": plan_slug,
        },
    )


def _invoice(*, subscription_id: str, invoice_id: str | None = None) -> dict:
    """The Invoice as the dispatcher hands it to the handler: already a
    plain dict, because ``routes.py`` round-trips it through JSON. Only
    the Subscription we fetch ourselves is a StripeObject."""
    return {
        "id": invoice_id or f"in_{uuid.uuid4().hex[:16]}",
        "object": "invoice",
        "status": "paid",
        "subscription": subscription_id,
        "total": 200,
        "amount_paid": 200,
        "currency": "aud",
        "charge": None,
        "payment_intent": None,
    }


def _ensure_plan(db, *, slug: str = "creator") -> CreatorPlan:
    plan = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
    if plan:
        return plan
    plan = CreatorPlan(
        id=_uid("cp"),
        name=slug.title(),
        slug=slug,
        monthly_price_cents=1900,
        transaction_fee_basis_points=800,
        collective_limit=1,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


# ---------------------------------------------------------------------------
# Premise — if these stop holding, the fix is moot and this file should be
# revisited rather than deleted
# ---------------------------------------------------------------------------


class TestThePremise:
    def test_a_real_subscription_is_not_a_dict_and_has_no_get(self):
        sub = _real_subscription()
        assert not isinstance(sub, dict)
        with pytest.raises(AttributeError) as exc:
            sub.get("metadata")  # type: ignore[attr-defined]
        # The Render traceback led with ``KeyError: 'get'`` because the
        # SDK chains it as the cause of the AttributeError it raises.
        assert isinstance(exc.value.__cause__, KeyError)
        assert exc.value.__cause__.args == ("get",)

    def test_subscript_access_works_which_is_why_dict_doubles_hid_this(self):
        """The handlers read with ``.get()``; the object only supports
        ``[]``. A dict supports both, so a dict fixture proves nothing."""
        sub = _real_subscription()
        assert sub["metadata"]["purchase_plan_id"] == LIVE_PURCHASE_PLAN_ID
        assert {}.get("metadata") is None  # a dict would have sailed through

    def test_the_discriminator_is_the_crash_site(self):
        """The precise reason a finite-plan invoice 500'd: the creator
        gate blew up before it could decline the event."""
        with pytest.raises(AttributeError):
            scb.is_creator_subscription(_real_subscription())

    def test_to_plain_dict_makes_the_discriminator_safe(self):
        """And the shared helper is sufficient — no new converter needed."""
        from app.checkout.stripe_client import to_plain_dict

        normalised = to_plain_dict(_real_subscription())
        assert type(normalised) is dict
        assert type(normalised["items"]) is dict          # recursive, not shallow
        assert scb.is_creator_subscription(normalised) is False


# ---------------------------------------------------------------------------
# Proofs 1 + 2 — the finite-plan invoice no longer 500s, on both event types
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db, monkeypatch):
    """TestClient wired to the test session, with Stripe configured and
    signature verification bypassed, so ``POST /api/webhooks/stripe``
    reaches the dispatcher."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _post_event(client, monkeypatch, *, event_type: str, invoice: dict):
    event = stripe.Event.construct_from(
        {
            "id": f"evt_test_{uuid.uuid4().hex[:16]}",
            "type": event_type,
            "livemode": False,
            "created": 1_700_000_000,
            "api_version": "2024-10-28.acacia",
            "data": {"object": invoice},
        },
        "sk_test_dummy",
    )
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda **_: event)
    return client.post(
        "/api/webhooks/stripe",
        headers={"Stripe-Signature": "irrelevant, mocked"},
        content=b"{}",
    )


class TestFinitePlanInvoiceNoLongerFivehundreds:
    """The live incident, driven through the real HTTP dispatcher.

    Stripe fired both event types for the one $2 instalment and FC
    500'd on both, so both are covered. The finite-plan handler is left
    real and finds no local ``PurchasePlan`` for this subscription,
    which is its own ``SkipWebhookEvent`` no-op — the point is that the
    creator-billing discriminator in front of it no longer crashes.
    """

    @pytest.mark.parametrize(
        "event_type", ["invoice.payment_succeeded", "invoice.paid"],
    )
    def test_finite_plan_invoice_returns_200(
        self, client, monkeypatch, event_type,
    ):
        with patch(_RETRIEVE, return_value=_finite_plan_subscription()):
            resp = _post_event(
                client, monkeypatch,
                event_type=event_type,
                invoice=_invoice(subscription_id=LIVE_SUB_ID),
            )

        assert resp.status_code == 200, (
            f"{event_type} 5xx = the StripeObject boundary regressed; "
            f"body: {resp.text!r}"
        )
        assert resp.json() == {"received": True}

    @pytest.mark.parametrize(
        "event_type", ["invoice.payment_succeeded", "invoice.paid"],
    )
    def test_the_event_reaches_the_finite_plan_handler(
        self, client, monkeypatch, event_type,
    ):
        """Not 500ing is half the requirement. The event must actually
        fall THROUGH to the finite-plan handler — a creator-billing
        handler that swallowed it would also return 200, and the
        instalment would silently never be recorded."""
        finite_handler = MagicMock()
        monkeypatch.setattr(
            "app.webhooks.finite_plan_handlers.handle_invoice_payment_succeeded",
            finite_handler,
        )
        invoice = _invoice(subscription_id=LIVE_SUB_ID)

        with patch(_RETRIEVE, return_value=_finite_plan_subscription()):
            resp = _post_event(
                client, monkeypatch, event_type=event_type, invoice=invoice,
            )

        assert resp.status_code == 200
        finite_handler.assert_called_once()
        forwarded_invoice = finite_handler.call_args.args[0]
        assert forwarded_invoice["id"] == invoice["id"]
        assert forwarded_invoice["subscription"] == LIVE_SUB_ID


# ---------------------------------------------------------------------------
# Proof 3 — creator-subscription invoice handling still works
# ---------------------------------------------------------------------------


class TestCreatorSubscriptionInvoiceStillWorks:
    def test_invoice_paid_activates_the_row_from_a_real_stripe_object(
        self, db, make_user,
    ):
        """The creator path reads far more off the Subscription than the
        discriminator does — ``metadata``, ``customer``,
        ``current_period_end``, ``cancel_at_period_end``. All of those
        are ``.get()`` reads, so all of them needed the normalisation,
        and this asserts the values landed rather than merely that
        nothing raised."""
        from app.webhooks.creator_billing_handlers import handle_invoice_paid

        creator = make_user(role="creator")
        plan = _ensure_plan(db)
        db.add(CreatorSubscription(
            id=_uid("csub"),
            user_id=creator.id,
            creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.past_due,
            starts_at=datetime.utcnow(),
            source="stripe_paid",
            stripe_subscription_id="sub_creator_live",
            stripe_customer_id="cus_live_x",
            grace_expires_at=datetime.utcnow() + timedelta(days=3),
        ))
        db.commit()

        subscription = _creator_subscription(creator_user_id=creator.id)
        with patch(_RETRIEVE, return_value=subscription):
            handled = handle_invoice_paid(
                _invoice(subscription_id="sub_creator_live"),
                db,
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                event_type="invoice.paid",
            )

        assert handled is True
        db.expire_all()
        row = (
            db.query(CreatorSubscription)
            .filter(CreatorSubscription.stripe_subscription_id == "sub_creator_live")
            .first()
        )
        assert row.status == CreatorSubscriptionStatus.active
        assert row.grace_expires_at is None
        assert row.cancel_at_period_end is False
        # Read off the StripeObject's ``current_period_end`` — proof the
        # conversion carried real values through, not just empty defaults.
        assert row.current_period_end == datetime.utcfromtimestamp(
            subscription["current_period_end"],
        )

    def test_invoice_payment_failed_opens_grace_from_a_real_stripe_object(
        self, db, make_user,
    ):
        """The second raw-retrieve boundary in this module. It is on a
        live route — ``invoice.payment_failed`` goes through the creator
        handler before the finite-plan one, exactly like invoice.paid —
        so it would have 500'd the first failed instalment of any plan.
        Fixed alongside, and covered here rather than left to be
        discovered by the next decline."""
        from app.webhooks.creator_billing_handlers import (
            handle_invoice_payment_failed,
        )

        creator = make_user(role="creator")
        plan = _ensure_plan(db)
        db.add(CreatorSubscription(
            id=_uid("csub"),
            user_id=creator.id,
            creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(),
            source="stripe_paid",
            stripe_subscription_id="sub_creator_fail",
            stripe_customer_id="cus_live_x",
        ))
        db.commit()

        subscription = _creator_subscription(
            creator_user_id=creator.id, sub_id="sub_creator_fail",
        )
        before = datetime.utcnow()
        with patch(_RETRIEVE, return_value=subscription):
            handled = handle_invoice_payment_failed(
                _invoice(subscription_id="sub_creator_fail"),
                db,
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                event_type="invoice.payment_failed",
            )

        assert handled is True
        db.expire_all()
        row = (
            db.query(CreatorSubscription)
            .filter(CreatorSubscription.stripe_subscription_id == "sub_creator_fail")
            .first()
        )
        assert row.status == CreatorSubscriptionStatus.past_due
        assert row.grace_expires_at is not None
        assert row.grace_expires_at >= before + timedelta(days=6)


# ---------------------------------------------------------------------------
# Proof 4 — non-creator metadata falls through, it is not claimed
# ---------------------------------------------------------------------------


class TestNonCreatorMetadataFallsThrough:
    @pytest.mark.parametrize("event_type", ["invoice.paid", "invoice.payment_succeeded"])
    def test_finite_plan_metadata_is_declined_not_claimed(
        self, db, event_type,
    ):
        """``handled is False`` is the contract the dispatcher routes on.
        Returning True here — or raising — is what strands a member's
        instalment."""
        from app.webhooks.creator_billing_handlers import handle_invoice_paid

        with patch(_RETRIEVE, return_value=_finite_plan_subscription()):
            handled = handle_invoice_paid(
                _invoice(subscription_id=LIVE_SUB_ID),
                db,
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                event_type=event_type,
            )

        assert handled is False

    def test_a_declined_event_is_not_claimed_in_the_dedup_table(self, db):
        """Fall-through must leave the event unclaimed, or the
        finite-plan handler's own idempotency guard would treat the
        instalment as already processed and skip it."""
        from sqlalchemy import text

        from app.webhooks.creator_billing_handlers import handle_invoice_paid

        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        with patch(_RETRIEVE, return_value=_finite_plan_subscription()):
            assert handle_invoice_paid(
                _invoice(subscription_id=LIVE_SUB_ID),
                db, event_id=event_id, event_type="invoice.paid",
            ) is False

        claimed = db.execute(
            text("SELECT id FROM stripe_webhook_events WHERE id = :id"),
            {"id": event_id},
        ).first()
        assert claimed is None

    def test_absent_metadata_also_falls_through(self, db):
        """A subscription with no metadata at all — Stripe objects
        created outside FC, or test-mode noise. Must decline, not
        crash on the empty read."""
        from app.webhooks.creator_billing_handlers import handle_invoice_paid

        with patch(_RETRIEVE, return_value=_real_subscription(metadata={})):
            handled = handle_invoice_paid(
                _invoice(subscription_id=LIVE_SUB_ID),
                db,
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                event_type="invoice.paid",
            )

        assert handled is False

    def test_no_creator_subscription_row_is_created_for_a_finite_plan(self, db):
        """The isolation invariant, stated as data: a member's plan
        invoice must never materialise a ``creator_subscriptions`` row."""
        from app.webhooks.creator_billing_handlers import handle_invoice_paid

        before = db.query(CreatorSubscription).count()
        with patch(_RETRIEVE, return_value=_finite_plan_subscription()):
            handle_invoice_paid(
                _invoice(subscription_id=LIVE_SUB_ID),
                db,
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                event_type="invoice.paid",
            )
        assert db.query(CreatorSubscription).count() == before
