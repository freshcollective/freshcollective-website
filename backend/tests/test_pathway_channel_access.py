"""Pathway-linked Conversation access mirrors canonical Pathway access.

The rule (fixed here, not to drift):

  If a member currently has access to the Pathway under the shared
  ``compute_pathway_access`` predicate, they can view the Pathway's
  Conversation Channel and appear in that Channel's @mention
  autocomplete. If they no longer have access — including after a
  purchase revoke that leaves only a residual ``Enrollment`` progress
  row — they lose the Channel immediately. Progress history is not
  an independent access source.

Positive branches: paid one_time / finite-plan-equivalent /
complimentary manual grant / access_type=free / access_type=included /
access_type=included_with_offer via AccessPass. Caretaker bypass
regression pin.

Negative branches: whole-purchase revoke (with and without residual
Enrollment), draft/archived/coming_soon Pathway, Enrollment-only
member with no PathwayEntitlement, non-space-member with a stray
PathwayEntitlement.

Cross-check: the member set produced by ``accessible_user_ids_for_channel``
matches the per-user ``can_view_channel`` result for every case above
— the mention autocomplete and the visibility check must not diverge.

Non-pathway channel types (open / private / gathering) are regression-
pinned so the widened predicate doesn't accidentally affect them.
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
from app.models.platform import (
    ChannelMembership,
    ConversationChannel,
    Enrollment,
    EnrollmentStatus,
    EntitlementSource,
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
    PathwayStatus,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.channel_permissions import (
    accessible_user_ids_for_channel,
    can_view_channel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


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


def _make_pathway(
    db, space, *, title: str = "The EMBODY Practice",
    access_type: str = "one_time",
    status: PathwayStatus = PathwayStatus.active,
) -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        access_type=access_type,
        status=status,
        price_cents=20000 if access_type in ("one_time", "subscription") else None,
    )
    db.add(p)
    db.flush()
    return p


def _make_pathway_channel(db, space, pathway) -> ConversationChannel:
    c = ConversationChannel(
        id=_uid("ch"),
        space_id=space.id,
        name=f"{pathway.title} — Live Group",
        slug=f"ch-{uuid.uuid4().hex[:8]}",
        channel_type="pathway",
        pathway_id=pathway.id,
    )
    db.add(c)
    db.flush()
    return c


def _grant_entitlement(
    db, *, user, space, pathway,
    source: EntitlementSource = EntitlementSource.one_time_purchase,
    status: EntitlementStatus = EntitlementStatus.active,
    ends_at=None,
) -> PathwayEntitlement:
    ent = PathwayEntitlement(
        id=_uid("ent"),
        user_id=user.id,
        space_id=space.id,
        pathway_id=pathway.id,
        source=source,
        status=status,
        starts_at=datetime.utcnow(),
        ends_at=ends_at,
    )
    db.add(ent)
    db.flush()
    return ent


def _make_enrollment(db, user, pathway) -> Enrollment:
    """A progress-tracking Enrollment row. This is what
    ``_ensure_enrollment`` in ``spaces.routes`` creates when a member
    marks their first step complete."""
    e = Enrollment(
        id=_uid("en"),
        user_id=user.id,
        pathway_id=pathway.id,
        status=EnrollmentStatus.active,
    )
    db.add(e)
    db.flush()
    return e


def _make_included_with_offer_bundle(
    db, space, pathway,
) -> tuple[PaymentOption, "PaymentOptionGrant"]:
    """A published PaymentOption whose AccessPass unlocks the Pathway.

    Since migration 125, ``PaymentOptionGrant`` is the sole source of
    truth for the "which Options include this Pathway" relationship —
    this fixture writes a grant row rather than the retired legacy
    ``PathwayUnlockRequirement`` row.
    """
    from app.models.payment_option_grant import PaymentOptionGrant
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=None,
        attaches_to_kind="event_series",
        attaches_to_id=_uid("es-anchor"),  # unused for this test's purposes
        name="Unlock offering",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=20000,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    grant = PaymentOptionGrant(
        id=_uid("pog"),
        payment_option_id=opt.id,
        grant_kind="pathway",
        pathway_id=pathway.id,
    )
    db.add(grant)
    db.flush()
    return opt, grant


def _grant_access_pass(db, *, user, space, payment_option) -> AccessPass:
    ap = AccessPass(
        id=_uid("ap"),
        user_id=user.id,
        space_id=space.id,
        pass_type=AccessPassType.pathway_access,
        status=AccessPassStatus.active,
        payment_option_id=payment_option.id,
        source=AccessPassSource.one_time_purchase,
    )
    db.add(ap)
    db.flush()
    return ap


def _assert_view_and_autocomplete_agree(
    db, *, user, channel, space, expected: bool,
) -> None:
    """Cross-check: the two surfaces must agree on this user's access."""
    view = can_view_channel(user, channel, space, db)
    assert view is expected, (
        f"can_view_channel returned {view}, expected {expected}"
    )
    ids = accessible_user_ids_for_channel(channel, space, db)
    in_set = user.id in ids
    assert in_set is expected, (
        f"accessible_user_ids_for_channel included={in_set}, expected {expected} "
        f"(divergence between view + autocomplete surfaces)"
    )


