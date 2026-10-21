"""Paid Offerings: checkout, webhook, and the money questions.

Section 7 of the Phase C/D brief. Stripe's network calls are mocked;
nothing else is. The Payment Option, the schedule, the grant, the
fulfilment snapshot, the ledger row, the entitlement, the membership
and the webhook handler are all the production ones, against a real
PostgreSQL database.

The one rule everything here orbits
-----------------------------------

**Starting checkout grants nothing.** Not an entitlement, not
membership, not a download. Access appears only when Stripe says the
money arrived, via ``checkout.session.completed`` → the shared
fulfilment service → the option's ``grant_kind='offering'`` grant. So
most of this file is the same assertion from different angles: after an
abandoned, failed, cancelled or merely-started checkout, the member
owns nothing.

Why there is no second checkout implementation to test
------------------------------------------------------

``POST /api/checkout/offering`` resolves the Offering, applies the
Offering-specific guards, and delegates to the unified endpoint. The
fee arithmetic, the Connect payout model, the discount reservation
ladder and the Stripe session are therefore the ones already covered
by ``test_checkout_unified`` and ``test_discount_checkout``. What is
new, and what is tested here, is the resolution, the guards, and the
offering grant travelling intact through the snapshot into fulfilment.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.checkout.routes import create_offering_checkout_session
from app.checkout.schemas import OfferingCheckoutRequest
from app.core.config import settings
from app.creator.plan_config import PLANS_BY_SLUG
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingEntitlementSource,
    OfferingEntitlementStatus,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
    OfferingPricingKind,
    OfferingStatus,
)
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from app.models.payment_option import PaymentOptionStatus
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.models.user import User
from app.services import offering_acquisition as acq
from app.services import offering_commerce
from app.services import offering_covers as covers


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _mock_session(session_id="cs_off_1", url="https://checkout.stripe.test/o"):
    return SimpleNamespace(id=session_id, url=url)


@pytest.fixture(autouse=True)
def _flag_on(offerings_enabled):
    """Handlers are called directly; the in-request flag check is real."""


@pytest.fixture
def stripe_configured(monkeypatch):
    """``settings.stripe_enabled`` checks both secrets."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")


def _plan(db, slug: str) -> CreatorPlan:
    cap = PLANS_BY_SLUG[slug]
    row = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
    if row is None:
        row = CreatorPlan(
            id=_uid("plan"), slug=slug, name=cap.display_name,
            monthly_price_cents=cap.monthly_price_cents or 0,
            currency="AUD", transaction_fee_basis_points=800,
            collective_limit=1, is_active=True,
        )
        db.add(row)
        db.flush()
    return row


@pytest.fixture
def selling_collective(db, make_space):
    """A Collective whose owner is on a plan that permits paid selling."""
    def _make(plan_slug: str = "creator"):
        space = make_space()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        plan = _plan(db, plan_slug)
        db.add(CreatorSubscription(
            id=_uid("sub"), user_id=owner.id, creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(), source="manual_grant",
        ))
        db.flush()
        return space, owner
    return _make


def _offering(db, space, **kw) -> Offering:
    defaults = dict(
        id=_uid("off"), space_id=space.id,
        created_by_user_id=space.creator_id,
        slug=f"o-{uuid.uuid4().hex[:8]}",
        title="Deep Rest Audio Course",
        summary="Six recorded practices.",
        default_cover_key=covers.DEFAULT_COVERS[0].key,
        status=OfferingStatus.published.value,
        pricing_kind=OfferingPricingKind.one_time.value,
        price_cents=2400,
        published_at=datetime.utcnow(),
    )
    defaults.update(kw)
    off = Offering(**defaults)
    db.add(off)
    db.flush()
    return off


def _file(db, offering, **kw) -> OfferingFile:
    defaults = dict(
        id=_uid("of"), offering_id=offering.id,
        storage_key=f"offering-files/{offering.id}/{uuid.uuid4().hex}_a.pdf",
        original_filename="practice.pdf",
        content_type="application/pdf",
        byte_size=8192, sort_order=0, resource_count=1,
        validation_status=FVS.passed.value,
        validated_at=datetime.utcnow(),
    )
    defaults.update(kw)
    f = OfferingFile(**defaults)
    db.add(f)
    db.flush()
    return f


def _sellable(db, space, **kw):
    """A published, paid Offering with a file and its commerce rows."""
    off = _offering(db, space, **kw)
    _file(db, off)
    offering_commerce.sync(db, offering=off, space=space)
    db.flush()
    return off


def _checkout(db, space, off, buyer, **kw):
    body = OfferingCheckoutRequest(
        space_slug=space.slug, offering_slug=off.slug,
        success_url="https://ok/s", cancel_url="https://ok/c",
        **kw,
    )
    return create_offering_checkout_session(body, current_user=buyer, db=db)


