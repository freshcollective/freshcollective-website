"""A member leaving a Collective of their own accord.

The permissions matrix has listed "Leave a collective — Yes. Cancels
active membership." since it was written; only the creator-initiated
removal existed. These tests cover the member-facing door and, in
passing, give ``creator.routes.remove_member`` the first coverage it has
ever had — both now end a membership through
``services.membership_removal``.

The centre of it is what leaving is *not* allowed to destroy. Walking
out of a room is not consent to forfeit what you paid for on the way in,
so every paid artefact is asserted to survive: Offerings in Your
Collection, purchased Pathway entitlements, access passes, future
bookings, payment records. The creator's moderation removal keeps its
own, harsher behaviour, and that difference is pinned here too so
neither can drift onto the other.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models.access_pass import AccessPass, AccessPassStatus, AccessPassType
from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingEntitlementSource,
    OfferingEntitlementStatus,
    OfferingFulfilmentKind,
    OfferingStatus,
)
from app.models.platform import (
    BookingStatus,
    CommunityPost,
    ConversationChannel,
    EntitlementSource,
    EntitlementStatus,
    EventBooking,
    Pathway,
    PostType,
    PathwayEntitlement,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import membership_removal
from app.spaces.routes import (
    leave_collective,
    preview_leaving_collective,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def space(make_space):
    return make_space(status="active", is_public=True)


@pytest.fixture
def member(db, space, make_user):
    user = make_user()
    _join(db, space, user)
    return user


def _join(db, space, user, *, role=SpaceRole.learner, source="joined"):
    row = SpaceMembership(
        id=_uid("sm"),
        space_id=space.id,
        user_id=user.id,
        role=role,
        status=SpaceMembershipStatus.active,
        source=source,
    )
    db.add(row)
    db.flush()
    return row


def _membership(db, space, user) -> SpaceMembership | None:
    return (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == user.id,
        )
        .first()
    )


def _pathway(db, space, *, access_type="included", status="active"):
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="A Pathway",
        status=status,
        access_type=access_type,
        pathway_type=PathwayType.guided_experience,
        pricing_mode="legacy",
        currency="AUD",
    )
    db.add(p)
    db.flush()
    return p


def _entitlement(db, space, user, pathway, *, source, status=None):
    row = PathwayEntitlement(
        id=_uid("pe"),
        user_id=user.id,
        space_id=space.id,
        pathway_id=pathway.id,
        source=source,
        status=status or EntitlementStatus.active,
    )
    db.add(row)
    db.flush()
    return row


def _pass(db, space, user, *, status=AccessPassStatus.active, **kw):
    defaults = dict(
        id=_uid("ap"),
        user_id=user.id,
        space_id=space.id,
        pass_type=AccessPassType.class_pass,
        status=status,
    )
    defaults.update(kw)
    row = AccessPass(**defaults)
    db.add(row)
    db.flush()
    return row


def _offering_owned(db, space, user):
    off = Offering(
        id=_uid("off"),
        space_id=space.id,
        created_by_user_id=space.creator_id,
        slug=f"guide-{uuid.uuid4().hex[:8]}",
        title="A Gentle Guide",
        summary="Short lines for a card.",
        status=OfferingStatus.published.value,
        fulfilment_kind=OfferingFulfilmentKind.digital_download.value,
    )
    db.add(off)
    db.flush()
    ent = OfferingEntitlement(
        id=_uid("oen"),
        user_id=user.id,
        offering_id=off.id,
        space_id=space.id,
        source=OfferingEntitlementSource.one_time_purchase.value,
        status=OfferingEntitlementStatus.active.value,
    )
    db.add(ent)
    db.flush()
    return off, ent


def _channel(db, space, *, channel_type="general"):
    """A Channel every active member of the Collective can read."""
    row = ConversationChannel(
        id=_uid("ch"),
        space_id=space.id,
        name="Common Room",
        slug=f"ch-{uuid.uuid4().hex[:8]}",
        channel_type=channel_type,
        is_default=True,
        is_system=True,
    )
    db.add(row)
    db.flush()
    return row


def _booking(db, event, user, *, status=BookingStatus.confirmed):
    row = EventBooking(
        id=_uid("bk"),
        event_id=event.id,
        user_id=user.id,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def _leave(db, space, user):
    return leave_collective(space.slug, db=db, current_user=user)


def _preview(db, space, user):
    return preview_leaving_collective(space.slug, db=db, current_user=user)


# ---------------------------------------------------------------------------
# 1. A member can leave their own Collective
# ---------------------------------------------------------------------------


class TestAMemberCanLeave:

    def test_leaving_succeeds(self, db, space, member):
        result = _leave(db, space, member)
        assert result.left is True
        assert result.space_name == space.name

    def test_the_membership_is_no_longer_active(self, db, space, member):
        _leave(db, space, member)
        assert _membership(db, space, member).status == (
            SpaceMembershipStatus.removed
        )

    def test_the_row_is_kept_rather_than_deleted(self, db, space, member):
        """Soft, like the creator path — the record of having been here
        survives, which is what the retention rules assume."""
        _leave(db, space, member)
        assert _membership(db, space, member) is not None

    def test_the_account_itself_is_untouched(self, db, space, member):
        from app.models.user import User

        _leave(db, space, member)
        assert db.query(User).filter(User.id == member.id).first() is not None

    def test_leaving_twice_is_a_404_not_a_second_departure(
        self, db, space, member,
    ):
        _leave(db, space, member)
        with pytest.raises(HTTPException) as exc:
            _leave(db, space, member)
        assert exc.value.status_code == 404

    def test_the_membership_page_no_longer_lists_it(self, db, space, member):
        """Requirement 6 — the page reads ``/me/memberships``, which
        filters on ``status='active'``. Asserted through that query
        rather than the route so the test does not need an async client.
        """
        def active_slugs():
            return [
                m.space_id
                for m in db.query(SpaceMembership).filter(
                    SpaceMembership.user_id == member.id,
                    SpaceMembership.status == SpaceMembershipStatus.active,
                ).all()
            ]

        assert space.id in active_slugs()
        _leave(db, space, member)
        assert space.id not in active_slugs()


# ---------------------------------------------------------------------------
# 2. Nobody can remove anybody else through this door
# ---------------------------------------------------------------------------


class TestItCanOnlyEndYourOwnMembership:

    def test_the_endpoint_takes_no_user_id_at_all(self):
        """The authorisation model, stated as a test: there is no
        parameter through which one member could name another, so this
        cannot regress into an authorisation bug."""
        import inspect

        params = set(inspect.signature(leave_collective).parameters)
        assert params == {"slug", "db", "current_user"}
        assert "user_id" not in params

    def test_leaving_does_not_touch_another_members_row(
        self, db, space, member, make_user,
    ):
        other = make_user()
        _join(db, space, other)
        _leave(db, space, member)
        assert _membership(db, space, other).status == (
            SpaceMembershipStatus.active
        )

    def test_a_non_member_cannot_leave_on_anybody_else_s_behalf(
        self, db, space, member, make_user,
    ):
        stranger = make_user()
        with pytest.raises(HTTPException) as exc:
            _leave(db, space, stranger)
        assert exc.value.status_code == 404
        # And the real member is still a member.
        assert _membership(db, space, member).status == (
            SpaceMembershipStatus.active
        )


# ---------------------------------------------------------------------------
# 3. Caretakers do not leave through the member door
# ---------------------------------------------------------------------------


class TestCaretakersCannotLeaveThisWay:

    def test_the_owner_cannot_leave_their_own_collective(self, db, space):
        from app.models.user import User

        owner = db.query(User).filter(User.id == space.creator_id).first()
        _join(db, space, owner, role=SpaceRole.creator,
              source="creator_owner")
        with pytest.raises(HTTPException) as exc:
            _leave(db, space, owner)
        assert exc.value.status_code == 409

    def test_the_owners_membership_survives_the_attempt(self, db, space):
        from app.models.user import User

        owner = db.query(User).filter(User.id == space.creator_id).first()
        _join(db, space, owner, role=SpaceRole.creator,
              source="creator_owner")
        with pytest.raises(HTTPException):
            _leave(db, space, owner)
        assert _membership(db, space, owner).status == (
            SpaceMembershipStatus.active
        )

    def test_a_collective_creator_role_cannot_leave(
        self, db, space, make_user,
    ):
        """Role, not ownership — a co-creator on somebody else's
        Collective is still a caretaker of it."""
        co = make_user()
        _join(db, space, co, role=SpaceRole.creator)
        with pytest.raises(HTTPException) as exc:
            _leave(db, space, co)
        assert exc.value.status_code == 409

    def test_a_moderator_cannot_leave(self, db, space, make_user):
        mod = make_user()
        _join(db, space, mod, role=SpaceRole.moderator)
        with pytest.raises(HTTPException) as exc:
            _leave(db, space, mod)
        assert exc.value.status_code == 409

    def test_the_preview_says_why(self, db, space, make_user):
        mod = make_user()
        _join(db, space, mod, role=SpaceRole.moderator)
        preview = _preview(db, space, mod)
        assert preview.can_leave is False
        assert preview.blocked_reason == "caretaker_role"


# ---------------------------------------------------------------------------
# 4. Automatically-managed Collectives
# ---------------------------------------------------------------------------


class TestAutoManagedCollectives:
    """World Builders and friends.

    ``creator_eligibility`` sets an ``auto_role`` row back to ``active``
    on its next run — and it creates those rows with
    ``role=learner``, so the member-facing card would show "Member" and
    offer a Leave that silently undoes itself.
    """

    def test_leaving_is_refused(self, db, make_space, make_user):
        space = make_space(status="active", auto_grant_role="creator")
        user = make_user()
        _join(db, space, user, source="auto_role")
        with pytest.raises(HTTPException) as exc:
            _leave(db, space, user)
        assert exc.value.status_code == 409

    def test_the_preview_names_the_reason(self, db, make_space, make_user):
        space = make_space(status="active", auto_grant_role="creator")
        user = make_user()
        _join(db, space, user, source="auto_role")
        preview = _preview(db, space, user)
        assert preview.can_leave is False
        assert preview.blocked_reason == "auto_managed_collective"

    def test_the_reconciler_would_have_undone_it(
        self, db, make_space, make_user,
    ):
        """The reason for the refusal, pinned against the reconciler
        itself rather than described in a comment."""
        from app.services.creator_eligibility import (
            apply_creator_eligibility_change,
        )

        space = make_space(status="active", auto_grant_role="creator")
        user = make_user(role="creator")
        row = _join(db, space, user, source="auto_role")
        row.status = SpaceMembershipStatus.removed
        db.flush()

        apply_creator_eligibility_change(user, db)
        db.flush()
        assert _membership(db, space, user).status == (
            SpaceMembershipStatus.active
        )


# ---------------------------------------------------------------------------
# 5. Leaving one Collective does not affect another
# ---------------------------------------------------------------------------


class TestOtherCollectivesAreUnaffected:

    def test_the_other_membership_stays_active(
        self, db, space, member, make_space,
    ):
        other = make_space(status="active", is_public=True)
        _join(db, other, member)
        _leave(db, space, member)
        assert _membership(db, other, member).status == (
            SpaceMembershipStatus.active
        )

    def test_entitlements_in_the_other_collective_are_untouched(
        self, db, space, member, make_space,
    ):
        other = make_space(status="active", is_public=True)
        _join(db, other, member)
        pw = _pathway(db, other)
        ent = _entitlement(
            db, other, member, pw, source=EntitlementSource.manual_grant,
        )
        _leave(db, space, member)
        assert ent.status == EntitlementStatus.active


# ---------------------------------------------------------------------------
# 6. Pathways — membership-dependent access goes, paid access stays
# ---------------------------------------------------------------------------


class TestPathwayAccess:

    def test_a_creator_granted_entitlement_is_revoked(
        self, db, space, member,
    ):
        """``manual_grant`` is a gift tied to being here, and no money
        changed hands."""
        pw = _pathway(db, space)
        ent = _entitlement(
            db, space, member, pw, source=EntitlementSource.manual_grant,
        )
        _leave(db, space, member)
        assert ent.status == EntitlementStatus.revoked
        assert ent.revoked_at is not None

    def test_a_purchased_entitlement_survives(self, db, space, member):
        """The decision this feature turns on. Revoking it would destroy
        paid access with no refund — see the table in
        ``services.membership_removal``."""
        pw = _pathway(db, space, access_type="one_time")
        ent = _entitlement(
            db, space, member, pw,
            source=EntitlementSource.one_time_purchase,
        )
        _leave(db, space, member)
        assert ent.status == EntitlementStatus.active

    def test_a_subscription_entitlement_survives(self, db, space, member):
        pw = _pathway(db, space, access_type="subscription")
        ent = _entitlement(
            db, space, member, pw, source=EntitlementSource.subscription,
        )
        _leave(db, space, member)
        assert ent.status == EntitlementStatus.active

    def test_an_admin_entitlement_survives(self, db, space, member):
        pw = _pathway(db, space, access_type="one_time")
        ent = _entitlement(
            db, space, member, pw, source=EntitlementSource.admin,
        )
        _leave(db, space, member)
        assert ent.status == EntitlementStatus.active

    def test_included_pathway_access_needs_no_revocation(
        self, db, space, member,
    ):
        """It was never a row. ``_check_pathway_access`` reads an active
        membership for ``included``, so ending the membership closes it
        with nothing to revoke."""
        from app.spaces.routes import _check_pathway_access

        pw = _pathway(db, space, access_type="included")
        _check_pathway_access(member, pw, space, db)  # no raise, today
        _leave(db, space, member)
        with pytest.raises(HTTPException) as exc:
            _check_pathway_access(member, pw, space, db)
        assert exc.value.status_code == 403

    def test_a_purchased_pathway_is_still_openable_after_leaving(
        self, db, space, member,
    ):
        """The other half, through the real gate: ``one_time`` reads the
        entitlement and does NOT require membership."""
        from app.spaces.routes import _check_pathway_access

        pw = _pathway(db, space, access_type="one_time")
        _entitlement(
            db, space, member, pw,
            source=EntitlementSource.one_time_purchase,
        )
        _leave(db, space, member)
        _check_pathway_access(member, pw, space, db)  # no raise

    def test_step_progress_is_preserved(self, db, space, member):
        """Requirement 3 — history is not destroyed."""
        from app.models.platform import PathwayStep, StepProgress

        pw = _pathway(db, space)
        step = PathwayStep(
            id=_uid("st"), pathway_id=pw.id, slug="s1", title="Step one",
            position=0, content_type="text",
        )
        db.add(step)
        db.flush()
        prog = StepProgress(
            id=_uid("sp"), user_id=member.id, step_id=step.id,
            completed_at=datetime.utcnow(),
        )
        db.add(prog)
        db.flush()

        _leave(db, space, member)
        assert db.query(StepProgress).filter(
            StepProgress.id == prog.id,
        ).first() is not None


# ---------------------------------------------------------------------------
# 7. Community access
# ---------------------------------------------------------------------------


class TestCommunityAccess:

    def test_channel_access_is_lost(self, db, space, member):
        """Not revoked — recomputed. ``can_view_channel`` requires an
        active membership, so the single membership write closes every
        Channel at once and no previously-opened page keeps working."""
        from app.services.channel_permissions import can_view_channel

        channel = _channel(db, space)

        assert can_view_channel(member, channel, space, db) is True
        _leave(db, space, member)
        assert can_view_channel(member, channel, space, db) is False

    def test_the_area_gate_closes(self, db, space, member):
        """The doorway, through the resolver every member surface uses."""
        from app.services.space_viewer import resolve_space_viewer

        assert resolve_space_viewer(db, member, space).qualifies is True
        _leave(db, space, member)
        assert resolve_space_viewer(db, member, space).qualifies is False

    def test_historical_posts_are_preserved(self, db, space, member):
        channel = _channel(db, space)
        post = CommunityPost(
            id=_uid("cp"),
            space_id=space.id,
            channel_id=channel.id,
            author_id=member.id,
            post_type=PostType.discussion,
            body="Something I said while I was here.",
        )
        db.add(post)
        db.flush()

        _leave(db, space, member)
        assert db.query(CommunityPost).filter(
            CommunityPost.id == post.id,
        ).first() is not None


# ---------------------------------------------------------------------------
# 8. Offerings — Your Collection survives
# ---------------------------------------------------------------------------


class TestOfferingsAreKept:

    def test_a_purchased_offering_entitlement_is_untouched(
        self, db, space, member,
    ):
        _off, ent = _offering_owned(db, space, member)
        _leave(db, space, member)
        assert ent.status == OfferingEntitlementStatus.active.value

    def test_a_free_offering_is_kept_too(self, db, space, member):
        _off, ent = _offering_owned(db, space, member)
        ent.source = OfferingEntitlementSource.free.value
        db.flush()
        _leave(db, space, member)
        assert ent.status == OfferingEntitlementStatus.active.value

    def test_your_collection_still_lists_it(self, db, space, member):
        """Through the endpoint, because that is what the member sees.
        Its own docstring already promises 'Offerings from Collectives
        the member has since left'."""
        from app.spaces._offering_member_routes import get_your_collection

        _off, _ent = _offering_owned(db, space, member)
        _leave(db, space, member)
        payload = get_your_collection(db=db, current_user=member)
        assert len(payload["items"]) == 1

    def test_the_response_reports_what_was_kept(self, db, space, member):
        _offering_owned(db, space, member)
        result = _leave(db, space, member)
        assert result.offerings_retained == 1

    def test_creator_removal_also_keeps_offerings(
        self, db, space, member,
    ):
        """Pinning the existing behaviour, which was already right and
        must not be changed by the refactor."""
        _off, ent = _offering_owned(db, space, member)
        membership_removal.end_membership(
            db,
            membership=_membership(db, space, member),
            space=space,
            actor_user_id=space.creator_id,
            now=datetime.utcnow(),
            decision=membership_removal.RemovalDecision(
                kind=membership_removal.REMOVAL_BY_CREATOR,
                reason=membership_removal.REASON_INAPPROPRIATE_BEHAVIOUR,
                note="Pinning the moderation path.",
                rejoin_blocked=True,
            ),
            revoke_purchased_access=True,
            cancel_passes=True,
            cancel_future_bookings=True,
            note="moderation",
        )
        db.flush()
        assert ent.status == OfferingEntitlementStatus.active.value


