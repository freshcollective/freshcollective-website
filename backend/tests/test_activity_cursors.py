"""Phase 2 — advancing a member's seen mark.

The cursor is the only thing standing between "you have seen this" and
"we have decided you have seen this". Two properties carry almost all
of the risk:

* it must never move backwards, or a slow response or a second tab
  reopens activity that was already cleared;
* it must never move further than the member could actually have been
  shown, or a crafted request silently buries activity that nothing
  will ever surface again.

Both are enforced in the service rather than trusted from the client,
and both are tested here against the attempt, not just the happy path.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.activity import Activity, CollectiveActivityCursor
from app.models.platform import (
    ConversationChannel,
    Pathway,
    PathwayStatus,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.activity_counts import unseen_counts
from app.services.activity_cursors import CursorRefused, advance


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _member(db, user, space, *, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id, role=role,
        status=SpaceMembershipStatus.active,
        joined_at=datetime.utcnow() - timedelta(days=30),
    ))
    db.flush()


def _pathway(db, space):
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="A Pathway", status=PathwayStatus.active, access_type="free",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p); db.flush()
    return p


def _activity(db, space, actor, *, created_at=None, category="pathways",
              event_type="pathway_published", **subject):
    if not subject:
        subject = {"pathway_id": _pathway(db, space).id}
    a = Activity(
        id=_uid("act"), event_type=event_type, category=category,
        priority="standard", actor_user_id=actor.id, recipient_user_id=None,
        collective_id=space.id, payload={}, dedupe_key=_uid("k"), **subject,
    )
    if created_at is not None:
        a.created_at = created_at
    db.add(a); db.flush()
    return a


def _cursor(db, user, space, category="pathways"):
    return (
        db.query(CollectiveActivityCursor)
        .filter(
            CollectiveActivityCursor.user_id == user.id,
            CollectiveActivityCursor.collective_id == space.id,
            CollectiveActivityCursor.category == category,
        )
        .first()
    )


def _total(db, user):
    return sum(c.total for c in unseen_counts(db, user))


# ---------------------------------------------------------------------------
# Creation and ordinary advancement
# ---------------------------------------------------------------------------

class TestAdvancing:
    def test_the_first_advance_creates_the_row(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        a = _activity(db, space, creator)
        db.commit()
        assert _cursor(db, member, space) is None, "nothing written before a visit"

        advance(db, member, collective_id=space.id, category="pathways",
                through_sequence=a.sequence_number)
        db.commit()

        row = _cursor(db, member, space)
        assert row is not None and row.seen_through_seq == a.sequence_number
        assert _total(db, member) == 0

    def test_a_later_visit_moves_it_further(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        first = _activity(db, space, creator)
        db.commit()
        advance(db, member, collective_id=space.id, category="pathways",
                through_sequence=first.sequence_number)
        db.commit()

        second = _activity(db, space, creator)
        db.commit()
        assert _total(db, member) == 1

        advance(db, member, collective_id=space.id, category="pathways",
                through_sequence=second.sequence_number)
        db.commit()

        assert _cursor(db, member, space).seen_through_seq == second.sequence_number
        assert _total(db, member) == 0

    def test_advancing_one_category_leaves_the_others(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw_row = _activity(db, space, creator)
        db.add(ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="R",
            slug=f"c-{uuid.uuid4().hex[:8]}", channel_type="open",
        ))
        db.commit()
        advance(db, member, collective_id=space.id, category="pathways",
                through_sequence=pw_row.sequence_number)
        db.commit()

        assert _cursor(db, member, space, "pathways") is not None
        assert _cursor(db, member, space, "conversations") is None

    def test_advancing_one_collective_leaves_the_other(self, db, make_space, make_user):
        a, b = make_space(), make_space()
        creator = make_user(); member = make_user()
        _member(db, member, a); _member(db, member, b)
        ra = _activity(db, a, creator)
        _activity(db, b, creator)
        db.commit()

        advance(db, member, collective_id=a.id, category="pathways",
                through_sequence=ra.sequence_number)
        db.commit()

        assert _total(db, member) == 1, "only the visited Collective cleared"


# ---------------------------------------------------------------------------
# Forward only — tabs and out-of-order responses
# ---------------------------------------------------------------------------

class TestForwardOnly:
    def test_an_older_mark_cannot_move_it_back(self, db, make_space, make_user):
        """A response from an earlier request arriving late."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        first = _activity(db, space, creator)
        second = _activity(db, space, creator)
        db.commit()

        advance(db, member, collective_id=space.id, category="pathways",
                through_sequence=second.sequence_number)
        db.commit()
        advance(db, member, collective_id=space.id, category="pathways",
                through_sequence=first.sequence_number)
        db.commit()

        assert _cursor(db, member, space).seen_through_seq == second.sequence_number
        assert _total(db, member) == 0, "the stale mark must not reopen anything"

    def test_two_tabs_settle_on_the_higher_mark(self, db, make_space, make_user):
        """Two tabs rendered different amounts and report independently;
        the order they arrive in must not matter."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        rows = [_activity(db, space, creator) for _ in range(3)]
        db.commit()
        tab_a = rows[0].sequence_number      # opened earlier, saw less
        tab_b = rows[2].sequence_number      # opened later, saw everything

        for order in ([tab_b, tab_a], [tab_a, tab_b]):
            db.query(CollectiveActivityCursor).delete()
            db.commit()
            for seq in order:
                advance(db, member, collective_id=space.id,
                        category="pathways", through_sequence=seq)
                db.commit()
            assert _cursor(db, member, space).seen_through_seq == tab_b, (
                f"arrival order {order} changed the outcome"
            )

    def test_the_timestamp_half_moves_forward_too(self, db, make_space, make_user):
        """Both columns take the greater value, so they cannot end up
        describing different visits."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        old = _activity(db, space, creator,
                        created_at=datetime.utcnow() - timedelta(days=5))
        new = _activity(db, space, creator)
        db.commit()

        advance(db, member, collective_id=space.id, category="pathways",
                through_sequence=new.sequence_number)
        db.commit()
        before = _cursor(db, member, space).seen_through
        advance(db, member, collective_id=space.id, category="pathways",
                through_sequence=old.sequence_number)
        db.commit()

        assert _cursor(db, member, space).seen_through == before


