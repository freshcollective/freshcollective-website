"""An ``included_with_offer`` Pathway unlocks on EITHER access record.

Production defect this pins
---------------------------
A member bought an A$10 Payment Option that carried a ``pathway``
grant. Everything financial worked: the payment succeeded, fulfilment
reported ``applied``, commission and Connect transfer were correct.
But the Pathway stayed locked.

``services.purchase_fulfilment.resolve_intent_from_grants`` writes one
``EntitlementIntent`` per ``pathway`` grant, and writes ``AccessPass``
rows **only** for ``event_series`` grants. The three
``included_with_offer`` access checks accepted **only** an
``AccessPass``. So the purchase wrote exactly the record the member
check never read — while Creator Studio's People panel, which reads
``pathway_entitlements``, cheerfully reported "Purchased".

Both records are now accepted. The entitlement arm is not a widening
of the product rule; it is the rule finally matching what fulfilment
writes. Everything that bounded access before still bounds it:

  * active ``SpaceMembership`` on the Collective is still required;
  * ``status`` must be ``active`` — revoked / expired / cancelled
    rows grant nothing;
  * ``ends_at`` must be NULL or in the future;
  * the entitlement must belong to this member AND this Pathway;
  * caretaker bypass is unchanged;
  * payment status alone never grants access — only a durable
    entitlement or pass does.

All three surfaces are asserted together in several tests, because the
original defect was precisely that they had drifted apart:

  * ``compute_pathway_access``            — member pages
  * ``spaces.routes._check_pathway_access`` — content endpoints (403)
  * ``channel_permissions``                — view + mention autocomplete
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

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
    ConversationChannel,
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
from app.services.channel_permissions import (
    accessible_user_ids_for_channel,
    can_view_channel,
)
from app.services.pathway_access import (
    compute_pathway_access,
    has_active_pathway_entitlement,
    included_with_offer_unlocked,
    users_with_included_with_offer_access,
)
from app.spaces.routes import _check_pathway_access


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _pathway(db, space, *, access_type="included_with_offer",
             status=PathwayStatus.active, title="Test Pathway") -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        status=status,
        access_type=access_type,
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def _option(db, space, *, name="Live payment test",
            status=PaymentOptionStatus.published) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=None,
        attaches_to_kind="pathway",
        attaches_to_id=_uid("anchor"),
        name=name,
        payment_type=PaymentOptionType.one_time,
        status=status,
        calculated_total_cents=1000,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _grant(db, option, pathway) -> PaymentOptionGrant:
    g = PaymentOptionGrant(
        id=_uid("pog"),
        payment_option_id=option.id,
        grant_kind="pathway",
        pathway_id=pathway.id,
    )
    db.add(g)
    db.flush()
    return g


def _member(db, user, space, *, role: SpaceRole = SpaceRole.learner,
            status: SpaceMembershipStatus = SpaceMembershipStatus.active):
    m = SpaceMembership(
        id=_uid("sm"),
        user_id=user.id,
        space_id=space.id,
        role=role,
        status=status,
        joined_at=datetime.utcnow(),
    )
    db.add(m)
    db.flush()
    return m


def _entitlement(db, *, user, space, pathway,
                 source: EntitlementSource = EntitlementSource.one_time_purchase,
                 status: EntitlementStatus = EntitlementStatus.active,
                 ends_at=None) -> PathwayEntitlement:
    """The row ``purchase_fulfilment._apply_entitlement`` writes for a
    ``pathway`` grant: perpetual (``ends_at=None``) and
    ``source='one_time_purchase'`` unless overridden."""
    e = PathwayEntitlement(
        id=_uid("ent"),
        user_id=user.id,
        space_id=space.id,
        pathway_id=pathway.id,
        source=source,
        status=status,
        starts_at=datetime.utcnow() - timedelta(minutes=5),
        ends_at=ends_at,
    )
    db.add(e)
    db.flush()
    return e


def _access_pass(db, *, user, space, option,
                 status: AccessPassStatus = AccessPassStatus.active,
                 valid_until=None) -> AccessPass:
    ap = AccessPass(
        id=_uid("ap"),
        user_id=user.id,
        space_id=space.id,
        pass_type=AccessPassType.pathway_access,
        status=status,
        payment_option_id=option.id,
        valid_from=datetime.utcnow() - timedelta(days=1),
        valid_until=valid_until,
        source=AccessPassSource.one_time_purchase,
    )
    db.add(ap)
    db.flush()
    return ap


def _channel(db, space, pathway) -> ConversationChannel:
    c = ConversationChannel(
        id=_uid("ch"),
        space_id=space.id,
        name=f"{pathway.title} — Group",
        slug=f"ch-{uuid.uuid4().hex[:8]}",
        channel_type="pathway",
        pathway_id=pathway.id,
    )
    db.add(c)
    db.flush()
    return c


def _content_access(user, pathway, space, db) -> bool:
    """``_check_pathway_access`` raises instead of returning; adapt it
    so the content surface can be compared with the others directly."""
    try:
        _check_pathway_access(user, pathway, space, db)
        return True
    except HTTPException:
        return False


def _assert_all_surfaces(db, *, user, pathway, space, expected: bool,
                         channel=None) -> None:
    """Every surface must agree. The production defect was a
    disagreement, so agreement is the thing worth asserting."""
    member_page = compute_pathway_access(user, pathway, space, db)
    assert member_page is expected, (
        f"compute_pathway_access returned {member_page}, expected {expected}"
    )
    content = _content_access(user, pathway, space, db)
    assert content is expected, (
        f"_check_pathway_access allowed={content}, expected {expected}"
    )
    if channel is not None:
        view = can_view_channel(user, channel, space, db)
        assert view is expected, (
            f"can_view_channel returned {view}, expected {expected}"
        )
        in_set = user.id in accessible_user_ids_for_channel(channel, space, db)
        assert in_set is expected, (
            f"mention autocomplete included={in_set}, expected {expected}"
        )


# ---------------------------------------------------------------------------
# 1 · The production scenario
# ---------------------------------------------------------------------------


class TestTheProductionScenario:
    def test_active_perpetual_entitlement_no_pass_grants_access(
        self, db, make_space, make_user,
    ):
        """Tom's exact state: active membership, ``included_with_offer``
        Pathway, active perpetual ``one_time_purchase`` entitlement, no
        AccessPass. Before the fix every surface here returned False."""
        space = make_space()
        tom = make_user()
        _member(db, tom, space)
        pathway = _pathway(db, space)
        option = _option(db, space)
        _grant(db, option, pathway)
        _entitlement(db, user=tom, space=space, pathway=pathway)
        channel = _channel(db, space, pathway)
        db.commit()

        assert not db.query(AccessPass).filter(
            AccessPass.user_id == tom.id).all(), "fixture must have no pass"

        _assert_all_surfaces(
            db, user=tom, pathway=pathway, space=space,
            expected=True, channel=channel,
        )

    def test_manual_grant_entitlement_also_unlocks(
        self, db, make_space, make_user,
    ):
        """Creator-issued manual grants land in the same table, so they
        unlock these Pathways on the same terms."""
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space)
        _grant(db, _option(db, space), pathway)
        _entitlement(
            db, user=user, space=space, pathway=pathway,
            source=EntitlementSource.manual_grant,
        )
        db.commit()

        assert compute_pathway_access(user, pathway, space, db) is True


# ---------------------------------------------------------------------------
# 2 · The pass arm is untouched
# ---------------------------------------------------------------------------


class TestAccessPassArmPreserved:
    def test_valid_access_pass_still_grants_access(
        self, db, make_space, make_user,
    ):
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space)
        option = _option(db, space)
        _grant(db, option, pathway)
        _access_pass(db, user=user, space=space, option=option)
        channel = _channel(db, space, pathway)
        db.commit()

        assert not db.query(PathwayEntitlement).filter(
            PathwayEntitlement.user_id == user.id).all(), \
            "fixture must have no entitlement — the pass alone must work"

        _assert_all_surfaces(
            db, user=user, pathway=pathway, space=space,
            expected=True, channel=channel,
        )

    def test_draft_option_pass_still_denied(self, db, make_space, make_user):
        """A pass on a draft Option never unlocked anything and still
        doesn't — the entitlement arm must not smuggle this in."""
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space)
        option = _option(db, space, status=PaymentOptionStatus.draft)
        _grant(db, option, pathway)
        _access_pass(db, user=user, space=space, option=option)
        db.commit()

        assert compute_pathway_access(user, pathway, space, db) is False


