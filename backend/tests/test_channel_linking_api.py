"""Channel management through the creator API.

Covers the parts a creator touches: creating the three access
arrangements, linking several experiences of mixed kinds, editing the
links without losing the others, and the two guards — cross-Collective
linking, and widening who can read an existing conversation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.platform import (
    BookingStatus,
    ChannelExperienceLink,
    ChannelMembership,
    CommunityPost,
    ConversationChannel,
    EventBooking,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def owner(make_user):
    return make_user(role="creator")


@pytest.fixture
def space(make_space, owner):
    return make_space(creator=owner)


@pytest.fixture
def client(db, owner):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: owner
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def pathway(db, space):
    from app.models.platform import Pathway

    row = Pathway(
        id=_uid("pw"), space_id=space.id, title="Know Yourself",
        slug=f"know-yourself-{uuid.uuid4().hex[:6]}", status="active",
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def series(db, space):
    from app.models.platform import EventSeries

    row = EventSeries(
        id=_uid("es"), space_id=space.id, title="Leadership Term",
        slug=f"leadership-{uuid.uuid4().hex[:6]}",
        starts_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _create(client, space, **body):
    payload = {
        "name": "Women's Circle",
        "channel_type": "open",
        **body,
    }
    return client.post(
        f"/api/creator/spaces/{space.slug}/channels", json=payload,
    )


def _links(db, channel_id):
    rows = db.query(ChannelExperienceLink).filter(
        ChannelExperienceLink.channel_id == channel_id,
    ).all()
    return {(r.experience_type, r.experience_id) for r in rows}


class TestTheThreeArrangements:
    def test_open(self, client, space, db):
        r = _create(client, space, name="Common Ground", channel_type="open")
        assert r.status_code == 201, r.text
        assert r.json()["channel_type"] == "open"
        assert r.json()["linked_experiences"] == []

    def test_private_with_initial_members(
        self, client, space, db, make_user,
    ):
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.commit()

        r = _create(
            client, space, name="Inner Circle", channel_type="private",
            initial_member_user_ids=[member.id],
        )
        assert r.status_code == 201, r.text
        row = db.query(ChannelMembership).filter(
            ChannelMembership.channel_id == r.json()["id"],
            ChannelMembership.user_id == member.id,
        ).first()
        assert row is not None and row.status == "active"
        assert row.source == "manual"

    def test_linked_requires_at_least_one_experience(self, client, space):
        r = _create(client, space, channel_type="gathering")
        assert r.status_code == 400
        assert "at least one" in r.text


class TestLinkingManyExperiences:
    def test_three_gatherings_on_one_channel(
        self, client, space, db, make_event,
    ):
        """The headline case: an ongoing circle across three months."""
        months = [
            make_event(space=space, title=f"{m} Circle")
            for m in ("November", "December", "January")
        ]
        db.commit()

        r = _create(
            client, space, channel_type="gathering",
            linked_experiences=[
                {"type": "gathering", "id": e.id} for e in months
            ],
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body["linked_experiences"]) == 3
        assert {e["title"] for e in body["linked_experiences"]} == {
            "November Circle", "December Circle", "January Circle",
        }

    def test_mixed_kinds_on_one_channel(
        self, client, space, db, make_event, pathway, series,
    ):
        event = make_event(space=space, title="Monthly Leadership Circle")
        db.commit()

        r = _create(
            client, space, name="Personal Leadership",
            channel_type="pathway",
            linked_experiences=[
                {"type": "pathway", "id": pathway.id},
                {"type": "gathering", "id": event.id},
                {"type": "series", "id": series.id},
            ],
        )
        assert r.status_code == 201, r.text
        assert _links(db, r.json()["id"]) == {
            ("pathway", pathway.id),
            ("gathering", event.id),
            ("series", series.id),
        }

    def test_duplicates_collapse(self, client, space, db, make_event):
        event = make_event(space=space)
        db.commit()
        r = _create(
            client, space, channel_type="gathering",
            linked_experiences=[
                {"type": "gathering", "id": event.id},
                {"type": "gathering", "id": event.id},
            ],
        )
        assert r.status_code == 201, r.text
        assert len(_links(db, r.json()["id"])) == 1

    def test_a_draft_experience_may_be_linked(
        self, client, space, db, make_event,
    ):
        """A creator sets the channel up before announcing anything.

        An unpublished Gathering has no confirmed bookings, so linking
        it admits nobody — the link is preparation, not access.
        """
        draft = make_event(space=space, is_published=False, title="Draft")
        db.commit()
        r = _create(
            client, space, channel_type="gathering",
            linked_experiences=[{"type": "gathering", "id": draft.id}],
        )
        assert r.status_code == 201, r.text


class TestEditingLinks:
    @pytest.fixture
    def channel(self, client, space, db, make_event):
        a = make_event(space=space, title="November Circle")
        b = make_event(space=space, title="December Circle")
        db.commit()
        r = _create(
            client, space, channel_type="gathering",
            linked_experiences=[
                {"type": "gathering", "id": a.id},
                {"type": "gathering", "id": b.id},
            ],
        )
        assert r.status_code == 201, r.text
        return r.json()["id"], a, b

    def _patch(self, client, space, channel_id, body):
        return client.patch(
            f"/api/creator/spaces/{space.slug}/channels/{channel_id}",
            json=body,
        )

    def test_adding_one_keeps_the_others(
        self, client, space, db, channel, make_event,
    ):
        channel_id, a, b = channel
        c = make_event(space=space, title="January Circle")
        db.commit()

        r = self._patch(client, space, channel_id, {
            "linked_experiences": [
                {"type": "gathering", "id": x.id} for x in (a, b, c)
            ],
        })
        assert r.status_code == 200, r.text
        assert len(_links(db, channel_id)) == 3

    def test_removing_one_keeps_the_others(
        self, client, space, db, channel,
    ):
        channel_id, a, b = channel
        r = self._patch(client, space, channel_id, {
            "linked_experiences": [{"type": "gathering", "id": a.id}],
        })
        assert r.status_code == 200, r.text
        assert _links(db, channel_id) == {("gathering", a.id)}

    def test_an_unrelated_edit_does_not_unlink_anything(
        self, client, space, db, channel,
    ):
        """``linked_experiences`` omitted means "leave them alone"."""
        channel_id, _, _ = channel
        r = self._patch(client, space, channel_id, {"name": "Renamed"})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Renamed"
        assert len(_links(db, channel_id)) == 2

    def test_participation_and_poll_settings_survive_an_edit(
        self, client, space, db, channel,
    ):
        """§7 — these must stay editable, and stay put."""
        channel_id, _, _ = channel
        r = self._patch(client, space, channel_id, {
            "member_posting_allowed": False, "polls_allowed": False,
        })
        assert r.status_code == 200, r.text
        assert r.json()["member_posting_allowed"] is False
        assert r.json()["polls_allowed"] is False

        r = self._patch(client, space, channel_id, {"description": "Hi"})
        assert r.json()["member_posting_allowed"] is False, (
            "an unrelated edit reset a participation setting"
        )
        assert r.json()["polls_allowed"] is False

    def test_existing_posts_are_untouched_by_an_edit(
        self, client, space, db, channel, owner,
    ):
        channel_id, _, _ = channel
        post = CommunityPost(
            id=_uid("cp"), space_id=space.id, channel_id=channel_id,
            author_id=owner.id, body="Before the edit", is_visible=True,
            publication_status="published",
        )
        db.add(post)
        db.commit()

        self._patch(client, space, channel_id, {"name": "Renamed"})
        db.refresh(post)
        assert post.body == "Before the edit"
        assert db.query(CommunityPost).filter(
            CommunityPost.channel_id == channel_id,
        ).count() == 1


class TestCrossCollectiveIsRejected:
    """§9 — the hole that was open before this change.

    The old code carried a comment promising this check and only
    implemented the Series branch, so Pathways and Gatherings from
    another Collective could be linked.
    """

    def test_foreign_pathway(self, client, space, db, make_space):
        from app.models.platform import Pathway

        other = make_space()
        foreign = Pathway(
            id=_uid("pw"), space_id=other.id, title="Theirs",
            slug=f"theirs-{uuid.uuid4().hex[:6]}", status="active",
        )
        db.add(foreign)
        db.commit()

        r = _create(
            client, space, channel_type="pathway",
            linked_experiences=[{"type": "pathway", "id": foreign.id}],
        )
        assert r.status_code == 400
        assert "not in this Collective" in r.text

    def test_foreign_gathering(self, client, space, db, make_space, make_event):
        other = make_space()
        foreign = make_event(space=other)
        db.commit()

        r = _create(
            client, space, channel_type="gathering",
            linked_experiences=[{"type": "gathering", "id": foreign.id}],
        )
        assert r.status_code == 400

    def test_foreign_series(self, client, space, db, make_space):
        from app.models.platform import EventSeries

        other = make_space()
        foreign = EventSeries(
            id=_uid("es"), space_id=other.id, title="Theirs",
            slug=f"theirs-{uuid.uuid4().hex[:6]}",
            starts_at=datetime.utcnow(),
        )
        db.add(foreign)
        db.commit()

        r = _create(
            client, space, channel_type="series",
            linked_experiences=[{"type": "series", "id": foreign.id}],
        )
        assert r.status_code == 400

    def test_a_patch_cannot_sneak_one_in_either(
        self, client, space, db, make_space, make_event,
    ):
        mine = make_event(space=space)
        db.commit()
        created = _create(
            client, space, channel_type="gathering",
            linked_experiences=[{"type": "gathering", "id": mine.id}],
        ).json()["id"]

        foreign = make_event(space=make_space())
        db.commit()
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/channels/{created}",
            json={"linked_experiences": [
                {"type": "gathering", "id": foreign.id},
            ]},
        )
        assert r.status_code == 400


class TestBroadeningAccessIsConfirmed:
    """§7 — never silently expose a private conversation."""

    @pytest.fixture
    def private_channel(self, client, space, db, owner):
        created = _create(
            client, space, name="Inner Circle", channel_type="private",
        ).json()["id"]
        db.add(CommunityPost(
            id=_uid("cp"), space_id=space.id, channel_id=created,
            author_id=owner.id, body="Said in confidence",
            is_visible=True, publication_status="published",
        ))
        db.commit()
        return created

    def test_private_to_open_is_refused_without_confirmation(
        self, client, space, private_channel,
    ):
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/channels/{private_channel}",
            json={"channel_type": "open"},
        )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "would_broaden_access"

    def test_private_to_open_succeeds_when_confirmed(
        self, client, space, db, private_channel,
    ):
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/channels/{private_channel}",
            json={"channel_type": "open", "confirm_broadening": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["channel_type"] == "open"

    def test_narrowing_needs_no_confirmation(
        self, client, space, db, make_event,
    ):
        """Nobody is newly exposed by making a channel more private."""
        created = _create(
            client, space, name="Was Open", channel_type="open",
        ).json()["id"]
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/channels/{created}",
            json={"channel_type": "private"},
        )
        assert r.status_code == 200, r.text

    def test_linked_to_open_is_also_a_broadening(
        self, client, space, db, make_event,
    ):
        event = make_event(space=space)
        db.commit()
        created = _create(
            client, space, channel_type="gathering",
            linked_experiences=[{"type": "gathering", "id": event.id}],
        ).json()["id"]

        r = client.patch(
            f"/api/creator/spaces/{space.slug}/channels/{created}",
            json={"channel_type": "open"},
        )
        assert r.status_code == 409


class TestCreatorMemberManagement:
    """§6 — add and remove, on a linked channel too."""

    @pytest.fixture
    def setup(self, client, space, db, make_event, make_user):
        event = make_event(space=space)
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.add(EventBooking(
            id=_uid("bk"), event_id=event.id, user_id=member.id,
            status=BookingStatus.confirmed, source="ticket_purchase",
            booked_at=datetime.utcnow(),
        ))
        db.commit()
        channel_id = _create(
            client, space, channel_type="gathering",
            linked_experiences=[{"type": "gathering", "id": event.id}],
        ).json()["id"]
        return channel_id, member, event

    def test_the_backfill_put_the_attendee_in(self, client, space, db, setup):
        channel_id, member, _ = setup
        r = client.get(
            f"/api/creator/spaces/{space.slug}/channels/{channel_id}/members",
        )
        assert r.status_code == 200, r.text
        assert member.id in [m["user_id"] for m in r.json()]

    def test_removal_leaves_a_tombstone_not_a_hole(
        self, client, space, db, setup,
    ):
        channel_id, member, _ = setup
        r = client.delete(
            f"/api/creator/spaces/{space.slug}/channels/{channel_id}"
            f"/members/{member.id}",
        )
        assert r.status_code == 204, r.text

        row = db.query(ChannelMembership).filter(
            ChannelMembership.channel_id == channel_id,
            ChannelMembership.user_id == member.id,
        ).first()
        assert row is not None, "a DELETE would let the next webhook back in"
        assert row.status == "removed"
        assert row.removed_reason == "creator"

        listed = client.get(
            f"/api/creator/spaces/{space.slug}/channels/{channel_id}/members",
        ).json()
        assert member.id not in [m["user_id"] for m in listed]

    def test_removal_takes_nothing_else_away(
        self, client, space, db, setup,
    ):
        """§6 — not the booking, not the Collective membership."""
        channel_id, member, event = setup
        client.delete(
            f"/api/creator/spaces/{space.slug}/channels/{channel_id}"
            f"/members/{member.id}",
        )
        booking = db.query(EventBooking).filter(
            EventBooking.event_id == event.id,
            EventBooking.user_id == member.id,
        ).first()
        assert booking.status == BookingStatus.confirmed
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == member.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        ).first() is not None

    def test_the_creator_can_add_them_back(self, client, space, db, setup):
        channel_id, member, _ = setup
        client.delete(
            f"/api/creator/spaces/{space.slug}/channels/{channel_id}"
            f"/members/{member.id}",
        )
        r = client.post(
            f"/api/creator/spaces/{space.slug}/channels/{channel_id}/members",
            json={"user_ids": [member.id]},
        )
        assert r.status_code == 200, r.text
        assert member.id in [m["user_id"] for m in r.json()]

    def test_open_channels_have_no_membership_list(
        self, client, space, db, make_user,
    ):
        created = _create(
            client, space, name="Common Ground", channel_type="open",
        ).json()["id"]
        r = client.post(
            f"/api/creator/spaces/{space.slug}/channels/{created}/members",
            json={"user_ids": [make_user().id]},
        )
        assert r.status_code == 400
        assert "every Collective member" in r.text
