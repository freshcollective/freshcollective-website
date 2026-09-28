"""Creator CRUD for discount codes — validation, editability, isolation.

Work Item 2 is the management layer only. Nothing here redeems anything;
where a test needs a redeemed code it writes a ledger row directly,
because redemption fulfilment is a later work item and this layer must
already behave correctly once rows exist.

Isolation is the part worth being strict about. A creator's codes are
their own, and a refusal must not confirm that another creator's code
exists — so every cross-Collective attempt is expected to read as 404,
which is the convention the Payment Option routes already use.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.discount_code import DiscountCode, DiscountRedemption
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus, SpaceRole


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user


def make_collective(db, make_user, make_space):
    """A Creator who owns and manages a Collective."""
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=creator.id, space_id=space.id,
        role=SpaceRole.creator, status=SpaceMembershipStatus.active,
    ))
    db.commit()
    return creator, space


def make_option(db, space, name="Activate") -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, name=name,
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        attaches_to_kind="space", attaches_to_id=space.id,
        calculated_total_cents=30600, currency="AUD",
    )
    db.add(opt)
    db.commit()
    return opt


def redeem(db, code, space, *, times=1):
    """Write ledger rows directly — fulfilment is a later work item, but
    this layer must already respect redemptions that exist."""
    for _ in range(times):
        txn = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.applied,
            space_id=space.id, currency="AUD",
            gross_amount_cents=15300, platform_fee_basis_points=0,
            platform_fee_cents=0, net_creator_amount_cents=15300,
            net_platform_amount_cents=0, stripe_mode="test",
            payout_status=PayoutStatus.pending,
        )
        db.add(txn)
        db.flush()
        db.add(DiscountRedemption(
            id=_uid("dr"), discount_code_id=code["id"], space_id=space.id,
            payment_transaction_id=txn.id,
            original_amount_cents=30600, discount_amount_cents=15300,
            final_amount_cents=15300, currency="AUD",
        ))
    db.commit()


HALF_OFF = {"code": "FAMILY50", "discount_type": "percentage", "percent_bps": 5000}


def base(slug: str) -> str:
    return f"/api/creator/spaces/{slug}/discount-codes"


@pytest.fixture
def collective(db, make_user, make_space):
    return make_collective(db, make_user, make_space)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_a_percentage_code_is_created_and_active_by_default(self, client, collective):
        creator, space = collective
        as_user(creator)

        res = client.post(base(space.slug), json=HALF_OFF)

        assert res.status_code == 201, res.text
        body = res.json()
        assert body["code"] == "FAMILY50"
        assert body["percent_bps"] == 5000
        assert body["is_active"] is True
        assert body["scope_kind"] == "space"
        assert body["redemption_count"] == 0
        assert body["definition_editable"] is True
        assert body["deletable"] is True

    @pytest.mark.parametrize("typed", ["family50", "Family50", "  family50  "])
    def test_the_code_is_stored_canonically_upper(self, client, collective, typed):
        creator, space = collective
        as_user(creator)

        res = client.post(base(space.slug), json={**HALF_OFF, "code": typed})

        assert res.status_code == 201, res.text
        assert res.json()["code"] == "FAMILY50"

    def test_a_fixed_amount_code_needs_an_amount_and_currency(self, client, collective):
        creator, space = collective
        as_user(creator)

        ok = client.post(base(space.slug), json={
            "code": "TAKE50", "discount_type": "fixed_amount",
            "amount_cents": 5000, "currency": "aud",
        })
        assert ok.status_code == 201, ok.text
        assert ok.json()["amount_cents"] == 5000
        assert ok.json()["currency"] == "AUD"

        no_currency = client.post(base(space.slug), json={
            "code": "TAKE51", "discount_type": "fixed_amount", "amount_cents": 5000,
        })
        assert no_currency.status_code == 422

    def test_percentage_and_amount_together_are_refused(self, client, collective):
        creator, space = collective
        as_user(creator)

        res = client.post(base(space.slug), json={
            "code": "BOTH", "discount_type": "percentage",
            "percent_bps": 5000, "amount_cents": 500,
        })
        assert res.status_code == 422

    @pytest.mark.parametrize("bps", [0, -1, 10000, 20000])
    def test_the_percentage_ceiling_is_ninety_nine(self, client, collective, bps):
        """100% is a complimentary pass, not a discount — the constant
        declared in Work Item 1 is enforced here."""
        creator, space = collective
        as_user(creator)

        res = client.post(base(space.slug), json={
            "code": "TOOMUCH", "discount_type": "percentage", "percent_bps": bps,
        })
        assert res.status_code == 422

    def test_ninety_nine_percent_is_allowed(self, client, collective):
        creator, space = collective
        as_user(creator)
        res = client.post(base(space.slug), json={
            "code": "NEARLYFREE", "discount_type": "percentage", "percent_bps": 9900,
        })
        assert res.status_code == 201, res.text

    def test_a_zero_or_negative_fixed_amount_is_refused(self, client, collective):
        creator, space = collective
        as_user(creator)
        for amount in (0, -100):
            res = client.post(base(space.slug), json={
                "code": "ZERO", "discount_type": "fixed_amount",
                "amount_cents": amount, "currency": "AUD",
            })
            assert res.status_code == 422

    def test_an_option_scoped_code_names_an_option_in_this_collective(
        self, client, db, collective,
    ):
        creator, space = collective
        option = make_option(db, space)
        as_user(creator)

        res = client.post(base(space.slug), json={
            **HALF_OFF, "code": "ACTIVATE50",
            "scope_kind": "payment_option", "scope_id": option.id,
        })

        assert res.status_code == 201, res.text
        assert res.json()["scope_id"] == option.id
        assert res.json()["scope_payment_option_name"] == "Activate"

    def test_an_option_scope_without_an_option_is_refused(self, client, collective):
        creator, space = collective
        as_user(creator)
        res = client.post(base(space.slug), json={
            **HALF_OFF, "scope_kind": "payment_option", "scope_id": None,
        })
        assert res.status_code == 422

    def test_a_collective_wide_code_may_not_name_an_option(self, client, db, collective):
        creator, space = collective
        option = make_option(db, space)
        as_user(creator)
        res = client.post(base(space.slug), json={
            **HALF_OFF, "scope_kind": "space", "scope_id": option.id,
        })
        assert res.status_code == 422

    def test_optional_expiry_and_limit_are_stored(self, client, collective):
        creator, space = collective
        as_user(creator)
        expires = (datetime.utcnow() + timedelta(days=30)).isoformat()

        res = client.post(base(space.slug), json={
            **HALF_OFF, "expires_at": expires, "max_redemptions": 25,
        })

        assert res.status_code == 201, res.text
        assert res.json()["max_redemptions"] == 25
        assert res.json()["expires_at"] is not None

    def test_a_blank_code_is_refused(self, client, collective):
        creator, space = collective
        as_user(creator)
        assert client.post(base(space.slug),
                           json={**HALF_OFF, "code": "   "}).status_code == 422


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------

class TestUniqueness:
    def test_the_same_code_twice_in_one_collective_is_refused(self, client, collective):
        creator, space = collective
        as_user(creator)

        assert client.post(base(space.slug), json=HALF_OFF).status_code == 201
        clash = client.post(base(space.slug), json=HALF_OFF)

        assert clash.status_code == 409
        assert "FAMILY50" in clash.json()["detail"]

    def test_case_does_not_escape_uniqueness(self, client, collective):
        creator, space = collective
        as_user(creator)

        client.post(base(space.slug), json=HALF_OFF)
        clash = client.post(base(space.slug), json={**HALF_OFF, "code": "family50"})

        assert clash.status_code == 409

    def test_two_collectives_may_both_run_family50(
        self, client, db, make_user, make_space,
    ):
        creator_a, space_a = make_collective(db, make_user, make_space)
        creator_b, space_b = make_collective(db, make_user, make_space)

        as_user(creator_a)
        assert client.post(base(space_a.slug), json=HALF_OFF).status_code == 201
        as_user(creator_b)
        assert client.post(base(space_b.slug), json=HALF_OFF).status_code == 201


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------

class TestIsolation:
    @pytest.fixture
    def two_creators(self, client, db, make_user, make_space):
        creator_a, space_a = make_collective(db, make_user, make_space)
        creator_b, space_b = make_collective(db, make_user, make_space)
        as_user(creator_a)
        code = client.post(base(space_a.slug), json=HALF_OFF).json()
        return creator_a, space_a, creator_b, space_b, code

    def test_a_creator_cannot_list_another_creators_codes(self, client, two_creators):
        _a, space_a, creator_b, space_b, _code = two_creators

        as_user(creator_b)
        own = client.get(base(space_b.slug))
        assert own.status_code == 200
        assert own.json() == []

        # And asking for A's Collective by slug is refused outright.
        assert client.get(base(space_a.slug)).status_code == 403

    def test_a_creator_cannot_read_another_creators_code(self, client, two_creators):
        """Addressed through B's own Collective, A's code simply is not
        found — the refusal does not confirm it exists."""
        _a, _space_a, creator_b, space_b, code = two_creators
        as_user(creator_b)

        assert client.get(f"{base(space_b.slug)}/{code['id']}").status_code == 404

    def test_a_creator_cannot_update_another_creators_code(self, client, two_creators):
        _a, _space_a, creator_b, space_b, code = two_creators
        as_user(creator_b)

        res = client.patch(f"{base(space_b.slug)}/{code['id']}",
                           json={"is_active": False})
        assert res.status_code == 404

    def test_a_creator_cannot_delete_another_creators_code(self, client, two_creators):
        _a, _space_a, creator_b, space_b, code = two_creators
        as_user(creator_b)

        assert client.delete(f"{base(space_b.slug)}/{code['id']}").status_code == 404

    def test_a_creator_cannot_deactivate_another_creators_code(self, client, two_creators):
        _a, _space_a, creator_b, space_b, code = two_creators
        as_user(creator_b)

        res = client.post(f"{base(space_b.slug)}/{code['id']}/deactivate")
        assert res.status_code == 404

    def test_addressing_another_collective_directly_is_forbidden(self, client, two_creators):
        """``_get_managed_space`` answers before any code lookup: a
        Creator who does not manage the Collective is refused there."""
        _a, space_a, creator_b, _space_b, code = two_creators
        as_user(creator_b)

        assert client.get(f"{base(space_a.slug)}/{code['id']}").status_code == 403

    def test_another_collectives_option_cannot_be_used_as_scope(
        self, client, db, two_creators,
    ):
        _a, space_a, creator_b, space_b, _code = two_creators
        foreign_option = make_option(db, space_a, name="Their Offer")
        as_user(creator_b)

        res = client.post(base(space_b.slug), json={
            **HALF_OFF, "code": "BORROWED",
            "scope_kind": "payment_option", "scope_id": foreign_option.id,
        })

        assert res.status_code == 400
        assert "not found in this Collective" in res.json()["detail"]

    def test_an_unknown_collective_is_not_found(self, client, collective):
        creator, _space = collective
        as_user(creator)
        assert client.get(base("no-such-collective")).status_code == 404


# ---------------------------------------------------------------------------
# Editability
# ---------------------------------------------------------------------------

class TestEditabilityBeforeRedemption:
    @pytest.fixture
    def code(self, client, collective):
        creator, space = collective
        as_user(creator)
        return creator, space, client.post(base(space.slug), json=HALF_OFF).json()

    def test_everything_about_the_definition_may_change(self, client, code):
        _creator, space, row = code

        res = client.patch(f"{base(space.slug)}/{row['id']}", json={
            "code": "FAMILY25", "percent_bps": 2500,
        })

        assert res.status_code == 200, res.text
        assert res.json()["code"] == "FAMILY25"
        assert res.json()["percent_bps"] == 2500

    def test_switching_type_must_leave_a_coherent_row(self, client, code):
        """A patch sending only ``discount_type`` would otherwise leave a
        percentage on a fixed-amount code — refused with a message a
        Creator can act on, rather than a database error."""
        _creator, space, row = code

        half = client.patch(f"{base(space.slug)}/{row['id']}",
                            json={"discount_type": "fixed_amount"})
        assert half.status_code == 422

        whole = client.patch(f"{base(space.slug)}/{row['id']}", json={
            "discount_type": "fixed_amount", "percent_bps": None,
            "amount_cents": 5000, "currency": "AUD",
        })
        assert whole.status_code == 200, whole.text
        assert whole.json()["discount_type"] == "fixed_amount"

    def test_renaming_onto_an_existing_code_is_refused(self, client, code):
        _creator, space, row = code
        client.post(base(space.slug), json={**HALF_OFF, "code": "OTHER"})

        res = client.patch(f"{base(space.slug)}/{row['id']}", json={"code": "OTHER"})
        assert res.status_code == 409

    def test_renaming_to_its_own_code_is_fine(self, client, code):
        _creator, space, row = code
        res = client.patch(f"{base(space.slug)}/{row['id']}", json={"code": "family50"})
        assert res.status_code == 200, res.text

    def test_scope_may_be_narrowed_and_widened(self, client, db, code):
        _creator, space, row = code
        option = make_option(db, space)

        narrowed = client.patch(f"{base(space.slug)}/{row['id']}", json={
            "scope_kind": "payment_option", "scope_id": option.id,
        })
        assert narrowed.status_code == 200, narrowed.text
        assert narrowed.json()["scope_id"] == option.id

        widened = client.patch(f"{base(space.slug)}/{row['id']}",
                               json={"scope_kind": "space"})
        assert widened.status_code == 200, widened.text
        assert widened.json()["scope_id"] is None


class TestEditabilityAfterRedemption:
    @pytest.fixture
    def redeemed(self, client, db, collective):
        creator, space = collective
        as_user(creator)
        row = client.post(base(space.slug), json={**HALF_OFF, "max_redemptions": 10}).json()
        redeem(db, row, space, times=3)
        return creator, space, row

    def test_the_count_is_reported_from_the_ledger(self, client, redeemed):
        _creator, space, row = redeemed
        body = client.get(f"{base(space.slug)}/{row['id']}").json()

        assert body["redemption_count"] == 3
        assert body["definition_editable"] is False
        assert body["deletable"] is False

    @pytest.mark.parametrize("patch", [
        {"code": "SOMETHINGELSE"},
        {"discount_type": "fixed_amount"},
        {"percent_bps": 1000},
        {"amount_cents": 500},
        {"currency": "USD"},
        {"scope_kind": "payment_option", "scope_id": "po_x"},
    ])
    def test_the_definition_is_frozen(self, client, redeemed, patch):
        _creator, space, row = redeemed

        res = client.patch(f"{base(space.slug)}/{row['id']}", json=patch)

        assert res.status_code == 409
        assert "redeemed" in res.json()["detail"]

    def test_operational_fields_stay_editable(self, client, redeemed):
        """What happens next, as opposed to what already happened."""
        _creator, space, row = redeemed
        later = (datetime.utcnow() + timedelta(days=60)).isoformat()

        res = client.patch(f"{base(space.slug)}/{row['id']}", json={
            "is_active": False, "expires_at": later, "max_redemptions": 50,
        })

        assert res.status_code == 200, res.text
        assert res.json()["is_active"] is False
        assert res.json()["max_redemptions"] == 50

    def test_the_limit_cannot_drop_below_what_is_already_used(self, client, redeemed):
        _creator, space, row = redeemed

        res = client.patch(f"{base(space.slug)}/{row['id']}",
                           json={"max_redemptions": 2})

        assert res.status_code == 409
        assert "redeemed 3 times" in res.json()["detail"]

    def test_the_limit_may_be_set_exactly_to_what_is_used(self, client, redeemed):
        """Closing a code to further use without deactivating it."""
        _creator, space, row = redeemed
        res = client.patch(f"{base(space.slug)}/{row['id']}",
                           json={"max_redemptions": 3})
        assert res.status_code == 200, res.text

    def test_deactivation_still_works(self, client, redeemed):
        """The alternative to deleting — it must never be refused, or a
        redeemed code would have no way to be stopped."""
        _creator, space, row = redeemed

        res = client.post(f"{base(space.slug)}/{row['id']}/deactivate")

        assert res.status_code == 200, res.text
        assert res.json()["is_active"] is False


# ---------------------------------------------------------------------------
# Activate / deactivate
# ---------------------------------------------------------------------------

class TestActivation:
    def test_deactivate_then_activate_round_trips(self, client, collective):
        creator, space = collective
        as_user(creator)
        row = client.post(base(space.slug), json=HALF_OFF).json()

        off = client.post(f"{base(space.slug)}/{row['id']}/deactivate")
        assert off.json()["is_active"] is False

        on = client.post(f"{base(space.slug)}/{row['id']}/activate")
        assert on.json()["is_active"] is True

    def test_patch_and_the_dedicated_verbs_agree(self, client, collective):
        """Both routes exist deliberately — the creator APIs patch status
        fields (``PaymentOptionUpdateRequest.status``,
        ``EventUpdateRequest.is_published``), and a dedicated verb is the
        natural shape for the everyday action. Two paths to one field
        invite drift, so this pins that they do the same thing."""
        creator, space = collective
        as_user(creator)
        a = client.post(base(space.slug), json={**HALF_OFF, "code": "VIAPATCH"}).json()
        b = client.post(base(space.slug), json={**HALF_OFF, "code": "VIAVERB"}).json()

        patched = client.patch(f"{base(space.slug)}/{a['id']}",
                               json={"is_active": False}).json()
        verbed = client.post(f"{base(space.slug)}/{b['id']}/deactivate").json()

        assert patched["is_active"] is verbed["is_active"] is False
        assert patched["definition_editable"] == verbed["definition_editable"]
        assert patched["deletable"] == verbed["deletable"]

    def test_it_is_idempotent(self, client, collective):
        creator, space = collective
        as_user(creator)
        row = client.post(base(space.slug), json=HALF_OFF).json()

        client.post(f"{base(space.slug)}/{row['id']}/deactivate")
        again = client.post(f"{base(space.slug)}/{row['id']}/deactivate")
        assert again.status_code == 200
        assert again.json()["is_active"] is False


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDelete:
    def test_an_unredeemed_code_is_deleted(self, client, collective):
        creator, space = collective
        as_user(creator)
        row = client.post(base(space.slug), json=HALF_OFF).json()

        assert client.delete(f"{base(space.slug)}/{row['id']}").status_code == 204
        assert client.get(f"{base(space.slug)}/{row['id']}").status_code == 404

    def test_a_redeemed_code_is_refused_and_pointed_at_deactivation(
        self, client, db, collective,
    ):
        creator, space = collective
        as_user(creator)
        row = client.post(base(space.slug), json=HALF_OFF).json()
        redeem(db, row, space)

        res = client.delete(f"{base(space.slug)}/{row['id']}")

        assert res.status_code == 409
        assert "Deactivate it instead" in res.json()["detail"]
        assert client.get(f"{base(space.slug)}/{row['id']}").status_code == 200

    def test_deleting_something_that_is_not_there_is_not_found(self, client, collective):
        creator, space = collective
        as_user(creator)
        assert client.delete(f"{base(space.slug)}/dc_nope").status_code == 404


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestList:
    def test_it_returns_this_collectives_codes_newest_first(self, client, collective):
        creator, space = collective
        as_user(creator)
        client.post(base(space.slug), json={**HALF_OFF, "code": "FIRST"})
        client.post(base(space.slug), json={**HALF_OFF, "code": "SECOND"})

        codes = [c["code"] for c in client.get(base(space.slug)).json()]

        assert set(codes) == {"FIRST", "SECOND"}

    def test_an_empty_collective_lists_nothing(self, client, collective):
        creator, space = collective
        as_user(creator)
        assert client.get(base(space.slug)).json() == []

    def test_the_cached_column_is_not_what_the_api_reports(self, client, db, collective):
        """``DiscountCode.redemption_count`` is a denormalised cache that
        redemption fulfilment will maintain. The API reads the ledger, so
        a stale cache cannot make the API lie — and the two never come to
        mean different things."""
        creator, space = collective
        as_user(creator)
        row = client.post(base(space.slug), json=HALF_OFF).json()
        redeem(db, row, space, times=2)

        stored = db.query(DiscountCode).filter(DiscountCode.id == row["id"]).one()
        stored.redemption_count = 99          # deliberately wrong
        db.commit()

        assert client.get(f"{base(space.slug)}/{row['id']}").json()["redemption_count"] == 2