# ---------------------------------------------------------------------------
# 1. Positive branches — canonical access sources grant the Channel
# ---------------------------------------------------------------------------


class TestPositivePathwayChannelAccess:
    def test_paid_one_time_entitlement_grants_channel(
        self, db, make_space, make_user,
    ):
        """The Awaken production case: fresh purchase → active
        PathwayEntitlement, no Enrollment row → channel visible."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(db, space, access_type="one_time")
        channel = _make_pathway_channel(db, space, pathway)
        _grant_entitlement(
            db, user=payer, space=space, pathway=pathway,
            source=EntitlementSource.one_time_purchase,
        )
        # No Enrollment — buyer hasn't marked any step complete.
        assert db.query(Enrollment).filter(
            Enrollment.user_id == payer.id,
        ).count() == 0
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

    def test_manual_grant_entitlement_grants_channel(
        self, db, make_space, make_user,
    ):
        """Complimentary / creator-side manual grant. Same shape as a
        paid entitlement — same rule applies."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(db, space, access_type="one_time")
        channel = _make_pathway_channel(db, space, pathway)
        _grant_entitlement(
            db, user=payer, space=space, pathway=pathway,
            source=EntitlementSource.manual_grant,
        )
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

    def test_finite_plan_first_payment_grants_channel(
        self, db, make_space, make_user,
    ):
        """Finite-plan first-payment fulfilment lands the same
        PathwayEntitlement shape as a pay-in-full purchase. Simulated
        here by seeding the entitlement directly — the fulfilment
        service is exercised end-to-end elsewhere in the suite; this
        test pins the access-check side of the contract."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(db, space, access_type="one_time")
        channel = _make_pathway_channel(db, space, pathway)
        # First-payment fulfilment records the entitlement source
        # as one_time_purchase (the plan is opaque to the channel
        # predicate — only status matters).
        _grant_entitlement(
            db, user=payer, space=space, pathway=pathway,
            source=EntitlementSource.one_time_purchase,
        )
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

    def test_free_pathway_grants_channel_to_any_active_member(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(db, space, access_type="free")
        channel = _make_pathway_channel(db, space, pathway)
        # No entitlement, no enrollment. Free pathway alone is the source.
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

    def test_included_pathway_grants_channel_to_any_active_member(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(db, space, access_type="included")
        channel = _make_pathway_channel(db, space, pathway)
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

    def test_included_with_offer_grants_channel_via_access_pass(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(db, space, access_type="included_with_offer")
        channel = _make_pathway_channel(db, space, pathway)
        opt, _req = _make_included_with_offer_bundle(db, space, pathway)
        _grant_access_pass(db, user=payer, space=space, payment_option=opt)
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

    def test_caretaker_bypass_regression_pin(
        self, db, make_space, make_user,
    ):
        """Creator/moderator on the Space see every channel regardless
        of pathway access — must not change under this fix."""
        space = make_space()
        mod = make_user()
        _member(db, mod, space, role=SpaceRole.moderator)
        pathway = _make_pathway(
            db, space, access_type="one_time", status=PathwayStatus.draft,
        )
        channel = _make_pathway_channel(db, space, pathway)
        db.commit()

        # Draft pathway would deny an ordinary member even with an
        # entitlement — the caretaker still sees the channel.
        _assert_view_and_autocomplete_agree(
            db, user=mod, channel=channel, space=space, expected=True,
        )


# ---------------------------------------------------------------------------
# 2. Negative branches — no legitimate access = no Channel, ever
# ---------------------------------------------------------------------------


class TestNegativePathwayChannelAccess:
    def test_enrollment_only_member_cannot_see_paid_pathway_channel(
        self, db, make_space, make_user,
    ):
        """The pinned rule: Enrollment alone is not an access source.
        A member with a residual progress record but no active
        PathwayEntitlement on a ``one_time`` pathway is denied."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(db, space, access_type="one_time")
        channel = _make_pathway_channel(db, space, pathway)
        _make_enrollment(db, payer, pathway)
        # No PathwayEntitlement. No AccessPass.
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=False,
        )

    def test_revoke_removes_channel_even_with_residual_enrollment(
        self, db, make_space, make_user,
    ):
        """The corrected revocation semantic: an entitlement flipped
        to ``revoked`` drops channel visibility immediately, even if
        the buyer had already marked a step complete and left an
        Enrollment behind."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(db, space, access_type="one_time")
        channel = _make_pathway_channel(db, space, pathway)
        ent = _grant_entitlement(
            db, user=payer, space=space, pathway=pathway,
            source=EntitlementSource.one_time_purchase,
        )
        # Member did some work — Enrollment now exists.
        _make_enrollment(db, payer, pathway)
        db.commit()
        # Sanity: before revoke they can see it.
        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

        # Revoke the entitlement (whole-purchase or single-entitlement
        # revoke both flip status to ``revoked``).
        ent.status = EntitlementStatus.revoked
        ent.revoked_at = datetime.utcnow()
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=False,
        )
        # Enrollment row is still there — deliberately unchanged. It
        # just no longer grants access on its own.
        assert db.query(Enrollment).filter(
            Enrollment.user_id == payer.id,
            Enrollment.pathway_id == pathway.id,
        ).count() == 1

    def test_expired_entitlement_removes_channel(
        self, db, make_space, make_user,
    ):
        """``ends_at`` in the past — entitlement no longer active."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(db, space, access_type="one_time")
        channel = _make_pathway_channel(db, space, pathway)
        _grant_entitlement(
            db, user=payer, space=space, pathway=pathway,
            source=EntitlementSource.one_time_purchase,
            ends_at=datetime.utcnow() - timedelta(days=1),
        )
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=False,
        )

    def test_non_space_member_with_entitlement_still_denied(
        self, db, make_space, make_user,
    ):
        """Outer ``is_active_space_member`` gate still blocks a user
        with a stray PathwayEntitlement but no SpaceMembership row."""
        space = make_space()
        stray = make_user()
        # No _member(stray, space) — deliberately absent.
        pathway = _make_pathway(db, space, access_type="one_time")
        channel = _make_pathway_channel(db, space, pathway)
        _grant_entitlement(
            db, user=stray, space=space, pathway=pathway,
            source=EntitlementSource.one_time_purchase,
        )
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=stray, channel=channel, space=space, expected=False,
        )

    def test_draft_pathway_hidden_from_ordinary_member(
        self, db, make_space, make_user,
    ):
        """Draft / archived / coming_soon Pathways deny non-caretakers
        regardless of entitlement (canonical rule)."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(
            db, space, access_type="one_time", status=PathwayStatus.draft,
        )
        channel = _make_pathway_channel(db, space, pathway)
        _grant_entitlement(
            db, user=payer, space=space, pathway=pathway,
            source=EntitlementSource.one_time_purchase,
        )
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=False,
        )


# ---------------------------------------------------------------------------
# 3. Overlap — one revoked, another still-active source preserves access
# ---------------------------------------------------------------------------


class TestOverlappingEntitlements:
    def test_two_entitlements_one_revoked_channel_still_visible(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(db, space, access_type="one_time")
        channel = _make_pathway_channel(db, space, pathway)
        ent1 = _grant_entitlement(
            db, user=payer, space=space, pathway=pathway,
            source=EntitlementSource.one_time_purchase,
        )
        _grant_entitlement(
            db, user=payer, space=space, pathway=pathway,
            source=EntitlementSource.manual_grant,
        )
        db.commit()

        ent1.status = EntitlementStatus.revoked
        ent1.revoked_at = datetime.utcnow()
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )


# ---------------------------------------------------------------------------
# 4. Non-pathway channel types — pinned so the widened predicate
#    doesn't accidentally affect them.
# ---------------------------------------------------------------------------


class TestOtherChannelTypesUnchanged:
    def test_open_channel_visible_to_active_member(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        ch = ConversationChannel(
            id=_uid("ch"),
            space_id=space.id,
            name="Common Room",
            slug="common-room",
            channel_type="general",
            is_default=True,
            is_system=True,
        )
        db.add(ch)
        db.commit()

        assert can_view_channel(payer, ch, space, db) is True

    def test_private_channel_needs_membership_row(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        insider = make_user()
        _member(db, payer, space)
        _member(db, insider, space)
        ch = ConversationChannel(
            id=_uid("ch"),
            space_id=space.id,
            name="Inner circle",
            slug=f"ch-{uuid.uuid4().hex[:8]}",
            channel_type="private",
        )
        db.add(ch)
        db.add(ChannelMembership(
            id=_uid("cm"),
            channel_id=ch.id,
            user_id=insider.id,
        ))
        db.commit()

        assert can_view_channel(payer, ch, space, db) is False
        assert can_view_channel(insider, ch, space, db) is True


# ---------------------------------------------------------------------------
# 5. Autocomplete parity — the set-based predicate matches per-user view
#    even under the boundary cases above.
# ---------------------------------------------------------------------------


class TestAutocompleteParityAcrossCases:
    def test_autocomplete_set_matches_can_view_for_paid_case(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer_in = make_user()
        payer_out = make_user()
        _member(db, payer_in, space)
        _member(db, payer_out, space)
        pathway = _make_pathway(db, space, access_type="one_time")
        channel = _make_pathway_channel(db, space, pathway)
        _grant_entitlement(
            db, user=payer_in, space=space, pathway=pathway,
            source=EntitlementSource.one_time_purchase,
        )
        db.commit()

        ids = accessible_user_ids_for_channel(channel, space, db)
        assert payer_in.id in ids
        assert payer_out.id not in ids
        assert can_view_channel(payer_in, channel, space, db) is True
        assert can_view_channel(payer_out, channel, space, db) is False

    def test_autocomplete_set_matches_can_view_for_included_with_offer(
        self, db, make_space, make_user,
    ):
        space = make_space()
        holder = make_user()
        non_holder = make_user()
        _member(db, holder, space)
        _member(db, non_holder, space)
        pathway = _make_pathway(db, space, access_type="included_with_offer")
        channel = _make_pathway_channel(db, space, pathway)
        opt, _req = _make_included_with_offer_bundle(db, space, pathway)
        _grant_access_pass(db, user=holder, space=space, payment_option=opt)
        db.commit()

        ids = accessible_user_ids_for_channel(channel, space, db)
        assert holder.id in ids
        assert non_holder.id not in ids
        assert can_view_channel(holder, channel, space, db) is True
        assert can_view_channel(non_holder, channel, space, db) is False

    def test_autocomplete_set_matches_can_view_for_free_pathway(
        self, db, make_space, make_user,
    ):
        space = make_space()
        member = make_user()
        non_member = make_user()
        _member(db, member, space)
        # non_member deliberately absent from Space.
        pathway = _make_pathway(db, space, access_type="free")
        channel = _make_pathway_channel(db, space, pathway)
        db.commit()

        ids = accessible_user_ids_for_channel(channel, space, db)
        assert member.id in ids
        assert non_member.id not in ids

    def test_autocomplete_excludes_revoked_even_with_enrollment(
        self, db, make_space, make_user,
    ):
        """Revocation parity: the autocomplete set must drop the
        revoked user even when their Enrollment row remains."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(db, space, access_type="one_time")
        channel = _make_pathway_channel(db, space, pathway)
        ent = _grant_entitlement(
            db, user=payer, space=space, pathway=pathway,
            source=EntitlementSource.one_time_purchase,
        )
        _make_enrollment(db, payer, pathway)
        db.commit()

        ids_before = accessible_user_ids_for_channel(channel, space, db)
        assert payer.id in ids_before

        ent.status = EntitlementStatus.revoked
        ent.revoked_at = datetime.utcnow()
        db.commit()

        ids_after = accessible_user_ids_for_channel(channel, space, db)
        assert payer.id not in ids_after


