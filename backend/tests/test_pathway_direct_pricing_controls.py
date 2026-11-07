"""Stage 2A — a creator can price a Pathway, and change the price.

Everything underneath already worked: the column, the checkout, the fee
calculation, the fulfilment, the member display. What Stage 0 removed
was the creator's ability to *reach* it, on the reasonable grounds that
offering a choice one surface could not maintain was worse than
offering none. Stage 2A restores it now that Settings can maintain it.

Three things here are about restraint rather than capability, and they
are the ones worth reading:

* **A preserved price must not become an offer.** Moving a $49 Pathway
  to Members only keeps the $49 — so returning to paid access does not
  mean re-typing it — but nothing may advertise or charge it in the
  meantime.
* **Currency is fixed once set.** Existing transactions are recorded in
  it, and re-denominating a Pathway that has sold would make a
  creator's own earnings unreadable without converting anything.
* **The $5/$2 protection still holds.** A direct price alongside a
  Payment Option is Stage 2B, behind its own gate. Until then
  ``pricing_mode`` is still the answer to "what does this cost".

And one plain bug: ``PathwayCreateRequest`` rejected
``included_with_offer`` while the update validator accepted it, so a
creator choosing "Payment Option access" on a *new* Pathway got a 422
from a choice the form offered. Live since Stage 0, and invisible
because every test for that access type built the row directly instead
of posting to the route.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.creator.routes import create_pathway, update_pathway
from app.creator.schemas import PathwayCreateRequest, PathwayUpdateRequest
from app.models.payment import PaymentTransaction, PaymentTransactionStatus
from app.models.platform import Pathway, PathwayEntitlement
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.services.pathway_access import compute_pathway_access


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def creator_space(db, make_user, make_space):
    owner = make_user(role="creator")
    return owner, make_space(creator=owner)


def _create(db, owner, space, **over):
    body = PathwayCreateRequest(**{
        "title": "Finding Your Courage",
        "create_channel": False,
        **over,
    })
    return create_pathway(
        slug=space.slug, body=body, background_tasks=BackgroundTasks(),
        db=db, current_user=owner,
    )


def _patch(db, owner, space, pathway_slug, **fields):
    """PATCH with only the named fields set, so ``exclude_unset`` behaves
    as it does for a real request body."""
    return update_pathway(
        slug=space.slug, pathway_slug=pathway_slug,
        body=PathwayUpdateRequest(**fields),
        background_tasks=BackgroundTasks(), db=db, current_user=owner,
    )


def _row(db, pathway_id) -> Pathway:
    p = db.get(Pathway, pathway_id)
    db.refresh(p)
    return p


# ---------------------------------------------------------------------------
# 1–2. Creating
# ---------------------------------------------------------------------------


class TestCreatingAPricedPathway:
    def test_a_direct_price_is_stored(self, db, creator_space):
        owner, space = creator_space
        result = _create(
            db, owner, space,
            access_type="one_time", price_cents=4900, currency="AUD",
        )
        assert result["access_type"] == "one_time"
        assert result["price_cents"] == 4900
        assert result["currency"] == "AUD"
        assert result["pricing_mode"] == "legacy"

    def test_a_non_aud_price_is_stored_as_given(self, db, creator_space):
        owner, space = creator_space
        result = _create(
            db, owner, space,
            access_type="one_time", price_cents=4900, currency="USD",
        )
        assert result["currency"] == "USD"

    def test_payment_option_access_can_be_chosen_at_creation(
        self, db, creator_space,
    ):
        """The bug. This returned 422 from a choice the form offered."""
        owner, space = creator_space
        result = _create(
            db, owner, space,
            access_type="included_with_offer", currency=None,
        )
        assert result["access_type"] == "included_with_offer"
        # No direct price, and the mode is still legacy until an Option
        # actually prices it — the adoption trigger owns that flip.
        assert result["price_cents"] is None
        assert result["pricing_mode"] == "legacy"

    def test_both_validators_now_accept_the_same_access_types(self):
        """The create and update validators disagreeing is what caused
        the bug, so the agreement is the thing to pin."""
        allowed = (
            "free", "included", "included_with_offer",
            "one_time", "subscription",
        )
        for value in allowed:
            PathwayCreateRequest(title="T", access_type=value)
            PathwayUpdateRequest(access_type=value)
        for cls in (PathwayCreateRequest, PathwayUpdateRequest):
            with pytest.raises(Exception):
                cls(**(
                    {"title": "T", "access_type": "nonsense"}
                    if cls is PathwayCreateRequest
                    else {"access_type": "nonsense"}
                ))


# ---------------------------------------------------------------------------
# 4–5. Editing, draft and published
# ---------------------------------------------------------------------------


class TestEditingThePrice:
    def test_a_draft_price_can_be_changed(self, db, creator_space):
        owner, space = creator_space
        created = _create(
            db, owner, space, status="draft",
            access_type="one_time", price_cents=4900, currency="AUD",
        )
        _patch(db, owner, space, created["slug"], price_cents=6900)
        assert _row(db, created["id"]).price_cents == 6900

    def test_a_published_price_can_be_changed(self, db, creator_space):
        """A$49 → A$69 on a live Pathway. The confirmed decision, and
        there is no status guard in the way."""
        owner, space = creator_space
        created = _create(
            db, owner, space, status="active",
            access_type="one_time", price_cents=4900, currency="AUD",
        )
        _patch(db, owner, space, created["slug"], price_cents=6900)
        row = _row(db, created["id"])
        assert row.price_cents == 6900
        assert row.status.value if hasattr(row.status, "value") else row.status

    def test_the_member_payload_reports_the_new_price(self, db, creator_space):
        """The display and the charge read the same column, so one
        assertion covers both."""
        owner, space = creator_space
        created = _create(
            db, owner, space, status="active",
            access_type="one_time", price_cents=4900, currency="AUD",
        )
        _patch(db, owner, space, created["slug"], price_cents=6900)

        from app.spaces.routes import get_pathway as member_get_pathway

        payload = member_get_pathway(
            slug=space.slug, pathway_slug=created["slug"],
            db=db, current_user=owner,
        )
        price = payload["price_cents"] if isinstance(payload, dict) else payload.price_cents
        assert price == 6900

    def test_stripe_receives_the_new_amount(self, db, creator_space, make_user):
        """The authoritative figure, read at request time. Mocked
        Stripe; no real charge."""
        from app.checkout.routes import _legacy_pathway_price_stripe_session
        from app.models.creator_billing import (
            CreatorPlan, CreatorSubscription, CreatorSubscriptionStatus,
        )

        owner, space = creator_space
        plan = CreatorPlan(
            id=_uid("cp"), slug="creator", name="Creator",
            monthly_price_cents=1900, currency="AUD",
            transaction_fee_basis_points=800, is_active=True,
            collective_limit=1,
        )
        db.add(plan)
        db.flush()
        db.add(CreatorSubscription(
            id=_uid("cs"), user_id=owner.id, creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow() - timedelta(days=1),
            source="stripe_paid",
        ))
        db.flush()

        created = _create(
            db, owner, space, status="active",
            access_type="one_time", price_cents=4900, currency="AUD",
        )
        _patch(db, owner, space, created["slug"], price_cents=6900)
        pathway = _row(db, created["id"])
        buyer = make_user(role="user")

        fake = SimpleNamespace(
            id=f"cs_test_{uuid.uuid4().hex[:12]}",
            url="https://checkout.stripe.test/p",
        )
        with patch("app.core.config.settings.stripe_secret_key", "sk_test_x"), \
             patch("app.core.config.settings.stripe_webhook_secret", "whsec_x"), \
             patch("stripe.checkout.Session.create", return_value=fake) as m:
            _legacy_pathway_price_stripe_session(
                db, pathway=pathway, payer=buyer,
                success_url="https://x.test/ok", cancel_url="https://x.test/no",
                now=datetime.utcnow(),
            )
        item = m.call_args.kwargs["line_items"][0]["price_data"]
        assert item["unit_amount"] == 6900
        assert item["currency"] == "aud"

        # And the fee is the plan's, on the new amount: 8% of $69.
        db.expire_all()
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.payer_user_id == buyer.id,
        ).one()
        assert txn.gross_amount_cents == 6900
        assert txn.platform_fee_basis_points == 800
        assert txn.platform_fee_cents == 552
        assert txn.net_creator_amount_cents == 6348


# ---------------------------------------------------------------------------
# 8–9. What a price change must not reach
# ---------------------------------------------------------------------------


class TestExistingPurchasesAreUntouched:
    def _sold(self, db, owner, space, buyer, *, price_cents=4900):
        created = _create(
            db, owner, space, status="active",
            access_type="one_time", price_cents=price_cents, currency="AUD",
        )
        pathway = _row(db, created["id"])
        txn = PaymentTransaction(
            id=_uid("txn"), space_id=space.id, payer_user_id=buyer.id,
            transaction_type="member_pathway_purchase",
            payment_provider="stripe",
            status=PaymentTransactionStatus.succeeded,
            gross_amount_cents=price_cents, currency="AUD",
            platform_fee_basis_points=800,
            platform_fee_cents=round(price_cents * 0.08),
            net_creator_amount_cents=price_cents - round(price_cents * 0.08),
            payout_model="manual", pathway_id=pathway.id,
        )
        db.add(txn)
        ent = PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, pathway_id=pathway.id,
            space_id=space.id, source="one_time_purchase",
        )
        db.add(ent)
        # Real fulfilment always does this: purchase_fulfilment calls
        # membership_grant.ensure_membership_for_purchase, so a buyer
        # holds an active ``learner`` SpaceMembership as well as the
        # entitlement. Without it this fixture is not a purchase that
        # can actually occur, and the ``included`` branch of
        # compute_pathway_access — which reads membership, not
        # entitlements — would refuse for the wrong reason.
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=buyer.id,
            role="learner", status=SpaceMembershipStatus.active,
            source="purchase", joined_at=datetime.utcnow(),
        ))
        db.flush()
        return created, pathway, txn, ent

    def test_a_historical_amount_is_not_rewritten(
        self, db, creator_space, make_user,
    ):
        owner, space = creator_space
        buyer = make_user(role="user")
        created, _p, txn, _e = self._sold(db, owner, space, buyer)

        _patch(db, owner, space, created["slug"], price_cents=6900)

        db.refresh(txn)
        assert txn.gross_amount_cents == 4900
        assert txn.platform_fee_cents == 392
        assert txn.net_creator_amount_cents == 4508

    def test_the_purchaser_keeps_access(self, db, creator_space, make_user):
        owner, space = creator_space
        buyer = make_user(role="user")
        created, pathway, _t, ent = self._sold(db, owner, space, buyer)

        _patch(db, owner, space, created["slug"], price_cents=6900)

        db.refresh(ent)
        assert ent.user_id == buyer.id
        assert ent.pathway_id == pathway.id
        # Asserted through the real runtime gate rather than the
        # narrower entitlement helper, so this fails if a price edit
        # breaks access by any route, not only by deleting the row.
        assert compute_pathway_access(
            buyer, _row(db, created["id"]), space, db, as_member=True,
        )

    def test_access_survives_moving_off_paid_access_entirely(
        self, db, creator_space, make_user,
    ):
        owner, space = creator_space
        buyer = make_user(role="user")
        created, pathway, _t, _e = self._sold(db, owner, space, buyer)

        _patch(db, owner, space, created["slug"], access_type="included")

        db.expire_all()
        assert compute_pathway_access(
            buyer, _row(db, created["id"]), space, db, as_member=True,
        )


# ---------------------------------------------------------------------------
# 10–14. Preserving an inactive price, and reactivating it deliberately
# ---------------------------------------------------------------------------


class TestAnInactivePriceIsKeptButNotOffered:
    def test_moving_to_members_only_preserves_the_price(
        self, db, creator_space,
    ):
        """Previously the form sent ``price_cents: null`` here and the
        $49 was destroyed, with no warning and no way back."""
        owner, space = creator_space
        created = _create(
            db, owner, space, status="active",
            access_type="one_time", price_cents=4900, currency="AUD",
        )
        _patch(db, owner, space, created["slug"], access_type="included")

        row = _row(db, created["id"])
        assert row.access_type == "included"
        assert row.price_cents == 4900, "the inactive price was destroyed"
        assert (row.currency or "AUD") == "AUD"

    def test_the_preserved_price_cannot_be_charged(self, db, creator_space, make_user):
        """The safeguard that matters. Storage and availability are
        separate concerns, and the checkout door is where that is
        enforced: it refuses anything but ``one_time``."""
        from app.checkout.routes import create_pathway_checkout_session
        from app.checkout.schemas import PathwayCheckoutRequest

        owner, space = creator_space
        created = _create(
            db, owner, space, status="active",
            access_type="one_time", price_cents=4900, currency="AUD",
        )
        _patch(db, owner, space, created["slug"], access_type="included")

        with patch("app.core.config.settings.stripe_secret_key", "sk_test_x"), \
             patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as exc:
                create_pathway_checkout_session(
                    PathwayCheckoutRequest(
                        pathway_id=created["id"],
                        success_url="https://x.test/ok",
                        cancel_url="https://x.test/no",
                    ),
                    current_user=make_user(role="user"), db=db,
                )
        assert exc.value.status_code == 400
        m.assert_not_called()

    def test_the_preserved_price_is_not_advertised(self, db, creator_space):
        """``isPathwayLocked`` covers only ``one_time``,
        ``subscription`` and ``included_with_offer``, so a members-only
        Pathway renders no price label. Asserted on the shared helper
        the card and the checkout page both use."""
        import pathlib

        helper = (
            pathlib.Path(__file__).resolve().parents[2]
            / "frontend" / "src" / "lib" / "pathwayAccess.ts"
        ).read_text()
        i = helper.index("export function isPathwayLocked")
        body = helper[i:i + 260]
        assert "'one_time'" in body
        assert "'included'" not in body.replace("'included_with_offer'", "")

    def test_returning_to_paid_access_finds_the_price_waiting(
        self, db, creator_space,
    ):
        """Reactivation is a deliberate act — the creator chooses
        One-time purchase again — and the amount they set is still
        there rather than needing to be retyped."""
        owner, space = creator_space
        created = _create(
            db, owner, space, status="active",
            access_type="one_time", price_cents=4900, currency="AUD",
        )
        _patch(db, owner, space, created["slug"], access_type="included")
        assert _row(db, created["id"]).price_cents == 4900

        _patch(db, owner, space, created["slug"], access_type="one_time")
        row = _row(db, created["id"])
        assert row.access_type == "one_time"
        assert row.price_cents == 4900

    def test_reactivation_is_not_automatic(self, db, creator_space):
        """Nothing flips the access type back on its own. The price
        sits dormant until the creator asks for it."""
        owner, space = creator_space
        created = _create(
            db, owner, space, status="active",
            access_type="one_time", price_cents=4900, currency="AUD",
        )
        _patch(db, owner, space, created["slug"], access_type="included")
        # Several unrelated edits later, it is still inactive.
        _patch(db, owner, space, created["slug"], title="Renamed")
        _patch(db, owner, space, created["slug"], description="New words")
        row = _row(db, created["id"])
        assert row.access_type == "included"
        assert row.price_cents == 4900


# ---------------------------------------------------------------------------
# 15–16. Currency, and leaving things alone
# ---------------------------------------------------------------------------


class TestCurrencyIsFixedOnceSet:
    def test_changing_it_is_refused(self, db, creator_space):
        owner, space = creator_space
        created = _create(
            db, owner, space, access_type="one_time",
            price_cents=4900, currency="AUD",
        )
        with pytest.raises(HTTPException) as exc:
            _patch(db, owner, space, created["slug"], currency="USD")
        assert exc.value.status_code == 400
        assert "cannot be changed" in str(exc.value.detail)
        assert _row(db, created["id"]).currency == "AUD"

    def test_resending_the_same_currency_is_fine(self, db, creator_space):
        """The form may legitimately echo it back; that is not a change."""
        owner, space = creator_space
        created = _create(
            db, owner, space, access_type="one_time",
            price_cents=4900, currency="AUD",
        )
        _patch(db, owner, space, created["slug"], currency="aud")
        assert _row(db, created["id"]).currency == "AUD"

    def test_an_unpriced_pathway_can_still_choose_its_currency(
        self, db, creator_space,
    ):
        """``pathways.currency`` is NOT NULL with a server default of
        ``'AUD'``, so every row has one from creation — including a free
        Pathway whose creator never chose it. Locking on the column
        alone would trap that Pathway in AUD forever. With no price
        there is no amount denominated in it, so the first real choice
        is allowed."""
        owner, space = creator_space
        created = _create(
            db, owner, space, access_type="included", currency=None,
        )
        row = _row(db, created["id"])
        assert row.currency == "AUD", "the column default"
        assert row.price_cents is None

        _patch(
            db, owner, space, created["slug"],
            access_type="one_time", price_cents=4900, currency="USD",
        )
        after = _row(db, created["id"])
        assert after.currency == "USD"
        assert after.price_cents == 4900

    def test_and_is_locked_from_then_on(self, db, creator_space):
        owner, space = creator_space
        created = _create(
            db, owner, space, access_type="included", currency=None,
        )
        _patch(
            db, owner, space, created["slug"],
            access_type="one_time", price_cents=4900, currency="USD",
        )
        with pytest.raises(HTTPException) as exc:
            _patch(db, owner, space, created["slug"], currency="AUD")
        assert exc.value.status_code == 400
        assert _row(db, created["id"]).currency == "USD"

    def test_it_is_never_silently_reset_to_aud(self, db, creator_space):
        """The live bug this replaces: Settings sent ``currency: 'AUD'``
        on every non-paid save, so editing a USD Pathway's title
        re-denominated it."""
        owner, space = creator_space
        created = _create(
            db, owner, space, access_type="one_time",
            price_cents=4900, currency="USD",
        )
        _patch(db, owner, space, created["slug"], title="Retitled")
        assert _row(db, created["id"]).currency == "USD"
        with pytest.raises(HTTPException):
            _patch(db, owner, space, created["slug"], currency="AUD")
        assert _row(db, created["id"]).currency == "USD"


class TestUnrelatedEditsLeavePricingAlone:
    def test_editing_the_title_changes_no_pricing_field(self, db, creator_space):
        owner, space = creator_space
        created = _create(
            db, owner, space, access_type="one_time",
            price_cents=4900, currency="AUD",
        )
        before = _row(db, created["id"])
        snapshot = (
            before.price_cents, before.currency,
            before.access_type, before.pricing_mode,
        )
        _patch(db, owner, space, created["slug"], title="A better title")
        after = _row(db, created["id"])
        assert (
            after.price_cents, after.currency,
            after.access_type, after.pricing_mode,
        ) == snapshot
        assert after.title == "A better title"


# ---------------------------------------------------------------------------
# 17–18. The protections that must still hold
# ---------------------------------------------------------------------------


class TestTheExistingProtectionsStillHold:
    def test_an_option_priced_pathway_still_refuses_the_direct_door(
        self, db, creator_space, make_user,
    ):
        """The $5/$2 protection. Stage 2A does not touch it — a direct
        price alongside an Option is Stage 2B, behind its own gate."""
        from app.checkout.routes import create_pathway_checkout_session
        from app.checkout.schemas import PathwayCheckoutRequest

        owner, space = creator_space
        created = _create(
            db, owner, space, status="active",
            access_type="one_time", price_cents=500, currency="AUD",
        )
        _patch(db, owner, space, created["slug"], pricing_mode="payment_options")

        with patch("app.core.config.settings.stripe_secret_key", "sk_test_x"), \
             patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as exc:
                create_pathway_checkout_session(
                    PathwayCheckoutRequest(
                        pathway_id=created["id"],
                        success_url="https://x.test/ok",
                        cancel_url="https://x.test/no",
                    ),
                    current_user=make_user(role="user"), db=db,
                )
        assert exc.value.status_code == 400
        assert "payment option" in str(exc.value.detail).lower()
        m.assert_not_called()
        # The dormant $5 is still on the row, and still not chargeable.
        assert _row(db, created["id"]).price_cents == 500

    def test_a_subscription_pathway_is_still_unsellable(
        self, db, creator_space, make_user,
    ):
        """Settable on the row, refused by the only door that could
        sell it. Pinned so restoring the price control did not quietly
        restore this too."""
        from app.checkout.routes import create_pathway_checkout_session
        from app.checkout.schemas import PathwayCheckoutRequest

        owner, space = creator_space
        created = _create(
            db, owner, space, status="active",
            access_type="subscription", price_cents=1900, currency="AUD",
        )
        with patch("app.core.config.settings.stripe_secret_key", "sk_test_x"), \
             patch("stripe.checkout.Session.create") as m:
            with pytest.raises(HTTPException) as exc:
                create_pathway_checkout_session(
                    PathwayCheckoutRequest(
                        pathway_id=created["id"],
                        success_url="https://x.test/ok",
                        cancel_url="https://x.test/no",
                    ),
                    current_user=make_user(role="user"), db=db,
                )
        assert exc.value.status_code == 400
        assert "one-time" in str(exc.value.detail).lower()
        m.assert_not_called()
