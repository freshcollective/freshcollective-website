"""Phase 3 — a visit marks what it showed, and nothing else.

Phase 2 stored one mark per category and the page sent a sequence
number. Both broke once a section shows only part of its category:

* a page renders **one** Channel, so a single mark per category meant
  reading Channel A silently cleared Channel B;
* a page renders content, not activity rows, so any sequence it named
  was a guess — and resolving the Pathway it displayed to "the newest
  activity for that Pathway" would sweep up a step published while
  the member was still reading.

So the page now sends the **subjects it displayed** and the
**boundary it displayed them against**. Those two together are the
whole correctness argument: subjects bound *what*, the boundary
bounds *when*. Each has a test here that fails without the other.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.activity import Activity, CollectiveActivityCursor
from app.models.platform import (
    ChannelMembership,
    CommunityPost,
    ConversationChannel,
    Event,
    EventSeries,
    Pathway,
    PathwayStatus,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.activity_counts import current_boundary, unseen_counts
from app.services.activity_cursors import CursorRefused, advance
from app.services.activity_visibility import resolve_member_scope


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _member(db, user, space, *, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id, role=role,
        status=SpaceMembershipStatus.active,
        joined_at=datetime.utcnow() - timedelta(days=30),
    ))
    db.flush()


def _pathway(db, space, *, access_type="free"):
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="A Pathway", status=PathwayStatus.active, access_type=access_type,
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p); db.flush()
    return p


def _channel(db, space, *, channel_type="open"):
    c = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="Room",
        slug=f"ch-{uuid.uuid4().hex[:8]}", channel_type=channel_type,
    )
    db.add(c); db.flush()
    return c


def _post(db, space, channel, author, *, hidden=False, visible=True):
    p = CommunityPost(
        id=_uid("cp"), space_id=space.id, channel_id=channel.id,
        author_id=author.id, title="A thread", body="hi",
        publication_status="published", is_visible=visible,
        cc_hidden_at=datetime.utcnow() if hidden else None,
    )
    db.add(p); db.flush()
    return p


def _gathering(db, space, *, past=False):
    base = datetime.utcnow() + (timedelta(days=-7) if past else timedelta(days=7))
    e = Event(
        id=_uid("e"), space_id=space.id, created_by_id=space.creator_id,
        title="A Gathering", starts_at=base, ends_at=base + timedelta(hours=1),
        is_published=True, status="active", requires_booking=True,
        capacity=20, gathering_type="circle", attendance_format="online",
    )
    db.add(e); db.flush()
    return e


def _series(db, space):
    s = EventSeries(
        id=_uid("es"), space_id=space.id, title="Term",
        slug=f"s-{uuid.uuid4().hex[:8]}", status="published",
        starts_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(s); db.flush()
    return s


def _activity(db, space, actor, *, category, event_type, **subject):
    a = Activity(
        id=_uid("act"), event_type=event_type, category=category,
        priority="standard", actor_user_id=actor.id, recipient_user_id=None,
        collective_id=space.id, payload={}, dedupe_key=_uid("k"), **subject,
    )
    db.add(a); db.flush()
    return a


def _boundary(db, user, space=None):
    return current_boundary(
        db,
        resolve_member_scope(
            db, user, collective_id=space.id if space else None,
        ),
    )


def _counts(db, user):
    return {c.collective_id: c for c in unseen_counts(db, user)}


def _total(db, user):
    return sum(c.total for c in unseen_counts(db, user))


def _cursors(db, user, space, category="conversations"):
    return {
        c.scope_key: c.seen_through_seq
        for c in db.query(CollectiveActivityCursor).filter(
            CollectiveActivityCursor.user_id == user.id,
            CollectiveActivityCursor.collective_id == space.id,
            CollectiveActivityCursor.category == category,
        )
    }


# ---------------------------------------------------------------------------
# 1 · The headline: one Channel at a time
# ---------------------------------------------------------------------------

class TestConversationChannelsAreIndependent:
    """The defect scoped cursors exist to fix. Channel A at the higher
    sequence, Channel B lower; reading A must leave B alone."""

    @staticmethod
    def _two_channels(db, make_space, make_user):
        space = make_space(); author = make_user(); member = make_user()
        _member(db, author, space); _member(db, member, space)
        chan_b, chan_a = _channel(db, space), _channel(db, space)
        post_b = _post(db, space, chan_b, author)
        post_a = _post(db, space, chan_a, author)
        act_b = _activity(db, space, author, category="conversations",
                          event_type="conversation_created",
                          conversation_id=post_b.id)
        act_a = _activity(db, space, author, category="conversations",
                          event_type="conversation_created",
                          conversation_id=post_a.id)
        db.commit()
        assert act_a.sequence_number > act_b.sequence_number
        return space, member, chan_a, chan_b, post_a, post_b

    def test_reading_the_newer_channel_leaves_the_older_unseen(
        self, db, make_space, make_user,
    ):
        space, member, chan_a, _cb, post_a, _pb = self._two_channels(
            db, make_space, make_user,
        )
        assert _counts(db, member)[space.id].conversations == 2

        advance(db, member, collective_id=space.id, category="conversations",
                subject_ids=[post_a.id],
                boundary_sequence=_boundary(db, member, space))
        db.commit()

        assert _counts(db, member)[space.id].conversations == 1, (
            "Channel B was cleared by a visit to Channel A"
        )
        assert set(_cursors(db, member, space)) == {chan_a.id}

    def test_reading_both_clears_both(self, db, make_space, make_user):
        space, member, chan_a, chan_b, post_a, post_b = self._two_channels(
            db, make_space, make_user,
        )
        b = _boundary(db, member, space)
        for post in (post_a, post_b):
            advance(db, member, collective_id=space.id,
                    category="conversations", subject_ids=[post.id],
                    boundary_sequence=b)
            db.commit()

        assert _counts(db, member)[space.id].conversations == 0
        assert set(_cursors(db, member, space)) == {chan_a.id, chan_b.id}

    def test_each_channel_keeps_its_own_mark(self, db, make_space, make_user):
        """A scope advances to its own content, not to the category's
        highest sequence."""
        space, member, _ca, chan_b, _pa, post_b = self._two_channels(
            db, make_space, make_user,
        )
        b = _boundary(db, member, space)
        advance(db, member, collective_id=space.id, category="conversations",
                subject_ids=[post_b.id], boundary_sequence=b)
        db.commit()

        marks = _cursors(db, member, space)
        assert list(marks) == [chan_b.id]
        assert marks[chan_b.id] < b


# ---------------------------------------------------------------------------
# 2 · The boundary: same subject, new activity
# ---------------------------------------------------------------------------

class TestActivityArrivingDuringAVisit:
    def test_a_new_subject_published_mid_visit_survives(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        shown = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=shown.id)
        db.commit()
        boundary = _boundary(db, member, space)

        later = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=later.id)
        db.commit()

        advance(db, member, collective_id=space.id, category="pathways",
                subject_ids=[shown.id], boundary_sequence=boundary)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 1

    def test_a_new_step_in_a_pathway_already_on_screen_survives(
        self, db, make_space, make_user,
    ):
        """The case subject ids alone cannot handle. The member is
        reading the Pathway; a second step is published *into it*. Its
        activity hangs off the same pathway_id the page will submit,
        so only the boundary keeps it unseen."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_step_released", pathway_id=pw.id)
        db.commit()
        boundary = _boundary(db, member, space)
        assert _counts(db, member)[space.id].pathways == 1

        mid_visit = _activity(db, space, creator, category="pathways",
                              event_type="pathway_step_released",
                              pathway_id=pw.id)
        db.commit()

        advance(db, member, collective_id=space.id, category="pathways",
                subject_ids=[pw.id], boundary_sequence=boundary)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 1, (
            "the step published mid-visit was swept up by its parent's id"
        )
        assert _cursors(db, member, space, "pathways")[""] < mid_visit.sequence_number

    def test_a_boundary_taken_too_late_does_clear_it(
        self, db, make_space, make_user,
    ):
        """States the failure mode directly, so the ordering rule is
        not merely documented: capture the boundary *before* fetching
        content, or the same call loses the step."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_step_released", pathway_id=pw.id)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_step_released", pathway_id=pw.id)
        db.commit()

        advance(db, member, collective_id=space.id, category="pathways",
                subject_ids=[pw.id],
                boundary_sequence=_boundary(db, member, space))
        db.commit()
        assert _counts(db, member)[space.id].pathways == 0


# ---------------------------------------------------------------------------
# 3 · Gatherings — upcoming, past, Series
# ---------------------------------------------------------------------------

class TestGatherings:
    def test_a_past_gathering_is_not_counted(self, db, make_space, make_user):
        """The page shows upcoming only; a past Gathering sits behind
        the archive link, so counting one leaves a badge no visit can
        clear."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        past = _gathering(db, space, past=True)
        _activity(db, space, creator, category="gatherings",
                  event_type="gathering_created", gathering_id=past.id)
        db.commit()

        assert _counts(db, member)[space.id].gatherings == 0

    def test_an_upcoming_gathering_counts_and_clears(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        ev = _gathering(db, space)
        _activity(db, space, creator, category="gatherings",
                  event_type="gathering_created", gathering_id=ev.id)
        db.commit()
        assert _counts(db, member)[space.id].gatherings == 1

        advance(db, member, collective_id=space.id, category="gatherings",
                subject_ids=[ev.id],
                boundary_sequence=_boundary(db, member, space))
        db.commit()
        assert _counts(db, member)[space.id].gatherings == 0

    def test_a_series_counts_once_and_clears_by_its_own_id(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        series = _series(db, space)
        _activity(db, space, creator, category="gatherings",
                  event_type="gathering_created", series_id=series.id)
        db.commit()
        assert _counts(db, member)[space.id].gatherings == 1

        advance(db, member, collective_id=space.id, category="gatherings",
                subject_ids=[series.id],
                boundary_sequence=_boundary(db, member, space))
        db.commit()
        assert _counts(db, member)[space.id].gatherings == 0

    def test_an_occurrence_id_does_not_clear_its_series(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        series = _series(db, space)
        occurrence = _gathering(db, space)
        _activity(db, space, creator, category="gatherings",
                  event_type="gathering_created", series_id=series.id)
        db.commit()

        advance(db, member, collective_id=space.id, category="gatherings",
                subject_ids=[occurrence.id],
                boundary_sequence=_boundary(db, member, space))
        db.commit()
        assert _counts(db, member)[space.id].gatherings == 1


# ---------------------------------------------------------------------------
# 4 · Hidden content never sticks
# ---------------------------------------------------------------------------

class TestHiddenPosts:
    def test_a_community_care_hidden_post_is_not_counted(
        self, db, make_space, make_user,
    ):
        """It never renders, so its id is never submitted. Counting it
        would leave a badge the member could never clear."""
        space = make_space(); author = make_user(); member = make_user()
        _member(db, author, space); _member(db, member, space)
        ch = _channel(db, space)
        post = _post(db, space, ch, author, hidden=True)
        _activity(db, space, author, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()

        assert _counts(db, member)[space.id].conversations == 0

    def test_an_invisible_post_is_not_counted(self, db, make_space, make_user):
        space = make_space(); author = make_user(); member = make_user()
        _member(db, author, space); _member(db, member, space)
        ch = _channel(db, space)
        post = _post(db, space, ch, author, visible=False)
        _activity(db, space, author, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()

        assert _counts(db, member)[space.id].conversations == 0

    def test_a_visible_post_still_counts(self, db, make_space, make_user):
        """Control — the filters narrow, they do not empty."""
        space = make_space(); author = make_user(); member = make_user()
        _member(db, author, space); _member(db, member, space)
        ch = _channel(db, space)
        post = _post(db, space, ch, author)
        _activity(db, space, author, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()

        assert _counts(db, member)[space.id].conversations == 1


# ---------------------------------------------------------------------------
# 5 · Forward only — tabs and out-of-order
# ---------------------------------------------------------------------------

class TestForwardOnly:
    @staticmethod
    def _two_posts(db, make_space, make_user):
        space = make_space(); author = make_user(); member = make_user()
        _member(db, author, space); _member(db, member, space)
        ch = _channel(db, space)
        first = _post(db, space, ch, author)
        second = _post(db, space, ch, author)
        for post in (first, second):
            _activity(db, space, author, category="conversations",
                      event_type="conversation_created",
                      conversation_id=post.id)
        db.commit()
        return space, member, ch, first, second

    def test_a_stale_submission_cannot_move_the_mark_back(
        self, db, make_space, make_user,
    ):
        space, member, ch, first, second = self._two_posts(
            db, make_space, make_user,
        )
        b = _boundary(db, member, space)
        advance(db, member, collective_id=space.id, category="conversations",
                subject_ids=[first.id, second.id], boundary_sequence=b)
        db.commit()
        high = _cursors(db, member, space)[ch.id]

        advance(db, member, collective_id=space.id, category="conversations",
                subject_ids=[first.id], boundary_sequence=b)
        db.commit()

        assert _cursors(db, member, space)[ch.id] == high
        assert _counts(db, member)[space.id].conversations == 0

    def test_two_tabs_settle_the_same_way_in_either_order(
        self, db, make_space, make_user,
    ):
        space, member, _ch, first, second = self._two_posts(
            db, make_space, make_user,
        )
        b = _boundary(db, member, space)
        both, one = [first.id, second.id], [first.id]

        for order in ([both, one], [one, both]):
            db.query(CollectiveActivityCursor).delete(); db.commit()
            for ids in order:
                advance(db, member, collective_id=space.id,
                        category="conversations", subject_ids=ids,
                        boundary_sequence=b)
                db.commit()
            assert _counts(db, member)[space.id].conversations == 0, (
                f"arrival order changed the outcome: {order}"
            )


# ---------------------------------------------------------------------------
# 6 · Categories and Collectives stay separate
# ---------------------------------------------------------------------------

class TestIsolation:
    def test_visiting_pathways_leaves_conversations_alone(
        self, db, make_space, make_user,
    ):
        space = make_space(); author = make_user(); member = make_user()
        _member(db, author, space); _member(db, member, space)
        pw = _pathway(db, space)
        _activity(db, space, author, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        ch = _channel(db, space); post = _post(db, space, ch, author)
        _activity(db, space, author, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()

        advance(db, member, collective_id=space.id, category="pathways",
                subject_ids=[pw.id],
                boundary_sequence=_boundary(db, member, space))
        db.commit()

        c = _counts(db, member)[space.id]
        assert c.pathways == 0 and c.conversations == 1

    def test_visiting_one_collective_leaves_the_other(
        self, db, make_space, make_user,
    ):
        a, b = make_space(), make_space()
        creator = make_user(); member = make_user()
        _member(db, member, a); _member(db, member, b)
        pa, pb = _pathway(db, a), _pathway(db, b)
        for sp, pw in ((a, pa), (b, pb)):
            _activity(db, sp, creator, category="pathways",
                      event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        advance(db, member, collective_id=a.id, category="pathways",
                subject_ids=[pa.id], boundary_sequence=_boundary(db, member))
        db.commit()

        assert _total(db, member) == 1


# ---------------------------------------------------------------------------
# 7 · Permissions and refusals
# ---------------------------------------------------------------------------

class TestPermissionsAndRefusals:
    def test_a_private_channel_id_resolves_to_nothing(
        self, db, make_space, make_user,
    ):
        """A crafted id for a thread this member cannot open must
        advance nothing — and must not raise either."""
        space = make_space(); author = make_user(); outsider = make_user()
        _member(db, author, space); _member(db, outsider, space)
        private = _channel(db, space, channel_type="private")
        hidden_post = _post(db, space, private, author)
        _activity(db, space, author, category="conversations",
                  event_type="conversation_created",
                  conversation_id=hidden_post.id)
        open_ch = _channel(db, space)
        seen_post = _post(db, space, open_ch, author)
        _activity(db, space, author, category="conversations",
                  event_type="conversation_created",
                  conversation_id=seen_post.id)
        db.commit()

        state = advance(
            db, outsider, collective_id=space.id, category="conversations",
            subject_ids=[hidden_post.id],
            boundary_sequence=_boundary(db, outsider, space),
        )
        db.commit()
        assert state.advanced == {}
        assert _counts(db, outsider)[space.id].conversations == 1

    def test_a_channel_member_can_clear_their_own_private_channel(
        self, db, make_space, make_user,
    ):
        space = make_space(); author = make_user(); insider = make_user()
        _member(db, author, space); _member(db, insider, space)
        private = _channel(db, space, channel_type="private")
        db.add(ChannelMembership(
            id=_uid("cm"), channel_id=private.id, user_id=insider.id,
            role="member", source="manual",
        ))
        post = _post(db, space, private, author)
        _activity(db, space, author, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()
        assert _counts(db, insider)[space.id].conversations == 1

        advance(db, insider, collective_id=space.id, category="conversations",
                subject_ids=[post.id],
                boundary_sequence=_boundary(db, insider, space))
        db.commit()
        assert _counts(db, insider)[space.id].conversations == 0

    def test_a_non_member_is_refused(self, db, make_space, make_user):
        space = make_space(); outsider = make_user()
        db.commit()
        with pytest.raises(CursorRefused) as e:
            advance(db, outsider, collective_id=space.id,
                    category="pathways", subject_ids=["pw_x"],
                    boundary_sequence=1)
        assert e.value.reason == "not_a_member"
        assert db.query(CollectiveActivityCursor).count() == 0

    def test_an_unreachable_area_is_refused(self, db, make_space, make_user):
        space = make_space()
        space.area_policies = {"areas": {"pathways": "active_access"}}
        creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        with pytest.raises(CursorRefused) as e:
            advance(db, member, collective_id=space.id, category="pathways",
                    subject_ids=[pw.id], boundary_sequence=10_000)
        assert e.value.reason == "area_unreachable"

    def test_your_own_activity_advances_nothing(self, db, make_space, make_user):
        space = make_space(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        _activity(db, space, member, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        state = advance(db, member, collective_id=space.id,
                        category="pathways", subject_ids=[pw.id],
                        boundary_sequence=_boundary(db, member, space))
        db.commit()
        assert state.advanced == {}

    @pytest.mark.parametrize("bad", ["personal", "account", "collective", ""])
    def test_an_unknown_category_is_refused(self, db, make_space, make_user, bad):
        space = make_space(); member = make_user()
        _member(db, member, space); db.commit()
        with pytest.raises(CursorRefused) as e:
            advance(db, member, collective_id=space.id, category=bad,
                    subject_ids=["x"], boundary_sequence=1)
        assert e.value.reason == "unknown_category"

    @pytest.mark.parametrize("bad", [-1, True, "5", 1.5, None])
    def test_a_bad_boundary_is_refused(self, db, make_space, make_user, bad):
        space = make_space(); member = make_user()
        _member(db, member, space); db.commit()
        with pytest.raises(CursorRefused) as e:
            advance(db, member, collective_id=space.id, category="pathways",
                    subject_ids=["x"], boundary_sequence=bad)
        assert e.value.reason == "invalid_boundary"

    @pytest.mark.parametrize("bad", ["notalist", [1, 2], [""], [None]])
    def test_bad_subject_ids_are_refused(self, db, make_space, make_user, bad):
        space = make_space(); member = make_user()
        _member(db, member, space); db.commit()
        with pytest.raises(CursorRefused) as e:
            advance(db, member, collective_id=space.id, category="pathways",
                    subject_ids=bad, boundary_sequence=1)
        assert e.value.reason == "invalid_subjects"

    def test_an_oversized_submission_is_refused(self, db, make_space, make_user):
        space = make_space(); member = make_user()
        _member(db, member, space); db.commit()
        with pytest.raises(CursorRefused) as e:
            advance(db, member, collective_id=space.id, category="pathways",
                    subject_ids=[f"x{i}" for i in range(501)],
                    boundary_sequence=1)
        assert e.value.reason == "too_many_subjects"


# ---------------------------------------------------------------------------
# 8 · Nothing to do is not a failure
# ---------------------------------------------------------------------------

class TestEmptyAndHarmless:
    @staticmethod
    def _one_unseen(db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()
        return space, member, pw

    def test_an_empty_list_advances_nothing(self, db, make_space, make_user):
        space, member, _pw = self._one_unseen(db, make_space, make_user)
        state = advance(db, member, collective_id=space.id,
                        category="pathways", subject_ids=[],
                        boundary_sequence=_boundary(db, member, space))
        db.commit()
        assert state.advanced == {}
        assert db.query(CollectiveActivityCursor).count() == 0
        assert _counts(db, member)[space.id].pathways == 1

    def test_an_unknown_id_is_harmless(self, db, make_space, make_user):
        space, member, _pw = self._one_unseen(db, make_space, make_user)
        state = advance(db, member, collective_id=space.id,
                        category="pathways", subject_ids=["pw_nonexistent"],
                        boundary_sequence=_boundary(db, member, space))
        db.commit()
        assert state.advanced == {}
        assert _counts(db, member)[space.id].pathways == 1

    def test_a_zero_boundary_advances_nothing(self, db, make_space, make_user):
        """A page whose boundary predates all activity must not clear
        anything created since."""
        space, member, pw = self._one_unseen(db, make_space, make_user)
        state = advance(db, member, collective_id=space.id,
                        category="pathways", subject_ids=[pw.id],
                        boundary_sequence=0)
        db.commit()
        assert state.advanced == {}
        assert _counts(db, member)[space.id].pathways == 1


# ---------------------------------------------------------------------------
# 9 · The boundary itself
# ---------------------------------------------------------------------------

class TestTheBoundary:
    def test_it_rises_with_new_activity(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        before = _boundary(db, member, space)
        pw = _pathway(db, space)
        a = _activity(db, space, creator, category="pathways",
                      event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        after = _boundary(db, member, space)
        assert after == a.sequence_number > before

    def test_a_member_of_nothing_gets_zero(self, db, make_user):
        assert _boundary(db, make_user()) == 0


# ---------------------------------------------------------------------------
# A navigation-hidden Channel has nothing to mark
# ---------------------------------------------------------------------------

class TestHiddenChannelsAreUnmarkable:
    """A hidden Channel is uncounted, so there is nothing to clear —
    and because one ``_liveness_filters`` definition serves the count,
    the clamp and the presented-id resolver, reaching it by direct
    link writes no cursor rather than writing a meaningless one.
    """

    def _hidden(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        ch = _channel(db, space, channel_type="open")
        ch.show_in_navigation = False
        db.flush()
        post = _post(db, space, ch, creator)
        _activity(db, space, creator, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()
        return space, member, ch, post

    def test_visiting_by_direct_link_writes_no_cursor(
        self, db, make_space, make_user,
    ):
        space, member, _ch, post = self._hidden(db, make_space, make_user)

        state = advance(
            db, member, collective_id=space.id, category="conversations",
            subject_ids=[post.id],
            boundary_sequence=_boundary(db, member, space),
        )
        db.commit()

        assert state.advanced == {}, (
            "nothing was counted for this Channel, so nothing may be marked"
        )
        assert _cursors(db, member, space) == {}

    def test_an_unhidden_channel_still_marks(self, db, make_space, make_user):
        # The control: the resolver must still work for a shown
        # Channel, or the test above would pass against a resolver
        # that refused everything.
        space, member, ch, post = self._hidden(db, make_space, make_user)
        ch.show_in_navigation = True
        db.commit()

        state = advance(
            db, member, collective_id=space.id, category="conversations",
            subject_ids=[post.id],
            boundary_sequence=_boundary(db, member, space),
        )
        db.commit()

        assert set(state.advanced) == {ch.id}
        assert _counts(db, member)[space.id].conversations == 0
