"""Series-linked Conversation Channels mirror canonical Series access.

The rule for MVP (pinned here so it can't drift):

  A member can view a ``series``-typed ConversationChannel while they
  hold a currently active, not-yet-expired AccessPass whose
  ``eligible_series_id`` matches the channel's ``series_id``. That
  covers pay-in-full, finite payment plan, and complimentary/manual
  grants uniformly (same AccessPass shape for all three). Caretakers
  bypass. Everyone else is denied.

  Attending one gathering inside the series (a confirmed
  EventBooking) is NOT a Series-access source. Once the pass expires,
  cancels, or is otherwise no longer active AND no overlapping valid
  pass remains, the Channel disappears.

  Archived-cohort Conversation access is out of scope for MVP and is
  deliberately NOT delivered here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.community.channels import (
    ChannelCreateRequest,
    create_channel,
    list_creator_channels,
    list_member_channels,
)
from app.models.access_pass import (
    AccessPass,
    AccessPassSource,
    AccessPassStatus,
    AccessPassType,
)
from app.models.platform import (
    BookingStatus,
    ChannelMembership,
    ConversationChannel,
    Event,
    EventBooking,
    EventSeries,
    Pathway,
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


def _make_series(
    db, space, *, title: str = "EMBODY Term 4 2026",
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    status: str = "published",
) -> EventSeries:
    starts_at = starts_at or (datetime.utcnow() + timedelta(days=30))
    s = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title,
        starts_at=starts_at,
        ends_at=ends_at if ends_at is not None else (starts_at + timedelta(days=60)),
        status=status,
    )
    db.add(s)
    db.flush()
    return s


def _make_series_channel(db, space, series) -> ConversationChannel:
    c = ConversationChannel(
        id=_uid("ch"),
        space_id=space.id,
        name=f"{series.title} — Live Group",
        slug=f"ch-{uuid.uuid4().hex[:8]}",
        channel_type="series",
        series_id=series.id,
    )
    db.add(c)
    db.flush()
    return c


def _grant_series_pass(
    db, *, user, space, series,
    source: AccessPassSource = AccessPassSource.one_time_purchase,
    status: AccessPassStatus = AccessPassStatus.active,
    valid_until: datetime | None = None,
) -> AccessPass:
    """Seed the AccessPass shape that pay-in-full, finite-plan
    fulfilment, and manual grants all land — different ``source`` /
    ``payment_option_id`` / ``purchase_plan_id`` fields, but the
    channel predicate only cares about ``eligible_series_id`` +
    status + window."""
    ap = AccessPass(
        id=_uid("ap"),
        user_id=user.id,
        space_id=space.id,
        pass_type=AccessPassType.term_pass,
        status=status,
        valid_from=series.starts_at,
        valid_until=valid_until if valid_until is not None else series.ends_at,
        eligible_series_id=series.id,
        source=source,
    )
    db.add(ap)
    db.flush()
    return ap


def _make_event_in_series(db, space, series) -> Event:
    e = Event(
        id=_uid("e"),
        space_id=space.id,
        created_by_id=space.creator_id,
        title="Session",
        starts_at=series.starts_at + timedelta(days=1),
        ends_at=series.starts_at + timedelta(days=1, hours=1),
        is_published=True,
        status="active",
        requires_booking=True,
        capacity=20,
        gathering_type="circle",
        attendance_format="online",
        booking_access_type="included_with_series",
        series_id=series.id,
    )
    db.add(e)
    db.flush()
    return e


def _confirm_booking(db, *, user, event) -> EventBooking:
    b = EventBooking(
        id=_uid("bk"),
        event_id=event.id,
        user_id=user.id,
        status=BookingStatus.confirmed,
        booked_at=datetime.utcnow(),
    )
    db.add(b)
    db.flush()
    return b


def _assert_view_and_autocomplete_agree(
    db, *, user, channel, space, expected: bool,
) -> None:
    view = can_view_channel(user, channel, space, db)
    assert view is expected, (
        f"can_view_channel returned {view}, expected {expected}"
    )
    ids = accessible_user_ids_for_channel(channel, space, db)
    in_set = user.id in ids
    assert in_set is expected, (
        f"accessible_user_ids_for_channel included={in_set}, expected {expected} "
        f"(view + autocomplete diverged)"
    )


# ---------------------------------------------------------------------------
# 1. Positive branches — every legitimate Series-access source grants
#    the Channel (including advance access before the series begins).
# ---------------------------------------------------------------------------


class TestPositiveSeriesChannelAccess:
    def test_pay_in_full_series_pass_grants_channel(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        series = _make_series(db, space)
        channel = _make_series_channel(db, space, series)
        _grant_series_pass(
            db, user=payer, space=space, series=series,
            source=AccessPassSource.one_time_purchase,
        )
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

    def test_finite_plan_series_pass_grants_channel(
        self, db, make_space, make_user,
    ):
        """Finite-plan first-payment fulfilment lands the same
        AccessPass shape as pay-in-full. Different fields on the row
        (``purchase_plan_id``, ``source`` might vary) — the channel
        predicate only cares about the eligible_series_id + status +
        window."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        series = _make_series(db, space)
        channel = _make_series_channel(db, space, series)
        _grant_series_pass(
            db, user=payer, space=space, series=series,
            source=AccessPassSource.subscription,
        )
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

    def test_manual_admin_grant_series_pass_grants_channel(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        series = _make_series(db, space)
        channel = _make_series_channel(db, space, series)
        _grant_series_pass(
            db, user=payer, space=space, series=series,
            source=AccessPassSource.admin_grant,
        )
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

    def test_advance_access_future_series_grants_channel(
        self, db, make_space, make_user,
    ):
        """The exact Awaken-in-September / Term-4-starts-October
        scenario. The pass's ``valid_from`` is a month away, but
        ``compute_series_access`` deliberately does not gate on it —
        the buyer owns a valid future pass and should see the
        Conversation immediately."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        future_start = datetime.utcnow() + timedelta(days=30)
        series = _make_series(
            db, space,
            starts_at=future_start,
            ends_at=future_start + timedelta(days=60),
        )
        channel = _make_series_channel(db, space, series)
        _grant_series_pass(db, user=payer, space=space, series=series)
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

    def test_caretaker_bypass_regression_pin(
        self, db, make_space, make_user,
    ):
        """Creator/moderator on the Space see every channel regardless
        of Series pass — required by ``is_caretaker`` in
        ``can_view_channel``."""
        space = make_space()
        mod = make_user()
        _member(db, mod, space, role=SpaceRole.moderator)
        series = _make_series(db, space)
        channel = _make_series_channel(db, space, series)
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=mod, channel=channel, space=space, expected=True,
        )


# ---------------------------------------------------------------------------
# 2. Negative branches — no pass, or the pass is no longer valid.
# ---------------------------------------------------------------------------


class TestNegativeSeriesChannelAccess:
    def test_member_without_pass_cannot_see_channel(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        series = _make_series(db, space)
        channel = _make_series_channel(db, space, series)
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=False,
        )

    def test_single_gathering_booking_does_not_grant_channel(
        self, db, make_space, make_user,
    ):
        """The pinned product rule: attending one session inside the
        series does not entitle the member to the whole-series
        conversation. Only a matching AccessPass does."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        series = _make_series(db, space)
        channel = _make_series_channel(db, space, series)
        event = _make_event_in_series(db, space, series)
        _confirm_booking(db, user=payer, event=event)
        # Deliberately no AccessPass.
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=False,
        )

    def test_cancelled_pass_removes_channel_immediately(
        self, db, make_space, make_user,
    ):
        """Whole-purchase revoke flips ``AccessPass.status`` to
        ``cancelled`` — the predicate reads current state, so
        visibility drops on the next request. Source-aware."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        series = _make_series(db, space)
        channel = _make_series_channel(db, space, series)
        ap = _grant_series_pass(db, user=payer, space=space, series=series)
        db.commit()
        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )

        ap.status = AccessPassStatus.cancelled
        ap.revoked_at = datetime.utcnow()
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=False,
        )

    def test_expired_pass_removes_channel(
        self, db, make_space, make_user,
    ):
        """``valid_until`` in the past → predicate returns False."""
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        past = datetime.utcnow() - timedelta(days=90)
        series = _make_series(
            db, space,
            starts_at=past,
            ends_at=past + timedelta(days=60),  # ended 30d ago
        )
        channel = _make_series_channel(db, space, series)
        _grant_series_pass(
            db, user=payer, space=space, series=series,
            valid_until=past + timedelta(days=60),
        )
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=False,
        )

    def test_non_space_member_with_pass_still_denied(
        self, db, make_space, make_user,
    ):
        """Outer ``is_active_space_member`` gate; autocomplete
        intersects with active SpaceMembership to match."""
        space = make_space()
        stray = make_user()
        # No _member(stray, space).
        series = _make_series(db, space)
        channel = _make_series_channel(db, space, series)
        _grant_series_pass(db, user=stray, space=space, series=series)
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=stray, channel=channel, space=space, expected=False,
        )


# ---------------------------------------------------------------------------
# 3. Overlap — one pass revoked, another still-active pass preserves access.
# ---------------------------------------------------------------------------


class TestOverlappingSeriesPasses:
    def test_two_passes_one_revoked_channel_still_visible(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        series = _make_series(db, space)
        channel = _make_series_channel(db, space, series)
        ap1 = _grant_series_pass(
            db, user=payer, space=space, series=series,
            source=AccessPassSource.one_time_purchase,
        )
        _grant_series_pass(
            db, user=payer, space=space, series=series,
            source=AccessPassSource.admin_grant,
        )
        db.commit()

        ap1.status = AccessPassStatus.cancelled
        ap1.revoked_at = datetime.utcnow()
        db.commit()

        _assert_view_and_autocomplete_agree(
            db, user=payer, channel=channel, space=space, expected=True,
        )


# ---------------------------------------------------------------------------
# 4. Autocomplete parity across boundary cases.
# ---------------------------------------------------------------------------


class TestAutocompleteParity:
    def test_autocomplete_includes_pass_holder_excludes_non_holder(
        self, db, make_space, make_user,
    ):
        space = make_space()
        holder = make_user()
        non_holder = make_user()
        _member(db, holder, space)
        _member(db, non_holder, space)
        series = _make_series(db, space)
        channel = _make_series_channel(db, space, series)
        _grant_series_pass(db, user=holder, space=space, series=series)
        db.commit()

        ids = accessible_user_ids_for_channel(channel, space, db)
        assert holder.id in ids
        assert non_holder.id not in ids
        assert can_view_channel(holder, channel, space, db) is True
        assert can_view_channel(non_holder, channel, space, db) is False

    def test_autocomplete_excludes_after_revoke(
        self, db, make_space, make_user,
    ):
        space = make_space()
        holder = make_user()
        _member(db, holder, space)
        series = _make_series(db, space)
        channel = _make_series_channel(db, space, series)
        ap = _grant_series_pass(db, user=holder, space=space, series=series)
        db.commit()
        assert holder.id in accessible_user_ids_for_channel(channel, space, db)

        ap.status = AccessPassStatus.cancelled
        db.commit()

        assert holder.id not in accessible_user_ids_for_channel(channel, space, db)


# ---------------------------------------------------------------------------
# 5. Regression pins — other channel types unchanged.
# ---------------------------------------------------------------------------


class TestOtherChannelTypesUnchanged:
    def test_pathway_channel_still_uses_pathway_access(
        self, db, make_space, make_user,
    ):
        """Adding the series branch must not affect pathway channels."""
        from app.models.platform import PathwayEntitlement, EntitlementSource, EntitlementStatus

        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        pathway = Pathway(
            id=_uid("pw"),
            space_id=space.id,
            slug=f"pw-{uuid.uuid4().hex[:8]}",
            title="The EMBODY Practice",
            access_type="one_time",
            price_cents=20000,
        )
        db.add(pathway)
        db.flush()
        channel = ConversationChannel(
            id=_uid("ch"),
            space_id=space.id,
            name="Practice channel",
            slug=f"ch-{uuid.uuid4().hex[:8]}",
            channel_type="pathway",
            pathway_id=pathway.id,
        )
        db.add(channel)
        db.add(PathwayEntitlement(
            id=_uid("ent"),
            user_id=payer.id,
            space_id=space.id,
            pathway_id=pathway.id,
            source=EntitlementSource.one_time_purchase,
            status=EntitlementStatus.active,
            starts_at=datetime.utcnow(),
        ))
        db.commit()

        assert can_view_channel(payer, channel, space, db) is True

    def test_private_channel_still_needs_membership_row(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        ch = ConversationChannel(
            id=_uid("ch"),
            space_id=space.id,
            name="Inner circle",
            slug=f"ch-{uuid.uuid4().hex[:8]}",
            channel_type="private",
        )
        db.add(ch)
        db.commit()

        assert can_view_channel(payer, ch, space, db) is False
        db.add(ChannelMembership(
            id=_uid("cm"),
            channel_id=ch.id,
            user_id=payer.id,
        ))
        db.commit()

        assert can_view_channel(payer, ch, space, db) is True


# ---------------------------------------------------------------------------
# 6. Create endpoint — accepts series_id + validates it belongs to Space.
# ---------------------------------------------------------------------------


class TestCreateSeriesChannel:
    def test_create_series_channel_persists_series_id(
        self, db, make_space, make_user,
    ):
        space = make_space()
        owner = db.get(type(make_user()), space.creator_id) or None
        # Use the Space's owner as caretaker (space.creator_id).
        from app.models.user import User
        owner = db.query(User).filter(User.id == space.creator_id).one()
        series = _make_series(db, space, title="EMBODY Term 4 2026")
        db.commit()

        result = create_channel(
            slug=space.slug,
            body=ChannelCreateRequest(
                name="EMBODY - Live Group",
                channel_type="series",
                series_id=series.id,
            ),
            db=db,
            current_user=owner,
        )
        assert result.channel_type == "series"
        assert result.series_id == series.id
        assert result.series_title == "EMBODY Term 4 2026"
        assert result.pathway_id is None
        assert result.gathering_id is None

    def test_create_series_channel_missing_series_id_400(
        self, db, make_space, make_user,
    ):
        from fastapi import HTTPException
        from app.models.user import User

        space = make_space()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_channel(
                slug=space.slug,
                body=ChannelCreateRequest(
                    name="Broken",
                    channel_type="series",
                    series_id=None,
                ),
                db=db,
                current_user=owner,
            )
        assert exc.value.status_code == 400

    def test_create_series_channel_wrong_space_series_400(
        self, db, make_space, make_user,
    ):
        """Caretaker of Collective A cannot link a Channel here to a
        Series that lives in Collective B."""
        from fastapi import HTTPException
        from app.models.user import User

        space_a = make_space()
        space_b = make_space()
        owner_a = db.query(User).filter(User.id == space_a.creator_id).one()
        series_b = _make_series(db, space_b, title="Term 4 in the other collective")
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_channel(
                slug=space_a.slug,
                body=ChannelCreateRequest(
                    name="Cross-space attempt",
                    channel_type="series",
                    series_id=series_b.id,
                ),
                db=db,
                current_user=owner_a,
            )
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 7. Read-through: linked-title enrichment in the API response.
# ---------------------------------------------------------------------------


class TestSeriesTitleEnrichment:
    def test_member_channels_endpoint_carries_series_title(
        self, db, make_space, make_user,
    ):
        space = make_space()
        payer = make_user()
        _member(db, payer, space)
        series = _make_series(db, space, title="EMBODY Term 4 2026")
        _make_series_channel(db, space, series)
        _grant_series_pass(db, user=payer, space=space, series=series)
        db.commit()

        rows = list_member_channels(
            slug=space.slug, db=db, current_user=payer,
        )
        linked = [r for r in rows if r.channel_type == "series"]
        assert len(linked) == 1
        assert linked[0].series_title == "EMBODY Term 4 2026"
        assert linked[0].series_archived is False
        assert linked[0].pathway_title is None
        assert linked[0].gathering_title is None

    def test_creator_channels_endpoint_carries_series_title(
        self, db, make_space, make_user,
    ):
        from app.models.user import User

        space = make_space()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        series = _make_series(db, space, title="EMBODY Term 4 2026")
        _make_series_channel(db, space, series)
        db.commit()

        rows = list_creator_channels(
            slug=space.slug, db=db, current_user=owner,
        )
        linked = [r for r in rows if r.channel_type == "series"]
        assert len(linked) == 1
        assert linked[0].series_title == "EMBODY Term 4 2026"
