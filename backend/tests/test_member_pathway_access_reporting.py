"""Creator Studio's People panel must not report access the member
doesn't have.

``creator.routes.get_member_pathway_access`` powers the "Pathway
access" list on a member's card. It reads ``pathway_entitlements`` and
labels an entitlement by its ``source`` — ``one_time_purchase`` renders
as **Purchased**.

The production defect it half-concealed
---------------------------------------
The endpoint treated ``status == 'active'`` as "has access" and never
looked at ``ends_at``. The member-facing predicate honours ``ends_at``.
So a lapsed entitlement read "Purchased" to the Creator while the
member was locked out — and when a *separate* bug locked out a member
whose entitlement was perfectly valid, this panel's confident
"Purchased" is what made the failure look like a payment mystery
rather than a permission one.

Pinned here: "currently valid" means the same thing on both surfaces —
active status, unexpired window, right member, right Pathway — and a
lapsed purchase is still visible as history rather than vanishing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.creator.routes import get_member_pathway_access
from app.models.access_pass import (
    AccessPass,
    AccessPassSource,
    AccessPassStatus,
    AccessPassType,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.platform import (
    EntitlementSource,
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
    PathwayStatus,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.pathway_access import compute_pathway_access


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _pathway(db, space, *, access_type="included_with_offer",
             title="Test Pathway") -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        status=PathwayStatus.active,
        access_type=access_type,
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def _member(db, user, space, *, role: SpaceRole = SpaceRole.learner):
    m = SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id, role=role,
        status=SpaceMembershipStatus.active, joined_at=datetime.utcnow(),
    )
    db.add(m)
    db.flush()
    return m


def _entitlement(db, *, user, space, pathway,
                 source: EntitlementSource = EntitlementSource.one_time_purchase,
                 status: EntitlementStatus = EntitlementStatus.active,
                 ends_at=None) -> PathwayEntitlement:
    e = PathwayEntitlement(
        id=_uid("ent"), user_id=user.id, space_id=space.id,
        pathway_id=pathway.id, source=source, status=status,
        starts_at=datetime.utcnow() - timedelta(minutes=5), ends_at=ends_at,
    )
    db.add(e)
    db.flush()
    return e


def _option_granting(db, space, pathway) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, pathway_id=None,
        attaches_to_kind="pathway", attaches_to_id=_uid("anchor"),
        name="Live payment test", payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=1000, currency="AUD",
    )
    db.add(opt)
    db.flush()
    db.add(PaymentOptionGrant(
        id=_uid("pog"), payment_option_id=opt.id,
        grant_kind="pathway", pathway_id=pathway.id,
    ))
    db.flush()
    return opt


def _report(db, space, owner, member) -> dict[str, object]:
    """The panel's rows for one member, keyed by pathway id."""
    items = get_member_pathway_access(
        slug=space.slug, user_id=member.id, db=db, current_user=owner,
    )
    return {i.id: i for i in items}


# ---------------------------------------------------------------------------
# 1 · A currently-valid purchase reads as Purchased
# ---------------------------------------------------------------------------