# ---------------------------------------------------------------------------
# 6. Read-through: linked-title enrichment in the API response
# ---------------------------------------------------------------------------


class TestLinkedTitleEnrichment:
    def test_member_channels_endpoint_carries_pathway_title(
        self, db, make_space, make_user,
    ):
        """``GET /api/spaces/{slug}/channels`` returns ``pathway_title``
        so the Creator Studio card + member selector can render
        'Linked to · <name>' without a sibling fetch."""
        from app.community.channels import list_member_channels

        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = _make_pathway(
            db, space, title="The EMBODY Practice", access_type="free",
        )
        _make_pathway_channel(db, space, pathway)
        db.commit()

        rows = list_member_channels(
            slug=space.slug, db=db, current_user=payer,
        )
        linked = [r for r in rows if r.channel_type == "pathway"]
        assert len(linked) == 1
        assert linked[0].pathway_title == "The EMBODY Practice"
        assert linked[0].pathway_archived is False
        assert linked[0].gathering_title is None

    def test_creator_channels_endpoint_carries_pathway_title(
        self, db, make_space, make_user,
    ):
        from app.community.channels import list_creator_channels

        space = make_space()
        owner = make_user()
        # The Space's owner is a caretaker via ``creator_id`` — no
        # SpaceMembership needed to reach ``list_creator_channels``.
        space.creator_id = owner.id
        db.flush()
        pathway = _make_pathway(
            db, space, title="The EMBODY Practice", access_type="one_time",
        )
        _make_pathway_channel(db, space, pathway)
        db.commit()

        rows = list_creator_channels(
            slug=space.slug, db=db, current_user=owner,
        )
        linked = [r for r in rows if r.channel_type == "pathway"]
        assert len(linked) == 1
        assert linked[0].pathway_title == "The EMBODY Practice"