# ---------------------------------------------------------------------------
# 9. Payment records, passes and bookings are preserved
# ---------------------------------------------------------------------------


class TestNothingPaidIsDestroyed:

    def test_an_active_pass_is_not_cancelled(self, db, space, member):
        ap = _pass(db, space, member)
        _leave(db, space, member)
        assert ap.status == AccessPassStatus.active

    def test_unused_credits_are_not_forfeited(self, db, space, member):
        ap = _pass(db, space, member, total_credits=10, used_credits=3)
        _leave(db, space, member)
        assert ap.status == AccessPassStatus.active
        assert ap.remaining_credits == 7

    def test_a_future_booking_is_not_cancelled(
        self, db, space, member, make_event,
    ):
        event = make_event(space=space)
        booking = _booking(db, event, member)
        _leave(db, space, member)
        assert booking.status == BookingStatus.confirmed

    def test_a_payment_transaction_is_untouched(
        self, db, space, member, make_event, make_pending_txn,
    ):
        event = make_event(space=space)
        txn, _payer = make_pending_txn(payer=member, space=space, event=event)
        before = txn.status
        _leave(db, space, member)
        assert txn.status == before

    def test_creator_removal_still_cancels_both(
        self, db, space, member, make_event,
    ):
        """The difference between the two callers, pinned from the other
        side so a future change cannot quietly make moderation lenient
        or departure destructive."""
        event = make_event(space=space)
        booking = _booking(db, event, member)
        ap = _pass(db, space, member)
        membership_removal.end_membership(
            db,
            membership=_membership(db, space, member),
            space=space,
            actor_user_id=space.creator_id,
            now=datetime.utcnow(),
            decision=membership_removal.RemovalDecision(
                kind=membership_removal.REMOVAL_BY_CREATOR,
                reason=membership_removal.REASON_INAPPROPRIATE_BEHAVIOUR,
                note="Pinning the moderation path.",
                rejoin_blocked=True,
            ),
            revoke_purchased_access=True,
            cancel_passes=True,
            cancel_future_bookings=True,
            note="moderation",
        )
        db.flush()
        assert ap.status == AccessPassStatus.cancelled
        assert booking.status == BookingStatus.cancelled

    def test_creator_removal_still_revokes_purchased_entitlements(
        self, db, space, member,
    ):
        pw = _pathway(db, space, access_type="one_time")
        ent = _entitlement(
            db, space, member, pw,
            source=EntitlementSource.one_time_purchase,
        )
        membership_removal.end_membership(
            db,
            membership=_membership(db, space, member),
            space=space,
            actor_user_id=space.creator_id,
            now=datetime.utcnow(),
            decision=membership_removal.RemovalDecision(
                kind=membership_removal.REMOVAL_BY_CREATOR,
                reason=membership_removal.REASON_INAPPROPRIATE_BEHAVIOUR,
                note="Pinning the moderation path.",
                rejoin_blocked=True,
            ),
            revoke_purchased_access=True,
            cancel_passes=True,
            cancel_future_bookings=True,
            note="moderation",
        )
        db.flush()
        assert ent.status == EntitlementStatus.revoked

    def test_past_bookings_are_left_alone_by_both(
        self, db, space, member, make_event,
    ):
        past = make_event(
            space=space,
            starts_at=datetime.utcnow() - timedelta(days=3),
            ends_at=datetime.utcnow() - timedelta(days=3) + timedelta(hours=1),
        )
        booking = _booking(db, past, member)
        _leave(db, space, member)
        assert booking.status == BookingStatus.confirmed


