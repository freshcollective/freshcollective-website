"""Creator removal: a recorded reason, and a separate decision to ban.

Creator removal did not always mean somebody had done something wrong.
Sometimes a creator is helping a person leave; sometimes they are acting
on behaviour. One ``removal_kind='creator'`` could not tell those apart,
so every creator removal had to be treated as irreversible — which made
ordinary tidying-up permanent.

Four fields now answer four questions (migration 166): ``removal_kind``
who, ``removal_reason`` why, ``removal_note`` in their words, and
``rejoin_blocked`` what follows. The last is independent of the third
**in both directions**, and most of this file exists to pin that:
"Inappropriate behaviour" does not bar anybody, and "Member requested
removal" does not stop a creator barring them.

Two guards follow from the distinction. Rule E refuses a purchase whose
delivery needs membership; Rule F refuses *any* purchase from a
Collective somebody is banned from, free Offerings included.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.creator.routes import (
    add_or_invite_member,
    list_removed_members,
    remove_member,
    remove_member_with_reason,
    set_rejoin_policy,
)
from app.creator.schemas import (
    AddMemberRequest,
    RejoinPolicyRequest,
    RemoveMemberRequest,
)
from app.models.platform import (
    MembershipRestrictionEvent,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services import membership_grant, membership_removal


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def space(make_space):
    return make_space(status="active", is_public=True)


@pytest.fixture
def owner(db, space):
    return db.query(User).filter(User.id == space.creator_id).first()


@pytest.fixture
def member(db, space, make_user):
    user = make_user()
    db.add(SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        source="joined",
    ))
    db.flush()
    return user


@pytest.fixture
def moderator(db, space, make_user):
    user = make_user()
    db.add(SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        role=SpaceRole.moderator, status=SpaceMembershipStatus.active,
        source="invited",
    ))
    db.flush()
    return user


def _row(db, space, user) -> SpaceMembership | None:
    return (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == user.id,
        )
        .first()
    )


def _remove(db, space, member, actor, **kw):
    body = RemoveMemberRequest(
        reason=kw.pop("reason", membership_removal.REASON_NO_LONGER_REQUIRED),
        **kw,
    )
    return remove_member_with_reason(
        space.slug, member.id, body, db=db, current_user=actor,
    )


def _events(db, space, user):
    return (
        db.query(MembershipRestrictionEvent)
        .filter(
            MembershipRestrictionEvent.space_id == space.id,
            MembershipRestrictionEvent.user_id == user.id,
        )
        .order_by(MembershipRestrictionEvent.created_at)
        .all()
    )


# ---------------------------------------------------------------------------
# 1. The reason is recorded, and never implies a ban
# ---------------------------------------------------------------------------


class TestTheReasonIsRecorded:

    @pytest.mark.parametrize("reason", membership_removal.REMOVAL_REASONS)
    def test_every_reason_is_accepted_and_stored(
        self, db, space, member, owner, reason,
    ):
        _remove(db, space, member, owner, reason=reason)
        assert _row(db, space, member).removal_reason == reason

    @pytest.mark.parametrize("reason", membership_removal.REMOVAL_REASONS)
    def test_no_reason_implies_a_ban(
        self, db, space, member, owner, reason,
    ):
        """The requirement, as a parametrised test over the whole
        vocabulary: a ban is never a consequence of the reason."""
        _remove(db, space, member, owner, reason=reason)
        row = _row(db, space, member)
        assert row.rejoin_blocked is False
        assert membership_grant.may_rejoin(row) is True

    def test_a_reason_is_required(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            RemoveMemberRequest()

    def test_an_unknown_reason_is_refused(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            RemoveMemberRequest(reason="he_was_annoying")

    def test_the_note_is_optional_for_an_ordinary_removal(
        self, db, space, member, owner,
    ):
        _remove(db, space, member, owner, reason="other")
        assert _row(db, space, member).removal_note is None

    def test_a_note_is_stored_when_given(self, db, space, member, owner):
        _remove(
            db, space, member, owner, reason="other",
            note="Moved overseas, asked to be taken off the list.",
        )
        assert "Moved overseas" in _row(db, space, member).removal_note

    def test_a_whitespace_note_is_not_stored_as_one(
        self, db, space, member, owner,
    ):
        _remove(db, space, member, owner, reason="other", note="   ")
        assert _row(db, space, member).removal_note is None

    def test_the_actor_and_time_are_recorded(
        self, db, space, member, owner,
    ):
        _remove(db, space, member, owner)
        row = _row(db, space, member)
        assert row.removed_by_user_id == owner.id
        assert row.removed_at is not None
        assert row.removal_kind == membership_removal.REMOVAL_BY_CREATOR


# ---------------------------------------------------------------------------
# 2. A ban is explicit, requires an explanation, and is owner-only
# ---------------------------------------------------------------------------


class TestABanIsAnExplicitDecision:

    def test_blocking_requires_a_written_explanation(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            RemoveMemberRequest(
                reason="inappropriate_behaviour", rejoin_blocked=True,
            )

    def test_a_whitespace_explanation_does_not_count(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            RemoveMemberRequest(
                reason="inappropriate_behaviour", rejoin_blocked=True,
                note="      ",
            )

    def test_the_service_refuses_one_too(self):
        """Belt to the braces — the schema is the creator-facing error,
        this is the one a programmatic caller hits."""
        with pytest.raises(membership_removal.RemovalDecisionError):
            membership_removal.RemovalDecision(
                kind=membership_removal.REMOVAL_BY_CREATOR,
                reason="payment_issues",
                rejoin_blocked=True,
            )

    def test_only_a_creator_removal_may_block(self):
        with pytest.raises(membership_removal.RemovalDecisionError):
            membership_removal.RemovalDecision(
                kind=membership_removal.REMOVAL_VOLUNTARY,
                note="x", rejoin_blocked=True,
            )

    def test_a_ban_with_an_explanation_succeeds(
        self, db, space, member, owner,
    ):
        result = _remove(
            db, space, member, owner,
            reason="inappropriate_behaviour",
            note="Repeated abuse in the Common Room.",
            rejoin_blocked=True,
        )
        assert result.rejoin_blocked is True
        row = _row(db, space, member)
        assert row.rejoin_blocked is True
        assert membership_grant.may_rejoin(row) is False

    def test_any_reason_may_carry_a_ban(self, db, space, member, owner):
        """Independence in the other direction: a creator may bar
        somebody while recording that they asked to leave."""
        _remove(
            db, space, member, owner,
            reason="member_requested",
            note="Asked to leave and asked not to be re-added.",
            rejoin_blocked=True,
        )
        row = _row(db, space, member)
        assert row.removal_reason == "member_requested"
        assert row.rejoin_blocked is True

    # -- who may impose one ---------------------------------------------

    def test_a_moderator_may_remove_ordinarily(
        self, db, space, member, moderator,
    ):
        _remove(db, space, member, moderator)
        assert _row(db, space, member).status == (
            SpaceMembershipStatus.removed
        )

    def test_a_moderator_may_not_ban(self, db, space, member, moderator):
        with pytest.raises(HTTPException) as exc:
            _remove(
                db, space, member, moderator,
                reason="inappropriate_behaviour",
                note="I think they were rude.",
                rejoin_blocked=True,
            )
        assert exc.value.status_code == 403

    def test_the_member_survives_a_refused_ban(
        self, db, space, member, moderator,
    ):
        with pytest.raises(HTTPException):
            _remove(
                db, space, member, moderator,
                reason="inappropriate_behaviour",
                note="I think they were rude.",
                rejoin_blocked=True,
            )
        assert _row(db, space, member).status == (
            SpaceMembershipStatus.active
        )

    def test_a_moderator_may_not_change_the_rejoin_policy(
        self, db, space, member, owner, moderator,
    ):
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", rejoin_blocked=True,
        )
        with pytest.raises(HTTPException) as exc:
            set_rejoin_policy(
                space.slug, member.id,
                RejoinPolicyRequest(rejoin_blocked=False),
                db=db, current_user=moderator,
            )
        assert exc.value.status_code == 403

    def test_nobody_can_remove_themselves_here(
        self, db, space, owner,
    ):
        with pytest.raises(HTTPException) as exc:
            _remove(db, space, owner, owner)
        assert exc.value.status_code == 400

    def test_the_owner_cannot_be_removed(
        self, db, space, owner, moderator,
    ):
        with pytest.raises(HTTPException) as exc:
            _remove(db, space, owner, moderator)
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 3. The database refuses an incoherent block
# ---------------------------------------------------------------------------


class TestTheDatabaseGuardsTheInvariant:

    def test_an_active_membership_cannot_be_blocked(
        self, db, space, member,
    ):
        """``rejoin_blocked`` on an active row would read as a ban to
        the purchase guards while the person was still inside the
        Collective."""
        from sqlalchemy.exc import IntegrityError

        row = _row(db, space, member)
        row.rejoin_blocked = True
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_an_unknown_reason_is_refused_at_the_column(
        self, db, space, member,
    ):
        from sqlalchemy.exc import IntegrityError

        row = _row(db, space, member)
        row.status = SpaceMembershipStatus.removed
        row.removal_reason = "made_up"
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


# ---------------------------------------------------------------------------
# 4. Rule F — a banned person transacts with nothing here
# ---------------------------------------------------------------------------


class TestRuleFBlocksEveryAcquisition:

    @pytest.fixture
    def banned(self, db, space, member, owner):
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", rejoin_blocked=True,
        )
        return member

    def test_the_predicate_says_so(self, db, space, banned):
        assert membership_removal.is_banned(
            db, user_id=banned.id, space_id=space.id,
        ) is True

    def test_an_ordinary_removal_is_not_banned(
        self, db, space, member, owner,
    ):
        _remove(db, space, member, owner)
        assert membership_removal.is_banned(
            db, user_id=member.id, space_id=space.id,
        ) is False

    def test_the_guard_refuses(self, db, space, banned):
        from app.services.checkout_orchestration import (
            check_not_banned_or_raise,
        )

        with pytest.raises(HTTPException) as exc:
            check_not_banned_or_raise(db, user=banned, space=space)
        assert exc.value.status_code == 402

    def test_the_refusal_does_not_disclose_the_moderation(
        self, db, space, banned,
    ):
        from app.services.checkout_orchestration import (
            check_not_banned_or_raise,
        )

        with pytest.raises(HTTPException) as exc:
            check_not_banned_or_raise(db, user=banned, space=space)
        detail = str(exc.value.detail).lower()
        assert "blocked" not in detail
        assert "removed" not in detail
        assert "creator" in detail

    def test_a_ban_in_another_collective_does_not_block_here(
        self, db, space, member, owner, make_space,
    ):
        from app.services.checkout_orchestration import (
            check_not_banned_or_raise,
        )

        other = make_space(status="active")
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", rejoin_blocked=True,
        )
        assert check_not_banned_or_raise(
            db, user=member, space=other,
        ) is None

    # -- free Offerings, which a payment-only ban would have missed -----

    def test_a_free_offering_is_refused(self, db, space, banned):
        """"Block new purchases" has to include free acquisition, or a
        ban is only a ban on paying."""
        from app.services import offering_acquisition as acq

        offering = self._offering(db, space)
        result = acq.check_acquirable(
            db, offering=offering, space=space, user=banned,
        )
        assert result.refusal == acq.REASON_BLOCKED_FROM_COLLECTIVE

    def test_the_raising_wrapper_refuses_too(self, db, space, banned):
        from app.services import offering_acquisition as acq

        offering = self._offering(db, space)
        with pytest.raises(acq.AcquisitionRefused):
            acq.guard_acquirable(
                db, offering=offering, space=space, user=banned,
                for_pricing="free",
            )

    def test_an_offering_already_owned_is_not_taken_away(
        self, db, space, member, owner,
    ):
        """A ban stops new acquisitions. It does not reach back and
        confiscate a file somebody already owns — the same principle
        the download route applies to the pilot flag."""
        from app.models.offering import (
            OfferingEntitlement,
            OfferingEntitlementSource,
            OfferingEntitlementStatus,
        )
        from app.services import offering_acquisition as acq

        offering = self._offering(db, space)
        ent = OfferingEntitlement(
            id=_uid("oen"), user_id=member.id, offering_id=offering.id,
            space_id=space.id,
            source=OfferingEntitlementSource.one_time_purchase.value,
            status=OfferingEntitlementStatus.active.value,
        )
        db.add(ent)
        db.flush()
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", rejoin_blocked=True,
        )
        result = acq.check_acquirable(
            db, offering=offering, space=space, user=member,
        )
        assert result.already_owned is True
        assert result.refusal is None
        assert ent.status == OfferingEntitlementStatus.active.value

    def _offering(self, db, space):
        from app.models.offering import (
            Offering,
            OfferingFulfilmentKind,
            OfferingStatus,
        )

        row = Offering(
            id=_uid("off"), space_id=space.id,
            created_by_user_id=space.creator_id,
            slug=f"g-{uuid.uuid4().hex[:8]}", title="A Guide",
            summary="Lines.",
            status=OfferingStatus.published.value,
            fulfilment_kind=OfferingFulfilmentKind.digital_download.value,
        )
        db.add(row)
        db.flush()
        return row

    # -- every entrance consults it -------------------------------------

    @pytest.mark.parametrize("module_name,func_name", [
        ("app.services.checkout_orchestration", "orchestrate_paid_checkout"),
        ("app.services.checkout_orchestration", "orchestrate_free_checkout"),
        ("app.services.finite_plan_orchestration", "start_finite_plan_setup"),
        ("app.services.gathering_tickets", "create_or_reuse_hold"),
    ])
    def test_the_entrance_runs_rule_f(self, module_name, func_name):
        import importlib
        import inspect

        mod = importlib.import_module(module_name)
        src = inspect.getsource(getattr(mod, func_name))
        assert "check_not_banned_or_raise" in src

    def test_the_legacy_pathway_checkout_runs_it(self):
        import inspect

        from app.checkout import routes

        src = inspect.getsource(routes)
        assert "check_not_banned_or_raise" in src

    def test_offerings_run_it_through_the_shared_predicate(self):
        import inspect

        from app.services import offering_acquisition

        src = inspect.getsource(offering_acquisition.check_acquirable)
        assert "is_banned" in src


# ---------------------------------------------------------------------------
# 5. A ban closes every way back in
# ---------------------------------------------------------------------------


class TestABanClosesEveryDoor:

    @pytest.fixture
    def banned(self, db, space, member, owner):
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", rejoin_blocked=True,
        )
        return member

    def test_pressing_join_is_refused(self, db, space, banned):
        from app.spaces.routes import join_space

        with pytest.raises(HTTPException) as exc:
            join_space(
                space.slug, db=db, current_user=banned,
                background_tasks=None,
            )
        assert exc.value.status_code == 409

    def test_a_purchase_cannot_readmit_them(self, db, space, banned):
        outcome = membership_grant.ensure_membership_for_purchase(
            db, user_id=banned.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.reactivated is False
        assert outcome.skipped_reason == "rejoin_blocked"

    def test_an_invitation_cannot_readmit_them(self, db, space, banned):
        """An invitation is not authority to overturn a block."""
        from app.models.platform import SpaceInvitation
        from app.spaces.routes import accept_invite

        token = str(uuid.uuid4())
        db.add(SpaceInvitation(
            id=_uid("inv"), space_id=space.id, email=banned.email.lower(),
            name=banned.email, role=SpaceRole.learner,
            invited_by_id=space.creator_id, token=token,
            sent_at=datetime.utcnow(),
        ))
        db.flush()
        with pytest.raises(HTTPException) as exc:
            accept_invite(
                token, db=db, current_user=banned, background_tasks=None,
            )
        assert exc.value.status_code == 409
        assert _row(db, space, banned).status == (
            SpaceMembershipStatus.removed
        )

    def test_the_creator_cannot_re_add_them_by_email(
        self, db, space, banned, owner,
    ):
        with pytest.raises(HTTPException) as exc:
            add_or_invite_member(
                space.slug,
                AddMemberRequest(email=banned.email, role="learner"),
                db=db, current_user=owner, background_tasks=None,
            )
        assert exc.value.status_code == 409
        assert "removed people" in str(exc.value.detail).lower()

    def test_reactivate_refuses_outright(self, db, space, banned):
        """Defence in depth: even a caller that skipped its check
        cannot lift a ban by accident."""
        with pytest.raises(ValueError):
            membership_grant.reactivate(
                db, _row(db, space, banned), now=datetime.utcnow(),
            )


# ---------------------------------------------------------------------------
# 6. Lifting a ban
# ---------------------------------------------------------------------------


class TestLiftingABan:

    @pytest.fixture
    def banned(self, db, space, member, owner):
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", rejoin_blocked=True,
        )
        return member

    def _lift(self, db, space, user, actor, note="Lifted on appeal."):
        return set_rejoin_policy(
            space.slug, user.id,
            RejoinPolicyRequest(rejoin_blocked=False, note=note),
            db=db, current_user=actor,
        )

    def test_the_owner_can_lift_it(self, db, space, banned, owner):
        assert self._lift(db, space, banned, owner).rejoin_blocked is False
        assert _row(db, space, banned).rejoin_blocked is False

    def test_lifting_does_not_restore_membership(
        self, db, space, banned, owner,
    ):
        """They become free to return; whether they do is theirs."""
        self._lift(db, space, banned, owner)
        assert _row(db, space, banned).status == (
            SpaceMembershipStatus.removed
        )

    def test_they_may_then_rejoin(self, db, space, banned, owner):
        from app.spaces.routes import join_space

        self._lift(db, space, banned, owner)
        result = join_space(
            space.slug, db=db, current_user=banned, background_tasks=None,
        )
        assert result.get("rejoined") is True

    def test_they_may_then_purchase(self, db, space, banned, owner):
        from app.services.checkout_orchestration import (
            check_not_banned_or_raise,
        )

        self._lift(db, space, banned, owner)
        assert check_not_banned_or_raise(
            db, user=banned, space=space,
        ) is None

    def test_lifting_restores_no_cancelled_pass(
        self, db, space, member, owner,
    ):
        from app.models.access_pass import (
            AccessPass, AccessPassStatus, AccessPassType,
        )

        ap = AccessPass(
            id=_uid("ap"), user_id=member.id, space_id=space.id,
            pass_type=AccessPassType.class_pass,
            status=AccessPassStatus.active,
        )
        db.add(ap)
        db.flush()
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", rejoin_blocked=True,
        )
        assert ap.status == AccessPassStatus.cancelled
        self._lift(db, space, member, owner)
        assert ap.status == AccessPassStatus.cancelled

    def test_the_removal_history_is_not_rewritten(
        self, db, space, banned, owner,
    ):
        """The removal still happened, for the reason recorded."""
        self._lift(db, space, banned, owner)
        row = _row(db, space, banned)
        assert row.removal_kind == membership_removal.REMOVAL_BY_CREATOR
        assert row.removal_reason == "inappropriate_behaviour"
        assert row.removal_note == "Abuse."

    # -- the ledger ------------------------------------------------------

    def test_imposing_a_ban_is_recorded(self, db, space, banned, owner):
        [event] = _events(db, space, banned)
        assert event.action == membership_removal.RESTRICTION_BLOCKED
        assert event.actor_user_id == owner.id
        assert event.note == "Abuse."

    def test_lifting_a_ban_is_recorded(self, db, space, banned, owner):
        self._lift(db, space, banned, owner, note="Apologised.")
        actions = [e.action for e in _events(db, space, banned)]
        assert actions == ["blocked", "unblocked"]
        assert _events(db, space, banned)[-1].note == "Apologised."

    def test_the_ledger_is_append_only_across_a_cycle(
        self, db, space, banned, owner,
    ):
        """Ban, lift, ban again — three entries, not an overwritten
        boolean."""
        self._lift(db, space, banned, owner)
        set_rejoin_policy(
            space.slug, banned.id,
            RejoinPolicyRequest(
                rejoin_blocked=True, note="Same behaviour again.",
            ),
            db=db, current_user=owner,
        )
        actions = [e.action for e in _events(db, space, banned)]
        assert actions == ["blocked", "unblocked", "blocked"]

    def test_lifting_twice_records_once(self, db, space, banned, owner):
        self._lift(db, space, banned, owner)
        self._lift(db, space, banned, owner)
        actions = [e.action for e in _events(db, space, banned)]
        assert actions == ["blocked", "unblocked"]

    def test_imposing_a_ban_after_the_fact_requires_an_explanation(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            RejoinPolicyRequest(rejoin_blocked=True)

    def test_a_ban_cannot_be_imposed_on_an_active_member(
        self, db, space, member, owner,
    ):
        with pytest.raises(HTTPException) as exc:
            set_rejoin_policy(
                space.slug, member.id,
                RejoinPolicyRequest(rejoin_blocked=True, note="x"),
                db=db, current_user=owner,
            )
        assert exc.value.status_code == 409

    def test_a_late_ban_adopts_its_explanation_as_the_note(
        self, db, space, member, owner,
    ):
        """Removed ordinarily with no note, blocked afterwards — the
        membership a reader sees first should carry a reason."""
        _remove(db, space, member, owner)
        set_rejoin_policy(
            space.slug, member.id,
            RejoinPolicyRequest(
                rejoin_blocked=True, note="Later found to be a duplicate.",
            ),
            db=db, current_user=owner,
        )
        row = _row(db, space, member)
        assert row.rejoin_blocked is True
        assert row.removal_note == "Later found to be a duplicate."


# ---------------------------------------------------------------------------
# 7. Active payment plans
# ---------------------------------------------------------------------------


class TestRemovalWithALivePaymentPlan:
    """Ordinary removal waits for the money; urgent behaviour removal
    does not, and says so."""

    def _plan(self, db, space, member, status="active"):
        from app.models.payment_option import (
            PaymentOption, PaymentOptionStatus, PaymentOptionType,
        )
        from app.models.payment_option_schedule import PaymentOptionSchedule
        from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus

        opt = PaymentOption(
            id=_uid("po"), space_id=space.id,
            attaches_to_kind="space", attaches_to_id=space.id,
            name="Four weekly payments",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=10000, currency="AUD",
        )
        db.add(opt)
        db.flush()
        sched = PaymentOptionSchedule(
            id=_uid("sched"), payment_option_id=opt.id, name="Weekly x 4",
            schedule_type="recurring_installments", status="published",
            installment_amount_cents=2500, installment_count=4,
            stripe_interval="week", stripe_interval_count=1,
            total_amount_cents=10000, currency="AUD",
        )
        db.add(sched)
        db.flush()
        now = datetime.utcnow()
        db.add(PurchasePlan(
            id=_uid("pplan"), member_user_id=member.id,
            payment_option_id=opt.id, payment_option_schedule_id=sched.id,
            space_id=space.id, status=PurchasePlanStatus(status),
            currency="AUD", installment_amount_cents=2500,
            installments_expected=4, installments_paid=1,
            total_expected_cents=10000, stripe_interval="week",
            stripe_interval_count=1, stripe_mode="test",
            snapshot_grants_json={
                "version": 1, "entitlements": [], "access_passes": [],
                "bookings": [],
            },
            created_at=now, updated_at=now,
        ))
        db.flush()

    @pytest.mark.parametrize("reason", [
        "member_requested", "no_longer_required", "payment_issues", "other",
    ])
    def test_an_ordinary_removal_is_blocked(
        self, db, space, member, owner, reason,
    ):
        self._plan(db, space, member)
        with pytest.raises(HTTPException) as exc:
            _remove(db, space, member, owner, reason=reason)
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "active_payment_plan"

    def test_the_member_stays_while_the_money_is_unresolved(
        self, db, space, member, owner,
    ):
        self._plan(db, space, member)
        with pytest.raises(HTTPException):
            _remove(db, space, member, owner)
        assert _row(db, space, member).status == (
            SpaceMembershipStatus.active
        )

    def test_an_urgent_behaviour_removal_needs_acknowledgement(
        self, db, space, member, owner,
    ):
        """It may proceed — but not silently."""
        self._plan(db, space, member)
        with pytest.raises(HTTPException) as exc:
            _remove(
                db, space, member, owner,
                reason="inappropriate_behaviour",
                note="Abuse.", rejoin_blocked=True,
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "acknowledgement_required"

    def test_the_warning_says_billing_continues(
        self, db, space, member, owner,
    ):
        self._plan(db, space, member)
        with pytest.raises(HTTPException) as exc:
            _remove(
                db, space, member, owner,
                reason="inappropriate_behaviour", note="Abuse.",
            )
        message = exc.value.detail["message"].lower()
        assert "keep collecting" in message
        assert "not cancel or refund" in message

    def test_acknowledged_it_proceeds(self, db, space, member, owner):
        self._plan(db, space, member)
        result = _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", rejoin_blocked=True,
            acknowledge_active_payment_plan=True,
        )
        assert result.removed is True
        assert result.payment_action_required is True
        assert _row(db, space, member).status == (
            SpaceMembershipStatus.removed
        )

    def test_the_outstanding_payment_is_recorded(
        self, db, space, member, owner,
    ):
        self._plan(db, space, member)
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", acknowledge_active_payment_plan=True,
        )
        assert _row(db, space, member).payment_action_required is True

    def test_it_is_not_presented_as_financially_resolved(
        self, db, space, member, owner,
    ):
        """The response says the money is still open, so no caller can
        render this as settled."""
        self._plan(db, space, member)
        result = _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", acknowledge_active_payment_plan=True,
        )
        assert result.payment_action_required is True

    def test_no_stripe_schedule_is_touched(self, db, space, member, owner):
        import inspect
        import re

        self._plan(db, space, member)
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", acknowledge_active_payment_plan=True,
        )
        # The plan is untouched in the database...
        from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus

        plan = db.query(PurchasePlan).filter(
            PurchasePlan.member_user_id == member.id,
        ).first()
        assert plan.status == PurchasePlanStatus.active
        assert plan.cancelled_at is None
        # ...and the endpoint makes no provider call. String literals
        # are stripped before the check: the warning deliberately names
        # Stripe, because telling the creator that billing continues is
        # the whole point of it. What must not exist is a call.
        src = inspect.getsource(remove_member_with_reason)
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        code = re.sub(r'"[^"\n]*"', '""', code)
        code = re.sub(r"'[^'\n]*'", "''", code)
        assert "stripe" not in code.lower()
        assert "refund" not in code.lower()

    def test_a_settled_plan_does_not_block(
        self, db, space, member, owner,
    ):
        self._plan(db, space, member, status="completed")
        assert _remove(db, space, member, owner).removed is True

    def test_the_flag_survives_readmission(
        self, db, space, member, owner,
    ):
        """Coming back does not settle the money."""
        self._plan(db, space, member)
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", acknowledge_active_payment_plan=True,
        )
        membership_grant.reactivate(
            db, _row(db, space, member), now=datetime.utcnow(),
        )
        db.flush()
        assert _row(db, space, member).payment_action_required is True


# ---------------------------------------------------------------------------
# 8. The deprecated DELETE endpoint
# ---------------------------------------------------------------------------


class TestTheOldDeleteEndpointCannotBypassTheNewDecisions:

    def test_it_still_removes(self, db, space, member, owner):
        result = remove_member(
            space.slug, member.id, db=db, current_user=owner,
        )
        assert result["removed"] is True
        assert _row(db, space, member).status == (
            SpaceMembershipStatus.removed
        )

    def test_it_records_an_administrative_reason(
        self, db, space, member, owner,
    ):
        remove_member(space.slug, member.id, db=db, current_user=owner)
        assert _row(db, space, member).removal_reason == (
            membership_removal.REASON_NO_LONGER_REQUIRED
        )

    def test_it_cannot_ban(self, db, space, member, owner):
        """A body-less call cannot express a ban, so it never imposes
        one — the decision stays deliberate."""
        remove_member(space.slug, member.id, db=db, current_user=owner)
        row = _row(db, space, member)
        assert row.rejoin_blocked is False
        assert membership_grant.may_rejoin(row) is True

    def test_it_cannot_push_past_an_active_payment_plan(
        self, db, space, member, owner,
    ):
        """It cannot acknowledge the warning, so it cannot skip it."""
        TestRemovalWithALivePaymentPlan()._plan(db, space, member)
        with pytest.raises(HTTPException) as exc:
            remove_member(space.slug, member.id, db=db, current_user=owner)
        assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# 9. Creator visibility — Removed People
# ---------------------------------------------------------------------------


class TestRemovedPeopleView:

    def test_a_removed_person_is_listed(self, db, space, member, owner):
        _remove(
            db, space, member, owner, reason="payment_issues",
            note="Chargebacks.",
        )
        [row] = list_removed_members(space.slug, db=db, current_user=owner)
        assert row.user_id == member.id
        assert row.removal_reason == "payment_issues"
        assert row.note == "Chargebacks."
        assert row.rejoin_blocked is False
        assert row.may_rejoin is True

    def test_a_banned_person_is_identifiable(
        self, db, space, member, owner,
    ):
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", rejoin_blocked=True,
        )
        [row] = list_removed_members(space.slug, db=db, current_user=owner)
        assert row.rejoin_blocked is True
        assert row.may_rejoin is False

    def test_it_names_who_removed_them(self, db, space, member, owner):
        _remove(db, space, member, owner)
        [row] = list_removed_members(space.slug, db=db, current_user=owner)
        assert row.removed_by_display_name in (owner.name, owner.email)

    def test_an_active_member_is_not_listed(self, db, space, member, owner):
        assert list_removed_members(
            space.slug, db=db, current_user=owner,
        ) == []

    def test_an_unresolved_payment_is_visible(
        self, db, space, member, owner,
    ):
        TestRemovalWithALivePaymentPlan()._plan(db, space, member)
        _remove(
            db, space, member, owner, reason="inappropriate_behaviour",
            note="Abuse.", acknowledge_active_payment_plan=True,
        )
        [row] = list_removed_members(space.slug, db=db, current_user=owner)
        assert row.payment_action_required is True

    def test_a_moderator_may_read_it(self, db, space, member, owner,
                                     moderator):
        """Reading is caretaker-level; only imposing and lifting are
        owner-only."""
        _remove(db, space, member, owner)
        rows = list_removed_members(
            space.slug, db=db, current_user=moderator,
        )
        assert len(rows) == 1

    def test_a_stranger_may_not(self, db, space, member, owner, make_user):
        _remove(db, space, member, owner)
        with pytest.raises(HTTPException) as exc:
            list_removed_members(
                space.slug, db=db, current_user=make_user(),
            )
        assert exc.value.status_code in (403, 404)

    def test_an_ordinary_member_may_not(
        self, db, space, member, owner, make_user,
    ):
        other = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=other.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            source="joined",
        ))
        db.flush()
        _remove(db, space, member, owner)
        with pytest.raises(HTTPException) as exc:
            list_removed_members(space.slug, db=db, current_user=other)
        assert exc.value.status_code in (403, 404)


# ---------------------------------------------------------------------------
# 10. Notes stay private
# ---------------------------------------------------------------------------


class TestRemovalNotesArePrivate:

    def test_the_member_facing_memberships_payload_omits_them(
        self, db, space, member, owner,
    ):
        """``/api/auth/me/memberships`` builds explicit keys; this pins
        that a removal note can never arrive among them."""
        import inspect

        from app.auth import routes as auth_routes

        src = inspect.getsource(auth_routes.get_memberships)
        assert "removal_note" not in src
        assert "removal_reason" not in src

    def test_the_creator_member_list_omits_them(self):
        from app.creator.schemas import CreatorMemberItem

        fields = set(CreatorMemberItem.model_fields)
        assert "note" not in fields
        assert "removal_note" not in fields

    def test_the_member_directory_omits_them(self):
        import inspect

        from app.members import routes as member_routes

        src = inspect.getsource(member_routes)
        assert "removal_note" not in src

    def test_the_space_payload_omits_them(self):
        from app.spaces.schemas import SpaceResponse

        assert "removal_note" not in set(SpaceResponse.model_fields)

    def test_only_the_creator_view_carries_the_note(self):
        from app.creator.schemas import RemovedMemberItem

        assert "note" in set(RemovedMemberItem.model_fields)


# ---------------------------------------------------------------------------
# 11. The member-initiated departure is untouched
# ---------------------------------------------------------------------------


class TestLeaveCollectiveStillWorks:

    def test_a_voluntary_departure_carries_no_reason_or_block(
        self, db, space, member,
    ):
        from app.spaces.routes import leave_collective

        leave_collective(space.slug, db=db, current_user=member)
        row = _row(db, space, member)
        assert row.removal_kind == membership_removal.REMOVAL_VOLUNTARY
        assert row.removal_reason is None
        assert row.rejoin_blocked is False
        assert membership_grant.may_rejoin(row) is True

    def test_a_voluntary_departure_writes_no_restriction_event(
        self, db, space, member,
    ):
        from app.spaces.routes import leave_collective

        leave_collective(space.slug, db=db, current_user=member)
        assert _events(db, space, member) == []

    def test_a_departed_member_is_listed_for_the_creator(
        self, db, space, member, owner,
    ):
        """Visible, and visibly not a removal the creator made."""
        from app.spaces.routes import leave_collective

        leave_collective(space.slug, db=db, current_user=member)
        [row] = list_removed_members(space.slug, db=db, current_user=owner)
        assert row.removal_kind == "voluntary"
        assert row.may_rejoin is True
