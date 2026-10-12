"""Renaming a plan is cosmetic. Billing keys on the slug.

In October 2026 the A$79 tier's World Management name changed from the
development shorthand "Pro" to its real customer-facing name, **Creator
Portfolio**. The internal slug stayed ``pro`` because Stripe was already
configured against it.

That rename is only safe if nothing commercial reads the name. These
tests pin that, against plan rows carrying the **new** name, so the
property is checked rather than assumed:

  * the commission a sale is charged comes from the row, by slug;
  * the Stripe Price ID is selected by slug, so product IDs, price IDs
    and live subscriptions are untouched by any name;
  * capability lookup is by slug, so the plan's limits and permissions
    survive the rename;
  * the creator-facing label is unchanged by the rename — it already
    read "Creator Portfolio" when the row said "Pro", and still does
    now that the row agrees.

A failure here means a name has become load-bearing, which is the thing
the rename was checked against.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.creator.plan_config import get_plan_capability
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.platform import Space
from app.purchases.checkout import _resolve_creator_plan_price_id
from app.services.checkout_orchestration import resolve_fee_context
from app.services.creator_plan_labels import creator_facing_plan_label

# The live commercial terms as set in World Management.
LIVE_TERMS = {
    "creator": {"name": "Creator",           "price": 1900, "fee_bps": 800, "limit": 1},
    "pro":     {"name": "Creator Portfolio", "price": 7900, "fee_bps": 400, "limit": 5},
}


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def live_plans(db):
    """Plan rows exactly as World Management now holds them — including
    the renamed ``pro`` row."""
    rows = {}
    for slug, t in LIVE_TERMS.items():
        row = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
        if row is None:
            row = CreatorPlan(
                id=f"cp_{slug}_{uuid.uuid4().hex[:6]}",
                slug=slug,
                name=t["name"],
                monthly_price_cents=t["price"],
                transaction_fee_basis_points=t["fee_bps"],
                collective_limit=t["limit"],
                is_active=True,
            )
            db.add(row)
        else:
            row.name = t["name"]
            row.monthly_price_cents = t["price"]
            row.transaction_fee_basis_points = t["fee_bps"]
            row.collective_limit = t["limit"]
        rows[slug] = row
    db.flush()
    return rows


def _subscribed_space(db, make_user, plan: CreatorPlan) -> Space:
    creator = make_user(role="creator")
    db.add(CreatorSubscription(
        id=_uid("sub"),
        user_id=creator.id,
        creator_plan_id=plan.id,
        status=CreatorSubscriptionStatus.active,
        starts_at=datetime.utcnow(),
        source="stripe_paid",
        stripe_subscription_id=_uid("stripe_sub"),
        stripe_customer_id=_uid("stripe_cus"),
    ))
    space = Space(
        id=_uid("s"),
        slug=f"sp-{uuid.uuid4().hex[:8]}",
        name="Test Collective",
        status="active",
        creator_id=creator.id,
    )
    db.add(space)
    db.flush()
    return space


class TestTheChargedCommissionComesFromTheRow:
    @pytest.mark.parametrize("slug,expected_bps", [("creator", 800), ("pro", 400)])
    def test_fee_resolution_matches_world_management(
        self, db, make_user, live_plans, slug, expected_bps,
    ):
        """What a member sale is actually charged. ``pro`` resolves 400
        while its row is named "Creator Portfolio" — the rename does not
        reach the money."""
        space = _subscribed_space(db, make_user, live_plans[slug])
        db.commit()

        ctx = resolve_fee_context(space, db)

        assert ctx.fee_bps == expected_bps
        assert ctx.creator_plan_id == live_plans[slug].id
        assert ctx.permits_paid_offers is True

    def test_the_two_tiers_do_not_collide(self, db, make_user, live_plans):
        """8% and 4% resolve independently — a shared lookup key would
        show up here as one tier inheriting the other's rate."""
        creator_space = _subscribed_space(db, make_user, live_plans["creator"])
        pro_space = _subscribed_space(db, make_user, live_plans["pro"])
        db.commit()

        assert resolve_fee_context(creator_space, db).fee_bps == 800
        assert resolve_fee_context(pro_space, db).fee_bps == 400


class TestStripeIsAddressedBySlug:
    @pytest.mark.parametrize("slug", ["creator", "pro"])
    def test_price_id_selection_ignores_the_plan_name(self, monkeypatch, slug):
        """Price IDs come from env vars chosen by slug. The plan row —
        name included — is never consulted, so renaming cannot point a
        subscription at a different Stripe Price."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "stripe_price_id_creator", "price_creator_live")
        monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_live")

        expected = "price_creator_live" if slug == "creator" else "price_pro_live"
        assert _resolve_creator_plan_price_id(slug) == expected

    def test_the_customer_facing_name_is_not_a_stripe_key(self, monkeypatch):
        """Passing the new display name where a slug belongs must fail
        loudly rather than resolve to something."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_live")
        with pytest.raises(Exception):
            _resolve_creator_plan_price_id("Creator Portfolio")


class TestCapabilitiesSurviveTheRename:
    def test_capability_lookup_is_by_slug(self, live_plans):
        cap = get_plan_capability(live_plans["pro"].slug)
        assert cap is not None, "the renamed row lost its capability record"
        assert cap.slug == "pro"
        assert cap.paid_offers_enabled is True
        assert cap.is_purchasable is True

    def test_the_display_name_is_not_a_capability_key(self):
        assert get_plan_capability("Creator Portfolio") is None


class TestTheLabelIsUnchangedByTheRename:
    def test_renamed_row_resolves_to_the_same_label(self):
        """Before the rename the row said "Pro" and the translator
        produced "Creator Portfolio". After it, the row already agrees.
        Both must give the same answer, or the rename would have moved
        what customers see."""
        before = creator_facing_plan_label(slug="pro", name="Pro")
        after = creator_facing_plan_label(slug="pro", name="Creator Portfolio")
        assert before == after == "Creator Portfolio"

    def test_the_creator_tier_is_untouched(self):
        assert creator_facing_plan_label(slug="creator", name="Creator") == "Creator"


class TestTheSlugItselfIsIntact:
    def test_the_internal_slug_is_still_pro(self, live_plans):
        """The whole arrangement rests on this. If the slug ever moved,
        Stripe price selection, capability lookup and the label mapping
        would all miss at once."""
        assert live_plans["pro"].slug == "pro"
        assert live_plans["pro"].name == "Creator Portfolio"
