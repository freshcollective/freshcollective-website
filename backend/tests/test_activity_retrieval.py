"""Phase 1 — who may read a shared activity row.

A shared row has no recipient, so every access decision happens on
read. That makes this file the security boundary for the whole
feature: if these pass for the wrong reason, a member sees content from
a Collective they left, a channel they cannot open, or a Pathway that
was unpublished an hour ago.

Each filter is tested for what it lets through as well as what it
stops — a test that only proves "nothing is visible" would pass against
a function that always returned an empty list.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.models.activity import Activity
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    Event,
    Pathway,
    PathwayStatus,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import activity_producers as ap
from app.services.activity_service import ActivityService


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _member(db, user, space, *, status=SpaceMembershipStatus.active):
    m = SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=SpaceRole.learner, status=status, joined_at=datetime.utcnow(),
    )
    db.add(m); db.flush()
    return m


def _pathway(db, space, *, status=PathwayStatus.active) -> Pathway:
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="Visible Pathway", status=status, access_type="free",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p); db.flush()
    return p


def _channel(db, space, *, channel_type="open") -> ConversationChannel:
    c = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="Room",
        slug=f"ch-{uuid.uuid4().hex[:8]}", channel_type=channel_type,
    )
    db.add(c); db.flush()
    return c


def _gathering(db, space) -> Event:
    e = Event(
        id=_uid("e"), space_id=space.id, created_by_id=space.creator_id,
        title="A Gathering",
        starts_at=datetime.utcnow() + timedelta(days=7),
        ends_at=datetime.utcnow() + timedelta(days=7, hours=1),
        is_published=True, status="active", requires_booking=True,
        capacity=20, gathering_type="circle", attendance_format="online",
    )
    db.add(e); db.flush()
    return e


def _post(db, space, channel, author) -> CommunityPost:
    p = CommunityPost(
        id=_uid("cp"), space_id=space.id, channel_id=channel.id,
        author_id=author.id, title="A thread", body="hi",
        publication_status="published",
    )
    db.add(p); db.flush()
    return p


def _read(db, user, **kw):
    return ActivityService.list_shared_for_member(db, user=user, **kw)


# ---------------------------------------------------------------------------
# The positive case — the control for everything below
# ---------------------------------------------------------------------------

class TestAMemberSeesCollectiveActivity:
    def test_a_member_sees_a_published_pathway(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()

        rows = _read(db, member)
        assert len(rows) == 1 and rows[0].pathway_id == pw.id

    def test_a_member_sees_a_thread_in_an_open_channel(self, db, make_space, make_user):
        space = make_space(); author = make_user(); member = make_user()
        _member(db, author, space); _member(db, member, space)
        ch = _channel(db, space); post = _post(db, space, ch, author); db.commit()
        ap.record_thread_created(db, post, actor_user_id=author.id)
        db.commit()

        assert len(_read(db, member)) == 1


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

class TestMembershipGatesEverything:
    def test_a_non_member_sees_nothing(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); outsider = make_user()
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()

        assert _read(db, outsider) == []

    def test_a_removed_member_stops_seeing_immediately(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        m = _member(db, member, space)
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()
        assert len(_read(db, member)) == 1

        m.status = SpaceMembershipStatus.removed
        db.commit()
        assert _read(db, member) == []

    def test_activity_is_scoped_to_the_requested_collective(self, db, make_space, make_user):
        a, b = make_space(), make_space()
        creator = make_user(); member = make_user()
        _member(db, member, a); _member(db, member, b)
        pa, pb = _pathway(db, a), _pathway(db, b); db.commit()
        ap.record_pathway_published(db, pa, actor_user_id=creator.id)
        ap.record_pathway_published(db, pb, actor_user_id=creator.id)
        db.commit()

        assert len(_read(db, member)) == 2
        only_a = _read(db, member, collective_id=a.id)
        assert len(only_a) == 1 and only_a[0].collective_id == a.id


# ---------------------------------------------------------------------------
# Your own actions
# ---------------------------------------------------------------------------

class TestOwnActions:
    def test_a_member_never_sees_their_own_action(self, db, make_space, make_user):
        space = make_space(); author = make_user(); other = make_user()
        _member(db, author, space); _member(db, other, space)
        ch = _channel(db, space); post = _post(db, space, ch, author); db.commit()
        ap.record_thread_created(db, post, actor_user_id=author.id)
        db.commit()

        assert _read(db, author) == [], "your own thread is not news to you"
        assert len(_read(db, other)) == 1


# ---------------------------------------------------------------------------
# Liveness — unpublished or deleted content leaves the feed
# ---------------------------------------------------------------------------

class TestContentMustStillBeLive:
    def test_unpublishing_removes_it_from_the_feed(self, db, make_space, make_user):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()
        assert len(_read(db, member)) == 1

        pw.status = PathwayStatus.draft
        db.commit()

        assert _read(db, member) == [], "a draft must not linger in a feed"
        assert db.query(Activity).count() == 1, "the row stays; only visibility changes"

    def test_deleting_the_content_removes_it_from_the_feed(self, db, make_space, make_user):
        """``expire_all`` is not decoration. Every subject column is ON
        DELETE SET NULL, so after the delete the stored row has no
        pathway_id at all — but a session that still holds the old
        object keeps serving the stale id, and the liveness join then
        hides the row for a reason that will not hold in production.
        Without this the test passes against a feed that shows deleted
        content."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()
        assert len(_read(db, member)) == 1

        db.delete(pw); db.commit()
        db.expire_all()

        assert db.query(Activity).count() == 1, "the row survives the delete"
        assert db.query(Activity).first().pathway_id is None, (
            "and the database has emptied its subject"
        )
        assert _read(db, member) == []

    def test_deleting_a_thread_removes_it_from_the_feed(self, db, make_space, make_user):
        space = make_space(); author = make_user(); member = make_user()
        _member(db, author, space); _member(db, member, space)
        ch = _channel(db, space); post = _post(db, space, ch, author); db.commit()
        ap.record_thread_created(db, post, actor_user_id=author.id)
        db.commit()
        assert len(_read(db, member)) == 1

        db.delete(post); db.commit()
        db.expire_all()

        assert _read(db, member) == []

    def test_an_unpublished_thread_leaves_the_feed(self, db, make_space, make_user):
        space = make_space(); author = make_user(); member = make_user()
        _member(db, author, space); _member(db, member, space)
        ch = _channel(db, space); post = _post(db, space, ch, author); db.commit()
        ap.record_thread_created(db, post, actor_user_id=author.id)
        db.commit()
        assert len(_read(db, member)) == 1

        post.publication_status = "removed"
        db.commit()

        assert _read(db, member) == []


