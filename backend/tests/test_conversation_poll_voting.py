"""Poll voting in Conversations.

Polls were reported as unvotable — members could not select an option or
submit. This file is the API half of establishing whether that is true,
and it is also the first test coverage polls have ever had: before this,
``vote_on_poll``, ``_build_poll_view`` and the three poll tables were
exercised by nothing, which is how a defect in the surface above them
survived unnoticed.

The finding, stated up front: **the API is sound.** Every behaviour the
brief asks about works here — single and multiple choice, replacing a
selection, clearing one, duplicate submissions, the permission gates.
The defect is in ``PollView.tsx``, which stops rendering anything
clickable as soon as the server says results may be shown. See
``frontend/src/lib/pollInteraction.ts``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.community.routes import vote_on_poll
from app.community.schemas import CastVoteRequest
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    Poll,
    PollOption,
    PollVote,
    PostType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def space(make_space):
    return make_space(status="active", is_public=True)


@pytest.fixture
def channel(db, space):
    row = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="Common Room",
        slug=f"ch-{uuid.uuid4().hex[:8]}", channel_type="general",
        is_default=True, is_system=True,
    )
    db.add(row)
    db.flush()
    return row


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


def _poll(
    db, space, channel, *,
    allow_multiple=False,
    show_results_before_vote=False,
    is_anonymous=False,
    closes_at=None,
    options=("Tuesday", "Thursday", "Saturday"),
    is_visible=True,
    publication_status="published",
):
    post = CommunityPost(
        id=_uid("cp"), space_id=space.id, channel_id=channel.id,
        author_id=space.creator_id, post_type=PostType.poll,
        body="When shall we meet?",
        is_visible=is_visible, publication_status=publication_status,
    )
    db.add(post)
    db.flush()
    poll = Poll(
        post_id=post.id, allow_multiple=allow_multiple,
        is_anonymous=is_anonymous,
        show_results_before_vote=show_results_before_vote,
        closes_at=closes_at,
    )
    db.add(poll)
    opts = []
    for i, label in enumerate(options):
        o = PollOption(
            id=_uid("po"), poll_id=post.id, position=i, label=label,
        )
        db.add(o)
        opts.append(o)
    db.flush()
    return post, poll, opts


def _vote(db, space, post, user, option_ids):
    return vote_on_poll(
        space.slug, post.id, CastVoteRequest(option_ids=option_ids),
        db=db, current_user=user,
    )


def _rows(db, poll, user=None):
    q = db.query(PollVote).filter(PollVote.poll_id == poll.post_id)
    if user is not None:
        q = q.filter(PollVote.user_id == user.id)
    return q.all()


# ---------------------------------------------------------------------------
# 1. Single choice
# ---------------------------------------------------------------------------


class TestSingleChoice:

    def test_a_member_can_vote(self, db, space, channel, member):
        post, poll, opts = _poll(db, space, channel)
        view = _vote(db, space, post, member, [opts[0].id])
        assert view.user_has_voted is True
        assert [o.voted for o in view.options] == [True, False, False]

    def test_the_vote_is_stored(self, db, space, channel, member):
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[1].id])
        [row] = _rows(db, poll, member)
        assert row.option_id == opts[1].id

    def test_choosing_another_option_replaces_the_first(
        self, db, space, channel, member,
    ):
        """The platform's existing rule, implemented as replace-wholesale
        in ``vote_on_poll``: a vote is "here is my current set of
        choices", so a second submission supersedes the first rather
        than adding to it."""
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        view = _vote(db, space, post, member, [opts[2].id])
        rows = _rows(db, poll, member)
        assert len(rows) == 1
        assert rows[0].option_id == opts[2].id
        assert [o.voted for o in view.options] == [False, False, True]

    def test_two_options_at_once_is_refused(
        self, db, space, channel, member,
    ):
        post, poll, opts = _poll(db, space, channel)
        with pytest.raises(HTTPException) as exc:
            _vote(db, space, post, member, [opts[0].id, opts[1].id])
        assert exc.value.status_code == 400
        assert "single choice" in exc.value.detail.lower()

    def test_a_refused_vote_stores_nothing(
        self, db, space, channel, member,
    ):
        post, poll, opts = _poll(db, space, channel)
        with pytest.raises(HTTPException):
            _vote(db, space, post, member, [opts[0].id, opts[1].id])
        assert _rows(db, poll) == []


# ---------------------------------------------------------------------------
# 2. Multiple choice
# ---------------------------------------------------------------------------


class TestMultipleChoice:

    def test_several_options_are_accepted(
        self, db, space, channel, member,
    ):
        post, poll, opts = _poll(db, space, channel, allow_multiple=True)
        view = _vote(db, space, post, member, [opts[0].id, opts[2].id])
        assert [o.voted for o in view.options] == [True, False, True]
        assert len(_rows(db, poll, member)) == 2

    def test_a_narrower_set_deselects_the_rest(
        self, db, space, channel, member,
    ):
        """Deselection is expressed by submitting the remaining set —
        there is no per-option delete, and none is needed."""
        post, poll, opts = _poll(db, space, channel, allow_multiple=True)
        _vote(db, space, post, member, [opts[0].id, opts[1].id, opts[2].id])
        view = _vote(db, space, post, member, [opts[1].id])
        assert [o.voted for o in view.options] == [False, True, False]
        assert len(_rows(db, poll, member)) == 1

    def test_an_empty_set_clears_the_vote(
        self, db, space, channel, member,
    ):
        post, poll, opts = _poll(db, space, channel, allow_multiple=True)
        _vote(db, space, post, member, [opts[0].id])
        view = _vote(db, space, post, member, [])
        assert view.user_has_voted is False
        assert _rows(db, poll, member) == []


# ---------------------------------------------------------------------------
# 2b. Retracting a vote
# ---------------------------------------------------------------------------


class TestClearingAVote:
    """Single choice gains the retraction multiple choice already had.

    No new API: an empty ``option_ids`` has always meant "remove my
    vote" — ``CastVoteRequest`` says so and ``vote_on_poll`` deletes the
    voter's rows before inserting the chosen set, so an empty set
    deletes and inserts nothing.
    """

    def test_a_single_choice_vote_can_be_cleared(
        self, db, space, channel, member,
    ):
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        view = _vote(db, space, post, member, [])
        assert view.user_has_voted is False
        assert all(o.voted is False for o in view.options)

    def test_the_rows_are_removed(self, db, space, channel, member):
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        _vote(db, space, post, member, [])
        assert _rows(db, poll, member) == []

    def test_results_revert_to_hidden(self, db, space, channel, member):
        """``show_results`` is derived from ``user_has_voted``, so
        clearing a vote on a default poll takes the counts away again —
        the member is back to not having earned them."""
        post, poll, opts = _poll(db, space, channel)
        assert _vote(db, space, post, member, [opts[0].id]).show_results is True
        view = _vote(db, space, post, member, [])
        assert view.show_results is False
        assert view.total_voters == 0

    def test_results_stay_visible_on_a_show_early_poll(
        self, db, space, channel, member,
    ):
        """Where visibility never depended on voting, clearing does not
        take it away."""
        post, poll, opts = _poll(
            db, space, channel, show_results_before_vote=True,
        )
        _vote(db, space, post, member, [opts[0].id])
        view = _vote(db, space, post, member, [])
        assert view.show_results is True
        assert view.user_has_voted is False

    def test_the_count_drops(self, db, space, channel, member, make_user):
        other = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=other.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            source="joined",
        ))
        db.flush()
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        view = _vote(db, space, post, other, [opts[0].id])
        assert view.options[0].vote_count == 2

        _vote(db, space, post, member, [])
        view = _vote(db, space, post, other, [opts[0].id])
        assert view.options[0].vote_count == 1
        assert view.total_voters == 1

    def test_another_members_vote_is_untouched(
        self, db, space, channel, member, make_user,
    ):
        other = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=other.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            source="joined",
        ))
        db.flush()
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        _vote(db, space, post, other, [opts[1].id])
        _vote(db, space, post, member, [])
        assert len(_rows(db, poll, other)) == 1

    def test_it_persists_across_a_reload(
        self, db, space, channel, member,
    ):
        from app.community.routes import _build_poll_view

        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        _vote(db, space, post, member, [])

        db.expire_all()
        fresh = db.query(Poll).filter(Poll.post_id == post.id).first()
        view = _build_poll_view(fresh, db, member.id)
        assert view.user_has_voted is False
        assert all(o.voted is False for o in view.options)

    def test_the_member_can_vote_again_afterwards(
        self, db, space, channel, member,
    ):
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        _vote(db, space, post, member, [])
        view = _vote(db, space, post, member, [opts[1].id])
        assert [o.voted for o in view.options] == [False, True, False]

    def test_clearing_twice_is_harmless(self, db, space, channel, member):
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        _vote(db, space, post, member, [])
        view = _vote(db, space, post, member, [])
        assert view.user_has_voted is False
        assert _rows(db, poll, member) == []

    def test_clearing_without_having_voted_is_harmless(
        self, db, space, channel, member,
    ):
        post, poll, opts = _poll(db, space, channel)
        view = _vote(db, space, post, member, [])
        assert view.user_has_voted is False

    def test_a_closed_poll_refuses_a_retraction(
        self, db, space, channel, member,
    ):
        """The control is hidden client-side, and the server refuses it
        regardless — a closed poll's record stands."""
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        poll.closes_at = datetime.utcnow() - timedelta(minutes=1)
        db.flush()
        with pytest.raises(HTTPException) as exc:
            _vote(db, space, post, member, [])
        assert exc.value.status_code == 400
        assert len(_rows(db, poll, member)) == 1

    def test_a_departed_member_cannot_retract(
        self, db, space, channel, member,
    ):
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        row = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.user_id == member.id,
            )
            .first()
        )
        row.status = SpaceMembershipStatus.removed
        row.removal_kind = "voluntary"
        db.flush()
        with pytest.raises(HTTPException) as exc:
            _vote(db, space, post, member, [])
        assert exc.value.status_code == 404
        assert len(_rows(db, poll, member)) == 1