# ---------------------------------------------------------------------------
# 9b. What a departed member can actually DO with a preserved booking
# ---------------------------------------------------------------------------


class TestAPreservedBookingAfterLeaving:
    """A reservation the member paid for stays reachable.

    Preserving the row was the approved decision; reaching it needed the
    per-reservation exception in ``spaces.retained_reservations``,
    because ``AREA_GATHERINGS`` defaults to ``POLICY_MEMBERS`` and the
    Gathering page used to 404 at the holder.

    The exception is scoped to one booking and one Gathering. These
    tests pin both halves: the paid reservation opens, and nothing else
    does.
    """

    def _events(self, db, space, user):
        from app.spaces.routes import list_events
        return list_events(space.slug, db=db, current_user=user)

    def _event_detail(self, db, space, event, user):
        from app.spaces.routes import get_event
        return get_event(space.slug, event.id, db=db, current_user=user)

    def _ics(self, db, space, event, user):
        from app.spaces.routes import download_ics
        return download_ics(space.slug, event.id, db=db, current_user=user)

    def test_the_booking_row_survives(self, db, space, member, make_event):
        event = make_event(space=space)
        booking = _booking(db, event, member)
        _leave(db, space, member)
        assert booking.status == BookingStatus.confirmed
        assert booking.cancelled_at is None

    # -- the Gathering they paid for ------------------------------------

    def test_a_paid_gathering_page_still_opens(
        self, db, space, member, make_event,
    ):
        """``make_event`` defaults to ``paid_separately``, so a
        confirmed booking on it is a bought ticket."""
        event = make_event(space=space)
        _booking(db, event, member)
        _leave(db, space, member)
        detail = self._event_detail(db, space, event, member)
        assert detail["id"] == event.id

    def test_the_joining_details_are_shown(
        self, db, space, member, make_event,
    ):
        """What they need in order to attend. The attendee gate
        (``show_sensitive``) already existed and already keyed on a
        confirmed booking — it just could not be reached."""
        event = make_event(
            space=space,
            location_url="https://zoom.example/abc",
            venue_address="1 Example St, Richmond VIC",
            access_instructions="Side door, ring the bell.",
        )
        _booking(db, event, member)
        _leave(db, space, member)
        detail = self._event_detail(db, space, event, member)
        assert detail["location_url"] == "https://zoom.example/abc"
        assert detail["venue_address"] == "1 Example St, Richmond VIC"
        assert detail["access_instructions"] == "Side door, ring the bell."

    def test_the_calendar_file_still_downloads(
        self, db, space, member, make_event,
    ):
        event = make_event(space=space, is_public=False)
        _booking(db, event, member)
        _leave(db, space, member)
        res = self._ics(db, space, event, member)
        assert res.status_code == 200

    def test_a_pass_funded_reservation_also_opens(
        self, db, space, member, make_event,
    ):
        """The other purchased shape: a session reserved against a term
        or class pass they bought. ``access_pass_id`` is the evidence,
        and the pass itself survives departure untouched."""
        ap = _pass(db, space, member, total_credits=10, used_credits=1)
        event = make_event(
            space=space, booking_access_type="included_with_collective",
            is_public=False,
        )
        booking = _booking(db, event, member)
        booking.access_pass_id = ap.id
        db.flush()
        _leave(db, space, member)
        assert self._event_detail(db, space, event, member)["id"] == event.id

    def test_cancelling_still_works(self, db, space, member, make_event):
        from app.spaces.routes import cancel_booking

        event = make_event(space=space)
        _booking(db, event, member)
        _leave(db, space, member)
        result = cancel_booking(
            space.slug, event.id, db=db, current_user=member,
        )
        assert result.status == "cancelled"

    def test_the_page_reports_that_it_can_be_cancelled(
        self, db, space, member, make_event,
    ):
        event = make_event(space=space)
        _booking(db, event, member)
        _leave(db, space, member)
        detail = self._event_detail(db, space, event, member)
        assert detail["can_cancel_booking"] is True

    # -- and nothing else ------------------------------------------------

    def test_the_gatherings_list_stays_closed(
        self, db, space, member, make_event,
    ):
        """The exception is per-reservation. It must not open the
        doorway, or a former member sees the whole programme."""
        event = make_event(space=space)
        _booking(db, event, member)
        _leave(db, space, member)
        with pytest.raises(HTTPException) as exc:
            self._events(db, space, member)
        assert exc.value.status_code == 404

    def test_another_gathering_in_the_same_collective_stays_closed(
        self, db, space, member, make_event,
    ):
        """Holding a ticket to one Gathering reveals one Gathering."""
        mine = make_event(space=space)
        other = make_event(space=space, is_public=False)
        _booking(db, mine, member)
        _leave(db, space, member)
        assert self._event_detail(db, space, mine, member)["id"] == mine.id
        with pytest.raises(HTTPException) as exc:
            self._event_detail(db, space, other, member)
        assert exc.value.status_code == 404

    def test_somebody_else_s_reservation_opens_nothing(
        self, db, space, member, make_user, make_event,
    ):
        """Holder-scoped at the query, so there is no shape of the call
        that returns another person's place."""
        stranger = make_user()
        event = make_event(space=space, is_public=False)
        _booking(db, event, member)
        with pytest.raises(HTTPException) as exc:
            self._event_detail(db, space, event, stranger)
        assert exc.value.status_code == 404

    def test_a_free_members_only_booking_is_not_covered(
        self, db, space, member, make_event,
    ):
        """Membership-derived, not purchased — so it goes with
        membership. The boundary the exception exists to respect."""
        event = make_event(
            space=space, booking_access_type="included_with_collective",
            is_public=False,
        )
        _booking(db, event, member)
        _leave(db, space, member)
        with pytest.raises(HTTPException) as exc:
            self._event_detail(db, space, event, member)
        assert exc.value.status_code == 404

    def test_a_cancelled_booking_opens_nothing(
        self, db, space, member, make_event,
    ):
        event = make_event(space=space, is_public=False)
        _booking(db, event, member, status=BookingStatus.cancelled)
        _leave(db, space, member)
        with pytest.raises(HTTPException) as exc:
            self._event_detail(db, space, event, member)
        assert exc.value.status_code == 404

    def test_a_pending_payment_hold_opens_nothing(
        self, db, space, member, make_event,
    ):
        """A hold is not a purchase — it is somebody part-way through
        Stripe Checkout, and it never grants access."""
        event = make_event(space=space, is_public=False)
        _booking(
            db, event, member, status=BookingStatus.pending_payment,
        )
        _leave(db, space, member)
        with pytest.raises(HTTPException) as exc:
            self._event_detail(db, space, event, member)
        assert exc.value.status_code == 404

    def test_pathways_stay_closed(self, db, space, member, make_event):
        """The exception touches Gatherings only."""
        from app.spaces.routes import list_steps

        event = make_event(space=space)
        _booking(db, event, member)
        pw = _pathway(db, space, access_type="included")
        _leave(db, space, member)
        with pytest.raises(HTTPException):
            list_steps(space.slug, pw.slug, db=db, current_user=member)

    def test_community_stays_closed(self, db, space, member, make_event):
        from app.services.channel_permissions import can_view_channel

        channel = _channel(db, space)
        event = make_event(space=space)
        _booking(db, event, member)
        _leave(db, space, member)
        assert can_view_channel(member, channel, space, db) is False

    def test_the_area_resolver_is_untouched(
        self, db, space, member, make_event,
    ):
        """Stated against the resolver itself: the fix is at three call
        sites, not in the rule every Collective shares."""
        import inspect

        from app.spaces import area_access
        from app.services.space_viewer import resolve_space_viewer

        event = make_event(space=space)
        _booking(db, event, member)
        _leave(db, space, member)
        assert resolve_space_viewer(db, member, space).qualifies is False
        access = area_access.resolve_area_access(db, space, member)
        assert "gatherings" not in access.reachable
        src = inspect.getsource(area_access)
        assert "retained_reservations" not in src
        assert "EventBooking" not in src

    # -- no new bookings through the exception ---------------------------

    def test_booking_again_is_refused(self, db, space, member, make_event):
        """``book_event`` is deliberately not a caller of the
        exception, so the turnstile is unaffected."""
        from app.spaces.routes import book_event

        event = make_event(space=space)
        _booking(db, event, member)
        _leave(db, space, member)
        with pytest.raises(HTTPException):
            book_event(
                space.slug, event.id, db=db, current_user=member,
                background_tasks=None,
            )

    def test_the_page_does_not_advertise_a_booking_button(
        self, db, space, member, make_event,
    ):
        """It would 404 on click. Reported honestly instead."""
        event = make_event(space=space)
        _booking(db, event, member)
        _leave(db, space, member)
        assert self._event_detail(db, space, event, member)["can_book"] is False

    def test_book_event_does_not_consult_the_exception(self):
        import inspect

        from app.spaces.routes import book_event

        assert "retained_reservations" not in inspect.getsource(book_event)

    # -- finding it again ------------------------------------------------

    def test_the_reservation_is_listed_for_the_holder(
        self, db, space, member, make_event,
    ):
        from app.spaces.routes import list_retained_reservations

        event = make_event(space=space)
        _booking(db, event, member)
        _leave(db, space, member)
        rows = list_retained_reservations(db=db, current_user=member)
        assert [r.event_id for r in rows] == [event.id]
        assert rows[0].space_slug == space.slug

    def test_a_current_member_sees_an_empty_list(
        self, db, space, member, make_event,
    ):
        """They find their Gatherings in the Collective's own tab;
        a second competing surface would be worse, not better."""
        from app.spaces.routes import list_retained_reservations

        event = make_event(space=space)
        _booking(db, event, member)
        assert list_retained_reservations(db=db, current_user=member) == []

    def test_a_membership_derived_booking_is_not_listed(
        self, db, space, member, make_event,
    ):
        from app.spaces.routes import list_retained_reservations

        event = make_event(
            space=space, booking_access_type="included_with_collective",
        )
        _booking(db, event, member)
        _leave(db, space, member)
        assert list_retained_reservations(db=db, current_user=member) == []

    def test_past_gatherings_are_not_listed(
        self, db, space, member, make_event,
    ):
        from app.spaces.routes import list_retained_reservations

        past = make_event(
            space=space,
            starts_at=datetime.utcnow() - timedelta(days=2),
            ends_at=datetime.utcnow() - timedelta(days=2) + timedelta(hours=1),
        )
        _booking(db, past, member)
        _leave(db, space, member)
        assert list_retained_reservations(db=db, current_user=member) == []

    def test_a_cancelled_gathering_is_not_listed(
        self, db, space, member, make_event,
    ):
        """Nothing to turn up to. The booking row stays; the listing
        does not send them anywhere."""
        from app.spaces.routes import list_retained_reservations

        event = make_event(space=space, status="cancelled")
        _booking(db, event, member)
        _leave(db, space, member)
        assert list_retained_reservations(db=db, current_user=member) == []

    def test_the_listing_names_no_user(self):
        import inspect

        from app.spaces.routes import list_retained_reservations

        params = set(
            inspect.signature(list_retained_reservations).parameters,
        )
        assert params == {"db", "current_user"}

    def test_the_preview_separates_paid_from_included_bookings(
        self, db, space, member, make_event,
    ):
        """So the dialog can say which ones survive."""
        paid = make_event(space=space)
        included = make_event(
            space=space, booking_access_type="included_with_collective",
        )
        _booking(db, paid, member)
        _booking(db, included, member)
        preview = _preview(db, space, member)
        assert preview.future_bookings == 2
        assert preview.purchased_future_bookings == 1