# ---------------------------------------------------------------------------
# 3 · Denials — every boundary that held before must still hold
# ---------------------------------------------------------------------------


class TestDenials:
    def test_neither_entitlement_nor_pass_is_denied(
        self, db, make_space, make_user,
    ):
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space)
        _grant(db, _option(db, space), pathway)
        channel = _channel(db, space, pathway)
        db.commit()

        _assert_all_surfaces(
            db, user=user, pathway=pathway, space=space,
            expected=False, channel=channel,
        )

    def test_expired_entitlement_is_denied(self, db, make_space, make_user):
        """``status='active'`` but ``ends_at`` in the past. This is the
        shape Creator Studio used to mislabel as "Purchased"."""
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space)
        _grant(db, _option(db, space), pathway)
        _entitlement(
            db, user=user, space=space, pathway=pathway,
            ends_at=datetime.utcnow() - timedelta(days=1),
        )
        channel = _channel(db, space, pathway)
        db.commit()

        _assert_all_surfaces(
            db, user=user, pathway=pathway, space=space,
            expected=False, channel=channel,
        )

    def test_future_ends_at_still_grants(self, db, make_space, make_user):
        """The boundary's other side — a window that hasn't closed."""
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space)
        _grant(db, _option(db, space), pathway)
        _entitlement(
            db, user=user, space=space, pathway=pathway,
            ends_at=datetime.utcnow() + timedelta(days=30),
        )
        db.commit()

        assert compute_pathway_access(user, pathway, space, db) is True

    def test_revoked_entitlement_is_denied(self, db, make_space, make_user):
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space)
        _grant(db, _option(db, space), pathway)
        _entitlement(
            db, user=user, space=space, pathway=pathway,
            status=EntitlementStatus.revoked,
        )
        channel = _channel(db, space, pathway)
        db.commit()

        _assert_all_surfaces(
            db, user=user, pathway=pathway, space=space,
            expected=False, channel=channel,
        )

    @pytest.mark.parametrize(
        "status",
        [EntitlementStatus.expired, EntitlementStatus.cancelled],
    )
    def test_non_active_statuses_are_denied(
        self, db, make_space, make_user, status,
    ):
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space)
        _grant(db, _option(db, space), pathway)
        _entitlement(
            db, user=user, space=space, pathway=pathway, status=status,
        )
        db.commit()

        assert compute_pathway_access(user, pathway, space, db) is False

    def test_another_members_entitlement_does_not_leak(
        self, db, make_space, make_user,
    ):
        """Buyer gets in; the other member does not. Same Pathway, same
        Collective — only the entitlement's owner differs."""
        space = make_space()
        buyer = make_user()
        bystander = make_user()
        _member(db, buyer, space)
        _member(db, bystander, space)
        pathway = _pathway(db, space)
        _grant(db, _option(db, space), pathway)
        _entitlement(db, user=buyer, space=space, pathway=pathway)
        channel = _channel(db, space, pathway)
        db.commit()

        _assert_all_surfaces(
            db, user=buyer, pathway=pathway, space=space,
            expected=True, channel=channel,
        )
        _assert_all_surfaces(
            db, user=bystander, pathway=pathway, space=space,
            expected=False, channel=channel,
        )

    def test_entitlement_for_another_pathway_does_not_leak(
        self, db, make_space, make_user,
    ):
        """Two ``included_with_offer`` Pathways in one Collective. An
        entitlement to one must not open the other."""
        space = make_space()
        user = make_user()
        _member(db, user, space)
        bought = _pathway(db, space, title="Bought Pathway")
        other = _pathway(db, space, title="Other Pathway")
        _grant(db, _option(db, space, name="Bought"), bought)
        _grant(db, _option(db, space, name="Other"), other)
        _entitlement(db, user=user, space=space, pathway=bought)
        bought_ch = _channel(db, space, bought)
        other_ch = _channel(db, space, other)
        db.commit()

        _assert_all_surfaces(
            db, user=user, pathway=bought, space=space,
            expected=True, channel=bought_ch,
        )
        _assert_all_surfaces(
            db, user=user, pathway=other, space=space,
            expected=False, channel=other_ch,
        )

    @pytest.mark.parametrize(
        "membership",
        ["none", "paused", "removed"],
    )
    def test_membership_requirement_preserved(
        self, db, make_space, make_user, membership,
    ):
        """An entitlement without active membership grants nothing —
        the requirement the fix was explicitly not allowed to relax."""
        space = make_space()
        user = make_user()
        if membership != "none":
            _member(
                db, user, space,
                status=SpaceMembershipStatus(membership),
            )
        pathway = _pathway(db, space)
        _grant(db, _option(db, space), pathway)
        _entitlement(db, user=user, space=space, pathway=pathway)
        channel = _channel(db, space, pathway)
        db.commit()

        _assert_all_surfaces(
            db, user=user, pathway=pathway, space=space,
            expected=False, channel=channel,
        )

    @pytest.mark.parametrize(
        "status", [PathwayStatus.draft, PathwayStatus.coming_soon],
    )
    def test_a_withheld_pathway_status_still_denies(
        self, db, make_space, make_user, status,
    ):
        """``draft`` and ``coming_soon`` are flat refusals whatever the
        member holds: one was never offered, the other is not open yet.

        ``archived`` used to be in this list and deliberately is not any
        more — it was revoking purchases. See
        ``TestArchivedPathwaysKeepTheirPurchasers`` below, and
        ``pathway_access.retains_acquired_access`` for the reasoning.
        """
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space, status=status)
        _grant(db, _option(db, space), pathway)
        _entitlement(db, user=user, space=space, pathway=pathway)
        db.commit()

        assert compute_pathway_access(user, pathway, space, db) is False

    def test_anonymous_visitor_still_denied(self, db, make_space):
        space = make_space()
        pathway = _pathway(db, space)
        db.commit()

        assert compute_pathway_access(None, pathway, space, db) is False