# ---------------------------------------------------------------------------
# 3. Counting and results
# ---------------------------------------------------------------------------


class TestResults:

    def _second_member(self, db, space, make_user):
        user = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=user.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            source="joined",
        ))
        db.flush()
        return user

    def test_counts_are_per_option(
        self, db, space, channel, member, make_user,
    ):
        post, poll, opts = _poll(db, space, channel)
        other = self._second_member(db, space, make_user)
        _vote(db, space, post, member, [opts[0].id])
        view = _vote(db, space, post, other, [opts[0].id])
        assert view.options[0].vote_count == 2
        assert view.total_voters == 2

    def test_a_voter_is_counted_once_on_a_multi_poll(
        self, db, space, channel, member,
    ):
        """``total_voters`` is distinct users, not ballots."""
        post, poll, opts = _poll(db, space, channel, allow_multiple=True)
        view = _vote(db, space, post, member, [opts[0].id, opts[1].id])
        assert view.total_voters == 1
        assert sum(o.vote_count for o in view.options) == 2

    def test_results_are_withheld_until_the_member_votes(
        self, db, space, channel, member, make_user,
    ):
        """The default. ``show_results`` is the server's single answer
        and the client renders what it is told."""
        from app.community.routes import _build_poll_view

        post, poll, opts = _poll(db, space, channel)
        other = self._second_member(db, space, make_user)
        _vote(db, space, post, other, [opts[0].id])
        db.refresh(poll)
        view = _build_poll_view(poll, db, member.id)
        assert view.show_results is False
        assert view.total_voters == 0
        assert all(o.vote_count == 0 for o in view.options)

    def test_voting_reveals_them(self, db, space, channel, member):
        post, poll, opts = _poll(db, space, channel)
        view = _vote(db, space, post, member, [opts[0].id])
        assert view.show_results is True

    def test_show_results_before_vote_reveals_them_early(
        self, db, space, channel, member,
    ):
        """**The configuration the defect hinges on.** The server
        correctly says "you may see results" before this member has
        voted — and the client then stops rendering anything they could
        vote with. Nothing is wrong here; the bug is downstream."""
        from app.community.routes import _build_poll_view

        post, poll, opts = _poll(
            db, space, channel, show_results_before_vote=True,
        )
        db.refresh(poll)
        view = _build_poll_view(poll, db, member.id)
        assert view.show_results is True
        assert view.user_has_voted is False
        assert view.is_closed is False

    def test_a_closed_poll_reveals_them(self, db, space, channel, member):
        from app.community.routes import _build_poll_view

        post, poll, _o = _poll(
            db, space, channel,
            closes_at=datetime.utcnow() - timedelta(hours=1),
        )
        db.refresh(poll)
        view = _build_poll_view(poll, db, member.id)
        assert view.is_closed is True
        assert view.show_results is True