def _entitlements(db, user, off):
    return (
        db.query(OfferingEntitlement)
        .filter(
            OfferingEntitlement.user_id == user.id,
            OfferingEntitlement.offering_id == off.id,
        )
        .all()
    )


def _memberships(db, space, user):
    return (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == user.id,
        )
        .all()
    )


def _deliver(db, session_id, metadata, *, payment_status="paid"):
    """Hand the webhook what Stripe would deliver."""
    from app.webhooks.routes import _handle_checkout_completed
    with patch("stripe.PaymentIntent.retrieve") as pi:
        pi.return_value = SimpleNamespace(
            status="succeeded", latest_charge=None,
        )
        _handle_checkout_completed(
            {
                "id": session_id,
                "payment_status": payment_status,
                "payment_intent": f"pi_{session_id}",
                "metadata": metadata,
            },
            db,
        )


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------


class TestPublishingProvisionsTheCommerceRows:

    def test_publish_makes_the_option_purchasable(
        self, db, selling_collective,
    ):
        from app.creator import _offering_routes as creator_api
        space, owner = selling_collective()
        off = _offering(db, space, status=OfferingStatus.draft.value)
        _file(db, off)
        creator_api.publish_offering(
            space.slug, off.slug, db=db, current_user=owner,
        )
        option = offering_commerce.find_option(db, off)
        assert option is not None
        assert option.status.value == PaymentOptionStatus.published.value
        schedule = offering_commerce.pay_in_full_schedule(db, option)
        assert schedule.status == "published"
        assert schedule.total_amount_cents == 2400

    def test_retiring_archives_the_option_and_touches_no_entitlement(
        self, db, selling_collective, make_user,
    ):
        from app.creator import _offering_routes as creator_api
        space, owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oe"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id,
            source=OfferingEntitlementSource.one_time_purchase.value,
            status=OfferingEntitlementStatus.active.value,
            acquired_at=datetime.utcnow(),
        ))
        db.flush()

        creator_api.retire_offering(
            space.slug, off.slug, db=db, current_user=owner,
        )

        option = offering_commerce.find_option(db, off)
        assert option.status.value == "archived"
        # The purchaser is entirely unaffected.
        [ent] = _entitlements(db, buyer, off)
        assert ent.status == OfferingEntitlementStatus.active.value
        assert ent.revoked_at is None

    def test_a_price_change_moves_the_schedule(self, db, selling_collective):
        from app.creator import _offering_routes as creator_api
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = selling_collective()
        off = _sellable(db, space)
        creator_api.update_offering(
            space.slug, off.slug,
            OfferingUpdateRequest(pricing_kind="one_time", price_cents=3900),
            db=db, current_user=owner,
        )
        option = offering_commerce.find_option(db, off)
        schedule = offering_commerce.pay_in_full_schedule(db, option)
        assert schedule.total_amount_cents == 3900
        assert option.override_total_cents == 3900

    def test_sync_is_idempotent(self, db, selling_collective):
        space, _owner = selling_collective()
        off = _sellable(db, space)
        first = offering_commerce.sync(db, offering=off, space=space)
        assert first.changed is False, "a no-op sync must not dirty rows"
        from app.models.payment_option import PaymentOption
        from app.models.payment_option_grant import PaymentOptionGrant
        assert db.query(PaymentOption).filter(
            PaymentOption.attaches_to_id == off.id,
        ).count() == 1
        assert db.query(PaymentOptionGrant).filter(
            PaymentOptionGrant.offering_id == off.id,
        ).count() == 1

    def test_an_offering_option_is_hidden_from_the_creator_panel(
        self, db, selling_collective,
    ):
        """It is derived, not authored. A creator finding a row they did
        not create — and could archive, silently stopping their
        Offering selling — is the failure this prevents."""
        from app.creator import _space_payment_options_routes as po_api
        space, owner = selling_collective()
        off = _sellable(db, space)
        listed = po_api.list_commerce_payment_options(
            space.slug, db=db, current_user=owner,
        )
        option = offering_commerce.find_option(db, off)
        assert option is not None
        assert option.id not in {o["id"] for o in listed}

    def test_an_offering_option_is_not_a_joining_door(
        self, db, selling_collective,
    ):
        """It must not appear among the Collective's ways in."""
        from app.spaces.joining_doors import list_joining_doors
        space, _owner = selling_collective()
        off = _sellable(db, space)
        option = offering_commerce.find_option(db, off)
        doors = list_joining_doors(db, space)
        assert option.id not in {d.get("id") for d in doors}


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