# ---------------------------------------------------------------------------
# 9c. Purchased Pathway content after leaving
# ---------------------------------------------------------------------------


class TestPurchasedPathwayContentAfterLeaving:
    """Requirement 4, verified through the endpoints a member uses
    rather than through the predicate alone.

    ``AREA_PATHWAYS`` defaults to ``POLICY_PUBLIC``, and the content
    endpoints carry no area gate of their own — they gate on
    ``_check_pathway_access``, which reads the entitlement and does not
    ask about membership for ``one_time``. So a purchased Pathway stays
    genuinely usable, not merely un-revoked.
    """

    def test_the_overview_still_loads(self, db, space, member):
        from app.spaces.routes import get_pathway_overview

        pw = _pathway(db, space, access_type="one_time")
        _entitlement(
            db, space, member, pw,
            source=EntitlementSource.one_time_purchase,
        )
        _leave(db, space, member)
        got = get_pathway_overview(
            space.slug, pw.slug, db=db, current_user=member,
        )
        assert got.slug == pw.slug
        assert got.user_has_access is True

    def test_the_steps_still_load(self, db, space, member):
        from app.models.platform import PathwayStep
        from app.spaces.routes import list_steps

        pw = _pathway(db, space, access_type="one_time")
        db.add(PathwayStep(
            id=_uid("st"), pathway_id=pw.id, slug="s1", title="Step one",
            position=0, content_type="text",
        ))
        _entitlement(
            db, space, member, pw,
            source=EntitlementSource.one_time_purchase,
        )
        db.flush()
        _leave(db, space, member)
        steps = list_steps(space.slug, pw.slug, db=db, current_user=member)
        assert len(steps) == 1

    def test_an_included_pathway_does_not_load(self, db, space, member):
        """The other side, unchanged: membership-derived access goes."""
        from app.spaces.routes import list_steps

        pw = _pathway(db, space, access_type="included")
        _leave(db, space, member)
        with pytest.raises(HTTPException) as exc:
            list_steps(space.slug, pw.slug, db=db, current_user=member)
        assert exc.value.status_code == 403

    def test_no_entitlement_was_invented(self, db, space, member):
        """Requirement 4's other half — nothing is silently widened.
        A Pathway they never bought stays shut."""
        from app.spaces.routes import list_steps

        pw = _pathway(db, space, access_type="one_time")
        _leave(db, space, member)
        with pytest.raises(HTTPException) as exc:
            list_steps(space.slug, pw.slug, db=db, current_user=member)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 10. A live payment plan blocks departure
