"""Phase 2 — what a member has not yet seen.

Counting is where the shared-row model earns its keep and where it is
most dangerous: one query decides, for every Collective at once,
which content a member is told about. A mistake here either leaks the
existence of content they cannot open, or silently stops telling them
about content they can.

So the permission cases are tested for what they let through as well
as what they stop. A file that only proved "the count is zero" would
pass against a function that always returned zero.
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
    EntitlementSource,
    EntitlementStatus,
    Event,
    EventSeries,
    Pathway,
    PathwayEntitlement,
    PathwayStatus,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.activity_counts import current_boundary, unseen_counts
from app.services.activity_visibility import resolve_member_scope


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _member(db, user, space, *, role=SpaceRole.learner, joined=None):
    m = SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id, role=role,
        status=SpaceMembershipStatus.active,
        joined_at=joined or (datetime.utcnow() - timedelta(days=30)),
    )
    db.add(m); db.flush()
    return m


def _pathway(db, space, *, status=PathwayStatus.active, access_type="free"):
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="A Pathway", status=status, access_type=access_type,
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


def _post(db, space, channel, author):
    p = CommunityPost(
        id=_uid("cp"), space_id=space.id, channel_id=channel.id,
        author_id=author.id, title="A thread", body="hi",
        publication_status="published",
    )
    db.add(p); db.flush()
    return p


def _entitle(db, user, space, pathway):
    e = PathwayEntitlement(
        id=_uid("ent"), user_id=user.id, space_id=space.id,
        pathway_id=pathway.id, source=EntitlementSource.manual_grant,
        status=EntitlementStatus.active, starts_at=datetime.utcnow(),
    )
    db.add(e); db.flush()
    return e


def _activity(db, space, actor, *, category, event_type, created_at=None, **subject):
    """A shared activity row.

    ``created_at`` is settable so timestamp collisions can be forced;
    ``sequence_number`` is left to the identity column so the tests
    exercise the real ordering rather than one they invented.
    """
    a = Activity(
        id=_uid("act"), event_type=event_type, category=category,
        priority="standard", actor_user_id=actor.id,
        recipient_user_id=None, collective_id=space.id, payload={},
        dedupe_key=_uid("k"), **subject,
    )
    if created_at is not None:
        a.created_at = created_at
    db.add(a); db.flush()
    return a


def _counts(db, user, **kw):
    return {c.collective_id: c for c in unseen_counts(db, user, **kw)}


def _total(db, user, **kw):
    return sum(c.total for c in unseen_counts(db, user, **kw))


# ---------------------------------------------------------------------------
# The control — counting works at all
# ---------------------------------------------------------------------------

class TestCountingTheBasics:
    def test_a_published_pathway_counts_for_a_member(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        c = _counts(db, member)[space.id]
        assert c.pathways == 1 and c.total == 1

    def test_your_own_publication_never_counts(self, db, make_space, make_user):
        space = make_space(); creator = make_user()
        _member(db, creator, space)
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        assert _total(db, creator) == 0

    def test_a_non_member_counts_nothing(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); outsider = make_user()
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        assert unseen_counts(db, outsider) == []


# ---------------------------------------------------------------------------
# Content items, not records
# ---------------------------------------------------------------------------

class TestUniqueContentItems:
    def test_three_steps_in_one_pathway_count_once(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        for _ in range(3):
            _activity(db, space, creator, category="pathways",
                      event_type="pathway_step_released", pathway_id=pw.id)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 1

    def test_a_series_counts_once_however_many_occurrences(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        series = EventSeries(
            id=_uid("es"), space_id=space.id, title="Term",
            slug=f"s-{uuid.uuid4().hex[:8]}", status="published",
            starts_at=datetime.utcnow() + timedelta(days=7),
        )
        db.add(series); db.flush()
        _activity(db, space, creator, category="gatherings",
                  event_type="gathering_created", series_id=series.id)
        db.commit()

        assert _counts(db, member)[space.id].gatherings == 1

    def test_two_different_pathways_count_twice(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        for _ in range(2):
            pw = _pathway(db, space)
            _activity(db, space, creator, category="pathways",
                      event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 2


# ---------------------------------------------------------------------------
# New members, cursors, categories
# ---------------------------------------------------------------------------

class TestWhereCountingStarts:
    def test_a_new_member_has_no_backlog(self, db, make_space, make_user):
        """Activity that predates the membership is not news to them."""
        space = make_space(); creator = make_user(); member = make_user()
        pw = _pathway(db, space)
        _activity(
            db, space, creator, category="pathways",
            event_type="pathway_published", pathway_id=pw.id,
            created_at=datetime.utcnow() - timedelta(days=10),
        )
        _member(db, member, space, joined=datetime.utcnow())
        db.commit()

        assert _total(db, member) == 0
        assert db.query(CollectiveActivityCursor).count() == 0, (
            "and no cursor row was written to achieve it"
        )

    def test_activity_after_joining_does_count(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space, joined=datetime.utcnow() - timedelta(days=1))
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        assert _total(db, member) == 1

    def test_a_cursor_hides_everything_at_or_below_it(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        a = _activity(db, space, creator, category="pathways",
                      event_type="pathway_published", pathway_id=pw.id)
        db.commit()
        assert _total(db, member) == 1

        db.add(CollectiveActivityCursor(
            id=_uid("cur"), user_id=member.id, collective_id=space.id,
            category="pathways", seen_through=a.created_at,
            seen_through_seq=a.sequence_number,
        ))
        db.commit()

        assert _total(db, member) == 0

    def test_a_cursor_in_one_category_leaves_the_others_alone(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space); _member(db, creator, space)
        pw = _pathway(db, space)
        a = _activity(db, space, creator, category="pathways",
                      event_type="pathway_published", pathway_id=pw.id)
        ch = _channel(db, space); post = _post(db, space, ch, creator)
        _activity(db, space, creator, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()

        db.add(CollectiveActivityCursor(
            id=_uid("cur"), user_id=member.id, collective_id=space.id,
            category="pathways", seen_through=a.created_at,
            seen_through_seq=a.sequence_number,
        ))
        db.commit()

        c = _counts(db, member)[space.id]
        assert c.pathways == 0
        assert c.conversations == 1, "visiting Pathways must not clear Conversations"


# ---------------------------------------------------------------------------
# Timestamp collisions — the reason sequence_number exists
# ---------------------------------------------------------------------------

class TestTimestampCollisions:
    def test_rows_sharing_a_timestamp_are_counted_independently(
        self, db, make_space, make_user,
    ):
        """``created_at`` defaults to ``now()``, which is the
        transaction timestamp, so rows written together are identical
        to the microsecond. A cursor on time alone would clear all of
        them once any one was presented."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        stamp = datetime.utcnow()
        made = []
        for _ in range(3):
            pw = _pathway(db, space)
            made.append(_activity(
                db, space, creator, category="pathways",
                event_type="pathway_published", pathway_id=pw.id,
                created_at=stamp,
            ))
        db.commit()

        assert len({a.created_at for a in made}) == 1, "fixture: timestamps collide"
        assert len({a.sequence_number for a in made}) == 3, (
            "but sequence numbers do not"
        )
        assert _counts(db, member)[space.id].pathways == 3

        # Mark only the lowest of the three as seen.
        lowest = min(made, key=lambda a: a.sequence_number)
        db.add(CollectiveActivityCursor(
            id=_uid("cur"), user_id=member.id, collective_id=space.id,
            category="pathways", seen_through=lowest.created_at,
            seen_through_seq=lowest.sequence_number,
        ))
        db.commit()

        assert _counts(db, member)[space.id].pathways == 2, (
            "the two never presented must survive a colliding timestamp"
        )


