"""A discussion says where it lives.

The post detail page offered a "← Conversations" link and nothing
else, so a member arriving from Recent Moments could read a thread
without ever learning which Channel it was in — and went back to the
Collective's default Channel rather than the one holding the post.

The Channel is resolved from the row the endpoint already loaded to
run its access gate, so these fields cost no extra query. And they
carry no permission flag of their own: reaching this payload required
``can_view_channel``, which is the same predicate the Channel feed
applies, so a reader holding the response is always authorised for
the feed it names.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.community.routes import get_community_post
from app.models.platform import (
    BookingStatus,
    CommunityPost,
    ConversationChannel,
    Event,
    EventBooking,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _member(db, user, space, *, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id, role=role,
        status=SpaceMembershipStatus.active, joined_at=datetime.utcnow(),
    ))
    db.flush()


def _channel(db, space, *, channel_type="open", name="Announcements", **kw):
    c = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name=name,
        slug=f"ch-{uuid.uuid4().hex[:8]}", channel_type=channel_type, **kw,
    )
    db.add(c); db.flush()
    return c


def _post(db, space, channel, author, *, title="A thread"):
    p = CommunityPost(
        id=_uid("cp"), space_id=space.id, channel_id=channel.id,
        author_id=author.id, title=title, body="hello",
        publication_status="published",
    )
    db.add(p); db.flush()
    return p


def _gathering(db, space):
    e = Event(
        id=_uid("e"), space_id=space.id, created_by_id=space.creator_id,
        title="Full Moon", starts_at=datetime.utcnow() + timedelta(days=3),
        ends_at=datetime.utcnow() + timedelta(days=3, hours=1),
        is_published=True, status="active", requires_booking=True,
        capacity=20, gathering_type="circle", attendance_format="online",
    )
    db.add(e); db.flush()
    return e


def _call(db, user, space, post):
    return get_community_post(space.slug, post.id, db=db, current_user=user)


class TestTheChannelIsNamed:
    def test_an_open_channel_reports_itself(self, db, make_space, make_user):
        space = make_space(); author = make_user(); member = make_user()
        _member(db, member, space)
        ch = _channel(db, space, channel_type="open", name="Announcements")
        post = _post(db, space, ch, author)
        db.commit()

        out = _call(db, member, space, post)
        assert out.channel_slug == ch.slug
        assert out.channel_name == "Announcements"
        assert out.channel_type == "open"
        assert out.channel_group_label == "OPEN DISCUSSIONS"

    def test_a_system_channel_has_no_group(self, db, make_space, make_user):
        # Start Here and Common Room belong to no heading in the
        # selector, so they report none here either.
        space = make_space(); author = make_user(); member = make_user()
        _member(db, member, space)
        ch = _channel(db, space, channel_type="general", name="Common Room",
                      is_default=True, is_system=True)
        post = _post(db, space, ch, author)
        db.commit()

        out = _call(db, member, space, post)
        assert out.channel_name == "Common Room"
        assert out.channel_group_label is None

    def test_a_pathway_channel_reports_its_type(self, db, make_space, make_user):
        space = make_space(); author = make_user(); member = make_user()
        _member(db, member, space)
        ch = _channel(db, space, channel_type="open", name="A Little Guide")
        post = _post(db, space, ch, author)
        db.commit()

        out = _call(db, member, space, post)
        assert out.channel_name == "A Little Guide"
        assert out.channel_type == "open"


class TestAccessIsUnchanged:
    """The new fields must not have widened anything. The gate that
    was already there is the only thing deciding who gets a payload at
    all — so there is nothing to name for someone it refuses."""

    def test_an_unbooked_member_still_gets_nothing(self, db, make_space, make_user):
        space = make_space(); author = make_user(); member = make_user()
        _member(db, member, space)
        ev = _gathering(db, space)
        ch = _channel(db, space, channel_type="gathering", name="Full Moon")
        ch.gathering_id = ev.id
        db.flush()
        post = _post(db, space, ch, author)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            _call(db, member, space, post)
        assert exc.value.status_code == 404, (
            "the confirmed-booking rule still decides, and 404 not 403"
        )

    def test_a_booked_member_gets_the_channel_named(self, db, make_space, make_user):
        # The control, and the proof the gathering branch is reached by
        # permission rather than by the field being absent.
        space = make_space(); author = make_user(); member = make_user()
        _member(db, member, space)
        ev = _gathering(db, space)
        ch = _channel(db, space, channel_type="gathering", name="Full Moon")
        ch.gathering_id = ev.id
        db.flush()
        db.add(EventBooking(
            id=_uid("bk"), event_id=ev.id, user_id=member.id,
            status=BookingStatus.confirmed, booked_at=datetime.utcnow(),
        ))
        post = _post(db, space, ch, author)
        db.commit()

        out = _call(db, member, space, post)
        assert out.channel_name == "Full Moon"
        assert out.channel_group_label == "GATHERINGS"

    def test_a_hidden_channel_still_names_itself(self, db, make_space, make_user):
        """A navigation-hidden Channel stays readable by direct link,
        so a post inside one must still say where it is — that link is
        the member's only route back to it."""
        space = make_space(); author = make_user(); member = make_user()
        _member(db, member, space)
        ch = _channel(db, space, channel_type="open", name="Quiet Corner")
        ch.show_in_navigation = False
        db.flush()
        post = _post(db, space, ch, author)
        db.commit()

        out = _call(db, member, space, post)
        assert out.channel_slug == ch.slug
        assert out.channel_name == "Quiet Corner"
