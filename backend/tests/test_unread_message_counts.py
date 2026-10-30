"""Unread direct messages, per Collective, on Your World.

The number behind the "✉ 1 unread message" indicator. It rides on
``/api/activities/unseen-counts`` so Your World stays at one request
however many Collectives a member belongs to, and it is kept **out**
of that response's ``total``: the activity badge and the message
indicator are two different sentences and are not added together.

What is worth testing here is the counting rule and its isolation —
a count that leaked across Collectives, or included a member's own
messages, would be wrong in a way nobody would notice until it had
been wrong for a while.
"""
from __future__ import annotations

import uuid

import pytest

import app.models.community_care  # noqa: F401
from app.models.messages import DirectMessage, MessageThread
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.message_counts import unread_message_counts


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _join(db, user, space, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=role, status=SpaceMembershipStatus.active,
    ))
    db.flush()


def _thread(db, space, creator, member):
    t = MessageThread(
        id=_uid("mt"), space_id=space.id,
        creator_id=creator.id, member_id=member.id,
    )
    db.add(t)
    db.flush()
    return t


def _msg(db, thread, sender, *, read=False, body="hello"):
    m = DirectMessage(
        id=_uid("dm"), thread_id=thread.id, sender_id=sender.id,
        body=body, is_read=read,
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def world(db, make_user, make_space):
    """One member, two Collectives, a creator in each."""
    member = make_user(name="Mem Ber")

    a_creator = make_user(role="creator", name="Ada Leader")
    a = make_space(creator=a_creator)
    _join(db, a_creator, a, role=SpaceRole.creator)
    _join(db, member, a)

    b_creator = make_user(role="creator", name="Bo Leader")
    b = make_space(creator=b_creator)
    _join(db, b_creator, b, role=SpaceRole.creator)
    _join(db, member, b)

    db.commit()
    return member, (a, a_creator), (b, b_creator)


# ---------------------------------------------------------------------------
# The counting rule
# ---------------------------------------------------------------------------

class TestWhatCounts:
    def test_nothing_unread_returns_nothing(self, db, world):
        member, (a, _), (b, _) = world
        assert unread_message_counts(db, member.id, [a.id, b.id]) == {}

    def test_one_unread_message(self, db, world):
        member, (a, a_creator), (b, _) = world
        _msg(db, _thread(db, a, a_creator, member), a_creator)
        db.commit()
        assert unread_message_counts(db, member.id, [a.id, b.id]) == {a.id: 1}

    def test_several_unread_messages(self, db, world):
        member, (a, a_creator), (b, _) = world
        t = _thread(db, a, a_creator, member)
        for i in range(3):
            _msg(db, t, a_creator, body=f"m{i}")
        db.commit()
        assert unread_message_counts(db, member.id, [a.id, b.id]) == {a.id: 3}

    def test_messages_the_member_sent_do_not_count(self, db, world):
        member, (a, a_creator), (b, _) = world
        t = _thread(db, a, a_creator, member)
        _msg(db, t, member)          # mine
        _msg(db, t, member)          # mine
        _msg(db, t, a_creator)       # theirs
        db.commit()
        assert unread_message_counts(db, member.id, [a.id, b.id]) == {a.id: 1}

    def test_read_messages_do_not_count(self, db, world):
        member, (a, a_creator), (b, _) = world
        t = _thread(db, a, a_creator, member)
        _msg(db, t, a_creator, read=True)
        _msg(db, t, a_creator, read=False)
        db.commit()
        assert unread_message_counts(db, member.id, [a.id, b.id]) == {a.id: 1}

    def test_marking_everything_read_clears_the_indicator(self, db, world):
        member, (a, a_creator), (b, _) = world
        t = _thread(db, a, a_creator, member)
        m = _msg(db, t, a_creator)
        db.commit()
        assert unread_message_counts(db, member.id, [a.id, b.id]) == {a.id: 1}

        m.is_read = True
        db.commit()
        assert unread_message_counts(db, member.id, [a.id, b.id]) == {}

    def test_a_creator_counts_replies_from_their_members(self, db, world):
        """Either side of a thread — the same rule the inbox uses."""
        member, (a, a_creator), _ = world
        t = _thread(db, a, a_creator, member)
        _msg(db, t, member)
        db.commit()
        assert unread_message_counts(db, a_creator.id, [a.id]) == {a.id: 1}
        # And the member has nothing: they sent it.
        assert unread_message_counts(db, member.id, [a.id]) == {}


# ---------------------------------------------------------------------------
# Isolation — the half that would fail quietly
# ---------------------------------------------------------------------------

class TestItStaysInItsOwnCollective:
    def test_each_collective_reports_its_own(self, db, world):
        member, (a, a_creator), (b, b_creator) = world
        ta = _thread(db, a, a_creator, member)
        tb = _thread(db, b, b_creator, member)
        _msg(db, ta, a_creator)
        for i in range(2):
            _msg(db, tb, b_creator, body=f"b{i}")
        db.commit()
        assert unread_message_counts(db, member.id, [a.id, b.id]) == {a.id: 1, b.id: 2}

    def test_a_collective_not_asked_for_is_not_returned(self, db, world):
        member, (a, a_creator), (b, b_creator) = world
        _msg(db, _thread(db, a, a_creator, member), a_creator)
        _msg(db, _thread(db, b, b_creator, member), b_creator)
        db.commit()
        assert unread_message_counts(db, member.id, [b.id]) == {b.id: 1}

    def test_somebody_elses_messages_are_never_counted(self, db, world, make_user):
        member, (a, a_creator), _ = world
        other = make_user(name="Other Member")
        _join(db, other, a)
        _msg(db, _thread(db, a, a_creator, other), a_creator)
        db.commit()
        # The thread belongs to ``other``; ``member`` has nothing.
        assert unread_message_counts(db, member.id, [a.id]) == {}
        assert unread_message_counts(db, other.id, [a.id]) == {a.id: 1}

    def test_an_empty_scope_asks_the_database_nothing(self, db, world):
        member, _, _ = world
        assert unread_message_counts(db, member.id, []) == {}
        assert unread_message_counts(db, member.id, [None]) == {}  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# How it reaches Your World
# ---------------------------------------------------------------------------

class TestItRidesOnTheExistingResponse:
    def test_the_response_carries_it_per_collective(self, db, world):
        from app.activities.routes import get_unseen_counts

        member, (a, a_creator), (b, _) = world
        _msg(db, _thread(db, a, a_creator, member), a_creator)
        db.commit()

        out = get_unseen_counts(collective_id=None, current_user=member, db=db)
        by_id = {c.collective_id: c for c in out.collectives}
        assert by_id[a.id].unread_messages == 1
        assert by_id[b.id].unread_messages == 0

    def test_it_is_not_added_to_the_activity_total(self, db, world):
        """The decision that keeps the two indicators separate."""
        from app.activities.routes import get_unseen_counts

        member, (a, a_creator), _ = world
        t = _thread(db, a, a_creator, member)
        for i in range(4):
            _msg(db, t, a_creator, body=f"m{i}")
        db.commit()

        out = get_unseen_counts(collective_id=None, current_user=member, db=db)
        row = next(c for c in out.collectives if c.collective_id == a.id)
        assert row.unread_messages == 4
        assert row.total == 0          # no activity happened
        assert out.total == 0          # and the page total is unmoved

    def test_messages_are_still_absent_from_the_activity_feed(self):
        """Recent Moments is not an inbox, and this did not make it one."""
        from app.services.activity_counts import COUNTED_CATEGORIES

        assert "personal" not in COUNTED_CATEGORIES