# ---------------------------------------------------------------------------
# Visibility — the part that must not leak
# ---------------------------------------------------------------------------

class TestVisibility:
    def test_a_private_channel_does_not_count_for_a_non_participant(
        self, db, make_space, make_user,
    ):
        space = make_space(); author = make_user(); outsider = make_user()
        _member(db, author, space); _member(db, outsider, space)
        ch = _channel(db, space, channel_type="private")
        post = _post(db, space, ch, author)
        _activity(db, space, author, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()

        assert _counts(db, outsider)[space.id].conversations == 0

    def test_the_same_thread_counts_for_a_channel_member(
        self, db, make_space, make_user,
    ):
        """Control for the test above."""
        space = make_space(); author = make_user(); insider = make_user()
        _member(db, author, space); _member(db, insider, space)
        ch = _channel(db, space, channel_type="private")
        db.add(ChannelMembership(
            id=_uid("cm"), channel_id=ch.id, user_id=insider.id,
            role="member", source="manual",
        ))
        post = _post(db, space, ch, author)
        _activity(db, space, author, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()

        assert _counts(db, insider)[space.id].conversations == 1

    def test_an_unreachable_area_counts_nothing(self, db, make_space, make_user):
        space = make_space()
        space.area_policies = {"areas": {"pathways": "active_access"}}
        creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 0

        space.area_policies = {"areas": {"pathways": "members"}}
        db.commit()
        assert _counts(db, member)[space.id].pathways == 1

    def test_unpublished_and_deleted_content_stops_counting(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()
        assert _total(db, member) == 1

        pw.status = PathwayStatus.draft
        db.commit()
        assert _total(db, member) == 0, "a draft is not news"

        pw.status = PathwayStatus.active
        db.commit()
        db.delete(pw); db.commit(); db.expire_all()
        assert _total(db, member) == 0, (
            "deletion empties the row rather than removing it; an empty "
            "row must not count"
        )

    def test_a_removed_member_counts_nothing(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        m = _member(db, member, space)
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()
        assert _total(db, member) == 1

        m.status = SpaceMembershipStatus.removed
        db.commit()
        assert unseen_counts(db, member) == []


# ---------------------------------------------------------------------------
# Paid Pathways — the Phase 2 product decision
# ---------------------------------------------------------------------------

class TestPaidPathways:
    """Approved rule: a newly published paid Pathway counts because its
    listing is visible, even unbought. A released *step* counts only
    where the member could open it."""

    def test_an_unbought_paid_pathway_still_counts_as_new(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space, access_type="one_time")
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 1, (
            "the listing is visible, so its publication is news"
        )

    def test_a_step_in_an_unbought_paid_pathway_does_not_count(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space, access_type="one_time")
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_step_released", pathway_id=pw.id)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 0, (
            "they cannot open the step, so it is not news to them"
        )

    def test_the_step_counts_once_they_hold_an_entitlement(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space, access_type="one_time")
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_step_released", pathway_id=pw.id)
        db.commit()
        assert _counts(db, member)[space.id].pathways == 0

        _entitle(db, member, space, pw)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 1

    def test_a_step_in_a_free_pathway_counts_without_any_grant(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space, access_type="free")
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_step_released", pathway_id=pw.id)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 1


# ---------------------------------------------------------------------------
# Many Collectives
# ---------------------------------------------------------------------------

class TestMultipleCollectives:
    def test_counts_are_independent_per_collective(
        self, db, make_space, make_user,
    ):
        a, b = make_space(), make_space()
        creator = make_user(); member = make_user()
        _member(db, member, a); _member(db, member, b)
        for space in (a, b):
            pw = _pathway(db, space)
            _activity(db, space, creator, category="pathways",
                      event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        counts = _counts(db, member)
        assert counts[a.id].pathways == 1
        assert counts[b.id].pathways == 1
        assert _total(db, member) == 2

    def test_a_collective_with_nothing_unseen_is_still_reported(
        self, db, make_space, make_user,
    ):
        """Phase 3 renders a list of Collectives; omitting the quiet
        ones would make it guess which exist."""
        a, b = make_space(), make_space()
        creator = make_user(); member = make_user()
        _member(db, member, a); _member(db, member, b)
        pw = _pathway(db, a)
        _activity(db, a, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        counts = _counts(db, member)
        assert set(counts) == {a.id, b.id}
        assert counts[b.id].total == 0

    def test_scoping_to_one_collective_excludes_the_others(
        self, db, make_space, make_user,
    ):
        a, b = make_space(), make_space()
        creator = make_user(); member = make_user()
        _member(db, member, a); _member(db, member, b)
        for space in (a, b):
            pw = _pathway(db, space)
            _activity(db, space, creator, category="pathways",
                      event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        only_a = _counts(db, member, collective_id=a.id)
        assert set(only_a) == {a.id}


# ---------------------------------------------------------------------------
# Query efficiency — the requirement that can only be asserted, not argued
# ---------------------------------------------------------------------------

class TestQueryEfficiency:
    """The point of the shared-row model is that counting does not grow
    with the number of Collectives. That is a claim about query count,
    so it is measured rather than reasoned about."""

    @staticmethod
    def _count_queries(db, fn):
        from sqlalchemy import event

        engine = db.get_bind()
        seen: list[str] = []

        def before(conn, cursor, statement, params, context, executemany):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", before)
        try:
            fn()
        finally:
            event.remove(engine, "before_cursor_execute", before)
        return len(seen)

    def _build(self, db, make_space, make_user, member, n):
        creator = make_user()
        for _ in range(n):
            space = make_space()
            _member(db, member, space)
            pw = _pathway(db, space)
            _channel(db, space)
            _activity(db, space, creator, category="pathways",
                      event_type="pathway_published", pathway_id=pw.id)
        db.commit()

    def test_query_count_does_not_grow_with_collectives(
        self, db, make_space, make_user,
    ):
        member = make_user()
        self._build(db, make_space, make_user, member, 1)
        db.expire_all()
        one = self._count_queries(db, lambda: unseen_counts(db, member))

        self._build(db, make_space, make_user, member, 9)
        db.expire_all()
        ten = self._count_queries(db, lambda: unseen_counts(db, member))

        assert _total(db, member) == 10, "fixture: ten Collectives with activity"
        assert ten == one, (
            f"counting cost {one} queries for 1 Collective and {ten} for 10 — "
            "the resolver is doing per-Collective work"
        )

    def test_the_whole_count_is_a_small_fixed_number_of_queries(
        self, db, make_space, make_user,
    ):
        member = make_user()
        self._build(db, make_space, make_user, member, 5)
        db.expire_all()
        n = self._count_queries(db, lambda: unseen_counts(db, member))
        assert n <= 12, f"expected a bounded pre-pass plus one count, got {n}"


class TestPathwayStatusAndAccessTypeAtTheEdges:
    """The step-accessibility rule reads both status and access type.
    Each needs its own case, because a mutation to either alone is
    otherwise invisible."""

    def test_a_step_in_a_coming_soon_pathway_does_not_count(
        self, db, make_space, make_user,
    ):
        """``coming_soon`` is listed but not openable, so its steps are
        not news — even though the Pathway itself is visible."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space, status=PathwayStatus.coming_soon)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_step_released", pathway_id=pw.id)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 0

        pw.status = PathwayStatus.active
        db.commit()
        assert _counts(db, member)[space.id].pathways == 1, (
            "control: the same step counts once the Pathway opens"
        )

    def test_the_coming_soon_pathway_itself_still_counts(
        self, db, make_space, make_user,
    ):
        """Listing visibility is the looser rule: a coming_soon
        Pathway appearing is news even though nothing opens yet."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space, status=PathwayStatus.coming_soon)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 1

    def test_an_included_with_offer_step_needs_an_unlock(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space, access_type="included_with_offer")
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_step_released", pathway_id=pw.id)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 0, (
            "membership alone does not unlock included_with_offer"
        )

        _entitle(db, member, space, pw)
        db.commit()
        assert _counts(db, member)[space.id].pathways == 1

    def test_an_included_step_needs_only_membership(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space, access_type="included")
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_step_released", pathway_id=pw.id)
        db.commit()

        assert _counts(db, member)[space.id].pathways == 1


# ---------------------------------------------------------------------------
# Navigation-hidden Channels — readable, but never announced
# ---------------------------------------------------------------------------

class TestHiddenChannelsAreNotNotifiable:
    """``show_in_navigation`` was applied on exactly one of six
    surfaces: the member Channel list. So a Channel a member could
    read but the creator had hidden raised a badge that no visit could
    ever clear — the Channel is absent from the selector, so nothing
    reports its posts.

    Access is deliberately unchanged. A hidden Channel stays readable
    by direct link and findable in search; it simply stops being
    announced.
    """

    def _hidden_post(self, db, space, creator, *, shown):
        ch = _channel(db, space, channel_type="open")
        ch.show_in_navigation = shown
        db.flush()
        post = _post(db, space, ch, creator)
        _activity(db, space, creator, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        return ch

    def test_a_hidden_channel_counts_nothing(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        self._hidden_post(db, space, creator, shown=False)
        db.commit()

        assert _counts(db, member)[space.id].conversations == 0

    def test_the_same_channel_counts_once_shown(self, db, make_space, make_user):
        # The control. A filter that dropped every conversation row
        # would pass the test above.
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        ch = self._hidden_post(db, space, creator, shown=False)
        db.commit()
        assert _counts(db, member)[space.id].conversations == 0

        ch.show_in_navigation = True
        db.commit()
        assert _counts(db, member)[space.id].conversations == 1

    def test_hiding_does_not_revoke_access(self, db, make_space, make_user):
        """The two sets answer different questions, and the hidden
        Channel must stay in the access one — that is what keeps a
        direct link and a search hit working."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        ch = self._hidden_post(db, space, creator, shown=False)
        db.commit()

        scope = resolve_member_scope(db, member)
        assert ch.id in scope.accessible_channel_ids, (
            "hiding a Channel from navigation must not revoke the right "
            "to read it"
        )
        assert ch.id not in scope.notifiable_channel_ids

    def test_a_caretaker_is_still_told(self, db, make_space, make_user):
        """A caretaker sees every Channel in their own selector —
        ``list_member_channels`` applies ``show_in_navigation`` to
        members only — so a caretaker can reach a hidden Channel and
        may be told about it."""
        space = make_space(); creator = make_user(); mod = make_user()
        _member(db, mod, space, role=SpaceRole.moderator)
        ch = self._hidden_post(db, space, creator, shown=False)
        db.commit()

        scope = resolve_member_scope(db, mod)
        assert ch.id in scope.notifiable_channel_ids
        assert _counts(db, mod)[space.id].conversations == 1

    def test_an_inaccessible_channel_is_still_excluded(self, db, make_space, make_user):
        """Regression: narrowing to the notifiable set must not have
        widened anything. A private Channel the member is not in stays
        out of both sets, shown in navigation or not."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        ch = _channel(db, space, channel_type="private")
        ch.show_in_navigation = True
        db.flush()
        post = _post(db, space, ch, creator)
        _activity(db, space, creator, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()

        scope = resolve_member_scope(db, member)
        assert ch.id not in scope.accessible_channel_ids
        assert ch.id not in scope.notifiable_channel_ids
        assert _counts(db, member)[space.id].conversations == 0


# ---------------------------------------------------------------------------
# Which Channels the number came from
# ---------------------------------------------------------------------------

class TestPerChannelBreakdown:
    """The selector marks each Channel with a dot; the navigation keeps
    the number. So the response says *which* Channels, not how many
    each — and the two must agree about the total.
    """

    def _two_channels(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        a = _channel(db, space); b = _channel(db, space)
        for ch in (a, b):
            post = _post(db, space, ch, creator)
            _activity(db, space, creator, category="conversations",
                      event_type="conversation_created", conversation_id=post.id)
        db.commit()
        return space, member, creator, a, b

    def test_each_channel_with_something_unseen_is_named(
        self, db, make_space, make_user,
    ):
        space, member, _creator, a, b = self._two_channels(db, make_space, make_user)
        row = _counts(db, member)[space.id]

        assert row.conversations == 2
        assert set(row.conversation_channels) == {a.id, b.id}

    def test_many_discussions_in_one_channel_name_it_once(
        self, db, make_space, make_user,
    ):
        """The safeguard: one dot per Channel, whatever it holds, while
        the badge keeps the true total."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        ch = _channel(db, space)
        for _ in range(3):
            post = _post(db, space, ch, creator)
            _activity(db, space, creator, category="conversations",
                      event_type="conversation_created", conversation_id=post.id)
        db.commit()

        row = _counts(db, member)[space.id]
        assert row.conversations == 3, "the badge must still show every discussion"
        assert row.conversation_channels == (ch.id,), "but the Channel gets one dot"

    def test_nothing_unseen_names_no_channel(self, db, make_space, make_user):
        space = make_space(); member = make_user()
        _member(db, member, space)
        db.commit()

        row = _counts(db, member)[space.id]
        assert row.conversations == 0
        assert row.conversation_channels == (), "zero activity must produce no dot"

    def test_a_visited_channel_drops_out_and_the_other_remains(
        self, db, make_space, make_user,
    ):
        """Dots clear independently, for the same reason the counts do:
        the cursor is scoped per Channel."""
        from app.services.activity_cursors import advance

        space, member, _creator, a, b = self._two_channels(db, make_space, make_user)
        post_a = (
            db.query(CommunityPost)
            .filter(CommunityPost.channel_id == a.id).first()
        )
        advance(
            db, member, collective_id=space.id, category="conversations",
            subject_ids=[post_a.id],
            boundary_sequence=current_boundary(db, resolve_member_scope(db, member)),
        )
        db.commit()

        row = _counts(db, member)[space.id]
        assert row.conversations == 1
        assert row.conversation_channels == (b.id,), (
            "visiting Channel A must clear only A's dot"
        )

    def test_the_total_is_the_sum_of_the_channels(self, db, make_space, make_user):
        """Guards the finer GROUP BY: the category number is now summed
        across scope rows rather than read from one, so an assignment
        where a sum belongs would silently under-count."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        for n in (1, 2, 3):
            ch = _channel(db, space)
            for _ in range(n):
                post = _post(db, space, ch, creator)
                _activity(db, space, creator, category="conversations",
                          event_type="conversation_created", conversation_id=post.id)
        db.commit()

        row = _counts(db, member)[space.id]
        assert row.conversations == 6
        assert len(row.conversation_channels) == 3

    def test_pathways_and_gatherings_are_untouched_by_the_finer_grouping(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        _activity(db, space, creator, category="pathways",
                  event_type="pathway_published", pathway_id=pw.id)
        db.commit()

        row = _counts(db, member)[space.id]
        assert row.pathways == 1
        assert row.conversation_channels == ()

    def test_a_hidden_channel_is_never_named(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        ch = _channel(db, space)
        ch.show_in_navigation = False
        db.flush()
        post = _post(db, space, ch, creator)
        _activity(db, space, creator, category="conversations",
                  event_type="conversation_created", conversation_id=post.id)
        db.commit()

        row = _counts(db, member)[space.id]
        assert row.conversations == 0
        assert row.conversation_channels == ()
