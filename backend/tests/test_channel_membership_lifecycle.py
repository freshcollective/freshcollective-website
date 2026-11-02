"""Membership that outlives the experience that created it.

The rule being protected: a linked-experience channel's membership is
materialised and authoritative. Qualifying for any ONE linked
experience admits you; nothing automatic ever removes you again except
an actual revocation of access; and a creator's removal outranks both.

Each of those is a separate claim and each can regress on its own, so
they are asserted separately rather than through one happy path.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.platform import (
    BookingStatus,
    ChannelExperienceLink,
    ChannelMembership,
    ConversationChannel,
    EventBooking,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import channel_membership as chm
from app.services import channel_permissions as perms


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def space(make_space):
    return make_space()


@pytest.fixture
def join(db):
    def _join(space, user, role=SpaceRole.learner):
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=user.id, space_id=space.id,
            role=role, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()
    return _join


@pytest.fixture
def channel(db, space):
    """A linked-experience channel with no links yet."""
    row = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="Women's Circle",
        slug=f"womens-circle-{uuid.uuid4().hex[:6]}",
        channel_type="gathering",
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def link(db):
    def _link(channel, *, pathway=None, event=None, series=None):
        row = ChannelExperienceLink(
            id=_uid("cel"), channel_id=channel.id,
            pathway_id=pathway.id if pathway is not None else None,
            event_id=event.id if event is not None else None,
            series_id=series.id if series is not None else None,
        )
        db.add(row)
        db.flush()
        return row
    return _link


@pytest.fixture
def attend(db):
    """A confirmed booking — the thing that qualifies somebody."""
    def _attend(event, user):
        row = EventBooking(
            id=_uid("bk"), event_id=event.id, user_id=user.id,
            status=BookingStatus.confirmed, source="ticket_purchase",
            booked_at=datetime.utcnow(),
        )
        db.add(row)
        db.flush()
        return row
    return _attend


def _row(db, channel, user):
    return (
        db.query(ChannelMembership)
        .filter(
            ChannelMembership.channel_id == channel.id,
            ChannelMembership.user_id == user.id,
        )
        .first()
    )


class TestAdmission:
    def test_one_linked_experience_is_enough(
        self, db, space, channel, link, attend, join, make_event, make_user,
    ):
        """Three Gatherings linked; the member bought one of them."""
        november = make_event(space=space, title="November Circle")
        december = make_event(space=space, title="December Circle")
        january = make_event(space=space, title="January Circle")
        for ev in (november, december, january):
            link(channel, event=ev)

        member = make_user()
        join(space, member)
        attend(november, member)
        db.commit()

        assert perms.qualifies_through_any_linked_experience(
            member, channel, space, db,
        ) is True
        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is True

    def test_qualifying_through_none_of_them_is_not_enough(
        self, db, space, channel, link, join, make_event, make_user,
    ):
        link(channel, event=make_event(space=space))
        member = make_user()
        join(space, member)
        db.commit()

        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is False

    def test_admission_is_idempotent(
        self, db, space, channel, link, attend, join, make_event, make_user,
    ):
        """Repeated webhook delivery must not produce a second row."""
        event = make_event(space=space)
        link(channel, event=event)
        member = make_user()
        join(space, member)
        attend(event, member)
        db.commit()

        first = chm.admit_for_experience(
            db, space_id=space.id, kind="gathering",
            experience_id=event.id, user_id=member.id,
        )
        second = chm.admit_for_experience(
            db, space_id=space.id, kind="gathering",
            experience_id=event.id, user_id=member.id,
        )
        db.commit()

        assert first[channel.id] == "added"
        assert second[channel.id] == "already_member"
        assert db.query(ChannelMembership).filter(
            ChannelMembership.channel_id == channel.id,
            ChannelMembership.user_id == member.id,
        ).count() == 1

    def test_qualifying_twice_still_yields_one_membership(
        self, db, space, channel, link, attend, join, make_event, make_user,
    ):
        """Two linked Gatherings, both attended."""
        a, b = make_event(space=space), make_event(space=space)
        link(channel, event=a)
        link(channel, event=b)
        member = make_user()
        join(space, member)
        attend(a, member)
        attend(b, member)
        db.commit()

        for ev in (a, b):
            chm.admit_for_experience(
                db, space_id=space.id, kind="gathering",
                experience_id=ev.id, user_id=member.id,
            )
        db.commit()

        assert db.query(ChannelMembership).filter(
            ChannelMembership.channel_id == channel.id,
            ChannelMembership.user_id == member.id,
        ).count() == 1


class TestMembershipPersists:
    """§5 — the business rule this whole model exists for."""

    @pytest.fixture
    def admitted(
        self, db, space, channel, link, attend, join, make_event, make_user,
    ):
        event = make_event(
            space=space, starts_at=datetime.utcnow() + timedelta(days=2),
        )
        link(channel, event=event)
        member = make_user()
        join(space, member)
        booking = attend(event, member)
        chm.admit_for_experience(
            db, space_id=space.id, kind="gathering",
            experience_id=event.id, user_id=member.id,
        )
        db.commit()
        return member, event, booking

    def test_retained_after_the_gathering_finishes(
        self, db, space, channel, admitted,
    ):
        member, event, _ = admitted
        event.starts_at = datetime.utcnow() - timedelta(days=30)
        event.ends_at = datetime.utcnow() - timedelta(days=30)
        db.commit()

        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is True

    def test_retained_after_the_experience_is_unlinked(
        self, db, space, channel, admitted,
    ):
        """Unlinking is a curation decision about the channel's
        subject, not an eviction notice."""
        member, event, _ = admitted
        db.query(ChannelExperienceLink).filter(
            ChannelExperienceLink.channel_id == channel.id,
        ).delete()
        db.commit()

        assert perms.qualifies_through_any_linked_experience(
            member, channel, space, db,
        ) is False, "no longer qualifies..."
        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is True, "...and is still a member"

    def test_retained_after_the_booking_is_cancelled(
        self, db, space, channel, admitted,
    ):
        """A booking becoming historical is not a revocation."""
        member, _, booking = admitted
        booking.status = BookingStatus.cancelled
        db.commit()

        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is True

    def test_retained_when_the_experience_is_deleted(
        self, db, space, channel, admitted, make_event,
    ):
        """The link cascades away; the member does not."""
        member, event, booking = admitted
        db.delete(booking)
        db.flush()
        db.delete(event)
        db.commit()

        assert db.query(ChannelExperienceLink).filter(
            ChannelExperienceLink.channel_id == channel.id,
        ).count() == 0
        assert db.query(ConversationChannel).get(channel.id) is not None
        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is True


class TestCreatorRemoval:
    """§6 — a deliberate decision that automation must not undo."""

    @pytest.fixture
    def removed(
        self, db, space, channel, link, attend, join, make_event, make_user,
    ):
        event = make_event(space=space)
        link(channel, event=event)
        member, creator = make_user(), make_user(role="creator")
        join(space, member)
        attend(event, member)
        chm.admit_for_experience(
            db, space_id=space.id, kind="gathering",
            experience_id=event.id, user_id=member.id,
        )
        chm.remove(
            db, channel_id=channel.id, user_id=member.id,
            reason=chm.REASON_CREATOR, actor_user_id=creator.id,
        )
        db.commit()
        return member, event, creator

    def test_removal_denies_access_even_though_they_qualify(
        self, db, space, channel, removed,
    ):
        member, _, _ = removed
        assert perms.qualifies_through_any_linked_experience(
            member, channel, space, db,
        ) is True, "they still hold a confirmed booking"
        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is False, "and are still out"

    def test_a_tombstone_is_left_rather_than_a_deletion(
        self, db, space, channel, removed,
    ):
        member, _, creator = removed
        row = _row(db, channel, member)
        assert row is not None, "deleting the row is what lets them back in"
        assert row.status == "removed"
        assert row.removed_reason == chm.REASON_CREATOR
        assert row.removed_by == creator.id

    def test_a_new_purchase_does_not_silently_re_admit(
        self, db, space, channel, removed, link, attend, make_event,
    ):
        """They buy December. That must not overturn the decision."""
        member, _, _ = removed
        december = make_event(space=space, title="December Circle")
        link(channel, event=december)
        attend(december, member)
        db.commit()

        outcome = chm.admit_for_experience(
            db, space_id=space.id, kind="gathering",
            experience_id=december.id, user_id=member.id,
        )
        db.commit()

        assert outcome[channel.id] == "blocked_by_creator_removal"
        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is False

    def test_a_backfill_does_not_re_admit_either(
        self, db, space, channel, removed,
    ):
        member, _, _ = removed
        chm.backfill_channel(db, channel=channel, space=space)
        db.commit()
        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is False

    def test_the_creator_can_add_them_back_explicitly(
        self, db, space, channel, removed,
    ):
        member, _, _ = removed
        outcome = chm.admit(
            db, channel_id=channel.id, user_id=member.id,
            source=chm.SOURCE_MANUAL,
        )
        db.commit()

        assert outcome == "readmitted"
        row = _row(db, channel, member)
        assert row.status == "active" and row.removed_reason is None
        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is True

    def test_removing_someone_who_was_never_materialised_still_sticks(
        self, db, space, channel, link, attend, join, make_event, make_user,
    ):
        """They qualify but have no row yet. Without a tombstone the
        admission predicate would wave them straight back through."""
        event = make_event(space=space)
        link(channel, event=event)
        member, creator = make_user(), make_user(role="creator")
        join(space, member)
        attend(event, member)
        db.commit()
        assert _row(db, channel, member) is None

        chm.remove(
            db, channel_id=channel.id, user_id=member.id,
            reason=chm.REASON_CREATOR, actor_user_id=creator.id,
        )
        db.commit()

        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is False


class TestRevocation:
    """Revocation is not expiry, and is treated differently."""

    @pytest.fixture
    def revoked(
        self, db, space, channel, link, attend, join, make_event, make_user,
    ):
        event = make_event(space=space)
        link(channel, event=event)
        member = make_user()
        join(space, member)
        booking = attend(event, member)
        chm.admit_for_experience(
            db, space_id=space.id, kind="gathering",
            experience_id=event.id, user_id=member.id,
        )
        booking.status = BookingStatus.cancelled
        chm.revoke_for_experience(
            db, space_id=space.id, kind="gathering",
            experience_id=event.id, user_id=member.id,
        )
        db.commit()
        return member, event

    def test_revocation_removes_them(self, db, space, channel, revoked):
        member, _ = revoked
        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is False
        assert _row(db, channel, member).removed_reason == (
            chm.REASON_ACCESS_REVOKED
        )

    def test_a_genuine_new_purchase_re_admits_after_revocation(
        self, db, space, channel, revoked, link, attend, make_event,
    ):
        """Unlike a creator removal — nobody decided they should be
        out of the conversation, their access simply ended."""
        member, _ = revoked
        december = make_event(space=space)
        link(channel, event=december)
        attend(december, member)
        db.commit()

        outcome = chm.admit_for_experience(
            db, space_id=space.id, kind="gathering",
            experience_id=december.id, user_id=member.id,
        )
        db.commit()

        assert outcome[channel.id] == "readmitted"
        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is True

    def test_a_creator_added_member_is_not_revoked_out(
        self, db, space, channel, link, attend, join, make_event, make_user,
    ):
        """The creator put them there deliberately; their having also
        bought something once is beside the point."""
        event = make_event(space=space)
        link(channel, event=event)
        member = make_user()
        join(space, member)
        attend(event, member)
        chm.admit(
            db, channel_id=channel.id, user_id=member.id,
            source=chm.SOURCE_MANUAL,
        )
        db.commit()

        outcome = chm.revoke_for_experience(
            db, space_id=space.id, kind="gathering",
            experience_id=event.id, user_id=member.id,
        )
        db.commit()

        assert outcome[channel.id] == "kept_creator_added"
        assert perms.can_access_linked_channel(
            member, channel, space, db,
        ) is True


class TestBackfillOnLinking:
    """§4 — linking an existing experience brings its people in."""

    def test_existing_qualifiers_are_admitted(
        self, db, space, channel, link, attend, join, make_event, make_user,
    ):
        event = make_event(space=space)
        already = [make_user() for _ in range(3)]
        for u in already:
            join(space, u)
            attend(event, u)
        outsider = make_user()
        join(space, outsider)
        db.commit()

        link(channel, event=event)
        counts = chm.backfill_channel(db, channel=channel, space=space)
        db.commit()

        assert counts["added"] == 3
        for u in already:
            assert _row(db, channel, u).status == "active"
        assert _row(db, channel, outsider) is None

    def test_backfill_twice_adds_nobody_twice(
        self, db, space, channel, link, attend, join, make_event, make_user,
    ):
        event = make_event(space=space)
        member = make_user()
        join(space, member)
        attend(event, member)
        link(channel, event=event)
        db.commit()

        chm.backfill_channel(db, channel=channel, space=space)
        db.commit()
        second = chm.backfill_channel(db, channel=channel, space=space)
        db.commit()

        assert second["added"] == 0
        assert second["already_member"] == 1


class TestCrossCollective:
    """§9 — a link must not reach into another Collective."""

    def test_a_link_in_another_collective_admits_nobody(
        self, db, space, channel, link, attend, join, make_space,
        make_event, make_user,
    ):
        other = make_space()
        foreign_event = make_event(space=other)
        link(channel, event=foreign_event)

        member = make_user()
        join(other, member)
        attend(foreign_event, member)
        db.commit()

        # Scoped by space_id, so the channel in `space` is not returned
        # for an experience that lives in `other`.
        assert chm.channels_linked_to(
            db, space_id=other.id, kind="gathering",
            experience_id=foreign_event.id,
        ) == []
