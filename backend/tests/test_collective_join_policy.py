"""How people get into a Collective.

Free joining stays first-class — ``open`` is the default, every
existing Collective has it, and nothing about that path changes.
``purchase_required`` closes the free door only, and only for the
Collectives whose creators choose it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_current_user, get_optional_user, get_verified_creator_user,
    get_verified_current_user,
)
from app.core.database import get_db
from app.main import app
from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.services.membership_grant import ensure_membership_for_purchase
from app.spaces import join_policy
from app.spaces.joining_doors import list_joining_doors


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    for dep in (get_current_user, get_optional_user,
                get_verified_current_user, get_verified_creator_user):
        app.dependency_overrides[dep] = lambda u=user: u


def membership(db, space, user):
    return (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id,
                SpaceMembership.user_id == user.id)
        .first()
    )


def make_option(db, space, **over):
    opt = PaymentOption(
        id=f"po_{uuid.uuid4().hex[:16]}",
        space_id=space.id,
        attaches_to_kind=over.pop("attaches_to_kind", "event_series"),
        attaches_to_id=over.pop("attaches_to_id", "es_test"),
        name=over.pop("name", "Term 4"),
        payment_type=over.pop("payment_type", PaymentOptionType.term_pass),
        status=over.pop("status", PaymentOptionStatus.published),
        currency="AUD",
        override_total_cents=over.pop("override_total_cents", 45000),
        is_joining_option=over.pop("is_joining_option", False),
        **over,
    )
    db.add(opt)
    db.flush()
    return opt


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


class TestPolicyVocabulary:
    def test_the_two_policies(self):
        assert join_policy.JOIN_POLICIES == ("open", "purchase_required")

    @pytest.mark.parametrize("bad", ["invite_only", "", "OPEN ", "free", None, 3])
    def test_unknown_values_are_refused_on_write(self, bad):
        """Strict: a typo must never quietly widen or close a door."""
        with pytest.raises(join_policy.JoinPolicyError):
            join_policy.validate(bad)

    def test_valid_values_round_trip(self):
        assert join_policy.validate(" open ") == "open"
        assert join_policy.validate("purchase_required") == "purchase_required"

    @pytest.mark.parametrize("stored", [None, "", "nonsense", 7])
    def test_unreadable_stored_values_resolve_to_open(self, stored):
        """Read-time is the wrong place to start refusing entry over a
        bad byte — write-time validation is where that is caught."""
        assert join_policy.resolve(stored) == "open"
        assert join_policy.allows_free_join(stored) is True


# ---------------------------------------------------------------------------
# Free joining — unchanged
# ---------------------------------------------------------------------------


class TestOpenCollectivesStillJoinFreely:
    def test_an_existing_collective_defaults_to_open(self, db, make_space):
        """Migration 136's whole promise: nothing changes until a
        creator says so."""
        space = make_space(is_public=True)
        db.flush()
        assert space.join_policy == "open"

    def test_free_join_works(self, client, db, make_space, make_user):
        space = make_space(is_public=True)
        joiner = make_user(role="user")
        db.flush()
        as_user(joiner)
        res = client.post(f"/api/spaces/{space.slug}/join")
        assert res.status_code == 201, res.text
        assert res.json() == {"joined": True, "already_member": False}
        assert membership(db, space, joiner).status == SpaceMembershipStatus.active

    def test_joining_twice_is_harmless(self, client, db, make_space, make_user):
        space = make_space(is_public=True)
        joiner = make_user(role="user")
        db.flush()
        as_user(joiner)
        client.post(f"/api/spaces/{space.slug}/join")
        res = client.post(f"/api/spaces/{space.slug}/join")
        assert res.json()["already_member"] is True


class TestPurchaseRequiredClosesTheFreeDoor:
    def test_free_join_is_refused_by_the_server(
        self, client, db, make_space, make_user,
    ):
        """Not by hiding the button. The endpoint is the boundary."""
        space = make_space(is_public=True, join_policy="purchase_required")
        joiner = make_user(role="user")
        db.flush()
        as_user(joiner)
        res = client.post(f"/api/spaces/{space.slug}/join")
        assert res.status_code == 403, res.text
        assert membership(db, space, joiner) is None

    def test_the_refusal_carries_a_stable_code(
        self, client, db, make_space, make_user,
    ):
        space = make_space(is_public=True, join_policy="purchase_required")
        db.flush()
        as_user(make_user(role="user"))
        detail = client.post(f"/api/spaces/{space.slug}/join").json()["detail"]
        assert detail["code"] == "join_purchase_required"
        assert detail["message"]

    def test_an_existing_member_is_unaffected(
        self, client, db, make_space, make_user,
    ):
        """Switching the policy must not evict anybody."""
        space = make_space(is_public=True)
        member = make_user(role="user")
        db.add(SpaceMembership(
            id=str(uuid.uuid4()), user_id=member.id, space_id=space.id,
            role="learner", status="active", source="joined",
        ))
        space.join_policy = "purchase_required"
        db.flush()
        assert membership(db, space, member).status == SpaceMembershipStatus.active

    def test_private_collectives_still_refuse_first(
        self, client, db, make_space, make_user,
    ):
        """The private guard runs before the policy guard; a private
        Collective's message should still point at request-access."""
        space = make_space(is_public=False, join_policy="purchase_required")
        db.flush()
        as_user(make_user(role="user"))
        res = client.post(f"/api/spaces/{space.slug}/join")
        assert res.status_code == 403
        assert "private" in str(res.json()["detail"]).lower()

    def test_auto_managed_collectives_are_unchanged(
        self, client, db, make_space, make_user,
    ):
        """World Builders answers before the policy is consulted."""
        space = make_space(is_public=True, auto_grant_role="creator")
        db.flush()
        as_user(make_user(role="user"))
        res = client.post(f"/api/spaces/{space.slug}/join")
        assert res.status_code == 403
        assert "automatically" in str(res.json()["detail"]).lower()