# ---------------------------------------------------------------------------


class TestALivePaymentPlanBlocksLeaving:
    """The conflict this feature refuses to resolve on its own.

    Revoking access while Stripe keeps charging is the one outcome
    nobody chose, and cancelling the schedule is a payment change that
    needs a person's approval. So the endpoint stops.
    """

    def _plan(self, db, space, member, status="active"):
        """A real finite instalment plan — the Payment Option and its
        schedule included, because ``purchase_plans`` has foreign keys
        to both and a fake id proves nothing about the guard."""
        from app.models.payment_option import (
            PaymentOption,
            PaymentOptionStatus,
            PaymentOptionType,
        )
        from app.models.payment_option_schedule import PaymentOptionSchedule
        from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus

        pw = _pathway(db, space, access_type="one_time")
        opt = PaymentOption(
            id=_uid("po"), space_id=space.id, pathway_id=pw.id,
            attaches_to_kind="pathway", attaches_to_id=pw.id,
            name="Four weekly payments",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=10000, currency="AUD",
        )
        db.add(opt)
        db.flush()
        sched = PaymentOptionSchedule(
            id=_uid("sched"), payment_option_id=opt.id,
            name="Weekly x 4", schedule_type="recurring_installments",
            status="published",
            installment_amount_cents=2500, installment_count=4,
            stripe_interval="week", stripe_interval_count=1,
            total_amount_cents=10000, currency="AUD",
        )
        db.add(sched)
        db.flush()
        now = datetime.utcnow()
        plan = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=member.id,
            payment_option_id=opt.id,
            payment_option_schedule_id=sched.id,
            space_id=space.id,
            status=PurchasePlanStatus(status),
            currency="AUD",
            installment_amount_cents=2500,
            installments_expected=4, installments_paid=1,
            total_expected_cents=10000,
            stripe_interval="week", stripe_interval_count=1,
            stripe_mode="test",
            snapshot_grants_json={
                "version": 1, "entitlements": [], "access_passes": [],
                "bookings": [],
            },
            created_at=now, updated_at=now,
        )
        db.add(plan)
        db.flush()
        return plan

    @pytest.mark.parametrize(
        "status",
        membership_removal.LIVE_PLAN_STATUSES,
    )
    def test_every_live_status_blocks(self, db, space, member, status):
        self._plan(db, space, member, status=status)
        with pytest.raises(HTTPException) as exc:
            _leave(db, space, member)
        assert exc.value.status_code == 409

    def test_the_membership_survives_the_refusal(self, db, space, member):
        self._plan(db, space, member)
        with pytest.raises(HTTPException):
            _leave(db, space, member)
        assert _membership(db, space, member).status == (
            SpaceMembershipStatus.active
        )

    def test_the_refusal_points_at_the_creator(self, db, space, member):
        self._plan(db, space, member)
        with pytest.raises(HTTPException) as exc:
            _leave(db, space, member)
        assert "creator" in exc.value.detail.lower()

    @pytest.mark.parametrize(
        "status", ["completed", "cancelled", "failed"],
    )
    def test_a_settled_plan_does_not_block(
        self, db, space, member, status,
    ):
        """Otherwise anybody who ever paid by instalments would be
        locked in for good."""
        self._plan(db, space, member, status=status)
        assert _leave(db, space, member).left is True

    def test_a_plan_in_another_collective_does_not_block(
        self, db, space, member, make_space,
    ):
        other = make_space(status="active")
        _join(db, other, member)
        self._plan(db, other, member)
        assert _leave(db, space, member).left is True

    def test_another_members_plan_does_not_block(
        self, db, space, member, make_user,
    ):
        other = make_user()
        _join(db, space, other)
        self._plan(db, space, other)
        assert _leave(db, space, member).left is True

    def test_the_preview_names_the_reason_and_the_count(
        self, db, space, member,
    ):
        self._plan(db, space, member)
        preview = _preview(db, space, member)
        assert preview.can_leave is False
        assert preview.blocked_reason == "live_payment_plan"
        assert preview.live_payment_plans == 1

    def test_no_stripe_call_is_made(self, db, space, member):
        """Stated as a source contract. The service must not reach the
        provider at all — not to cancel, not to refund."""
        import inspect
        import re

        src = inspect.getsource(membership_removal)
        # Comment- and docstring-stripped. The module explains at length
        # why it never calls Stripe, so a raw search matches the
        # explanation and passes vacuously — or, as here, fails on it.
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert "stripe" not in code.lower(), (
            "membership_removal must not reach the payment provider"
        )


# ---------------------------------------------------------------------------
# 11. The departure preview
# ---------------------------------------------------------------------------


class TestTheDeparturePreview:

    def test_a_plain_member_may_leave(self, db, space, member):
        preview = _preview(db, space, member)
        assert preview.can_leave is True
        assert preview.blocked_reason is None

    def test_it_counts_what_is_at_stake(
        self, db, space, member, make_event,
    ):
        _pass(db, space, member, total_credits=8, used_credits=2)
        event = make_event(space=space)
        _booking(db, event, member)
        _offering_owned(db, space, member)
        pw = _pathway(db, space, access_type="one_time")
        _entitlement(
            db, space, member, pw,
            source=EntitlementSource.one_time_purchase,
        )

        preview = _preview(db, space, member)
        assert preview.active_passes == 1
        assert preview.unused_credits == 6
        assert preview.future_bookings == 1
        assert preview.offerings_retained == 1
        assert preview.purchased_pathways == 1

    def test_membership_gated_paid_pathways_are_surfaced(
        self, db, space, member,
    ):
        """``included_with_offer`` is paid for but gated on membership,
        so leaving closes it. The dialog has to say so."""
        _pass(db, space, member)
        _pathway(db, space, access_type="included_with_offer")
        _pathway(db, space, access_type="included_with_offer")
        preview = _preview(db, space, member)
        assert preview.membership_gated_paid_pathways == 2

    def test_none_are_reported_without_a_pass_to_unlock_them(
        self, db, space, member,
    ):
        _pathway(db, space, access_type="included_with_offer")
        preview = _preview(db, space, member)
        assert preview.membership_gated_paid_pathways == 0

    def test_a_non_member_gets_an_answer_not_a_404(
        self, db, space, make_user,
    ):
        """The Membership page may render a stale card; the preview says
        so rather than erroring."""
        stranger = make_user()
        preview = _preview(db, space, stranger)
        assert preview.can_leave is False
        assert preview.blocked_reason == "not_a_member"

    def test_the_preview_changes_nothing(self, db, space, member):
        _preview(db, space, member)
        assert _membership(db, space, member).status == (
            SpaceMembershipStatus.active
        )


# ---------------------------------------------------------------------------
# 12. Rejoining — removal provenance decides who may come back
# ---------------------------------------------------------------------------


def _press_join(db, space, user):
    """The member pressing Join — distinct from the ``_join`` factory
    above, which fabricates a membership row directly."""
    from app.spaces.routes import join_space
    return join_space(space.slug, db=db, current_user=user,
                      background_tasks=None)


def _accept_invite(db, space, user):
    """Create and consume an invitation for this person."""
    import uuid as _uuid

    from app.models.platform import SpaceInvitation, SpaceRole as _Role
    from app.spaces.routes import accept_invite

    token = str(_uuid.uuid4())
    db.add(SpaceInvitation(
        id=_uid("inv"), space_id=space.id, email=user.email.lower(),
        name=user.name or user.email, role=_Role.learner,
        invited_by_id=space.creator_id, token=token,
        sent_at=datetime.utcnow(),
    ))
    db.flush()
    return accept_invite(
        token, db=db, current_user=user, background_tasks=None,
    )


def _removal(db, space, user) -> tuple[str | None, object, object]:
    row = _membership(db, space, user)
    return row.removal_kind, row.removed_at, row.removed_by_user_id