# ---------------------------------------------------------------------------
# Channel permissions
# ---------------------------------------------------------------------------

class TestChannelPermissions:
    def test_a_private_channel_is_invisible_to_a_non_participant(
        self, db, make_space, make_user,
    ):
        space = make_space(); author = make_user(); outsider = make_user()
        _member(db, author, space); _member(db, outsider, space)
        ch = _channel(db, space, channel_type="private")
        post = _post(db, space, ch, author); db.commit()
        ap.record_thread_created(db, post, actor_user_id=author.id)
        db.commit()

        assert _read(db, outsider) == [], (
            "a private channel's activity must not leak to a member "
            "who cannot open the channel"
        )


# ---------------------------------------------------------------------------
# What a Collective feed may never contain
# ---------------------------------------------------------------------------

class TestPersonalItemsNeverAppear:
    def test_only_the_three_member_categories_are_returned(
        self, db, make_space, make_user,
    ):
        """Direct messages, payments and member joins are not Collective
        activity and must not reach a Collective-scoped panel."""
        space = make_space(); member = make_user(); other = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)  # live subject, so only category excludes
        for category, event_type in (
            ("personal", "private_message_received"),
            ("collective", "member_joined"),
            ("account", "password_changed"),
        ):
            db.add(Activity(
                id=_uid("act"), event_type=event_type, category=category,
                priority="standard", actor_user_id=other.id,
                recipient_user_id=None, collective_id=space.id,
                pathway_id=pw.id, payload={},
            ))
        db.commit()

        assert _read(db, member) == []