# ---------------------------------------------------------------------------
# Membership that arrives with a purchase
# ---------------------------------------------------------------------------


class TestPurchaseMembership:
    def test_a_purchase_creates_membership(self, db, make_space, make_user):
        space = make_space(is_public=True, join_policy="purchase_required")
        buyer = make_user(role="user")
        db.flush()
        out = ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert out.created and out.changed
        row = membership(db, space, buyer)
        assert row.status == SpaceMembershipStatus.active
        assert row.source == "purchase"
        assert row.role == "learner"

    def test_an_active_membership_is_left_entirely_alone(
        self, db, make_space, make_user,
    ):
        space = make_space(is_public=True)
        buyer = make_user(role="user")
        db.add(SpaceMembership(
            id=str(uuid.uuid4()), user_id=buyer.id, space_id=space.id,
            role="moderator", status="active", source="invited",
        ))
        db.flush()
        out = ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert not out.changed
        assert out.skipped_reason == "already_active"
        row = membership(db, space, buyer)
        assert row.role == "moderator", "buying must not demote a moderator"
        assert row.source == "invited", "nor rewrite how they first arrived"

    def test_no_duplicate_row_is_ever_created(self, db, make_space, make_user):
        space = make_space(is_public=True)
        buyer = make_user(role="user")
        db.flush()
        for _ in range(3):
            ensure_membership_for_purchase(
                db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
            )
        count = (
            db.query(SpaceMembership)
            .filter(SpaceMembership.space_id == space.id,
                    SpaceMembership.user_id == buyer.id)
            .count()
        )
        assert count == 1

    @pytest.mark.parametrize("source", ["purchase", "joined", "ticket_purchase"])
    def test_a_removed_self_service_membership_is_restored(
        self, db, make_space, make_user, source,
    ):
        """They chose to be here once, or paid to be; they have paid
        again. Leaving a buyer outside the Collective they just bought
        into is the failure this fixes."""
        space = make_space(is_public=True)
        buyer = make_user(role="user")
        db.add(SpaceMembership(
            id=str(uuid.uuid4()), user_id=buyer.id, space_id=space.id,
            role="learner", status="removed", source=source,
        ))
        db.flush()
        out = ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert out.reactivated
        row = membership(db, space, buyer)
        assert row.status == SpaceMembershipStatus.active
        assert row.source == source, "provenance of the original join is kept"

    @pytest.mark.parametrize("source", [
        "auto_role", "creator_owner", "invited", "manual", "manual_grant",
        "creator_pass", "template",
    ])
    def test_a_removed_platform_or_person_granted_membership_is_not_restored(
        self, db, make_space, make_user, source,
    ):
        """A card being charged is not consent to overturn a decision
        somebody made about this person."""
        space = make_space(is_public=True)
        buyer = make_user(role="user")
        db.add(SpaceMembership(
            id=str(uuid.uuid4()), user_id=buyer.id, space_id=space.id,
            role="learner", status="removed", source=source,
        ))
        db.flush()
        out = ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert not out.changed
        assert out.skipped_reason == f"source_{source}"
        assert membership(db, space, buyer).status == SpaceMembershipStatus.removed

    def test_a_paused_membership_is_not_restored(self, db, make_space, make_user):
        """``paused`` is written only by the auto-grant eligibility
        sweep — platform-held state, not a door a purchase opens."""
        space = make_space(is_public=True)
        buyer = make_user(role="user")
        db.add(SpaceMembership(
            id=str(uuid.uuid4()), user_id=buyer.id, space_id=space.id,
            role="learner", status="paused", source="purchase",
        ))
        db.flush()
        out = ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert not out.changed
        assert out.skipped_reason == "status_paused"

    def test_an_auto_managed_collective_is_never_touched(
        self, db, make_space, make_user,
    ):
        space = make_space(is_public=True, auto_grant_role="creator")
        buyer = make_user(role="user")
        db.flush()
        out = ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert out.skipped_reason == "auto_managed_collective"
        assert membership(db, space, buyer) is None