class TestDepartureRecordsItself:
    """Migration 166. ``source`` says how a membership began; these
    columns say how it ended, which is the question that decides
    whether somebody may return."""

    def test_a_voluntary_departure_is_recorded_as_such(
        self, db, space, member,
    ):
        _leave(db, space, member)
        kind, at, by = _removal(db, space, member)
        assert kind == membership_removal.REMOVAL_VOLUNTARY
        assert at is not None
        assert by == member.id

    def test_a_creator_removal_is_recorded_as_such(
        self, db, space, member,
    ):
        membership_removal.end_membership(
            db,
            membership=_membership(db, space, member),
            space=space,
            actor_user_id=space.creator_id,
            now=datetime.utcnow(),
            decision=membership_removal.RemovalDecision(
                kind=membership_removal.REMOVAL_BY_CREATOR,
                reason=membership_removal.REASON_INAPPROPRIATE_BEHAVIOUR,
                note="Pinning the moderation path.",
                rejoin_blocked=True,
            ),
            revoke_purchased_access=True,
            cancel_passes=True,
            cancel_future_bookings=True,
            note="moderation",
        )
        db.flush()
        kind, _at, by = _removal(db, space, member)
        assert kind == membership_removal.REMOVAL_BY_CREATOR
        assert by == space.creator_id

    def test_the_creator_endpoint_stamps_it(self):
        import inspect

        from app.creator import routes as creator_routes

        src = inspect.getsource(creator_routes.remove_member_with_reason)
        assert "REMOVAL_BY_CREATOR" in src

    def test_the_member_endpoint_stamps_it(self):
        import inspect

        src = inspect.getsource(leave_collective)
        assert "REMOVAL_VOLUNTARY" in src

    def test_the_decision_is_required_not_defaulted(self, db, space, member):
        """No default, because either choice would make a forgetful
        caller silently wrong in one direction or the other."""
        import inspect

        sig = inspect.signature(membership_removal.end_membership)
        assert sig.parameters["decision"].default is inspect.Parameter.empty

    def test_an_unknown_kind_is_refused(self, db, space, member):
        with pytest.raises(membership_removal.RemovalDecisionError):
            membership_removal.RemovalDecision(kind="because_i_said_so")

    def test_an_unknown_reason_is_refused(self):
        with pytest.raises(membership_removal.RemovalDecisionError):
            membership_removal.RemovalDecision(
                kind=membership_removal.REMOVAL_BY_CREATOR,
                reason="vibes",
            )

    def test_the_database_refuses_one_too(self, db, space, member):
        """Belt to the braces — a path that bypasses the service still
        cannot invent a value ``may_rejoin`` has never heard of."""
        from sqlalchemy.exc import IntegrityError

        row = _membership(db, space, member)
        row.status = SpaceMembershipStatus.removed
        row.removal_kind = "something_new"
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestAVoluntaryDeparterMayRejoin:

    def test_pressing_join_rejoins_them(self, db, space, member):
        """The bug this release fixes. This used to return
        ``already_member: true`` and join nobody."""
        _leave(db, space, member)
        result = _press_join(db, space, member)
        assert result["joined"] is True
        assert result.get("rejoined") is True
        assert _membership(db, space, member).status == (
            SpaceMembershipStatus.active
        )

    def test_the_departure_provenance_is_cleared(self, db, space, member):
        _leave(db, space, member)
        _press_join(db, space, member)
        kind, at, by = _removal(db, space, member)
        assert (kind, at, by) == (None, None, None)

    def test_the_original_row_is_reused_not_duplicated(
        self, db, space, member,
    ):
        """``space_memberships_user_space_unique`` spans every status,
        so a second row is not merely untidy — it cannot exist."""
        before = _membership(db, space, member).id
        _leave(db, space, member)
        _press_join(db, space, member)
        rows = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.user_id == member.id,
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == before

    def test_joined_at_is_not_restamped(self, db, space, member):
        """It records when the relationship began, which has not
        changed."""
        original = _membership(db, space, member).joined_at
        _leave(db, space, member)
        _press_join(db, space, member)
        assert _membership(db, space, member).joined_at == original

    def test_the_original_source_is_preserved(self, db, space, member):
        _leave(db, space, member)
        _press_join(db, space, member)
        assert _membership(db, space, member).source == "joined"

    def test_they_can_leave_again(self, db, space, member):
        _leave(db, space, member)
        _press_join(db, space, member)
        assert _leave(db, space, member).left is True

    def test_rejoining_restores_community_access(self, db, space, member):
        from app.services.channel_permissions import can_view_channel

        channel = _channel(db, space)
        _leave(db, space, member)
        assert can_view_channel(member, channel, space, db) is False
        _press_join(db, space, member)
        assert can_view_channel(member, channel, space, db) is True


class TestRejoiningRestoresNothingElse:
    """Membership only. Reviving what was revoked on the way out would
    hand back paid access nobody paid for twice."""

    def test_a_revoked_granted_entitlement_stays_revoked(
        self, db, space, member,
    ):
        pw = _pathway(db, space)
        ent = _entitlement(
            db, space, member, pw, source=EntitlementSource.manual_grant,
        )
        _leave(db, space, member)
        assert ent.status == EntitlementStatus.revoked
        _press_join(db, space, member)
        assert ent.status == EntitlementStatus.revoked

    def test_a_creator_cancelled_pass_stays_cancelled(
        self, db, space, member,
    ):
        ap = _pass(db, space, member)
        membership_removal.end_membership(
            db,
            membership=_membership(db, space, member),
            space=space,
            actor_user_id=space.creator_id,
            now=datetime.utcnow(),
            decision=membership_removal.RemovalDecision(
                kind=membership_removal.REMOVAL_BY_CREATOR,
                reason=membership_removal.REASON_INAPPROPRIATE_BEHAVIOUR,
                note="Pinning the moderation path.",
                rejoin_blocked=True,
            ),
            revoke_purchased_access=True,
            cancel_passes=True,
            cancel_future_bookings=True,
            note="moderation",
        )
        db.flush()
        assert ap.status == AccessPassStatus.cancelled
        # Re-added by the creator — the pass does not come back with
        # them. The block has to be lifted first; reactivating a blocked
        # membership is refused.
        from app.services import membership_grant

        row = _membership(db, space, member)
        with pytest.raises(ValueError):
            membership_grant.reactivate(db, row, now=datetime.utcnow())
        membership_removal.lift_restriction(
            db, membership=row, actor_user_id=space.creator_id,
            note="Lifted on appeal.", now=datetime.utcnow(),
        )
        membership_grant.reactivate(db, row, now=datetime.utcnow())
        db.flush()
        assert ap.status == AccessPassStatus.cancelled

    def test_a_cancelled_booking_stays_cancelled(
        self, db, space, member, make_event,
    ):
        """Resurrecting one would re-seat somebody at a Gathering that
        may already have happened."""
        from app.services import membership_grant

        event = make_event(space=space)
        booking = _booking(db, event, member)
        membership_removal.end_membership(
            db,
            membership=_membership(db, space, member),
            space=space,
            actor_user_id=space.creator_id,
            now=datetime.utcnow(),
            decision=membership_removal.RemovalDecision(
                kind=membership_removal.REMOVAL_BY_CREATOR,
                reason=membership_removal.REASON_INAPPROPRIATE_BEHAVIOUR,
                note="Pinning the moderation path.",
                rejoin_blocked=True,
            ),
            revoke_purchased_access=True,
            cancel_passes=True,
            cancel_future_bookings=True,
            note="moderation",
        )
        db.flush()
        assert booking.status == BookingStatus.cancelled
        row = _membership(db, space, member)
        membership_removal.lift_restriction(
            db, membership=row, actor_user_id=space.creator_id,
            note="Lifted on appeal.", now=datetime.utcnow(),
        )
        membership_grant.reactivate(db, row, now=datetime.utcnow())
        db.flush()
        assert booking.status == BookingStatus.cancelled

    def test_preserved_paid_access_is_simply_still_there(
        self, db, space, member,
    ):
        """The other side: a voluntary departure revoked nothing paid,
        so rejoining has nothing to restore and the entitlement was
        never interrupted."""
        pw = _pathway(db, space, access_type="one_time")
        ent = _entitlement(
            db, space, member, pw,
            source=EntitlementSource.one_time_purchase,
        )
        _leave(db, space, member)
        _press_join(db, space, member)
        assert ent.status == EntitlementStatus.active

    def test_rejoining_charges_nothing(self, db, space, member):
        """An open Collective's Join is free, and rejoining uses the
        same door — no PurchaseIntent, no transaction."""
        from app.models.payment import PaymentTransaction

        _leave(db, space, member)
        before = db.query(PaymentTransaction).filter(
            PaymentTransaction.payer_user_id == member.id,
        ).count()
        _press_join(db, space, member)
        after = db.query(PaymentTransaction).filter(
            PaymentTransaction.payer_user_id == member.id,
        ).count()
        assert after == before