# ---------------------------------------------------------------------------
# The mid-visit rule — the subtle one
# ---------------------------------------------------------------------------

class TestActivityArrivingDuringAVisit:
    def test_something_published_while_you_read_is_not_cleared(
        self, db, make_space, make_user,
    ):
        """The mark is the newest thing *rendered*, never ``now()``.
        Anything created after the page loaded is above it and
        survives — which is the whole reason this is a cursor and not
        a 'mark all seen' button."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        rendered = [_activity(db, space, creator) for _ in range(2)]
        db.commit()
        high_water = max(r.sequence_number for r in rendered)

        # ... the member is reading; a Pathway is published meanwhile.
        mid_visit = _activity(db, space, creator)
        db.commit()

        # ... and only then does the page report what it had shown.
        advance(db, member, collective_id=space.id, category="pathways",
                through_sequence=high_water)
        db.commit()

        assert _total(db, member) == 1, "the mid-visit publication was cleared"
        assert _cursor(db, member, space).seen_through_seq < mid_visit.sequence_number

    def test_a_client_claiming_now_cannot_clear_the_future(
        self, db, make_space, make_user,
    ):
        """Even if a client reports far beyond what exists, the clamp
        holds it to the newest row that actually exists — so activity
        created afterwards still counts."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        _activity(db, space, creator)
        db.commit()

        advance(db, member, collective_id=space.id, category="pathways",
                through_sequence=9_999_999)
        db.commit()

        later = _activity(db, space, creator)
        db.commit()
        assert _total(db, member) == 1
        assert _cursor(db, member, space).seen_through_seq < later.sequence_number


# ---------------------------------------------------------------------------
# Safeguards — what a client may not do
# ---------------------------------------------------------------------------