# ---------------------------------------------------------------------------
# Joining doors
# ---------------------------------------------------------------------------


class TestJoiningDoors:
    def test_a_nominated_published_option_is_offered(self, db, make_space):
        space = make_space(is_public=True, join_policy="purchase_required")
        make_option(db, space, is_joining_option=True, name="Term 4 — 2x week")
        doors = list_joining_doors(db, space)
        assert [d["name"] for d in doors] == ["Term 4 — 2x week"]
        assert doors[0]["price_cents"] == 45000

    def test_an_option_the_creator_did_not_nominate_is_not_a_door(self, db, make_space):
        """A Collective sells many things; only some are ways in."""
        space = make_space(is_public=True, join_policy="purchase_required")
        make_option(db, space, is_joining_option=False, name="Single workshop")
        assert list_joining_doors(db, space) == []

    @pytest.mark.parametrize("status", [
        PaymentOptionStatus.draft, PaymentOptionStatus.archived,
    ])
    def test_an_unpublished_option_is_never_shown(self, db, make_space, status):
        space = make_space(is_public=True, join_policy="purchase_required")
        make_option(db, space, is_joining_option=True, status=status)
        assert list_joining_doors(db, space) == []

    def test_an_open_collective_offers_no_doors(self, db, make_space):
        """It has a free one."""
        space = make_space(is_public=True)
        make_option(db, space, is_joining_option=True)
        assert list_joining_doors(db, space) == []

    def test_no_nominated_options_is_an_empty_answer_not_a_free_door(
        self, client, db, make_space, make_user,
    ):
        """The escape hatch that must not exist: a purchase-required
        Collective with nothing to sell stays closed."""
        space = make_space(is_public=True, join_policy="purchase_required")
        db.flush()
        assert list_joining_doors(db, space) == []
        as_user(make_user(role="user"))
        assert client.post(f"/api/spaces/{space.slug}/join").status_code == 403

    def test_doors_from_another_collective_never_leak_in(
        self, db, make_space,
    ):
        mine = make_space(is_public=True, join_policy="purchase_required")
        theirs = make_space(is_public=True, join_policy="purchase_required")
        make_option(db, theirs, is_joining_option=True, name="Their door")
        assert list_joining_doors(db, mine) == []

    def test_nomination_does_not_change_what_the_option_grants(self, db, make_space):
        """The flag is presentation. Entitlements come from the grants
        layer and are untouched by it."""
        space = make_space(is_public=True, join_policy="purchase_required")
        opt = make_option(db, space, is_joining_option=True, grants_pathway_id=None)
        before = (opt.attaches_to_kind, opt.attaches_to_id, opt.grants_pathway_id)
        list_joining_doors(db, space)
        db.refresh(opt)
        assert (opt.attaches_to_kind, opt.attaches_to_id, opt.grants_pathway_id) == before