def _ordinary_creator_removal(db, space, member, *, reason=None):
    """A creator removal with no block — the common case.

    Administrative tidying: the person may come back through the
    ordinary Join flow. This is the behaviour the reason/ban separation
    exists to make possible.
    """
    membership_removal.end_membership(
        db,
        membership=_membership(db, space, member),
        space=space,
        actor_user_id=space.creator_id,
        now=datetime.utcnow(),
        decision=membership_removal.RemovalDecision(
            kind=membership_removal.REMOVAL_BY_CREATOR,
            reason=reason or membership_removal.REASON_NO_LONGER_REQUIRED,
        ),
        revoke_purchased_access=True,
        cancel_passes=True,
        cancel_future_bookings=True,
        note="ordinary removal",
    )
    db.flush()


class TestAnOrdinaryCreatorRemovalPermitsReturn:
    """Creator removal is not automatically a ban.

    This is the behaviour change the reason/decision split buys: most
    removals are a creator helping somebody leave or tidying up, and
    those people may come back. Only an explicit ``rejoin_blocked``
    stops them.
    """

    def test_they_may_rejoin(self, db, space, member):
        from app.services import membership_grant

        _ordinary_creator_removal(db, space, member)
        assert membership_grant.may_rejoin(
            _membership(db, space, member),
        ) is True

    def test_pressing_join_lets_them_back(self, db, space, member):
        _ordinary_creator_removal(db, space, member)
        result = _press_join(db, space, member)
        assert result.get("rejoined") is True
        assert _membership(db, space, member).status == (
            SpaceMembershipStatus.active
        )

    def test_a_purchase_lets_them_back(self, db, space, member):
        from app.services import membership_grant

        _ordinary_creator_removal(db, space, member)
        outcome = membership_grant.ensure_membership_for_purchase(
            db, user_id=member.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.reactivated is True

    def test_an_invitation_lets_them_back(self, db, space, member):
        _ordinary_creator_removal(db, space, member)
        assert _accept_invite(db, space, member)["accepted"] is True
        assert _membership(db, space, member).status == (
            SpaceMembershipStatus.active
        )

    def test_the_reason_is_recorded_without_implying_a_ban(
        self, db, space, member,
    ):
        """Even the reasons that sound punitive. A creator may record
        "Inappropriate behaviour" and still let somebody return — the
        ban is the separate decision."""
        _ordinary_creator_removal(
            db, space, member,
            reason=membership_removal.REASON_INAPPROPRIATE_BEHAVIOUR,
        )
        row = _membership(db, space, member)
        assert row.removal_reason == "inappropriate_behaviour"
        assert row.rejoin_blocked is False

        from app.services import membership_grant

        assert membership_grant.may_rejoin(row) is True

    def test_purchases_are_not_blocked(self, db, space, member):
        """Rule F applies to bans only."""
        from app.services.checkout_orchestration import (
            check_not_banned_or_raise,
        )

        _ordinary_creator_removal(db, space, member)
        assert check_not_banned_or_raise(
            db, user=member, space=space,
        ) is None

    def test_no_restriction_event_is_written(self, db, space, member):
        from app.models.platform import MembershipRestrictionEvent

        _ordinary_creator_removal(db, space, member)
        assert db.query(MembershipRestrictionEvent).filter(
            MembershipRestrictionEvent.user_id == member.id,
        ).count() == 0


class TestCreatorRemovalCannotBeUndoneByTheMember:
    """A **banned** removal, which is the one the member cannot reverse.

    An ordinary creator removal now lets the person back — see
    ``TestAnOrdinaryCreatorRemovalPermitsReturn``. What makes a removal
    irreversible by the member is ``rejoin_blocked``, set explicitly by
    the owner, not the fact that a creator did it.
    """

    def _creator_removes(self, db, space, member):
        membership_removal.end_membership(
            db,
            membership=_membership(db, space, member),
            space=space,
            actor_user_id=space.creator_id,
            now=datetime.utcnow(),
            decision=membership_removal.RemovalDecision(
                kind=membership_removal.REMOVAL_BY_CREATOR,
                reason=membership_removal.REASON_INAPPROPRIATE_BEHAVIOUR,
                note="Repeated abuse in the Common Room.",
                rejoin_blocked=True,
            ),
            revoke_purchased_access=True,
            cancel_passes=True,
            cancel_future_bookings=True,
            note="moderation",
        )
        db.flush()

    def test_pressing_join_is_refused(self, db, space, member):
        self._creator_removes(db, space, member)
        with pytest.raises(HTTPException) as exc:
            _press_join(db, space, member)
        assert exc.value.status_code == 409

    def test_the_refusal_does_not_disclose_the_moderation(
        self, db, space, member,
    ):
        """A join button must not tell somebody a creator removed them —
        and it says the same thing for a paused membership, so the
        message itself reveals nothing."""
        self._creator_removes(db, space, member)
        with pytest.raises(HTTPException) as exc:
            _press_join(db, space, member)
        detail = exc.value.detail.lower()
        assert "removed" not in detail
        assert "creator" in detail

    def test_they_stay_removed(self, db, space, member):
        self._creator_removes(db, space, member)
        with pytest.raises(HTTPException):
            _press_join(db, space, member)
        assert _membership(db, space, member).status == (
            SpaceMembershipStatus.removed
        )

    def test_a_purchase_cannot_buy_them_back_in(self, db, space, member):
        """The gap ``membership_grant``'s docstring used to name: a card
        being charged is not consent to overturn moderation."""
        from app.services import membership_grant

        self._creator_removes(db, space, member)
        outcome = membership_grant.ensure_membership_for_purchase(
            db, user_id=member.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.reactivated is False
        assert outcome.skipped_reason == "rejoin_blocked"
        assert _membership(db, space, member).status == (
            SpaceMembershipStatus.removed
        )
        assert _membership(db, space, member).rejoin_blocked is True

    def test_an_admin_revocation_cannot_be_bought_back_either(
        self, db, space, member,
    ):
        from app.services import membership_grant

        row = _membership(db, space, member)
        row.status = SpaceMembershipStatus.removed
        row.removal_kind = membership_removal.REMOVAL_BY_ADMIN
        row.source = "purchase"
        db.flush()
        outcome = membership_grant.ensure_membership_for_purchase(
            db, user_id=member.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.reactivated is False

    def test_re_adding_a_banned_person_is_refused_until_unblocked(
        self, db, space, member,
    ):
        """Lifting a ban must be deliberate and recorded, not a side
        effect of typing an email into the add-member field."""
        from app.creator.routes import add_or_invite_member
        from app.creator.schemas import AddMemberRequest
        from app.models.user import User

        owner = db.query(User).filter(User.id == space.creator_id).first()
        self._creator_removes(db, space, member)
        with pytest.raises(HTTPException) as exc:
            add_or_invite_member(
                space.slug,
                AddMemberRequest(email=member.email, role="learner"),
                db=db, current_user=owner, background_tasks=None,
            )
        assert exc.value.status_code == 409
        assert "removed people" in str(exc.value.detail).lower()

    def test_the_creator_endpoint_reactivates_rather_than_inserting(
        self, db, space, member,
    ):
        """``add_or_invite_member`` used to INSERT and hit the unique
        constraint, so re-adding a removed member was a 500. Shown on an
        ordinary removal — a banned one is refused until unblocked."""
        from app.creator.routes import add_or_invite_member
        from app.creator.schemas import AddMemberRequest
        from app.models.user import User

        owner = db.query(User).filter(User.id == space.creator_id).first()
        _ordinary_creator_removal(db, space, member)
        result = add_or_invite_member(
            space.slug,
            AddMemberRequest(email=member.email, role="learner"),
            db=db,
            current_user=owner,
            background_tasks=None,
        )
        assert result.result == "added_as_member"
        assert _membership(db, space, member).status == (
            SpaceMembershipStatus.active
        )
        rows = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.user_id == member.id,
            )
            .count()
        )
        assert rows == 1


class TestARefusedReactivationCanLeaveABuyerCharged:
    """What membership refusal costs a buyer — now that checkout
    refuses first.

    This class was written to document a gap: nothing in checkout
    consulted membership status, so a creator-removed member could be
    charged and only then refused. Rule E
    (``checkout_orchestration.check_membership_deliverable_or_raise``)
    closed it for the two purchases that cannot be delivered without
    membership. What remains here is the shape of the refusal itself —
    which purchases need membership and which do not — because that is
    what Rule E is derived from, and it should not drift from it
    silently.

    The residual mid-checkout race lives in
    ``test_checkout_membership_safeguard.py``.
    """

    def _not_readmittable(self, db, space, member, *, source="purchase"):
        """An admin revocation — the remaining case where membership
        cannot be delivered and the buyer is not already stopped by
        Rule F. An ordinary creator removal is readmittable now, and a
        ban is refused by Rule F before Rule E is consulted."""
        row = _membership(db, space, member)
        row.status = SpaceMembershipStatus.removed
        row.removal_kind = membership_removal.REMOVAL_BY_ADMIN
        row.source = source
        db.flush()

    def test_checkout_now_refuses_before_charging(self):
        """The gap this class used to document. Rule E reads membership
        status before any Session exists."""
        import inspect

        from app.services import checkout_orchestration

        src = inspect.getsource(checkout_orchestration)
        assert "SpaceMembership" in src
        assert hasattr(
            checkout_orchestration, "check_membership_deliverable_or_raise",
        )

    def test_paying_to_join_does_not_make_them_a_member(
        self, db, space, member,
    ):
        """Membership was the product. The buyer is charged and the
        reactivation is refused."""
        from app.services import membership_grant

        space.join_policy = "purchase_required"
        db.flush()
        self._not_readmittable(db, space, member)
        outcome = membership_grant.ensure_membership_for_purchase(
            db, user_id=member.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.reactivated is False
        assert outcome.skipped_reason == "removal_admin"

    def test_an_included_with_offer_pathway_stays_shut(
        self, db, space, member,
    ):
        """Paid unlock, membership-gated gate. The one access type where
        paying again genuinely delivers nothing."""
        from app.spaces.routes import _check_pathway_access

        self._not_readmittable(db, space, member)
        _pass(db, space, member)
        pw = _pathway(db, space, access_type="included_with_offer")
        with pytest.raises(HTTPException) as exc:
            _check_pathway_access(member, pw, space, db)
        assert exc.value.status_code == 403

    def test_a_purchased_pathway_is_still_delivered(
        self, db, space, member,
    ):
        """Scope of the gap: entitlement-gated access does not read
        membership, so it arrives normally."""
        from app.spaces.routes import _check_pathway_access

        self._not_readmittable(db, space, member)
        pw = _pathway(db, space, access_type="one_time")
        _entitlement(
            db, space, member, pw,
            source=EntitlementSource.one_time_purchase,
        )
        _check_pathway_access(member, pw, space, db)  # no raise

    def test_an_offering_is_still_delivered(self, db, space, member):
        self._not_readmittable(db, space, member)
        _off, ent = _offering_owned(db, space, member)
        assert ent.status == OfferingEntitlementStatus.active.value

    def test_a_paid_gathering_ticket_is_still_delivered(
        self, db, space, member, make_event,
    ):
        """And reachable, through the paid-reservation exception."""
        from app.spaces.routes import get_event

        event = make_event(space=space)
        _booking(db, event, member)
        self._not_readmittable(db, space, member)
        assert get_event(
            space.slug, event.id, db=db, current_user=member,
        )["id"] == event.id

    def test_the_two_undeliverable_shapes_are_what_rule_e_refuses(self):
        """Guard and consequence, kept in step: the purchases refused at
        checkout are exactly the ones that cannot be delivered."""
        import inspect

        from app.services import checkout_orchestration

        src = inspect.getsource(
            checkout_orchestration._purchase_needs_membership,
        )
        assert "is_joining_option" in src
        assert "included_with_offer" in src


class TestHistoricalRemovalsAreNotAssumedVoluntary:
    """Migration 166 backfills nothing. A ``removed`` row from before it
    existed has ``removal_kind IS NULL`` — unknown, not harmless."""

    def _historical(self, db, space, member, *, source="joined"):
        row = _membership(db, space, member)
        row.status = SpaceMembershipStatus.removed
        row.removal_kind = None
        row.removed_at = None
        row.removed_by_user_id = None
        row.source = source
        db.flush()
        return row

    def test_may_rejoin_refuses_an_unknown_removal(
        self, db, space, member,
    ):
        from app.services import membership_grant

        row = self._historical(db, space, member)
        assert membership_grant.may_rejoin(row) is False

    def test_pressing_join_is_refused(self, db, space, member):
        self._historical(db, space, member)
        with pytest.raises(HTTPException) as exc:
            _press_join(db, space, member)
        assert exc.value.status_code == 409

    def test_a_purchase_does_not_restore_it(self, db, space, member):
        """Previously it would have: ``source='joined'`` was in
        ``REACTIVATABLE_SOURCES`` and nothing else was asked."""
        from app.services import membership_grant

        self._historical(db, space, member, source="purchase")
        outcome = membership_grant.ensure_membership_for_purchase(
            db, user_id=member.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.reactivated is False
        assert outcome.skipped_reason == "removal_unknown"

    def test_the_creator_can_re_add_them(self, db, space, member):
        """Which is why refusing is safe rather than punitive."""
        from app.services import membership_grant

        row = self._historical(db, space, member)
        membership_grant.reactivate(db, row, now=datetime.utcnow())
        db.flush()
        assert row.status == SpaceMembershipStatus.active

    def test_the_rule_is_an_allow_list_not_a_deny_list(self):
        """Stated as a test because the asymmetry is the whole design:
        requiring ``voluntary`` makes every unrecorded case refuse,
        where excluding ``creator`` would have let them all through."""
        import inspect

        from app.services import membership_grant

        src = inspect.getsource(membership_grant.may_rejoin)
        assert "== REMOVAL_VOLUNTARY" in src
        assert "!=" not in src.split('"""')[-1]


class TestRejoiningIsSubjectToTheUsualRequirements:

    def test_a_full_collective_refuses_the_rejoin(self, db, space, member):
        """"Subject to its membership requirements" is not a hedge —
        the member allowance is re-checked, so a Collective that filled
        up while they were away says so."""
        from fastapi import HTTPException as _HTTPException

        _leave(db, space, member)

        import app.spaces.routes as routes

        original = routes.guard_member_allowance

        def _full(*_a, **_kw):
            raise _HTTPException(status_code=402, detail="Collective is full.")

        routes.guard_member_allowance = _full
        try:
            with pytest.raises(_HTTPException) as exc:
                _press_join(db, space, member)
            assert exc.value.status_code == 402
        finally:
            routes.guard_member_allowance = original

        assert _membership(db, space, member).status == (
            SpaceMembershipStatus.removed
        )

    def test_the_rejoin_path_re_checks_the_allowance(self):
        import inspect

        from app.spaces.routes import join_space

        src = inspect.getsource(join_space)
        rejoin = src[src.index("may_rejoin"):]
        assert "guard_member_allowance" in rejoin

    def test_a_purchase_required_collective_still_demands_payment(
        self, db, space, member,
    ):
        """The join policy is evaluated before the rejoin branch is
        reached, so leaving does not become a way to re-enter a paid
        Collective for free."""
        import inspect

        from app.spaces.routes import join_space

        src = inspect.getsource(join_space)
        assert src.index("purchase") < src.index("may_rejoin")


class TestBothDoorsReadOneRule:

    def test_join_consults_may_rejoin(self):
        import inspect

        from app.spaces.routes import join_space

        assert "may_rejoin" in inspect.getsource(join_space)

    def test_purchase_reactivation_consults_may_rejoin(self):
        import inspect

        from app.services import membership_grant

        src = inspect.getsource(
            membership_grant.ensure_membership_for_purchase,
        )
        assert "may_rejoin" in src

    def test_neither_door_inserts_a_second_row(self):
        import inspect

        from app.services import membership_grant
        from app.spaces.routes import join_space

        src = inspect.getsource(join_space)
        # The rejoin branch only — the brand-new-member INSERT lives
        # further down and is correct.
        start = src.index("may_rejoin")
        rejoin = src[start:src.index("raise HTTPException", start)]
        assert "SpaceMembership(" not in rejoin
        assert "reactivate(" in rejoin
        grant = inspect.getsource(
            membership_grant.ensure_membership_for_purchase,
        )
        assert grant.count("SpaceMembership(") == 1  # the no-row branch only


# ---------------------------------------------------------------------------
# 13. One removal path, two callers
# ---------------------------------------------------------------------------


class TestOneRemovalPath:

    def test_the_creator_endpoint_reads_the_shared_service(self):
        import inspect

        from app.creator import routes as creator_routes

        src = inspect.getsource(creator_routes.remove_member_with_reason)
        assert "membership_removal.end_membership" in src

    def test_the_member_endpoint_reads_the_shared_service(self):
        import inspect

        src = inspect.getsource(leave_collective)
        assert "membership_removal.end_membership" in src

    def test_the_creator_endpoint_still_refuses_self_removal(self):
        import inspect

        from app.creator import routes as creator_routes

        src = inspect.getsource(creator_routes._resolve_removable_membership)
        assert "cannot remove yourself" in src.lower()