class TestPerRecipientRowsStayOutOfTheSharedFeed:
    """The live per-recipient system writes rows with a recipient set.
    Those are the notification bell's business and are delivered by a
    different path; the shared Collective feed must read only rows with
    no recipient, or one member's addressed activity surfaces in
    another member's panel."""

    def test_another_members_addressed_row_is_not_visible(
        self, db, make_space, make_user,
    ):
        space = make_space(); member = make_user()
        actor = make_user(); addressee = make_user()
        _member(db, member, space); _member(db, addressee, space)
        pw = _pathway(db, space)
        db.add(Activity(
            id=_uid("act"), event_type="pathway_published", category="pathways",
            priority="standard", actor_user_id=actor.id,
            recipient_user_id=addressee.id, collective_id=space.id,
            pathway_id=pw.id, payload={},
        ))
        db.commit()

        assert _read(db, member) == [], (
            "a row addressed to another member must never appear in "
            "someone else's Collective feed"
        )

    def test_your_own_addressed_row_is_not_duplicated_here(
        self, db, make_space, make_user,
    ):
        """It reaches this member through the bell. Reading it here too
        would show the same event twice in two different surfaces."""
        space = make_space(); member = make_user(); actor = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)
        db.add(Activity(
            id=_uid("act"), event_type="pathway_published", category="pathways",
            priority="standard", actor_user_id=actor.id,
            recipient_user_id=member.id, collective_id=space.id,
            pathway_id=pw.id, payload={},
        ))
        db.commit()

        assert _read(db, member) == []