# ---------------------------------------------------------------------------
# 3b · Archiving takes a Pathway out of circulation, not out of a
#      member's hands
# ---------------------------------------------------------------------------


class TestArchivedPathwaysKeepTheirPurchasers:
    """All three surfaces used to test ``status in ("draft",
    "archived", "coming_soon")`` and refuse *before* looking at what
    the member held, so archiving revoked every purchase — entitlement
    row, progress and reflections all still in the database, all
    unreachable.

    Asserted through ``_assert_all_surfaces`` for the same reason the
    rest of this file is: the original defect here was three surfaces
    disagreeing, and a fourth copy of the status rule is exactly how
    that would happen again.
    """

    def test_an_entitlement_holder_keeps_an_archived_pathway(
        self, db, make_space, make_user,
    ):
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space, status=PathwayStatus.archived)
        _grant(db, _option(db, space), pathway)
        _entitlement(db, user=user, space=space, pathway=pathway)
        channel = _channel(db, space, pathway)
        db.commit()

        _assert_all_surfaces(
            db, user=user, pathway=pathway, space=space,
            expected=True, channel=channel,
        )

    def test_a_pass_holder_keeps_an_archived_pathway(
        self, db, make_space, make_user,
    ):
        """The other durable record. Same answer, because "what
        survives archiving" and "what unlocks an
        ``included_with_offer`` Pathway" are the same question."""
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space, status=PathwayStatus.archived)
        option = _option(db, space)
        _grant(db, option, pathway)
        _access_pass(db, user=user, space=space, option=option)
        channel = _channel(db, space, pathway)
        db.commit()

        _assert_all_surfaces(
            db, user=user, pathway=pathway, space=space,
            expected=True, channel=channel,
        )

    def test_a_member_holding_nothing_is_denied(
        self, db, make_space, make_user,
    ):
        """The narrowing half. Archiving is still how a creator takes a
        Pathway out of circulation — it does not become a members'
        freebie."""
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space, status=PathwayStatus.archived)
        _grant(db, _option(db, space), pathway)
        channel = _channel(db, space, pathway)
        db.commit()

        _assert_all_surfaces(
            db, user=user, pathway=pathway, space=space,
            expected=False, channel=channel,
        )

    def test_a_revoked_entitlement_opens_nothing(
        self, db, make_space, make_user,
    ):
        """"Preserve purchases" is not "grant access forever". The
        record has to still be good."""
        from app.models.platform import EntitlementStatus

        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space, status=PathwayStatus.archived)
        _grant(db, _option(db, space), pathway)
        _entitlement(
            db, user=user, space=space, pathway=pathway,
            status=EntitlementStatus.revoked,
        )
        db.commit()

        assert compute_pathway_access(user, pathway, space, db) is False

    def test_an_expired_entitlement_opens_nothing(
        self, db, make_space, make_user,
    ):
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space, status=PathwayStatus.archived)
        _grant(db, _option(db, space), pathway)
        _entitlement(
            db, user=user, space=space, pathway=pathway,
            ends_at=datetime.utcnow() - timedelta(days=1),
        )
        db.commit()

        assert compute_pathway_access(user, pathway, space, db) is False

    def test_membership_is_still_required_where_it_always_was(
        self, db, make_space, make_user,
    ):
        """The archive rule is applied *in addition to* the access-type
        rule, never instead of it. An ``included_with_offer`` Pathway
        requires active membership, and archiving does not waive that —
        otherwise archiving would widen access, which is the one thing
        it must not do."""
        space = make_space()
        user = make_user()  # deliberately not a member
        pathway = _pathway(db, space, status=PathwayStatus.archived)
        _grant(db, _option(db, space), pathway)
        _entitlement(db, user=user, space=space, pathway=pathway)
        db.commit()

        assert compute_pathway_access(user, pathway, space, db) is False

    def test_an_anonymous_visitor_is_still_denied(self, db, make_space):
        """Nobody anonymous holds anything, so this stays a flat
        refusal — an archived Pathway is never publicly reachable."""
        space = make_space()
        pathway = _pathway(db, space, status=PathwayStatus.archived)
        db.commit()

        assert compute_pathway_access(None, pathway, space, db) is False