class TestValidPurchaseReporting:
    def test_active_perpetual_entitlement_reads_purchased(
        self, db, make_space, make_user,
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        tom = make_user()
        _member(db, tom, space)
        pathway = _pathway(db, space)
        _option_granting(db, space, pathway)
        _entitlement(db, user=tom, space=space, pathway=pathway)
        db.commit()

        row = _report(db, space, owner, tom)[pathway.id]
        assert row.access_state == "accessible"
        assert row.access_label == "Purchased"
        assert row.access_source == "one_time_purchase"

    def test_future_ends_at_reads_purchased(self, db, make_space, make_user):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        tom = make_user()
        _member(db, tom, space)
        pathway = _pathway(db, space)
        _entitlement(
            db, user=tom, space=space, pathway=pathway,
            ends_at=datetime.utcnow() + timedelta(days=30),
        )
        db.commit()

        row = _report(db, space, owner, tom)[pathway.id]
        assert row.access_state == "accessible"
        assert row.access_label == "Purchased"

    def test_manual_grant_label_unchanged(self, db, make_space, make_user):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        tom = make_user()
        _member(db, tom, space)
        pathway = _pathway(db, space)
        _entitlement(
            db, user=tom, space=space, pathway=pathway,
            source=EntitlementSource.manual_grant,
        )
        db.commit()

        row = _report(db, space, owner, tom)[pathway.id]
        assert row.access_state == "accessible"
        assert row.access_label == "Manual grant"


# ---------------------------------------------------------------------------
# 2 · A lapsed purchase must not read as current access
# ---------------------------------------------------------------------------


class TestLapsedPurchaseReporting:
    def test_expired_window_does_not_read_purchased(
        self, db, make_space, make_user,
    ):
        """``status='active'`` with ``ends_at`` in the past. The member
        is locked out, so the panel must not claim otherwise."""
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        tom = make_user()
        _member(db, tom, space)
        pathway = _pathway(db, space)
        _entitlement(
            db, user=tom, space=space, pathway=pathway,
            ends_at=datetime.utcnow() - timedelta(days=1),
        )
        db.commit()

        row = _report(db, space, owner, tom)[pathway.id]
        assert row.access_label != "Purchased"
        assert row.access_state != "accessible"
        assert row.access_state == "expired"
        assert row.access_label == "Expired"

    def test_lapsed_purchase_history_is_preserved(
        self, db, make_space, make_user,
    ):
        """Expiring access must not erase the fact of the purchase —
        the row stays listed and keeps its source."""
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        tom = make_user()
        _member(db, tom, space)
        pathway = _pathway(db, space)
        _entitlement(
            db, user=tom, space=space, pathway=pathway,
            ends_at=datetime.utcnow() - timedelta(days=400),
        )
        db.commit()

        rows = _report(db, space, owner, tom)
        assert pathway.id in rows, "a lapsed purchase must stay visible"
        assert rows[pathway.id].access_source == "one_time_purchase"

    def test_revoked_entitlement_reads_revoked(self, db, make_space, make_user):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        tom = make_user()
        _member(db, tom, space)
        pathway = _pathway(db, space)
        _entitlement(
            db, user=tom, space=space, pathway=pathway,
            status=EntitlementStatus.revoked,
        )
        db.commit()

        row = _report(db, space, owner, tom)[pathway.id]
        assert row.access_state == "revoked"
        assert row.access_label == "Revoked"


# ---------------------------------------------------------------------------
# 3 · Right member, right Pathway
# ---------------------------------------------------------------------------


class TestOwnershipScoping:
    def test_another_members_purchase_is_not_reported(
        self, db, make_space, make_user,
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        buyer = make_user()
        bystander = make_user()
        _member(db, buyer, space)
        _member(db, bystander, space)
        pathway = _pathway(db, space)
        _entitlement(db, user=buyer, space=space, pathway=pathway)
        db.commit()

        assert _report(db, space, owner, buyer)[pathway.id].access_label \
            == "Purchased"
        # The bystander's own card must not borrow the buyer's purchase.
        bystander_rows = _report(db, space, owner, bystander)
        if pathway.id in bystander_rows:
            assert bystander_rows[pathway.id].access_label != "Purchased"
            assert bystander_rows[pathway.id].access_state != "accessible"

    def test_purchase_of_one_pathway_is_not_reported_on_another(
        self, db, make_space, make_user,
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        tom = make_user()
        _member(db, tom, space)
        bought = _pathway(db, space, title="Bought Pathway")
        other = _pathway(db, space, title="Other Pathway")
        _entitlement(db, user=tom, space=space, pathway=bought)
        db.commit()

        rows = _report(db, space, owner, tom)
        assert rows[bought.id].access_label == "Purchased"
        if other.id in rows:
            assert rows[other.id].access_label != "Purchased"
            assert rows[other.id].access_state != "accessible"


# ---------------------------------------------------------------------------
# 4 · The two surfaces must agree
# ---------------------------------------------------------------------------


class TestSurfaceAgreement:
    @pytest.mark.parametrize("access_type", ["included_with_offer", "one_time"])
    @pytest.mark.parametrize(
        "ends_at_delta,status,expect_access",
        [
            (None, EntitlementStatus.active, True),
            (timedelta(days=30), EntitlementStatus.active, True),
            (timedelta(days=-1), EntitlementStatus.active, False),
            (None, EntitlementStatus.revoked, False),
            (None, EntitlementStatus.expired, False),
        ],
    )
    def test_reported_accessible_matches_member_predicate(
        self, db, make_space, make_user,
        access_type, ends_at_delta, status, expect_access,
    ):
        """Whatever the entitlement's shape, "accessible" in Creator
        Studio and ``compute_pathway_access`` must come out the same.
        This is the invariant whose absence produced the original
        "Purchased but locked" report."""
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        tom = make_user()
        _member(db, tom, space)
        pathway = _pathway(db, space, access_type=access_type)
        _option_granting(db, space, pathway)
        _entitlement(
            db, user=tom, space=space, pathway=pathway, status=status,
            ends_at=(datetime.utcnow() + ends_at_delta)
            if ends_at_delta is not None else None,
        )
        db.commit()

        member_sees = compute_pathway_access(tom, pathway, space, db)
        row = _report(db, space, owner, tom)[pathway.id]
        reported = row.access_state == "accessible"

        assert member_sees is expect_access
        assert reported is expect_access, (
            f"Creator Studio reported accessible={reported} while the member "
            f"predicate says {member_sees} (access_type={access_type}, "
            f"status={status}, ends_at_delta={ends_at_delta})"
        )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Known reporting gap, deliberately not fixed in this change: a "
            "member whose access comes from an AccessPass alone (no "
            "entitlement) genuinely HAS access, but the People panel reads "
            "only pathway_entitlements and shows 'Locked'. This is the "
            "mirror image of the bug just fixed, in the opposite direction "
            "— it under-reports rather than over-reports, so it cannot "
            "cause a false promise of access. Fixing it means teaching the "
            "panel about AccessPasses, which is a display change beyond "
            "this permission correction. When that lands, delete this "
            "xfail; strict=True makes it fail loudly once it passes."
        ),
    )
    def test_access_pass_only_member_is_reported_as_accessible(
        self, db, make_space, make_user,
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        tom = make_user()
        _member(db, tom, space)
        pathway = _pathway(db, space)
        option = _option_granting(db, space, pathway)
        db.add(AccessPass(
            id=_uid("ap"), user_id=tom.id, space_id=space.id,
            pass_type=AccessPassType.pathway_access,
            status=AccessPassStatus.active, payment_option_id=option.id,
            valid_from=datetime.utcnow() - timedelta(days=1),
            valid_until=None, source=AccessPassSource.one_time_purchase,
        ))
        db.commit()

        assert compute_pathway_access(tom, pathway, space, db) is True
        row = _report(db, space, owner, tom)[pathway.id]
        assert row.access_state == "accessible"