class TestStartingCheckout:

    def test_it_returns_a_stripe_url_and_a_pending_ledger_row(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_start")
            res = _checkout(db, space, off, buyer)

        assert res.checkout_url == "https://checkout.stripe.test/o"
        assert res.free is False
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        assert txn.status == PaymentTransactionStatus.pending
        assert txn.fulfilment_status == PaymentFulfilmentStatus.pending
        assert txn.gross_amount_cents == 2400
        assert txn.transaction_type == (
            PaymentTransactionType.member_payment_option_purchase
        )

    def test_starting_checkout_grants_absolutely_nothing(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """The single most important assertion in this file."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_nothing")
            _checkout(db, space, off, buyer)

        assert _entitlements(db, buyer, off) == []
        assert _memberships(db, space, buyer) == []

    def test_the_stripe_line_item_names_the_offering(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_name")
            _checkout(db, space, off, buyer)
        items = m.call_args.kwargs["line_items"]
        assert items[0]["price_data"]["product_data"]["name"] == (
            "Deep Rest Audio Course"
        )
        assert items[0]["price_data"]["unit_amount"] == 2400

    def test_the_snapshot_carries_the_offering_grant(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """The snapshot is what fulfils, so this is what makes a
        creator editing the Offering mid-checkout harmless."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_snap")
            res = _checkout(db, space, off, buyer)
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        assert txn.snapshot_grants_json is not None
        assert txn.snapshot_grants_json["offerings"] == [
            {"offering_id": off.id, "space_id": space.id},
        ]
        # And nothing else was bundled in by accident.
        assert txn.snapshot_grants_json["entitlements"] == []
        assert txn.snapshot_grants_json["access_passes"] == []


class TestWhatCheckoutRefuses:

    def test_an_offering_already_owned(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """``check_same_option_not_active`` cannot see this — an
        Offering purchase produces no AccessPass and no
        PathwayEntitlement — so without this guard a member could be
        charged twice for the same file."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oe"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id,
            source=OfferingEntitlementSource.one_time_purchase.value,
            status=OfferingEntitlementStatus.active.value,
            acquired_at=datetime.utcnow(),
        ))
        db.flush()
        with pytest.raises(HTTPException) as e:
            _checkout(db, space, off, buyer)
        assert e.value.status_code == 409
        assert e.value.detail["reason"] == "already_owned"

    def test_a_retired_offering(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, _owner = selling_collective()
        off = _sellable(db, space)
        off.status = OfferingStatus.retired.value
        off.retired_at = datetime.utcnow()
        offering_commerce.sync(db, offering=off, space=space)
        db.flush()
        with pytest.raises(HTTPException) as e:
            _checkout(db, space, off, make_user())
        assert e.value.detail["reason"] == acq.REASON_RETIRED

    def test_a_draft_offering_is_a_404(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, owner = selling_collective()
        off = _offering(db, space, status=OfferingStatus.draft.value)
        _file(db, off)
        offering_commerce.sync(db, offering=off, space=space)
        db.flush()
        # Even its owner.
        with pytest.raises(HTTPException) as e:
            _checkout(db, space, off, owner)
        assert e.value.status_code == 404

    def test_an_offering_with_nothing_downloadable(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, _owner = selling_collective()
        off = _offering(db, space)
        _file(db, off, validation_status=FVS.pending.value, validated_at=None)
        offering_commerce.sync(db, offering=off, space=space)
        db.flush()
        with pytest.raises(HTTPException) as e:
            _checkout(db, space, off, make_user())
        assert e.value.detail["reason"] == acq.REASON_NO_FILES

    def test_a_free_offering_cannot_be_bought(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """A free Offering has no commerce rows at all. The refusal must
        still be a clean 409 rather than a crash in the resolver."""
        space, _owner = selling_collective()
        off = _offering(db, space, pricing_kind="free", price_cents=None)
        _file(db, off)
        db.flush()
        with pytest.raises(HTTPException) as e:
            _checkout(db, space, off, make_user())
        assert e.value.status_code == 409
        assert e.value.detail["reason"] in (
            acq.REASON_WRONG_PRICING, acq.REASON_NOT_SELLABLE,
        )

    def test_an_archived_option_is_refused_rather_than_400ing(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """Published Offering, archived option — the state a hand-edit
        or an interrupted sync could leave. The buyer gets a clear
        refusal, not a resolver error."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        option = offering_commerce.find_option(db, off)
        option.status = PaymentOptionStatus.archived.value
        db.flush()
        with pytest.raises(HTTPException) as e:
            _checkout(db, space, off, make_user())
        assert e.value.detail["reason"] == acq.REASON_NOT_SELLABLE

    def test_a_stale_price_is_refused_rather_than_charged(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """If the projection and the Offering disagree, charging either
        figure would charge a price the page did not state."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        option = offering_commerce.find_option(db, off)
        schedule = offering_commerce.pay_in_full_schedule(db, option)
        schedule.total_amount_cents = 9900      # drifted
        db.flush()
        with pytest.raises(HTTPException) as e:
            _checkout(db, space, off, make_user())
        assert e.value.detail["reason"] == acq.REASON_NOT_SELLABLE

    def test_the_feature_flag_closes_it(
        self, db, selling_collective, make_user, stripe_configured,
        monkeypatch,
    ):
        space, _owner = selling_collective()
        off = _sellable(db, space)
        monkeypatch.setattr(settings, "offerings_enabled", False)
        with pytest.raises(HTTPException) as e:
            _checkout(db, space, off, make_user())
        assert e.value.status_code == 404


class TestCreatorPlanEligibility:
    """Section 7: enforce this in backend purchase authorisation, not
    merely by hiding purchase buttons."""

    def test_a_community_creator_cannot_sell(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, _owner = selling_collective("community")
        off = _sellable(db, space)
        with pytest.raises(HTTPException) as e:
            _checkout(db, space, off, make_user())
        assert e.value.detail["reason"] == acq.REASON_PLAN_FORBIDS_PAID

    def test_a_creator_with_no_plan_at_all_cannot_sell(
        self, db, make_space, make_user, stripe_configured,
    ):
        """No subscription row resolves through the Community fallback,
        which does not permit paid selling."""
        space = make_space()
        _plan(db, "community")
        off = _sellable(db, space)
        with pytest.raises(HTTPException) as e:
            _checkout(db, space, off, make_user())
        assert e.value.detail["reason"] == acq.REASON_PLAN_FORBIDS_PAID

    def test_a_downgrade_stops_new_sales_and_keeps_existing_ones(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """The whole of section 7's downgrade clause, in one test."""
        space, owner = selling_collective("creator")
        off = _sellable(db, space)
        existing_buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oe"), user_id=existing_buyer.id, offering_id=off.id,
            space_id=space.id,
            source=OfferingEntitlementSource.one_time_purchase.value,
            status=OfferingEntitlementStatus.active.value,
            acquired_at=datetime.utcnow(),
        ))
        db.flush()

        # Downgrade: cancel the paid subscription so resolution falls
        # through to the Community fallback.
        community = _plan(db, "community")
        del community
        for sub in (
            db.query(CreatorSubscription)
            .filter(CreatorSubscription.user_id == owner.id)
            .all()
        ):
            sub.status = CreatorSubscriptionStatus.cancelled
        db.flush()

        # New purchases: refused.
        with pytest.raises(HTTPException) as e:
            _checkout(db, space, off, make_user())
        assert e.value.detail["reason"] == acq.REASON_PLAN_FORBIDS_PAID

        # Existing purchaser: untouched, and still gets the download.
        [ent] = _entitlements(db, existing_buyer, off)
        assert ent.status == OfferingEntitlementStatus.active.value
        from app.spaces import _offering_member_routes as member_api
        detail = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=existing_buyer,
        )
        assert detail["viewer_owns"] is True
        assert detail["files"][0]["download_url"] is not None
        # And the Offering itself still exists with its files.
        assert db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).count() == 1


