"""Every legitimate plan assignment still resolves to itself.

Release verification for the fallback correction in ``9795cc4``.

The question being answered is not "does Community resolve correctly" —
that is covered in ``test_plan_fallback_determinism`` — but the riskier
one: **did making the fallback deterministic take anything away from
anybody?**

The structural answer is no, and it is worth stating because it bounds
the blast radius exactly. ``resolve_creator_plan`` consults a
subscription row first:

    active | trialing | past_due   → that plan wins; the fallback is
                                     never reached
    cancelled | unpaid | no row    → the fallback decides

So a creator with a current subscription of any kind — paid, Founding
Creator, Organisation, complimentary, manually assigned — cannot be
affected by a change to the fallback. The only creators whose answer
moves are those who had no current subscription, and for them the
intended answer was always Community; the old code could hand them
Founding Creator or Organisation instead.

The change can therefore only ever *remove* over-entitlement. These
tests assert that, shape by shape, rather than asking anyone to take it
on trust.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.creator.plan_config import PLANS_BY_SLUG
from app.creator.plan_guards import (
    CURRENT_SUBSCRIPTION_STATUSES, fallback_creator_plan, resolve_creator_plan,
)
from app.models.creator_billing import (
    CreatorPlan, CreatorSubscription, CreatorSubscriptionStatus,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def all_plans(db):
    """Every plan, priced as production prices them.

    Three of them cost zero — Community, Founding Creator and
    Organisation — which is the tie that made the old fallback
    arbitrary. Inserted with the rivals first so insertion order cannot
    flatter the result.
    """
    rows = [
        ("founding-creator", 0),
        ("organisation", 0),
        ("community", 0),
        ("creator", 1900),
        ("pro", 7900),
    ]
    out = {}
    for slug, cents in rows:
        existing = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
        if existing is None:
            existing = CreatorPlan(
                id=_uid("cp"), slug=slug,
                name=PLANS_BY_SLUG.get(slug).display_name if slug in PLANS_BY_SLUG else slug,
                monthly_price_cents=cents, currency="AUD",
                transaction_fee_basis_points=0, collective_limit=1,
                is_active=True,
            )
            db.add(existing)
        out[slug] = existing
    db.flush()
    return out


def _subscribe(
    db, user, plan, *, status=CreatorSubscriptionStatus.active,
    source="stripe_paid", ends_at=None,
) -> CreatorSubscription:
    row = CreatorSubscription(
        id=_uid("sub"), user_id=user.id, creator_plan_id=plan.id,
        status=status, source=source, starts_at=datetime.utcnow(),
        ends_at=ends_at,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# The creators the fix is for
# ---------------------------------------------------------------------------


class TestCreatorsWithoutASubscription:

    def test_no_subscription_row_resolves_to_community(
        self, db, all_plans, make_user,
    ):
        """The free Community creator. No row is written for them on
        activation, so this is the path every one of them takes."""
        creator = make_user(role="creator")
        capability = resolve_creator_plan(creator, db)
        assert capability is not None
        assert capability.slug == "community"

    def test_they_get_community_capabilities_not_founder_ones(
        self, db, all_plans, make_user,
    ):
        """The specific over-entitlement the old code could hand out."""
        creator = make_user(role="creator")
        capability = resolve_creator_plan(creator, db)
        assert capability.paid_offers_enabled is False
        assert capability.active_collective_limit == 1
        assert capability.member_allowance_per_collective == 100
        assert capability.commercial_use is False

    def test_it_is_the_same_answer_every_time(self, db, all_plans, make_user):
        creator = make_user(role="creator")
        answers = {resolve_creator_plan(creator, db).slug for _ in range(25)}
        assert answers == {"community"}, f"non-deterministic: {answers}"

    @pytest.mark.parametrize(
        "status", [CreatorSubscriptionStatus.cancelled,
                   CreatorSubscriptionStatus.unpaid],
    )
    def test_a_lapsed_subscription_also_lands_on_community(
        self, db, all_plans, make_user, status,
    ):
        """Cancelled and unpaid are not "current", so these creators go
        through the fallback too — and must land on Community, not on
        the plan they used to hold and not on Founding Creator."""
        creator = make_user(role="creator")
        _subscribe(db, creator, all_plans["pro"], status=status)
        assert resolve_creator_plan(creator, db).slug == "community"


# ---------------------------------------------------------------------------
# Everybody else — unchanged
# ---------------------------------------------------------------------------


class TestLegitimateEntitlementsAreIntact:

    @pytest.mark.parametrize("slug", ["creator", "pro", "founding-creator",
                                      "organisation", "community"])
    def test_an_active_subscription_resolves_to_its_own_plan(
        self, db, all_plans, make_user, slug,
    ):
        creator = make_user(role="creator")
        _subscribe(db, creator, all_plans[slug])
        capability = resolve_creator_plan(creator, db)
        assert capability is not None
        assert capability.slug == slug, (
            f"a {slug} subscriber resolved to {capability.slug}"
        )

    def test_a_founding_creator_keeps_founder_capabilities(
        self, db, all_plans, make_user,
    ):
        """The plan the old bug could hand out by accident must still
        work for the people who are genuinely on it."""
        creator = make_user(role="creator")
        _subscribe(db, creator, all_plans["founding-creator"])
        capability = resolve_creator_plan(creator, db)
        assert capability.slug == "founding-creator"
        assert capability.paid_offers_enabled is True
        assert capability.active_collective_limit is None     # unrestricted
        assert capability.transaction_fee_basis_points == 0

    def test_an_organisation_subscriber_keeps_organisation(
        self, db, all_plans, make_user,
    ):
        creator = make_user(role="creator")
        _subscribe(db, creator, all_plans["organisation"])
        capability = resolve_creator_plan(creator, db)
        assert capability.slug == "organisation"
        assert capability.paid_offers_enabled is True

    def test_a_manual_grant_is_honoured(self, db, all_plans, make_user):
        """Complimentary / manually assigned grants carry
        ``source='manual_grant'`` and a finite ``ends_at``. Still a
        current subscription, so still wins."""
        creator = make_user(role="creator")
        _subscribe(
            db, creator, all_plans["founding-creator"],
            source="manual_grant",
            ends_at=datetime.utcnow() + timedelta(days=90),
        )
        assert resolve_creator_plan(creator, db).slug == "founding-creator"

    def test_a_manual_grant_on_a_paid_plan_is_honoured(
        self, db, all_plans, make_user,
    ):
        creator = make_user(role="creator")
        _subscribe(
            db, creator, all_plans["pro"], source="manual_grant",
            ends_at=datetime.utcnow() + timedelta(days=30),
        )
        assert resolve_creator_plan(creator, db).slug == "pro"

    @pytest.mark.parametrize("status", CURRENT_SUBSCRIPTION_STATUSES)
    def test_every_current_status_bypasses_the_fallback(
        self, db, all_plans, make_user, status,
    ):
        """active, trialing and past_due all keep the creator on their
        own plan — past_due deliberately so, to preserve authoring
        capability through the grace window."""
        creator = make_user(role="creator")
        _subscribe(
            db, creator, all_plans["pro"],
            status=CreatorSubscriptionStatus(status),
        )
        assert resolve_creator_plan(creator, db).slug == "pro"

    def test_a_platform_owner_is_still_outside_the_plan_system(
        self, db, all_plans, make_user,
    ):
        owner = make_user(role="admin")
        # Platform Owner resolves to None — no creator plan applies.
        from app.creator.plan_guards import is_platform_owner
        if is_platform_owner(owner):
            assert resolve_creator_plan(owner, db) is None


class TestTheChangeCanOnlyRemoveOverEntitlement:

    def test_the_fallback_is_never_consulted_for_a_subscriber(
        self, db, all_plans, make_user, monkeypatch,
    ):
        """Proved by making the fallback explode. If a subscriber's
        resolution touches it, this test fails loudly."""
        creator = make_user(role="creator")
        _subscribe(db, creator, all_plans["creator"])

        import app.creator.plan_guards as guards

        def boom(_db):
            raise AssertionError(
                "the fallback was consulted for a creator who has a "
                "current subscription"
            )

        monkeypatch.setattr(guards, "fallback_creator_plan", boom)
        assert resolve_creator_plan(creator, db).slug == "creator"

    def test_the_fallback_never_returns_a_non_purchasable_plan(
        self, db, all_plans,
    ):
        """Founding Creator and Organisation are assigned by hand. The
        fallback must not be a route onto either."""
        chosen = fallback_creator_plan(db)
        assert chosen is not None
        capability = PLANS_BY_SLUG.get(chosen.slug)
        assert capability is not None
        assert capability.is_purchasable is True
        assert chosen.slug not in ("founding-creator", "organisation")