class TestTheSpacePayload:
    def test_an_open_collective_reports_open_and_no_doors(
        self, client, db, make_space,
    ):
        space = make_space(is_public=True)
        db.flush()
        app.dependency_overrides[get_optional_user] = lambda: None
        body = client.get(f"/api/spaces/{space.slug}").json()
        assert body["join_policy"] == "open"
        assert body["joining_options"] == []

    def test_a_purchase_required_collective_publishes_its_doors(
        self, client, db, make_space,
    ):
        space = make_space(is_public=True, join_policy="purchase_required")
        make_option(db, space, is_joining_option=True, name="Term 4")
        db.flush()
        app.dependency_overrides[get_optional_user] = lambda: None
        body = client.get(f"/api/spaces/{space.slug}").json()
        assert body["join_policy"] == "purchase_required"
        assert [o["name"] for o in body["joining_options"]] == ["Term 4"]


class TestCreatorConfiguration:
    def test_the_owner_can_set_the_policy(self, client, db, make_space, make_user):
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner)
        db.flush()
        as_user(owner)
        res = client.patch(
            f"/api/creator/spaces/{space.slug}",
            json={"join_policy": "purchase_required"},
        )
        assert res.status_code == 200, res.text
        db.refresh(space)
        assert space.join_policy == "purchase_required"
        assert res.json()["join_policy"] == "purchase_required"

    def test_an_invalid_policy_is_a_400(self, client, db, make_space, make_user):
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner)
        db.flush()
        as_user(owner)
        res = client.patch(
            f"/api/creator/spaces/{space.slug}", json={"join_policy": "invite_only"},
        )
        assert res.status_code == 400, res.text
        db.refresh(space)
        assert space.join_policy == "open"

    def test_other_edits_do_not_disturb_the_policy(
        self, client, db, make_space, make_user,
    ):
        owner = make_user(role="creator")
        space = make_space(
            is_public=True, creator=owner, join_policy="purchase_required",
        )
        db.flush()
        as_user(owner)
        client.patch(f"/api/creator/spaces/{space.slug}", json={"tagline": "Hello"})
        db.refresh(space)
        assert space.join_policy == "purchase_required"


# ---------------------------------------------------------------------------
# Standalone Gathering tickets — the path that used to be the exception
# ---------------------------------------------------------------------------


