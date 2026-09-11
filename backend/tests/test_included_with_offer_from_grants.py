"""Pathway ``access_type='included_with_offer'`` mirrors
``PaymentOptionGrant`` as the single source of truth.

Migration 125 backfilled every legacy
``PathwayUnlockRequirement (pathway_id, payment_option_id)`` pair into
the equivalent
``PaymentOptionGrant (payment_option_id, grant_kind='pathway',
pathway_id=X)`` row. From this release on, ``compute_pathway_access``
consults ``PaymentOptionGrant`` exclusively for the unlock set. The
old ``pathway_unlock_requirements`` table is left in place for
rollback safety but is never read.

Product rules pinned here:

  * Ordinary member: must be an active ``SpaceMembership`` on the
    Collective AND hold an active, not-yet-expired ``AccessPass``
    whose ``payment_option_id`` grants this Pathway via
    ``PaymentOptionGrant``.
  * Caretakers (platform admin / Space owner / active
    creator|moderator ``SpaceMembership``) bypass.
  * Draft Payment Options are never in the unlock set — they're not
    purchasable. Archived Options remain in the unlock set so
    historical buyers keep access. Published Options are the
    canonical case.
  * A naturally-expired pass (past ``valid_until`` with no admin
    revoke) no longer grants access — bringing this branch into line
    with the ``one_time``/``subscription`` branch and with the
    Series-channel + advance-booking predicates already in place.
  * Overlap: two active passes on the unlock set → revoking one
    leaves the other active and access preserved.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

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
    Pathway,
    PathwayStatus,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.pathway_access import compute_pathway_access


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_included_with_offer_pathway(db, space, *, title="EMBODY In-Person Sessions") -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        status=PathwayStatus.active,
        access_type="included_with_offer",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def _make_option(
    db, space, *, name="Awaken",
    status: PaymentOptionStatus = PaymentOptionStatus.published,
) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=None,
        attaches_to_kind="pathway",
        attaches_to_id=_uid("anchor"),  # not exercised for these tests
        name=name,
        payment_type=PaymentOptionType.one_time,
        status=status,
        calculated_total_cents=20000,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _grant_option_to_pathway(db, option, pathway) -> PaymentOptionGrant:
    g = PaymentOptionGrant(
        id=_uid("pog"),
        payment_option_id=option.id,
        grant_kind="pathway",
        pathway_id=pathway.id,
    )
    db.add(g)
    db.flush()
    return g


def _member(db, user, space, *, role: SpaceRole = SpaceRole.learner) -> SpaceMembership:
    m = SpaceMembership(
        id=_uid("sm"),
        user_id=user.id,
        space_id=space.id,
        role=role,
        status=SpaceMembershipStatus.active,
        joined_at=datetime.utcnow(),
    )
    db.add(m)
    db.flush()
    return m


def _issue_pass(
    db, *, user, space, payment_option,
    valid_until: datetime | None = None,
    status: AccessPassStatus = AccessPassStatus.active,
) -> AccessPass:
    ap = AccessPass(
        id=_uid("ap"),
        user_id=user.id,
        space_id=space.id,
        pass_type=AccessPassType.pathway_access,
        status=status,
        payment_option_id=payment_option.id,
        valid_from=datetime.utcnow() - timedelta(days=1),
        valid_until=valid_until,
        source=AccessPassSource.one_time_purchase,
    )
    db.add(ap)
    db.flush()
    return ap


# ---------------------------------------------------------------------------
# Positive cases
# ---------------------------------------------------------------------------


class TestActiveAccessGranted:
    def test_active_pass_from_published_option_grants_access(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_included_with_offer_pathway(db, space)
        awaken = _make_option(db, space, name="Awaken")
        _grant_option_to_pathway(db, awaken, pathway)
        _issue_pass(db, user=payer, space=space, payment_option=awaken)
        db.commit()

        assert compute_pathway_access(payer, pathway, space, db) is True

    def test_archived_option_preserves_historical_access(
        self, db, make_space, make_user,
    ):
        """When a Payment Option is archived (no longer sold), the
        AccessPasses issued while it was published continue to grant
        access — critical for legitimate historical buyers."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_included_with_offer_pathway(db, space)
        # The Option is now archived — but the buyer's pass still
        # references it, and the grant relationship is intact.
        old_option = _make_option(
            db, space, name="Awaken (archived)",
            status=PaymentOptionStatus.archived,
        )
        _grant_option_to_pathway(db, old_option, pathway)
        _issue_pass(db, user=payer, space=space, payment_option=old_option)
        db.commit()

        assert compute_pathway_access(payer, pathway, space, db) is True

    def test_two_overlapping_passes_one_revoked_still_grants(
        self, db, make_space, make_user,
    ):
        """Overlapping-purchase independence: revoking one pass leaves
        access via the other."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_included_with_offer_pathway(db, space)
        awaken = _make_option(db, space, name="Awaken")
        empower = _make_option(db, space, name="Empower")
        _grant_option_to_pathway(db, awaken, pathway)
        _grant_option_to_pathway(db, empower, pathway)
        ap_awaken = _issue_pass(db, user=payer, space=space, payment_option=awaken)
        _issue_pass(db, user=payer, space=space, payment_option=empower)
        db.commit()

        # Revoke Awaken's pass.
        ap_awaken.status = AccessPassStatus.cancelled
        ap_awaken.revoked_at = datetime.utcnow()
        ap_awaken.revoked_by_user_id = make_user(role="admin").id
        db.commit()

        assert compute_pathway_access(payer, pathway, space, db) is True

    @pytest.mark.parametrize("role", [SpaceRole.creator, SpaceRole.moderator])
    def test_caretaker_bypass_regression_pin(
        self, db, make_space, make_user, role,
    ):
        """Caretakers see the Pathway without holding any Pass."""
        space = make_space()
        caretaker = make_user()
        _member(db, caretaker, space, role=role)
        pathway = _make_included_with_offer_pathway(db, space)
        db.commit()

        assert compute_pathway_access(caretaker, pathway, space, db) is True


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


class TestAccessDenied:
    def test_active_member_with_no_pass_is_denied(
        self, db, make_space, make_user,
    ):
        """The pinned rule: Collective membership alone is not enough
        under ``included_with_offer``."""
        space = make_space()
        member_only = make_user()
        _member(db, member_only, space)
        pathway = _make_included_with_offer_pathway(db, space)
        awaken = _make_option(db, space, name="Awaken")
        _grant_option_to_pathway(db, awaken, pathway)
        db.commit()

        assert compute_pathway_access(member_only, pathway, space, db) is False

    def test_revoked_pass_removes_access(self, db, make_space, make_user):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_included_with_offer_pathway(db, space)
        awaken = _make_option(db, space, name="Awaken")
        _grant_option_to_pathway(db, awaken, pathway)
        ap = _issue_pass(db, user=payer, space=space, payment_option=awaken)
        db.commit()
        assert compute_pathway_access(payer, pathway, space, db) is True

        ap.status = AccessPassStatus.cancelled
        db.commit()

        assert compute_pathway_access(payer, pathway, space, db) is False

    def test_naturally_expired_pass_removes_access(
        self, db, make_space, make_user,
    ):
        """The new ``valid_until`` check. A pass whose ``valid_until``
        is in the past — even if ``status`` still says active — must
        not grant access. Fixes the pre-existing latent bug in the
        included_with_offer branch."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_included_with_offer_pathway(db, space)
        awaken = _make_option(db, space, name="Awaken")
        _grant_option_to_pathway(db, awaken, pathway)
        _issue_pass(
            db, user=payer, space=space, payment_option=awaken,
            valid_until=datetime.utcnow() - timedelta(days=1),
        )
        db.commit()

        assert compute_pathway_access(payer, pathway, space, db) is False

    def test_non_member_with_active_pass_is_denied(
        self, db, make_space, make_user,
    ):
        """Explicit SpaceMembership requirement. A stray active pass
        held by someone who is no longer an active member of the
        Collective must not unlock access."""
        space = make_space()
        stray = make_user()
        # No SpaceMembership row (or set status=removed).
        pathway = _make_included_with_offer_pathway(db, space)
        awaken = _make_option(db, space, name="Awaken")
        _grant_option_to_pathway(db, awaken, pathway)
        _issue_pass(db, user=stray, space=space, payment_option=awaken)
        db.commit()

        assert compute_pathway_access(stray, pathway, space, db) is False

    def test_draft_option_does_not_unlock_access(
        self, db, make_space, make_user,
    ):
        """Draft Options are not purchasable; even if a pass somehow
        references one (edge case / manual DB), it must not unlock.
        Only published + archived Options count."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_included_with_offer_pathway(db, space)
        draft_option = _make_option(
            db, space, name="Draft Preview",
            status=PaymentOptionStatus.draft,
        )
        _grant_option_to_pathway(db, draft_option, pathway)
        _issue_pass(db, user=payer, space=space, payment_option=draft_option)
        db.commit()

        assert compute_pathway_access(payer, pathway, space, db) is False

    def test_empty_grant_set_denies_all_members(
        self, db, make_space, make_user,
    ):
        """When no Payment Option grants this Pathway, ``included_with_offer``
        rejects everyone (except caretakers). The frontend surface warns the
        creator so this state is visible and correctable."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_included_with_offer_pathway(db, space)
        db.commit()

        assert compute_pathway_access(payer, pathway, space, db) is False


# ---------------------------------------------------------------------------
# Regression pins: other branches unchanged.
# ---------------------------------------------------------------------------


class TestOtherAccessTypesUnchanged:
    def test_free_branch_still_grants_active_member(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = Pathway(
            id=_uid("pw"),
            space_id=space.id,
            slug=f"pw-{uuid.uuid4().hex[:8]}",
            title="Free path",
            status=PathwayStatus.active,
            access_type="free",
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pathway)
        db.commit()

        assert compute_pathway_access(payer, pathway, space, db) is True

    def test_included_branch_still_grants_active_member(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = Pathway(
            id=_uid("pw"),
            space_id=space.id,
            slug=f"pw-{uuid.uuid4().hex[:8]}",
            title="Included path",
            status=PathwayStatus.active,
            access_type="included",
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pathway)
        db.commit()

        assert compute_pathway_access(payer, pathway, space, db) is True