class TestTheClampOnWhatWasPresented:
    def test_an_arbitrary_future_sequence_is_clamped(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        real = _activity(db, space, creator)
        db.commit()

        state = advance(db, member, collective_id=space.id,
                        category="pathways", through_sequence=2_000_000_000)
        db.commit()

        assert state.seen_through_seq == real.sequence_number, (
            "the cursor must not pass the newest row this member could see"
        )

    def test_the_clamp_uses_what_this_member_may_see_not_what_exists(
        self, db, make_space, make_user,
    ):
        """A private-channel thread nobody showed them must not raise
        the ceiling — otherwise a crafted request could clear activity
        they are entitled to, by pointing past activity they are not."""
        space = make_space(); author = make_user(); member = make_user()
        _member(db, author, space); _member(db, member, space)
        visible = _activity(db, space, author)
        private = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Private",
            slug=f"c-{uuid.uuid4().hex[:8]}", channel_type="private",
        )
        db.add(private); db.flush()
        from app.models.platform import CommunityPost

        hidden_post = CommunityPost(
            id=_uid("cp"), space_id=space.id, channel_id=private.id,
            author_id=author.id, title="Hidden", body="x",
            publication_status="published",
        )
        db.add(hidden_post); db.flush()
        hidden = _activity(
            db, space, author, category="conversations",
            event_type="conversation_created", conversation_id=hidden_post.id,
        )
        db.commit()
        assert hidden.sequence_number > visible.sequence_number

        state = advance(db, member, collective_id=space.id,
                        category="pathways", through_sequence=hidden.sequence_number)
        db.commit()

        assert state.seen_through_seq == visible.sequence_number

    def test_your_own_activity_does_not_raise_the_ceiling(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space); _member(db, creator, space)
        theirs = _activity(db, space, creator)
        mine = _activity(db, space, member)
        db.commit()
        assert mine.sequence_number > theirs.sequence_number

        state = advance(db, member, collective_id=space.id,
                        category="pathways", through_sequence=mine.sequence_number)
        db.commit()
        assert state.seen_through_seq == theirs.sequence_number


class TestRefusals:
    def test_a_non_member_cannot_advance(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); outsider = make_user()
        _activity(db, space, creator)
        db.commit()

        with pytest.raises(CursorRefused) as e:
            advance(db, outsider, collective_id=space.id,
                    category="pathways", through_sequence=1)
        assert e.value.reason == "not_a_member"
        assert db.query(CollectiveActivityCursor).count() == 0

    def test_an_unknown_category_is_refused(self, db, make_space, make_user):
        space = make_space(); member = make_user()
        _member(db, member, space); db.commit()

        for bad in ("personal", "account", "collective", "", "pathways; drop"):
            with pytest.raises(CursorRefused) as e:
                advance(db, member, collective_id=space.id,
                        category=bad, through_sequence=1)
            assert e.value.reason == "unknown_category"

    def test_a_negative_or_non_integer_sequence_is_refused(
        self, db, make_space, make_user,
    ):
        space = make_space(); member = make_user()
        _member(db, member, space); db.commit()

        for bad in (-1, True, "5", 1.5, None):
            with pytest.raises(CursorRefused) as e:
                advance(db, member, collective_id=space.id,
                        category="pathways", through_sequence=bad)
            assert e.value.reason == "invalid_sequence"

    def test_an_unreachable_area_is_refused(self, db, make_space, make_user):
        space = make_space()
        space.area_policies = {"areas": {"pathways": "active_access"}}
        creator = make_user(); member = make_user()
        _member(db, member, space)
        a = _activity(db, space, creator)
        db.commit()

        with pytest.raises(CursorRefused) as e:
            advance(db, member, collective_id=space.id,
                    category="pathways", through_sequence=a.sequence_number)
        assert e.value.reason == "area_unreachable"

    def test_an_unknown_collective_is_refused_as_not_a_member(
        self, db, make_space, make_user,
    ):
        member = make_user()
        db.commit()
        with pytest.raises(CursorRefused) as e:
            advance(db, member, collective_id="s_does_not_exist",
                    category="pathways", through_sequence=1)
        assert e.value.reason == "not_a_member"


class TestOneMemberCannotTouchAnother:
    def test_the_cursor_always_belongs_to_the_caller(
        self, db, make_space, make_user,
    ):
        """The request names a Collective and a category — never a
        user — so there is no parameter through which one member could
        reach another's state. This pins that shape."""
        space = make_space(); creator = make_user()
        alice = make_user(); bob = make_user()
        _member(db, alice, space); _member(db, bob, space)
        a = _activity(db, space, creator)
        db.commit()

        advance(db, alice, collective_id=space.id, category="pathways",
                through_sequence=a.sequence_number)
        db.commit()

        assert _cursor(db, alice, space) is not None
        assert _cursor(db, bob, space) is None, "Bob's state was touched"
        assert _total(db, bob) == 1, "and Bob still has his count"

    def test_advance_takes_no_user_parameter(self):
        import inspect

        from app.services import activity_cursors

        params = set(inspect.signature(activity_cursors.advance).parameters)
        for leak in ("user_id", "recipient_user_id", "member_id", "for_user"):
            assert leak not in params, (
                f"`{leak}` would let a caller name someone else's cursor"
            )