class TestStandaloneTicketPurchase:
    """A seat at one Gathering now brings the buyer into the
    Collective, like every other purchase. It used to mint the booking
    and the pass and leave them a non-member — which a
    purchase-required Collective would experience as selling a
    Gathering to someone who then could not get in."""

    @staticmethod
    def _hold(db, event, buyer):
        from app.services import gathering_tickets as gt
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        return gt.create_or_reuse_hold(
            db, offer=offer, buyer=buyer, hold_ttl_minutes=30,
            fee_bps=800, creator_plan_id=None, creator_subscription_id=None,
        )

    @staticmethod
    def _fulfil(db, event, buyer, txn_id, amount):
        from app.services import gathering_tickets as gt
        return gt.fulfil_ticket_purchase(
            db,
            transaction_id=txn_id,
            event_id=event.id,
            payer_user_id=buyer.id,
            stripe_amount_total=amount,
            stripe_currency="AUD",
            stripe_payment_intent_id="pi_join_1",
            stripe_charge_id="ch_join_1",
        )

    def test_buying_a_ticket_makes_the_buyer_a_member(
        self, db, make_event, make_user,
    ):
        event = make_event()
        buyer = make_user()
        held = self._hold(db, event, buyer)
        self._fulfil(db, event, buyer, held.transaction.id,
                     held.transaction.gross_amount_cents)

        row = (
            db.query(SpaceMembership)
            .filter(SpaceMembership.space_id == event.space_id,
                    SpaceMembership.user_id == buyer.id)
            .first()
        )
        assert row is not None, "ticket buyer was left outside the Collective"
        assert row.status == SpaceMembershipStatus.active
        assert row.source == "ticket_purchase"

    def test_an_existing_member_keeps_their_role(self, db, make_event, make_user):
        event = make_event()
        buyer = make_user()
        db.add(SpaceMembership(
            id=str(uuid.uuid4()), user_id=buyer.id, space_id=event.space_id,
            role="moderator", status="active", source="invited",
        ))
        db.flush()
        held = self._hold(db, event, buyer)
        self._fulfil(db, event, buyer, held.transaction.id,
                     held.transaction.gross_amount_cents)
        row = (
            db.query(SpaceMembership)
            .filter(SpaceMembership.space_id == event.space_id,
                    SpaceMembership.user_id == buyer.id)
            .one()
        )
        assert row.role == "moderator"
        assert row.source == "invited"

    def test_the_booking_still_works_exactly_as_before(
        self, db, make_event, make_user,
    ):
        """Membership is an addition, not a change to what a ticket
        buys."""
        from app.models.platform import BookingStatus
        event = make_event()
        buyer = make_user()
        held = self._hold(db, event, buyer)
        result = self._fulfil(db, event, buyer, held.transaction.id,
                              held.transaction.gross_amount_cents)
        assert result.booking.status == BookingStatus.confirmed
        assert result.booking.access_pass_id == result.access_pass.id
        assert result.access_pass.space_id == event.space_id

    def test_membership_lands_in_the_same_transaction_as_the_booking(
        self, db, make_event, make_user,
    ):
        """Atomicity: rolling back the fulfilment must take the
        membership with it, or a failed purchase leaves a member."""
        event = make_event()
        buyer = make_user()
        held = self._hold(db, event, buyer)
        txn_id, amount = held.transaction.id, held.transaction.gross_amount_cents
        self._fulfil(db, event, buyer, txn_id, amount)
        db.rollback()
        row = (
            db.query(SpaceMembership)
            .filter(SpaceMembership.space_id == event.space_id,
                    SpaceMembership.user_id == buyer.id)
            .first()
        )
        assert row is None


class TestFailedPaymentGrantsNothing:
    def test_a_failed_first_payment_creates_no_membership(
        self, db, make_event, make_user,
    ):
        """A hold is not a purchase. Nothing is fulfilled, so nobody
        joins."""
        from app.services import gathering_tickets as gt
        event = make_event()
        buyer = make_user()
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        gt.create_or_reuse_hold(
            db, offer=offer, buyer=buyer, hold_ttl_minutes=30,
            fee_bps=800, creator_plan_id=None, creator_subscription_id=None,
        )
        row = (
            db.query(SpaceMembership)
            .filter(SpaceMembership.space_id == event.space_id,
                    SpaceMembership.user_id == buyer.id)
            .first()
        )
        assert row is None