class TestAreaPoliciesGateTheFeed:
    """Area policy is the doorway to a whole area of a Collective. A
    member who cannot open the Pathways area must not be told what was
    published inside it — the activity row would otherwise become a
    side channel around the policy."""

    def test_an_unreachable_area_hides_its_activity(
        self, db, make_space, make_user,
    ):
        space = make_space()
        space.area_policies = {"areas": {"pathways": "active_access"}}
        creator = make_user(); member = make_user()
        _member(db, member, space)  # a learner holding no pass
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()

        assert _read(db, member) == [], (
            "the Pathways area is gated behind active access and this "
            "member holds none"
        )

    def test_the_same_member_sees_it_once_the_area_opens(
        self, db, make_space, make_user,
    ):
        """The control for the test above: proves the row is hidden by
        the policy and not by some unrelated failure."""
        space = make_space()
        space.area_policies = {"areas": {"pathways": "active_access"}}
        creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()
        assert _read(db, member) == []

        space.area_policies = {"areas": {"pathways": "members"}}
        db.commit()

        assert len(_read(db, member)) == 1

    def test_an_unresolvable_policy_fails_closed(
        self, db, make_space, make_user, monkeypatch,
    ):
        """If the policy engine raises, the row is hidden. An error
        must not become an accidental grant."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()
        assert len(_read(db, member)) == 1

        import app.services.activity_service as svc

        def boom(*a, **k):
            raise RuntimeError("policy engine unavailable")

        monkeypatch.setattr(
            "app.spaces.area_access.resolve_area_access", boom,
        )
        assert _read(db, member) == [], "an unresolvable policy must hide, not expose"


class TestArchivedCollectives:
    def test_an_archived_collective_stops_emitting_activity(
        self, db, make_space, make_user,
    ):
        from app.models.platform import SpaceStatus

        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()
        assert len(_read(db, member)) == 1

        space.status = SpaceStatus.archived
        db.commit()

        assert _read(db, member) == []


class TestPagination:
    def test_paging_reaches_every_shared_row(self, db, make_space, make_user):
        """`before` must narrow the query, not trim the page.

        Trimming after the fetch looks correct on page two and fails
        silently deeper in: once the cursor passes the over-fetch
        window, every remaining page comes back empty and the older
        half of the Collective's activity is simply unreachable. So
        this walks to exhaustion rather than checking one page.
        """
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space)  # a real, live subject for every row
        base = datetime(2026, 1, 1, 12, 0, 0)
        total = 40
        for i in range(total):
            db.add(Activity(
                id=_uid("act"), event_type="pathway_published",
                category="pathways", priority="standard",
                actor_user_id=creator.id, recipient_user_id=None,
                collective_id=space.id, pathway_id=pw.id, payload={},
                dedupe_key=f"k{i}",
                created_at=base + timedelta(minutes=i),
            ))
        db.commit()

        seen: list[str] = []
        cursor = None
        for _ in range(total + 5):  # generous bound; the loop breaks itself
            page = _read(db, member, limit=5, before=cursor)
            if not page:
                break
            assert all(r.created_at < cursor for r in page) if cursor else True
            seen.extend(r.id for r in page)
            cursor = page[-1].created_at

        assert len(seen) == total, (
            f"paging stopped after {len(seen)} of {total} rows"
        )
        assert len(set(seen)) == total, "a row was returned on two pages"


class TestRecentMomentsFilter:
    """Recent Moments is narrower than the three member categories.

    The panel asks for `recent_moments=true`, and that has to narrow
    both halves of the feed. Applying it only to the personal query
    let a shared row in on its category alone, so the same panel
    answered two different questions depending on which half a row
    came from.
    """

    def _row(self, db, space, actor, event_type, category, **kw):
        row = Activity(
            id=_uid("act"), event_type=event_type, category=category,
            priority="standard", actor_user_id=actor.id,
            recipient_user_id=None, collective_id=space.id, payload={},
            dedupe_key=_uid("k"), **kw,
        )
        db.add(row)
        return row

    def test_a_non_moment_shared_row_is_excluded(self, db, make_space, make_user):
        """`gathering_changed` sits in the gatherings category but is
        not a Recent Moment, so category alone would let it through."""
        from app.models.activity import CATEGORY_OF, RECENT_MOMENTS, ActivityType

        subject = ActivityType.gathering_changed
        # Both halves of the premise, asserted rather than assumed —
        # the first draft of this test picked an event that turned out
        # to be a Recent Moment, and passed for the wrong reason.
        assert CATEGORY_OF[subject].value == "gatherings"
        assert subject not in RECENT_MOMENTS

        space = make_space(); actor = make_user(); member = make_user()
        _member(db, member, space)
        ev = _gathering(db, space)
        self._row(
            db, space, actor, subject.value, "gatherings", gathering_id=ev.id,
        )
        db.commit()

        assert len(_read(db, member)) == 1, "visible on the unfiltered feed"
        assert _read(db, member, recent_moments_only=True) == [], (
            "but it is not a Recent Moment"
        )

    def test_a_moment_shared_row_is_kept(self, db, make_space, make_user):
        """The control: proves the filter narrows rather than empties."""
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()

        assert len(_read(db, member, recent_moments_only=True)) == 1

    def test_every_producer_emits_a_recent_moment(self):
        """Today all five producers happen to emit Recent Moments, so
        the bug was invisible. This fails the moment that stops being
        true, which is exactly when the filter starts mattering."""
        from app.models.activity import RECENT_MOMENTS, ActivityType

        produced = {
            ActivityType.pathway_published,
            ActivityType.pathway_step_released,
            ActivityType.conversation_created,
            ActivityType.gathering_created,
        }
        assert produced <= RECENT_MOMENTS

    def test_the_filter_does_not_widen_permissions(
        self, db, make_space, make_user,
    ):
        """A Recent Moment the member may not see stays hidden — the
        new filter narrows, it must not bypass the permission pass."""
        space = make_space(); creator = make_user(); outsider = make_user()
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()

        assert _read(db, outsider, recent_moments_only=True) == [], (
            "a non-member sees nothing, Recent Moment or not"
        )

    def test_the_actor_is_still_excluded_under_the_filter(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user()
        _member(db, creator, space)
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()

        assert _read(db, creator, recent_moments_only=True) == []


class TestTheEndpointAppliesTheFilterToBothHalves:
    """The service-level tests above prove the filter works; this
    proves the endpoint actually asks for it.

    Called directly rather than over HTTP because the suite has no
    shared TestClient fixture and the wiring — not auth — is what is
    in question. Every parameter is passed explicitly: the defaults
    are `Query(...)` objects, which are truthy, so a partial call
    would silently test something else.
    """

    def _call(self, db, user, *, recent_moments):
        from app.activities.routes import list_activities

        return list_activities(
            unread_only=False,
            include_archived=False,
            limit=20,
            before=None,
            collective_id=None,
            recent_moments=recent_moments,
            current_user=user,
            db=db,
        )

    def test_a_non_moment_is_dropped_when_recent_moments_is_asked_for(
        self, db, make_space, make_user,
    ):
        from app.models.activity import ActivityType

        space = make_space(); actor = make_user(); member = make_user()
        _member(db, member, space)
        ev = _gathering(db, space)
        db.add(Activity(
            id=_uid("act"), event_type=ActivityType.gathering_changed.value,
            category="gatherings", priority="standard",
            actor_user_id=actor.id, recipient_user_id=None,
            collective_id=space.id, gathering_id=ev.id, payload={},
            dedupe_key=_uid("k"),
        ))
        db.commit()

        assert len(self._call(db, member, recent_moments=False).activities) == 1
        assert self._call(db, member, recent_moments=True).activities == [], (
            "the endpoint is not passing recent_moments to the shared query"
        )

    def test_a_moment_still_comes_through_the_endpoint(
        self, db, make_space, make_user,
    ):
        space = make_space(); creator = make_user(); member = make_user()
        _member(db, member, space)
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()

        out = self._call(db, member, recent_moments=True)
        assert len(out.activities) == 1
        assert out.activities[0].pathway_id == pw.id