class TestAHollowedRowCannotRaiseTheCeiling:
    """Deleting content empties an activity row rather than removing
    it — every subject column is ON DELETE SET NULL. Such a row must
    not count towards how far a member may advance, or deleting a
    Pathway would quietly let the cursor jump past activity that is
    still live."""

    def test_a_subjectless_row_does_not_raise_the_clamp(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        live = _activity(db, space, creator)
        doomed_pathway = _pathway(db, space)
        hollow = _activity(db, space, creator, pathway_id=doomed_pathway.id)
        db.commit()
        assert hollow.sequence_number > live.sequence_number

        db.delete(doomed_pathway); db.commit(); db.expire_all()
        assert db.query(Activity).filter(
            Activity.id == hollow.id
        ).first().pathway_id is None, "fixture: the row was hollowed, not removed"

        state = advance(db, member, collective_id=space.id,
                        category="pathways",
                        through_sequence=hollow.sequence_number)
        db.commit()

        assert state.seen_through_seq == live.sequence_number


class TestEmptyAndInaccessibleSectionsClearNothing:
    """Visiting a section with nothing in it must be a no-op.

    The risk is not the empty section itself but its neighbours: a
    visit that quietly created a cursor at some default — or worse, at
    ``now()`` — would clear activity in a category the member never
    opened, and nothing would ever show it again.
    """

    def test_an_empty_section_creates_no_cursor(self, db, make_space, make_user):
        space = make_space(); member = make_user()
        _member(db, member, space); db.commit()

        with pytest.raises(CursorRefused) as e:
            advance(db, member, collective_id=space.id,
                    category="pathways", through_sequence=5)
        assert e.value.reason == "nothing_to_advance"
        assert db.query(CollectiveActivityCursor).count() == 0

    def test_a_section_holding_only_your_own_activity_is_empty_to_you(
        self, db, make_space, make_user,
    ):
        space = make_space(); member = make_user()
        _member(db, member, space)
        mine = _activity(db, space, member)
        db.commit()

        with pytest.raises(CursorRefused) as e:
            advance(db, member, collective_id=space.id,
                    category="pathways", through_sequence=mine.sequence_number)
        assert e.value.reason == "nothing_to_advance"

    def test_visiting_an_empty_section_leaves_other_categories_counted(
        self, db, make_space, make_user,
    ):
        """The one that matters: an empty Pathways section must not
        touch unread Conversations."""
        from app.models.platform import CommunityPost

        space = make_space(); author = make_user(); member = make_user()
        _member(db, author, space); _member(db, member, space)
        ch = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="R",
            slug=f"c-{uuid.uuid4().hex[:8]}", channel_type="open",
        )
        db.add(ch); db.flush()
        post = CommunityPost(
            id=_uid("cp"), space_id=space.id, channel_id=ch.id,
            author_id=author.id, title="T", body="x",
            publication_status="published",
        )
        db.add(post); db.flush()
        _activity(db, space, author, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()
        assert _total(db, member) == 1

        with pytest.raises(CursorRefused):
            advance(db, member, collective_id=space.id,
                    category="pathways", through_sequence=10_000)

        assert _total(db, member) == 1, "the Conversations count was disturbed"
        assert db.query(CollectiveActivityCursor).count() == 0

    def test_an_inaccessible_section_clears_nothing(self, db, make_space, make_user):
        space = make_space()
        space.area_policies = {"areas": {"pathways": "active_access"}}
        creator = make_user(); member = make_user()
        _member(db, member, space)
        a = _activity(db, space, creator)
        db.commit()
        assert _total(db, member) == 0, "an unreachable Area counts nothing anyway"

        with pytest.raises(CursorRefused):
            advance(db, member, collective_id=space.id,
                    category="pathways", through_sequence=a.sequence_number)

        assert db.query(CollectiveActivityCursor).count() == 0

        # And once the Area opens, the activity is still there to see.
        space.area_policies = {"areas": {"pathways": "members"}}
        db.commit()
        assert _total(db, member) == 1