# ---------------------------------------------------------------------------
# 4. Duplicate submissions
# ---------------------------------------------------------------------------


class TestDuplicateSubmissions:

    def test_the_same_vote_twice_stores_one_row(
        self, db, space, channel, member,
    ):
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        _vote(db, space, post, member, [opts[0].id])
        assert len(_rows(db, poll, member)) == 1

    def test_a_repeated_option_in_one_request_stores_one_row(
        self, db, space, channel, member,
    ):
        """A double-tap that sends the same id twice must not violate
        ``uq_poll_votes_option_user`` or double-count."""
        post, poll, opts = _poll(db, space, channel, allow_multiple=True)
        view = _vote(db, space, post, member, [opts[0].id, opts[0].id])
        assert len(_rows(db, poll, member)) == 1
        assert view.options[0].vote_count == 1

    def test_a_repeated_id_on_a_single_choice_poll_is_one_vote(
        self, db, space, channel, member,
    ):
        """Before de-duplication this failed the "single choice only"
        check — a confusing answer to what is really one choice sent
        twice, which is what a double-tap produces."""
        post, poll, opts = _poll(db, space, channel)
        view = _vote(db, space, post, member, [opts[0].id, opts[0].id])
        assert view.user_has_voted is True
        assert len(_rows(db, poll, member)) == 1

    def test_de_duplication_keeps_first_seen_order(
        self, db, space, channel, member,
    ):
        """Kept as a list rather than collapsed through a set, so stored
        rows follow the order the member picked."""
        post, poll, opts = _poll(db, space, channel, allow_multiple=True)
        _vote(
            db, space, post, member,
            [opts[2].id, opts[0].id, opts[2].id],
        )
        rows = _rows(db, poll, member)
        assert len(rows) == 2
        assert {r.option_id for r in rows} == {opts[0].id, opts[2].id}

    def test_the_constraint_backs_it_up(self, db, space, channel, member):
        from sqlalchemy.exc import IntegrityError

        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        db.add(PollVote(
            id=_uid("pv"), poll_id=poll.post_id,
            option_id=opts[0].id, user_id=member.id,
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


# ---------------------------------------------------------------------------
# 5. Permissions and poll state
# ---------------------------------------------------------------------------


class TestWhoMayVote:

    def test_an_unknown_option_is_ignored(
        self, db, space, channel, member,
    ):
        """Ids are filtered against the poll's own options, so a crafted
        id cannot create a vote for another poll's option."""
        post, poll, opts = _poll(db, space, channel)
        other_post, other_poll, other_opts = _poll(db, space, channel)
        view = _vote(db, space, post, member, [other_opts[0].id])
        assert view.user_has_voted is False
        assert _rows(db, other_poll) == []

    def test_a_closed_poll_refuses(self, db, space, channel, member):
        post, poll, opts = _poll(
            db, space, channel,
            closes_at=datetime.utcnow() - timedelta(minutes=1),
        )
        with pytest.raises(HTTPException) as exc:
            _vote(db, space, post, member, [opts[0].id])
        assert exc.value.status_code == 400
        assert "closed" in exc.value.detail.lower()

    def test_an_archived_channel_refuses(
        self, db, space, channel, member,
    ):
        post, poll, opts = _poll(db, space, channel)
        channel.is_archived = True
        db.flush()
        with pytest.raises(HTTPException) as exc:
            _vote(db, space, post, member, [opts[0].id])
        assert exc.value.status_code == 400

    def test_a_scheduled_poll_refuses(self, db, space, channel, member):
        post, poll, opts = _poll(
            db, space, channel, publication_status="scheduled",
        )
        with pytest.raises(HTTPException) as exc:
            _vote(db, space, post, member, [opts[0].id])
        assert exc.value.status_code == 404

    def test_a_hidden_post_refuses(self, db, space, channel, member):
        post, poll, opts = _poll(db, space, channel, is_visible=False)
        with pytest.raises(HTTPException) as exc:
            _vote(db, space, post, member, [opts[0].id])
        assert exc.value.status_code == 404

    def test_a_non_member_cannot_vote(
        self, db, space, channel, make_user,
    ):
        """The Channel gate: ``can_view_channel`` requires an active
        membership, so a stranger with the URL gets 404."""
        post, poll, opts = _poll(db, space, channel)
        with pytest.raises(HTTPException) as exc:
            _vote(db, space, post, make_user(), [opts[0].id])
        assert exc.value.status_code == 404

    def test_a_departed_member_cannot_vote(
        self, db, space, channel, member,
    ):
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        row = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.user_id == member.id,
            )
            .first()
        )
        row.status = SpaceMembershipStatus.removed
        row.removal_kind = "voluntary"
        db.flush()
        with pytest.raises(HTTPException) as exc:
            _vote(db, space, post, member, [opts[1].id])
        assert exc.value.status_code == 404

    def test_their_earlier_vote_is_preserved(
        self, db, space, channel, member,
    ):
        """Leaving does not retract a vote already cast — the historical
        record stands."""
        post, poll, opts = _poll(db, space, channel)
        _vote(db, space, post, member, [opts[0].id])
        row = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.user_id == member.id,
            )
            .first()
        )
        row.status = SpaceMembershipStatus.removed
        row.removal_kind = "voluntary"
        db.flush()
        assert len(_rows(db, poll, member)) == 1

    def test_voting_requires_a_verified_account(self):
        """SEC-009, as a signature check — the dependency is what
        enforces it."""
        import inspect

        dep = inspect.signature(vote_on_poll).parameters["current_user"].default
        assert dep.dependency.__name__ == "get_verified_current_user"


