"""Who the backfill may permanently admit, and who it may not.

Materialising membership is irreversible in the sense that matters: a
row keeps somebody in a channel after their experience access ends.
So the question it answers must be "did this person join?", not "may
this person open it today".

Those two differ in three ways, and all three were being counted:

  * a caretaker reaches every channel in their Collective by role,
  * a **free** Pathway's audience is every member of the Collective,
  * a **draft** Pathway is reachable by caretakers only.

Only the third was ever refused. The first two would have hardened
role-based and openness-based access into permanent membership —
surviving the caretaker losing the role, and the Pathway ceasing to be
free.

Nobody loses access by being excluded here, which these tests assert
explicitly: the admission clause still admits anyone who genuinely
qualifies.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.access_pass import AccessPass, AccessPassStatus, AccessPassType
from app.models.platform import (
    BookingStatus,
    ChannelExperienceLink,
    ChannelMembership,
    ConversationChannel,
    EntitlementStatus,
    EventBooking,
    Pathway,
    PathwayEntitlement,
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
def pathway(db, space):
    def _make(status="active", access_type="free", title="A Pathway"):
        row = Pathway(
            id=_uid("pw"), space_id=space.id, title=title,
            slug=f"pw-{uuid.uuid4().hex[:8]}",
            status=status, access_type=access_type,
        )
        db.add(row)
        db.flush()
        return row
    return _make


@pytest.fixture
def channel(db, space):
    def _make(channel_type="pathway"):
        row = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Channel",
            slug=f"ch-{uuid.uuid4().hex[:8]}", channel_type=channel_type,
        )
        db.add(row)
        db.flush()
        return row
    return _make


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


def _row(db, channel, user):
    return (
        db.query(ChannelMembership)
        .filter(
            ChannelMembership.channel_id == channel.id,
            ChannelMembership.user_id == user.id,
        )
        .first()
    )


class TestDraftPathways:
    """Q1 — can a draft Pathway grant channel access?"""

    def test_a_draft_pathway_admits_no_ordinary_member(
        self, db, space, channel, link, pathway, join, make_user,
    ):
        """``WITHHELD_STATUSES`` covers draft, so the answer is no."""
        ch = channel()
        link(ch, pathway=pathway(status="draft"))
        member = make_user()
        join(space, member)
        db.commit()

        assert perms.qualifies_through_any_linked_experience(
            member, ch, space, db,
        ) is False
        assert perms.can_access_linked_channel(member, ch, space, db) is False

    def test_a_draft_pathway_is_visible_to_the_owner(
        self, db, space, channel, link, pathway, make_user,
    ):
        """Q3 — and this is what explains seeing one without enrolling.

        The Collective's owner reaches it through the caretaker bypass
        in ``compute_pathway_access``, not through any defect.
        """
        ch = channel()
        link(ch, pathway=pathway(status="draft"))
        owner = db.query(type(make_user())).filter_by(id=space.creator_id).first()
        db.commit()

        assert perms.can_access_linked_channel(owner, ch, space, db) is True

    def test_a_draft_pathway_is_never_backfilled(
        self, db, space, channel, link, pathway, join, make_user,
    ):
        """The explicit instruction: nobody is permanently admitted on
        the strength of an unpublished draft they never joined."""
        ch = channel()
        link(ch, pathway=pathway(status="draft"))
        member = make_user()
        join(space, member)
        db.commit()

        counts = chm.backfill_channel(db, channel=ch, space=space)
        db.commit()

        assert counts["added"] == 0
        assert _row(db, ch, member) is None


class TestCaretakersAreNotMaterialised:
    """A role is not a membership."""

    @pytest.fixture
    def setup(self, db, space, channel, link, pathway, join, make_user):
        ch = channel()
        link(ch, pathway=pathway(status="active", access_type="free"))
        moderator = make_user()
        join(space, moderator, role=SpaceRole.moderator)
        db.commit()
        return ch, moderator

    def test_a_moderator_is_skipped(self, db, space, setup):
        ch, moderator = setup
        counts = chm.backfill_channel(db, channel=ch, space=space)
        db.commit()

        assert counts["skipped_caretaker"] >= 1
        assert _row(db, ch, moderator) is None, (
            "a membership row would outlive the moderator role"
        )

    def test_but_they_still_reach_the_channel(self, db, space, setup):
        """Excluding them from the backfill takes nothing away."""
        ch, moderator = setup
        assert perms.can_access_linked_channel(
            moderator, ch, space, db,
        ) is True

    def test_the_owner_is_skipped_too(
        self, db, space, channel, link, pathway, make_user,
    ):
        ch = channel()
        link(ch, pathway=pathway(status="active", access_type="free"))
        db.commit()
        counts = chm.backfill_channel(db, channel=ch, space=space)
        db.commit()
        assert counts["added"] == 0


class TestOpennessIsNotJoining:
    """A free Pathway's audience is every member, which is not a list
    of people who joined it."""

    @pytest.fixture
    def setup(self, db, space, channel, link, pathway, join, make_user):
        ch = channel()
        pw = pathway(status="active", access_type="free")
        link(ch, pathway=pw)
        members = [make_user() for _ in range(3)]
        for m in members:
            join(space, m)
        db.commit()
        return ch, pw, members

    def test_free_pathway_members_are_not_backfilled(self, db, space, setup):
        ch, _, members = setup
        counts = chm.backfill_channel(db, channel=ch, space=space)
        db.commit()

        assert counts["added"] == 0
        assert counts["skipped_no_acquisition"] == 3
        for m in members:
            assert _row(db, ch, m) is None

    def test_but_they_can_still_open_it(self, db, space, setup):
        ch, _, members = setup
        for m in members:
            assert perms.can_access_linked_channel(m, ch, space, db) is True, (
                "they keep the access they have; only the permanent "
                "row is withheld"
            )

    def test_an_entitlement_holder_IS_backfilled(
        self, db, space, setup, make_user, join,
    ):
        """The distinction in one test: same Pathway, two members, one
        of whom actually acquired it."""
        ch, pw, _ = setup
        buyer = make_user()
        join(space, buyer)
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, space_id=space.id,
            pathway_id=pw.id, status=EntitlementStatus.active,
            source="admin",
        ))
        db.commit()

        counts = chm.backfill_channel(db, channel=ch, space=space)
        db.commit()

        assert counts["added"] == 1
        assert _row(db, ch, buyer).status == "active"


class TestWhatIsLegitimatelyBackfilled:
    """The people the feature exists for."""

    def test_a_confirmed_attendee(
        self, db, space, channel, link, join, make_event, make_user,
    ):
        ch = channel(channel_type="gathering")
        event = make_event(space=space)
        link(ch, event=event)
        attendee = make_user()
        join(space, attendee)
        db.add(EventBooking(
            id=_uid("bk"), event_id=event.id, user_id=attendee.id,
            status=BookingStatus.confirmed, source="ticket_purchase",
            booked_at=datetime.utcnow(),
        ))
        db.commit()

        counts = chm.backfill_channel(db, channel=ch, space=space)
        db.commit()
        assert counts["added"] == 1
        assert _row(db, ch, attendee).source == chm.SOURCE_EXPERIENCE

    def test_a_pending_payment_hold_is_not_an_acquisition(
        self, db, space, channel, link, join, make_event, make_user,
    ):
        """Starting Checkout is not joining."""
        ch = channel(channel_type="gathering")
        event = make_event(space=space)
        link(ch, event=event)
        shopper = make_user()
        join(space, shopper)
        db.add(EventBooking(
            id=_uid("bk"), event_id=event.id, user_id=shopper.id,
            status=BookingStatus.pending_payment, source="ticket_purchase",
            hold_expires_at=datetime.utcnow() + timedelta(minutes=20),
        ))
        db.commit()

        counts = chm.backfill_channel(db, channel=ch, space=space)
        db.commit()
        assert counts["added"] == 0
        assert _row(db, ch, shopper) is None

    def test_an_archived_pathway_with_an_entitlement_still_counts(
        self, db, space, channel, link, pathway, join, make_user,
    ):
        """Archiving a Pathway must not erase who bought it — the
        instruction not to revoke on 'archived' applies here too."""
        ch = channel()
        pw = pathway(status="archived", access_type="one_time")
        link(ch, pathway=pw)
        buyer = make_user()
        join(space, buyer)
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, space_id=space.id,
            pathway_id=pw.id, status=EntitlementStatus.active,
            source="admin",
        ))
        db.commit()

        counts = chm.backfill_channel(db, channel=ch, space=space)
        db.commit()
        assert counts["added"] == 1

    def test_a_revoked_entitlement_does_not_count(
        self, db, space, channel, link, pathway, join, make_user,
    ):
        ch = channel()
        pw = pathway(status="active", access_type="one_time")
        link(ch, pathway=pw)
        former = make_user()
        join(space, former)
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=former.id, space_id=space.id,
            pathway_id=pw.id, status=EntitlementStatus.revoked,
            source="admin",
        ))
        db.commit()

        counts = chm.backfill_channel(db, channel=ch, space=space)
        db.commit()
        assert counts["added"] == 0

    def test_a_series_pass_holder(
        self, db, space, channel, link, join, make_user, make_space,
    ):
        from app.models.platform import EventSeries

        ch = channel(channel_type="series")
        series = EventSeries(
            id=_uid("es"), space_id=space.id, title="Term",
            slug=f"term-{uuid.uuid4().hex[:6]}", starts_at=datetime.utcnow(),
        )
        db.add(series)
        db.flush()
        link(ch, series=series)
        holder = make_user()
        join(space, holder)
        db.add(AccessPass(
            id=_uid("ap"), user_id=holder.id, space_id=space.id,
            eligible_series_id=series.id, status=AccessPassStatus.active,
            pass_type=AccessPassType.term_pass,
        ))
        db.commit()

        counts = chm.backfill_channel(db, channel=ch, space=space)
        db.commit()
        assert counts["added"] == 1


class TestTheExplainOutput:
    """What an operator reads before committing."""

    def test_every_considered_member_is_accounted_for(
        self, db, space, channel, link, pathway, join, make_user,
    ):
        ch = channel()
        pw = pathway(status="active", access_type="free")
        link(ch, pathway=pw)

        buyer, browser = make_user(), make_user()
        for m in (buyer, browser):
            join(space, m)
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, space_id=space.id,
            pathway_id=pw.id, status=EntitlementStatus.active,
            source="admin",
        ))
        db.commit()

        explain: list[dict] = []
        counts = chm.backfill_channel(
            db, channel=ch, space=space, explain=explain,
        )
        db.commit()

        assert len(explain) == counts["considered"]
        by_user = {e["user_id"]: e for e in explain}
        assert by_user[buyer.id]["outcome"] == "added"
        assert "joined via pathway" in by_user[buyer.id]["reason"]
        assert by_user[browser.id]["outcome"] == "skipped"
        assert "never joined" in by_user[browser.id]["reason"]