# ---------------------------------------------------------------------------
# The webhook
# ---------------------------------------------------------------------------


class TestTheWebhookGrantsAccess:

    def _started(self, db, space, off, buyer, session_id="cs_wh"):
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session(session_id)
            res = _checkout(db, space, off, buyer)
        return res, m.call_args.kwargs["metadata"]

    def test_a_confirmed_payment_grants_the_offering_and_membership(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        res, metadata = self._started(db, space, off, buyer, "cs_ok")

        _deliver(db, "cs_ok", metadata)

        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied

        [ent] = _entitlements(db, buyer, off)
        assert ent.status == OfferingEntitlementStatus.active.value
        assert ent.source == OfferingEntitlementSource.one_time_purchase.value
        assert ent.payment_transaction_id == txn.id
        assert ent.space_id == space.id

        [membership] = _memberships(db, space, buyer)
        assert membership.status == SpaceMembershipStatus.active
        assert membership.source == "purchase"

    def test_the_metadata_names_no_pathway_or_series(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, _owner = selling_collective()
        off = _sellable(db, space)
        _res, metadata = self._started(
            db, space, off, make_user(), "cs_meta",
        )
        assert "pathway_id" not in metadata
        assert "series_id" not in metadata
        assert metadata["space_id"] == space.id

    def test_a_duplicate_delivery_changes_nothing(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """Stripe re-delivers. Twice must look exactly like once."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        _res, metadata = self._started(db, space, off, buyer, "cs_dup")

        _deliver(db, "cs_dup", metadata)
        [first] = _entitlements(db, buyer, off)
        first_id = first.id

        _deliver(db, "cs_dup", metadata)
        _deliver(db, "cs_dup", metadata)

        rows = _entitlements(db, buyer, off)
        assert len(rows) == 1
        assert rows[0].id == first_id
        assert len(_memberships(db, space, buyer)) == 1
        assert db.query(PaymentTransaction).filter(
            PaymentTransaction.space_id == space.id,
        ).count() == 1

    def test_an_unpaid_session_grants_nothing(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """``payment_status != 'paid'`` — a delayed-notification method
        that has not cleared."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        res, metadata = self._started(db, space, off, buyer, "cs_unpaid")

        _deliver(db, "cs_unpaid", metadata, payment_status="unpaid")

        assert _entitlements(db, buyer, off) == []
        assert _memberships(db, space, buyer) == []
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        assert txn.status == PaymentTransactionStatus.pending

    def test_an_abandoned_checkout_grants_nothing(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """No webhook ever arrives. The ledger row stays pending and the
        member owns nothing — which is also what Stripe's own 24-hour
        session expiry leaves behind."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        res, _metadata = self._started(db, space, off, buyer, "cs_aband")

        assert _entitlements(db, buyer, off) == []
        assert _memberships(db, space, buyer) == []
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        assert txn.status == PaymentTransactionStatus.pending
        assert txn.fulfilment_status == PaymentFulfilmentStatus.pending

    def test_an_expired_session_grants_nothing(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        from app.webhooks.routes import _handle_checkout_expired
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        res, metadata = self._started(db, space, off, buyer, "cs_exp")

        _handle_checkout_expired(
            {"id": "cs_exp", "metadata": metadata}, db,
        )

        assert _entitlements(db, buyer, off) == []
        assert _memberships(db, space, buyer) == []
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        assert txn.status != PaymentTransactionStatus.succeeded

    def test_fulfilment_comes_from_the_snapshot_not_live_rows(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """A creator retiring the Offering between "Pay" and the webhook
        must not deprive a member who has already paid."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        _res, metadata = self._started(db, space, off, buyer, "cs_retire")

        # Creator retires it while the buyer is on Stripe's page.
        off.status = OfferingStatus.retired.value
        off.retired_at = datetime.utcnow()
        offering_commerce.sync(db, offering=off, space=space)
        db.flush()

        _deliver(db, "cs_retire", metadata)

        [ent] = _entitlements(db, buyer, off)
        assert ent.status == OfferingEntitlementStatus.active.value, (
            "they paid; they own it"
        )

    def test_a_price_change_mid_checkout_charges_the_stated_price(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """Stripe charges what the Session says. The ledger records that
        figure, and the creator's later edit does not reach back."""
        space, owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        res, metadata = self._started(db, space, off, buyer, "cs_price")

        from app.creator import _offering_routes as creator_api
        from app.creator.schemas_offerings import OfferingUpdateRequest
        creator_api.update_offering(
            space.slug, off.slug,
            OfferingUpdateRequest(pricing_kind="one_time", price_cents=9900),
            db=db, current_user=owner,
        )

        _deliver(db, "cs_price", metadata)

        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        assert txn.gross_amount_cents == 2400, "the price they agreed to"
        assert len(_entitlements(db, buyer, off)) == 1

    def test_a_missing_offering_blocks_rather_than_half_fulfils(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """Pre-write validation. The member has paid, so the txn
        succeeds — but fulfilment is marked blocked for an operator
        rather than membership being granted with no Offering."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        res, metadata = self._started(db, space, off, buyer, "cs_gone")

        # Point the snapshot at an Offering that does not exist.
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        txn.snapshot_grants_json = {
            **txn.snapshot_grants_json,
            "offerings": [{"offering_id": "off_vanished", "space_id": space.id}],
        }
        db.flush()

        _deliver(db, "cs_gone", metadata)

        db.refresh(txn)
        assert txn.fulfilment_status == PaymentFulfilmentStatus.blocked
        assert _entitlements(db, buyer, off) == []
        assert _memberships(db, space, buyer) == [], (
            "no membership without the thing it accompanies"
        )


class TestAMisprovisionedOfferingIsRefusedBeforeStripe:

    def test_an_option_with_no_offering_grant_never_reaches_stripe(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """The legacy resolver cannot represent an Offering purchase and
        would grant nothing — recording a *successful* purchase that
        gave the buyer only Collective membership. The dispatcher
        refuses, the mandatory snapshot runs before Stripe, and nobody
        is charged."""
        from app.models.payment_option_grant import (
            GRANT_KIND_OFFERING, PaymentOptionGrant,
        )
        space, _owner = selling_collective()
        off = _sellable(db, space)
        option = offering_commerce.find_option(db, off)
        for g in (
            db.query(PaymentOptionGrant)
            .filter(
                PaymentOptionGrant.payment_option_id == option.id,
                PaymentOptionGrant.grant_kind == GRANT_KIND_OFFERING,
            )
            .all()
        ):
            db.delete(g)
        db.flush()
        db.refresh(option)

        with patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as e:
                _checkout(db, space, off, make_user())
        assert e.value.status_code in (409, 503)
        assert m.call_count == 0, "Stripe must not be contacted"

    def test_the_resolver_itself_reports_a_fatal_error(
        self, db, selling_collective,
    ):
        from app.models.payment_option_grant import (
            GRANT_KIND_OFFERING, PaymentOptionGrant,
        )
        from app.services.purchase_fulfilment import resolve_intent_for_option
        space, _owner = selling_collective()
        off = _sellable(db, space)
        option = offering_commerce.find_option(db, off)
        for g in (
            db.query(PaymentOptionGrant)
            .filter(PaymentOptionGrant.offering_id == off.id)
            .all()
        ):
            db.delete(g)
        db.flush()
        db.refresh(option)

        resolution = resolve_intent_for_option(
            db, payment_option=option, metadata_pathway_id=None,
            now=datetime.utcnow(),
        )
        assert resolution.fatal_error is not None
        assert "offering" in resolution.fatal_error.lower()
        # And emphatically not a silently empty intent.
        assert resolution.intent.entitlements == ()
        assert resolution.intent.offerings == ()


class TestDiscountCodes:

    def _code(self, db, space, **kw):
        from app.models.discount_code import DiscountCode
        defaults = dict(
            id=_uid("dc"), space_id=space.id,
            code=f"SAVE{uuid.uuid4().hex[:4].upper()}",
            discount_type="percentage", percent_bps=5000,
            is_active=True, scope_kind="space", scope_id=None,
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        )
        defaults.update(kw)
        row = DiscountCode(**defaults)
        db.add(row)
        db.flush()
        return row

    def test_a_space_scoped_code_applies_to_an_offering(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """The existing discount architecture, reused unchanged: a
        space-scoped code covers every paid offer in the Collective,
        and an Offering is one."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        code = self._code(db, space)
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_disc")
            res = _checkout(db, space, off, make_user(), discount_code=code.code)
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        assert txn.gross_amount_cents == 1200, "50% of $24"
        assert (txn.discount_snapshot_json or {}).get("code") == code.code

    def test_a_code_that_would_make_it_free_is_refused(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """Free access is a complimentary pass, arranged deliberately —
        not something a code produces as a side effect. The existing
        rule, confirmed to hold for Offerings."""
        space, _owner = selling_collective()
        off = _sellable(db, space)
        code = self._code(
            db, space, discount_type="fixed_amount",
            percent_bps=None, amount_cents=5000, currency="AUD",
        )
        with patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as e:
                _checkout(
                    db, space, off, make_user(), discount_code=code.code,
                )
        assert e.value.status_code == 409
        assert m.call_count == 0
        assert _entitlements(db, make_user(), off) == []

    def test_an_unknown_code_is_refused_without_charging(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, _owner = selling_collective()
        off = _sellable(db, space)
        with patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as e:
                _checkout(db, space, off, make_user(), discount_code="NOPE")
        assert e.value.status_code == 409
        assert m.call_count == 0


class TestCreatorEarningsVisibility:
    """Section 9: extend the existing payments surface, do not build a
    second ledger."""

    def test_a_sale_appears_in_payments_received_naming_the_offering(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        from app.creator.routes import list_creator_payments
        space, owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user(name="Ada Buyer")
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_earn")
            _checkout(db, space, off, buyer)
        _deliver(db, "cs_earn", m.call_args.kwargs["metadata"])

        rows = list_creator_payments(
            space_slug=space.slug, current_user=owner, db=db,
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.offering_id == off.id
        assert row.offering_title == "Deep Rest Audio Course"
        assert row.offering_slug == off.slug
        assert row.payer_name == "Ada Buyer"
        assert row.gross_amount_cents == 2400
        assert row.status == "succeeded"
        assert row.net_creator_amount_cents is not None
        assert row.platform_fee_cents is not None
        assert row.created_at is not None

    def test_the_grant_state_is_intact_not_no_grant_records(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        """``no_grant_records`` means "payment taken, nothing granted" —
        the signal an operator investigates. A sale that worked
        perfectly must not look like that."""
        from app.creator.routes import list_creator_payments
        space, owner = selling_collective()
        off = _sellable(db, space)
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_state")
            _checkout(db, space, off, make_user())
        _deliver(db, "cs_state", m.call_args.kwargs["metadata"])

        [row] = list_creator_payments(
            space_slug=space.slug, current_user=owner, db=db,
        )
        assert row.grant_state == "intact"

    def test_a_revoked_offering_shows_as_revoked(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        from app.creator.routes import list_creator_payments
        space, owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_rev")
            _checkout(db, space, off, buyer)
        _deliver(db, "cs_rev", m.call_args.kwargs["metadata"])

        [ent] = _entitlements(db, buyer, off)
        ent.status = OfferingEntitlementStatus.revoked.value
        ent.revoked_at = datetime.utcnow()
        ent.revoked_reason = "fraud"
        db.flush()

        [row] = list_creator_payments(
            space_slug=space.slug, current_user=owner, db=db,
        )
        assert row.grant_state == "fully_revoked"
        assert row.grant_revoked_at is not None

    def test_a_free_acquisition_does_not_appear_as_money(
        self, db, selling_collective, make_user,
    ):
        from app.creator.routes import list_creator_payments
        from app.spaces import _offering_member_routes as member_api
        space, owner = selling_collective()
        off = _offering(db, space, pricing_kind="free", price_cents=None)
        _file(db, off)
        db.flush()
        member_api.acquire_offering(
            space.slug, off.slug, db=db, current_user=make_user(),
        )
        assert list_creator_payments(
            space_slug=space.slug, current_user=owner, db=db,
        ) == []


class TestConnectRouting:
    """Section 7: "Creator Connect accounts that are not ready."

    The established platform answer is **not** to refuse the sale. A
    creator without a working Connect account still sells; their share
    goes into the manual payout queue and is paid out by an operator.
    Refusing the purchase would punish a member for a creator's
    unfinished paperwork, and the existing Pathway and Gathering paths
    behave exactly this way.

    Pinned here so that "handle Connect readiness" is never later read
    as "block the purchase".
    """

    def _account(self, db, owner, **kw):
        from app.models.creator_stripe_account import CreatorStripeAccount
        defaults = dict(
            id=_uid("csa"), creator_user_id=owner.id,
            stripe_mode=settings.stripe_mode,
            stripe_account_id=f"acct_{uuid.uuid4().hex[:16]}",
            onboarding_state="ready",
            transfers_status="active", payouts_status="active",
            transfers_enabled=True, payouts_enabled=True,
            # Stripe being ready is not enough: Fresh Collective
            # switches each creator over explicitly, and this field is
            # the switch. Without it the row routes manually, which is
            # the existing platform behaviour and not an Offerings
            # concern. ``ck_creator_stripe_accounts_routing_requires_ack``
            # additionally requires the fee disclosure to be recorded
            # before routing can be enabled, so all three travel
            # together.
            connect_payouts_enabled_at=datetime.utcnow(),
            fee_disclosure_acknowledged_at=datetime.utcnow(),
            fee_disclosure_version=1,
        )
        defaults.update(kw)
        row = CreatorStripeAccount(**defaults)
        db.add(row)
        db.flush()
        return row

    def test_a_ready_account_routes_through_connect(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        from app.models.payment import PayoutModel
        space, owner = selling_collective()
        account = self._account(db, owner)
        off = _sellable(db, space)
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_conn_ok")
            res = _checkout(db, space, off, make_user())
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        assert txn.payout_model == PayoutModel.connect.value
        assert txn.connect_destination_account_id == account.stripe_account_id

    def test_no_connect_account_still_sells_and_queues_manually(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        from app.models.payment import PayoutModel, PayoutStatus
        space, _owner = selling_collective()
        off = _sellable(db, space)
        buyer = make_user()
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_conn_none")
            res = _checkout(db, space, off, buyer)
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        assert txn.payout_model == PayoutModel.manual.value
        assert txn.connect_destination_account_id is None

        _deliver(db, "cs_conn_none", m.call_args.kwargs["metadata"])
        db.refresh(txn)
        # The member got what they paid for...
        assert len(_entitlements(db, buyer, off)) == 1
        # ...and the creator's share is in the manual queue.
        assert txn.payout_status == PayoutStatus.pending

    def test_payouts_not_yet_enabled_also_queues_manually(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        from app.models.payment import PayoutModel
        space, owner = selling_collective()
        self._account(
            db, owner, payouts_status="pending", payouts_enabled=False,
            onboarding_state="onboarding",
            # Routing cannot be enabled on an account that cannot
            # receive payouts, and the schema says so.
            connect_payouts_enabled_at=None,
            fee_disclosure_acknowledged_at=None,
            fee_disclosure_version=None,
        )
        off = _sellable(db, space)
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_conn_pending")
            res = _checkout(db, space, off, make_user())
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == res.transaction_id,
        ).one()
        assert txn.payout_model == PayoutModel.manual.value


class TestTheUnifiedEndpointAppliesOfferingRules:
    """Defence in depth at the other entrance.

    ``POST /api/checkout`` takes a Payment Option id. Its own guards are
    option-shaped: duplicate access passes, unfulfillable grant kinds.
    They know nothing about a retired Offering, a quarantined file, or a
    creator who has since downgraded.

    No payload exposes an Offering's option id — asserted in
    ``test_offering_creator_studio`` — so this is not a reachable hole.
    It is here because the rules should belong to the purchase rather
    than to whichever door was used, and because "nothing exposes it"
    is a property that has to stay true to keep being a defence.
    """

    def _call_unified(self, db, buyer, option, schedule, **kw):
        from app.checkout.routes import create_unified_checkout_session
        from app.checkout.schemas import UnifiedCheckoutRequest
        return create_unified_checkout_session(
            UnifiedCheckoutRequest(
                payment_option_id=option.id,
                payment_option_schedule_id=schedule.id,
                success_url="https://ok/s", cancel_url="https://ok/c",
                **kw,
            ),
            current_user=buyer, db=db,
        )

    def _rows(self, db, off):
        option = offering_commerce.find_option(db, off)
        return option, offering_commerce.pay_in_full_schedule(db, option)

    def test_a_retired_offering_is_refused_there_too(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, _owner = selling_collective()
        off = _sellable(db, space)
        option, schedule = self._rows(db, off)
        off.status = OfferingStatus.retired.value
        off.retired_at = datetime.utcnow()
        db.flush()

        with patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as e:
                self._call_unified(db, make_user(), option, schedule)
        assert e.value.status_code == 409
        assert e.value.detail["reason"] == acq.REASON_RETIRED
        assert m.call_count == 0

    def test_an_already_owned_offering_is_refused_there_too(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, _owner = selling_collective()
        off = _sellable(db, space)
        option, schedule = self._rows(db, off)
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oe"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id,
            source=OfferingEntitlementSource.one_time_purchase.value,
            status=OfferingEntitlementStatus.active.value,
            acquired_at=datetime.utcnow(),
        ))
        db.flush()

        with patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as e:
                self._call_unified(db, buyer, option, schedule)
        assert e.value.detail["reason"] == acq.REASON_ALREADY_OWNED
        assert m.call_count == 0

    def test_nothing_downloadable_is_refused_there_too(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, _owner = selling_collective()
        off = _sellable(db, space)
        option, schedule = self._rows(db, off)
        for f in db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).all():
            f.validation_status = FVS.quarantined.value
            f.quarantined_at = datetime.utcnow()
        db.flush()

        with patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as e:
                self._call_unified(db, make_user(), option, schedule)
        assert e.value.detail["reason"] == acq.REASON_NO_FILES
        assert m.call_count == 0

    def test_a_plan_downgrade_is_refused_there_too(
        self, db, selling_collective, make_user, stripe_configured,
    ):
        space, owner = selling_collective("creator")
        off = _sellable(db, space)
        option, schedule = self._rows(db, off)
        _plan(db, "community")
        for sub in db.query(CreatorSubscription).filter(
            CreatorSubscription.user_id == owner.id,
        ).all():
            sub.status = CreatorSubscriptionStatus.cancelled
        db.flush()

        with patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as e:
                self._call_unified(db, make_user(), option, schedule)
        assert e.value.detail["reason"] == acq.REASON_PLAN_FORBIDS_PAID
        assert m.call_count == 0

    def test_a_pathway_purchase_through_the_unified_endpoint_is_untouched(
        self, db, make_space, make_user, stripe_configured,
    ):
        """The guard must be a no-op for every non-Offering option. This
        is the regression that matters: the shared endpoint serves
        Pathways and Series, and they must not acquire an Offering's
        rules."""
        from app.models.payment_option import PaymentOption, PaymentOptionType
        from app.models.payment_option_grant import (
            GRANT_KIND_PATHWAY, PaymentOptionGrant,
        )
        from app.models.payment_option_schedule import PaymentOptionSchedule
        from app.models.platform import Pathway, PathwayType

        space = make_space()
        pw = Pathway(
            id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
            title="Practice", status="active", access_type="free",
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pw)
        option = PaymentOption(
            id=_uid("po"), space_id=space.id,
            attaches_to_kind="pathway", attaches_to_id=pw.id,
            name="Full access", payment_type=PaymentOptionType.one_time,
            status="published", currency="AUD", override_total_cents=5000,
        )
        db.add(option)
        db.flush()
        db.add(PaymentOptionGrant(
            id=_uid("pog"), payment_option_id=option.id,
            grant_kind=GRANT_KIND_PATHWAY, pathway_id=pw.id, position=0,
        ))
        schedule = PaymentOptionSchedule(
            id=_uid("pos"), payment_option_id=option.id, name="Pay in full",
            schedule_type="pay_in_full", status="published",
            total_amount_cents=5000, currency="AUD",
        )
        db.add(schedule)
        db.flush()
        db.refresh(option)

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session("cs_pathway_unaffected")
            res = self._call_unified(db, make_user(), option, schedule)
        assert res.checkout_url == "https://checkout.stripe.test/o"
        assert m.call_count == 1
