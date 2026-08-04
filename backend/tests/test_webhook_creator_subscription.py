"""Stage 3 — Stripe webhook handling for creator-subscription
PurchaseIntents.

The webhook is exercised via its dispatch helper
``_handle_purchase_intent_completed`` directly, so tests use the
same DB session the fixture wraps (see ``test_world_builders_access``
for the same pattern). The Stripe SDK never runs — we construct a
plain dict shaped like ``stripe.checkout.Session``.

Covers:
  * Anonymous new-user flow: mark paid + snapshot Stripe IDs, leave
    intent ``paid`` for the visitor to claim.
  * Known-payer flow: mark paid + auto-claim + subscription
    activated + role promoted + World Builders enrolment.
  * Idempotent replay: repeat delivery is a no-op.
  * Missing / unknown ``purchase_intent_id`` handled gracefully.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.creator.plan_activation import ActivationSource
from app.models.creator_billing import CreatorPlan
from app.models.platform import Space, SpaceMembership
from app.models.purchase_intent import (
    PurchaseIntent,
    PurchaseIntentKind,
    PurchaseIntentStatus,
)
from app.models.user import UserRole
from app.purchases.service import build_intent
from app.webhooks.routes import _handle_purchase_intent_completed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _plans(db):
    for slug, price, fee_bps, cap in (
        ("creator", 1900, 800, 1),
        ("pro", 7900, 300, 5),
    ):
        if db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first() is None:
            db.add(CreatorPlan(
                id=f"cp_{slug}",
                name=slug.title(),
                slug=slug,
                monthly_price_cents=price,
                transaction_fee_basis_points=fee_bps,
                collective_limit=cap,
                is_active=True,
            ))
    db.flush()


@pytest.fixture
def world_builders(db, make_user):
    owner = make_user(role="admin")
    space = Space(
        id=f"s_wb_{uuid.uuid4().hex[:8]}",
        slug=f"wb-{uuid.uuid4().hex[:8]}",
        name="World Builders",
        status="active",
        is_public=False,
        creator_id=owner.id,
        auto_grant_role=UserRole.creator.value,
    )
    db.add(space)
    db.flush()
    return space


def _pending_intent(db, *, plan_slug="creator", payer_user_id=None) -> PurchaseIntent:
    intent = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug=plan_slug,
        payer_user_id=payer_user_id,
    )
    intent.provider_checkout_session_id = f"cs_test_{uuid.uuid4().hex[:8]}"
    db.add(intent)
    db.flush()
    return intent


def _stripe_session(intent_id: str, *, email: str | None = "buyer@example.test",
                    subscription_id: str = "sub_test_x",
                    customer_id: str = "cus_test_x",
                    payment_status: str = "paid") -> dict:
    return {
        "id": f"cs_test_{uuid.uuid4().hex[:8]}",
        "payment_status": payment_status,
        "subscription": subscription_id,
        "customer": customer_id,
        "customer_details": {"email": email} if email else {},
        "metadata": {
            "purchase_intent_id": intent_id,
            "kind": "creator_subscription",
        },
    }


# ---------------------------------------------------------------------------
# Anonymous new-user flow
# ---------------------------------------------------------------------------


class TestAnonymousFlow:
    def test_marks_paid_and_captures_stripe_ids_but_does_not_consume(
        self, db, _plans, world_builders,
    ):
        intent = _pending_intent(db)  # no payer
        session = _stripe_session(intent.id, email="buyer@example.test")
        _handle_purchase_intent_completed(session, db, session["metadata"])
        db.flush()

        db.refresh(intent)
        assert intent.status == PurchaseIntentStatus.paid
        assert intent.paid_at is not None
        assert intent.provider_subscription_id == "sub_test_x"
        assert intent.provider_customer_id == "cus_test_x"
        assert intent.claim_email == "buyer@example.test"
        assert intent.consumed_by_user_id is None


# ---------------------------------------------------------------------------
# Known-payer flow — auto-claim
# ---------------------------------------------------------------------------


class TestKnownPayerFlow:
    def test_auto_claims_and_activates_subscription(
        self, db, make_user, _plans, world_builders,
    ):
        buyer = make_user(role="user", email="buyer@example.test")
        intent = _pending_intent(db, payer_user_id=buyer.id)
        session = _stripe_session(intent.id, email=buyer.email)
        _handle_purchase_intent_completed(session, db, session["metadata"])
        db.flush()

        db.refresh(intent)
        db.refresh(buyer)
        assert intent.status == PurchaseIntentStatus.consumed
        assert intent.consumed_by_user_id == buyer.id
        assert buyer.role == "creator"

        # World Builders enrolment happened via the eligibility reconciler.
        wb = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == buyer.id,
                SpaceMembership.source == "auto_role",
            )
            .first()
        )
        assert wb is not None
        assert wb.status == "active"

    def test_existing_member_keeps_original_role_bumped_to_creator(
        self, db, make_user, _plans, world_builders,
    ):
        """An existing Member paying for Creator: same user id, role
        goes user → creator, existing SpaceMemberships untouched."""
        buyer = make_user(role="user", email="member@example.test")
        # Add an unrelated membership to prove it survives.
        other_space = Space(
            id=f"s_other_{uuid.uuid4().hex[:6]}",
            slug=f"other-{uuid.uuid4().hex[:6]}",
            name="Other",
            status="active",
            is_public=True,
            creator_id=make_user(role="creator").id,
        )
        db.add(other_space)
        db.flush()
        db.add(SpaceMembership(
            id=f"sm_{uuid.uuid4().hex[:8]}",
            user_id=buyer.id,
            space_id=other_space.id,
            role="learner",
            status="active",
            source="joined",
        ))
        db.flush()

        intent = _pending_intent(db, payer_user_id=buyer.id)
        session = _stripe_session(intent.id, email=buyer.email)
        _handle_purchase_intent_completed(session, db, session["metadata"])
        db.flush()

        db.refresh(buyer)
        assert buyer.role == "creator"
        # Pre-existing membership is intact — no duplicate account.
        other = db.query(SpaceMembership).filter(
            SpaceMembership.user_id == buyer.id,
            SpaceMembership.space_id == other_space.id,
        ).first()
        assert other is not None
        assert other.status == "active"


# ---------------------------------------------------------------------------
# Replay / idempotency
# ---------------------------------------------------------------------------


class TestReplay:
    def test_replay_after_consumption_is_noop(
        self, db, make_user, _plans, world_builders,
    ):
        buyer = make_user(role="user", email="buyer@example.test")
        intent = _pending_intent(db, payer_user_id=buyer.id)
        session = _stripe_session(intent.id, email=buyer.email)

        _handle_purchase_intent_completed(session, db, session["metadata"])
        db.flush()
        db.refresh(intent)
        first_consumed_at = intent.consumed_at

        _handle_purchase_intent_completed(session, db, session["metadata"])
        db.flush()
        db.refresh(intent)
        assert intent.consumed_at == first_consumed_at

    def test_replay_after_paid_but_unclaimed_is_noop_for_mark_paid(
        self, db, _plans, world_builders,
    ):
        intent = _pending_intent(db)  # anonymous
        session = _stripe_session(intent.id, email="buyer@example.test",
                                  subscription_id="sub_first",
                                  customer_id="cus_first")
        _handle_purchase_intent_completed(session, db, session["metadata"])
        db.flush()
        db.refresh(intent)
        first_paid_at = intent.paid_at
        first_sub_id = intent.provider_subscription_id

        # Second delivery — even with different Stripe IDs, we must
        # not overwrite the recorded snapshot.
        session2 = _stripe_session(intent.id, email="different@example.test",
                                   subscription_id="sub_second",
                                   customer_id="cus_second")
        _handle_purchase_intent_completed(session2, db, session2["metadata"])
        db.flush()
        db.refresh(intent)

        assert intent.paid_at == first_paid_at
        assert intent.provider_subscription_id == first_sub_id
        assert intent.claim_email == "buyer@example.test"


# ---------------------------------------------------------------------------
# Missing / unknown metadata
# ---------------------------------------------------------------------------


class TestMissingMetadata:
    def test_missing_purchase_intent_id_is_logged_and_ignored(self, db):
        session = {
            "id": "cs_test_missing",
            "payment_status": "paid",
            "customer_details": {},
            "metadata": {},
        }
        # Should not raise.
        _handle_purchase_intent_completed(session, db, session["metadata"])

    def test_unknown_purchase_intent_id_is_logged_and_ignored(self, db):
        session = {
            "id": "cs_test_unknown",
            "payment_status": "paid",
            "customer_details": {},
            "metadata": {"purchase_intent_id": "no_such_intent"},
        }
        # Should not raise.
        _handle_purchase_intent_completed(session, db, session["metadata"])