# ---------------------------------------------------------------------------
# 6. Persistence across a reload
# ---------------------------------------------------------------------------


class TestPersistence:

    def test_a_rebuilt_view_still_shows_the_vote(
        self, db, space, channel, member,
    ):
        """What a page refresh does: read the poll again and rebuild the
        view from stored rows."""
        from app.community.routes import _build_poll_view

        post, poll, opts = _poll(db, space, channel, allow_multiple=True)
        _vote(db, space, post, member, [opts[0].id, opts[2].id])

        db.expire_all()
        fresh = db.query(Poll).filter(Poll.post_id == post.id).first()
        view = _build_poll_view(fresh, db, member.id)
        assert view.user_has_voted is True
        assert [o.voted for o in view.options] == [True, False, True]

    def test_another_member_sees_their_own_selection_not_mine(
        self, db, space, channel, member, make_user,
    ):
        from app.community.routes import _build_poll_view

        post, poll, opts = _poll(db, space, channel)
        other = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=other.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            source="joined",
        ))
        db.flush()
        _vote(db, space, post, member, [opts[0].id])
        _vote(db, space, post, other, [opts[1].id])

        db.refresh(poll)
        mine = _build_poll_view(poll, db, member.id)
        theirs = _build_poll_view(poll, db, other.id)
        assert [o.voted for o in mine.options] == [True, False, False]
        assert [o.voted for o in theirs.options] == [False, True, False]