# ---------------------------------------------------------------------------
# 4 · Caretaker bypass unchanged
# ---------------------------------------------------------------------------


class TestCaretakerBypassUnchanged:
    def test_owner_moderator_and_admin_keep_access_without_either_record(
        self, db, make_space, make_user,
    ):
        """None of these three holds a pass or an entitlement. Their
        bypass is untouched by the change."""
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        moderator = make_user()
        admin = make_user(role="admin")
        _member(db, moderator, space, role=SpaceRole.moderator)
        pathway = _pathway(db, space)
        _grant(db, _option(db, space), pathway)
        db.commit()

        for user in (owner, moderator, admin):
            assert compute_pathway_access(user, pathway, space, db) is True
            assert _content_access(user, pathway, space, db) is True


# ---------------------------------------------------------------------------
# 5 · Other access types unchanged
# ---------------------------------------------------------------------------


class TestOtherAccessTypesUnchanged:
    def test_free_pathway_grants_any_active_member(
        self, db, make_space, make_user,
    ):
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space, access_type="free")
        db.commit()

        assert compute_pathway_access(user, pathway, space, db) is True

    def test_included_pathway_needs_active_membership_only(
        self, db, make_space, make_user,
    ):
        space = make_space()
        member = make_user()
        outsider = make_user()
        _member(db, member, space)
        pathway = _pathway(db, space, access_type="included")
        db.commit()

        assert compute_pathway_access(member, pathway, space, db) is True
        assert compute_pathway_access(outsider, pathway, space, db) is False

    def test_one_time_pathway_still_requires_entitlement(
        self, db, make_space, make_user,
    ):
        """The ``one_time`` branch now calls the shared helper. Its
        behaviour must be exactly what it was."""
        space = make_space()
        buyer = make_user()
        other = make_user()
        _member(db, buyer, space)
        _member(db, other, space)
        pathway = _pathway(db, space, access_type="one_time")
        _entitlement(db, user=buyer, space=space, pathway=pathway)
        db.commit()

        assert compute_pathway_access(buyer, pathway, space, db) is True
        assert compute_pathway_access(other, pathway, space, db) is False

    def test_one_time_pathway_expired_entitlement_denied(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        _member(db, buyer, space)
        pathway = _pathway(db, space, access_type="one_time")
        _entitlement(
            db, user=buyer, space=space, pathway=pathway,
            ends_at=datetime.utcnow() - timedelta(hours=1),
        )
        db.commit()

        assert compute_pathway_access(buyer, pathway, space, db) is False

    def test_access_pass_does_not_unlock_a_one_time_pathway(
        self, db, make_space, make_user,
    ):
        """The two arms are joined only for ``included_with_offer``.
        A ``one_time`` Pathway must not start accepting passes."""
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space, access_type="one_time")
        option = _option(db, space)
        _grant(db, option, pathway)
        _access_pass(db, user=user, space=space, option=option)
        db.commit()

        assert compute_pathway_access(user, pathway, space, db) is False


# ---------------------------------------------------------------------------
# 6 · The shared helpers themselves
# ---------------------------------------------------------------------------


class TestSharedHelpers:
    def test_unlocked_helper_accepts_either_arm_independently(
        self, db, make_space, make_user,
    ):
        space = make_space()
        pass_holder = make_user()
        entitled = make_user()
        neither = make_user()
        for u in (pass_holder, entitled, neither):
            _member(db, u, space)
        pathway = _pathway(db, space)
        option = _option(db, space)
        _grant(db, option, pathway)
        _access_pass(db, user=pass_holder, space=space, option=option)
        _entitlement(db, user=entitled, space=space, pathway=pathway)
        db.commit()

        for user, expected in (
            (pass_holder, True), (entitled, True), (neither, False),
        ):
            assert included_with_offer_unlocked(
                db, user_id=user.id, space_id=space.id,
                pathway_id=pathway.id,
            ) is expected

    def test_set_helper_matches_the_per_user_helper(
        self, db, make_space, make_user,
    ):
        """The autocomplete set and the per-user predicate must not be
        able to disagree — that disagreement was the original bug."""
        space = make_space()
        pass_holder = make_user()
        entitled = make_user()
        expired = make_user()
        revoked = make_user()
        neither = make_user()
        everyone = [pass_holder, entitled, expired, revoked, neither]
        for u in everyone:
            _member(db, u, space)
        pathway = _pathway(db, space)
        option = _option(db, space)
        _grant(db, option, pathway)
        _access_pass(db, user=pass_holder, space=space, option=option)
        _entitlement(db, user=entitled, space=space, pathway=pathway)
        _entitlement(
            db, user=expired, space=space, pathway=pathway,
            ends_at=datetime.utcnow() - timedelta(days=2),
        )
        _entitlement(
            db, user=revoked, space=space, pathway=pathway,
            status=EntitlementStatus.revoked,
        )
        db.commit()

        as_set = users_with_included_with_offer_access(
            db, space_id=space.id, pathway_id=pathway.id,
        )
        for u in everyone:
            per_user = included_with_offer_unlocked(
                db, user_id=u.id, space_id=space.id, pathway_id=pathway.id,
            )
            assert (u.id in as_set) is per_user, (
                f"set/per-user divergence for {u.id}"
            )
        assert as_set == {pass_holder.id, entitled.id}

    def test_entitlement_helper_ignores_starts_at(
        self, db, make_space, make_user,
    ):
        """``starts_at`` has never gated access. Pinned so a future
        change to honour it is a deliberate decision, not a surprise."""
        space = make_space()
        user = make_user()
        _member(db, user, space)
        pathway = _pathway(db, space, access_type="one_time")
        ent = _entitlement(db, user=user, space=space, pathway=pathway)
        ent.starts_at = datetime.utcnow() + timedelta(days=7)
        db.commit()

        assert has_active_pathway_entitlement(
            db, user_id=user.id, pathway_id=pathway.id,
        ) is True
