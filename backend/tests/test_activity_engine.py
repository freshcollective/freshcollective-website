"""
Tests for the Fresh Collective Activity Engine (foundation).

Covers:

* ``ActivityService.create`` — resolves category + default priority,
  writes the row, respects payload/subject-entity args.
* ``ActivityService.create_for_recipients`` — fan-out, dedupe, no
  self-notify.
* Priority override.
* ``unread_count`` — respects read + archived state.
* ``mark_read`` — marks own only; refuses cross-user read.
* ``mark_all_read`` — bulk update, count returned.
* ``list_for_recipient`` — newest-first, unread filter, before cursor,
  archived filter.
* ``list_for_collective`` — Creator Dashboard feed.
* Route handlers — HTTP surface for the four notification-centre
  endpoints + the collective-scoped feed, including the ownership
  guard.

Tests use the same session/factory pattern as the rest of the suite:
per-test SAVEPOINT wrapping, real Postgres, direct import of route
handlers (no TestClient).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.activities.routes import (
    get_unread_count,
    list_activities,
    list_collective_activity,
    mark_activity_read,
    mark_all_activities_read,
)
from app.models.activity import (
    Activity,
    ActivityCategory,
    ActivityPriority,
    ActivityType,
    CATEGORY_OF,
    DEFAULT_PRIORITY_OF,
    RECENT_MOMENTS,
)
from app.services.activity_service import ActivityService


# ---------------------------------------------------------------------------
# Service — write path
# ---------------------------------------------------------------------------


def test_create_writes_row_with_derived_category_and_default_priority(db, make_user, make_space):
    actor = make_user()
    recipient = make_user()
    space = make_space()

    a = ActivityService.create(
        db,
        event_type=ActivityType.reply_received,
        recipient_user_id=recipient.id,
        actor_user_id=actor.id,
        collective_id=space.id,
        payload={"title": "Alex replied to your post", "url": "/spaces/foo"},
    )

    assert a.id.startswith("act_")
    assert a.event_type == "reply_received"
    assert a.category == ActivityCategory.personal.value
    assert a.priority == ActivityPriority.important.value
    assert a.actor_user_id == actor.id
    assert a.recipient_user_id == recipient.id
    assert a.collective_id == space.id
    assert a.payload == {"title": "Alex replied to your post", "url": "/spaces/foo"}
    assert a.read_at is None
    assert a.archived_at is None
    assert a.created_at is not None


def test_create_rejects_non_enum_event_type(db, make_user):
    recipient = make_user()
    with pytest.raises(TypeError):
        ActivityService.create(
            db,
            event_type="reply_received",  # type: ignore[arg-type]
            recipient_user_id=recipient.id,
        )


def test_create_respects_priority_override(db, make_user):
    recipient = make_user()
    # payment_successful defaults to `important` — override to critical
    # (e.g. for a first-time paying member celebration).
    a = ActivityService.create(
        db,
        event_type=ActivityType.payment_successful,
        recipient_user_id=recipient.id,
        priority=ActivityPriority.critical,
    )
    assert a.priority == ActivityPriority.critical.value


def test_priority_map_covers_every_event_type():
    """Regression: adding a new ActivityType must also extend the
    priority + category maps. The model file asserts this at import,
    but pin it here too so a broken map fails during collection."""
    assert set(CATEGORY_OF) == set(ActivityType)
    assert set(DEFAULT_PRIORITY_OF) == set(ActivityType)
    # Every default priority is a valid ActivityPriority.
    for p in DEFAULT_PRIORITY_OF.values():
        assert isinstance(p, ActivityPriority)


def test_priority_examples_from_spec():
    """Spot-check the priority classification called out in the spec."""
    assert DEFAULT_PRIORITY_OF[ActivityType.payment_failed]      == ActivityPriority.critical
    assert DEFAULT_PRIORITY_OF[ActivityType.gathering_cancelled] == ActivityPriority.critical
    assert DEFAULT_PRIORITY_OF[ActivityType.invitation_received] == ActivityPriority.critical

    assert DEFAULT_PRIORITY_OF[ActivityType.reply_received]      == ActivityPriority.important
    assert DEFAULT_PRIORITY_OF[ActivityType.mention_received]    == ActivityPriority.important
    assert DEFAULT_PRIORITY_OF[ActivityType.booking_confirmed]   == ActivityPriority.important

    assert DEFAULT_PRIORITY_OF[ActivityType.resource_added]      == ActivityPriority.standard
    assert DEFAULT_PRIORITY_OF[ActivityType.conversation_created] == ActivityPriority.standard
    assert DEFAULT_PRIORITY_OF[ActivityType.member_joined]       == ActivityPriority.standard

    assert DEFAULT_PRIORITY_OF[ActivityType.pathway_completed]   == ActivityPriority.passive
    assert DEFAULT_PRIORITY_OF[ActivityType.creator_payout]      == ActivityPriority.passive


# ---------------------------------------------------------------------------
# Service — fan-out
# ---------------------------------------------------------------------------


def test_create_for_recipients_writes_one_row_per_unique_recipient(db, make_user):
    actor = make_user()
    r1 = make_user()
    r2 = make_user()
    r3 = make_user()

    rows = ActivityService.create_for_recipients(
        db,
        event_type=ActivityType.pathway_published,
        recipient_user_ids=[r1.id, r2.id, r3.id],
        actor_user_id=actor.id,
        payload={"title": "New pathway"},
    )
    assert len(rows) == 3
    assert {r.recipient_user_id for r in rows} == {r1.id, r2.id, r3.id}
    # All share the derived category + default priority.
    assert {r.category for r in rows} == {ActivityCategory.pathways.value}
    assert {r.priority for r in rows} == {ActivityPriority.standard.value}


def test_create_for_recipients_deduplicates(db, make_user):
    r = make_user()
    rows = ActivityService.create_for_recipients(
        db,
        event_type=ActivityType.pathway_published,
        recipient_user_ids=[r.id, r.id, r.id],
    )
    assert len(rows) == 1


def test_create_for_recipients_skips_self_notify(db, make_user):
    actor = make_user()
    other = make_user()
    rows = ActivityService.create_for_recipients(
        db,
        event_type=ActivityType.pathway_published,
        recipient_user_ids=[actor.id, other.id],
        actor_user_id=actor.id,
    )
    assert [r.recipient_user_id for r in rows] == [other.id]


def test_create_for_recipients_ignores_empty_ids(db, make_user):
    r = make_user()
    rows = ActivityService.create_for_recipients(
        db,
        event_type=ActivityType.member_joined,
        recipient_user_ids=[r.id, "", None],  # type: ignore[list-item]
    )
    assert [row.recipient_user_id for row in rows] == [r.id]


# ---------------------------------------------------------------------------
# Service — read helpers
# ---------------------------------------------------------------------------


def test_unread_count_excludes_read_and_archived(db, make_user):
    r = make_user()
    a1 = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    a2 = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    a3 = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)

    # Mark one as read, archive another.
    ActivityService.mark_read(db, activity_id=a1.id, recipient_user_id=r.id)
    a3.archived_at = datetime.utcnow()
    db.flush()

    assert ActivityService.unread_count(db, recipient_user_id=r.id) == 1
    # Ensure we didn't accidentally read cross-user rows.
    other = make_user()
    ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=other.id)
    assert ActivityService.unread_count(db, recipient_user_id=r.id) == 1


def test_mark_read_only_marks_own(db, make_user):
    owner = make_user()
    intruder = make_user()
    a = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=owner.id)

    # Wrong user → returns None, doesn't mark.
    assert ActivityService.mark_read(db, activity_id=a.id, recipient_user_id=intruder.id) is None
    db.refresh(a)
    assert a.read_at is None

    # Right user → marks + returns the row.
    got = ActivityService.mark_read(db, activity_id=a.id, recipient_user_id=owner.id)
    assert got is not None
    assert got.read_at is not None


def test_mark_read_is_idempotent(db, make_user):
    r = make_user()
    a = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    first = ActivityService.mark_read(db, activity_id=a.id, recipient_user_id=r.id)
    ts = first.read_at
    # Second call must not push the timestamp forward.
    second = ActivityService.mark_read(db, activity_id=a.id, recipient_user_id=r.id)
    assert second.read_at == ts


def test_mark_all_read_updates_only_unread_for_user(db, make_user):
    r = make_user()
    other = make_user()
    a1 = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    a2 = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    ActivityService.mark_read(db, activity_id=a1.id, recipient_user_id=r.id)
    ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=other.id)

    n = ActivityService.mark_all_read(db, recipient_user_id=r.id)
    assert n == 1  # only a2 was unread for r
    # Other user's row still unread.
    remaining = ActivityService.unread_count(db, recipient_user_id=other.id)
    assert remaining == 1


def test_list_for_recipient_newest_first_with_cursor(db, make_user):
    r = make_user()
    a1 = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    # Force a monotonic ordering that doesn't depend on wall-clock
    # jitter (server_default now() is applied on insert; we spread the
    # created_at values manually so the cursor test is deterministic).
    a1.created_at = datetime.utcnow() - timedelta(minutes=5)
    a2 = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    a2.created_at = datetime.utcnow() - timedelta(minutes=3)
    a3 = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    a3.created_at = datetime.utcnow() - timedelta(minutes=1)
    db.flush()

    page = ActivityService.list_for_recipient(db, recipient_user_id=r.id, limit=2)
    assert [x.id for x in page] == [a3.id, a2.id]

    next_page = ActivityService.list_for_recipient(
        db, recipient_user_id=r.id, limit=2, before=page[-1].created_at,
    )
    assert [x.id for x in next_page] == [a1.id]


def test_list_for_recipient_unread_and_archived_filters(db, make_user):
    r = make_user()
    a_read = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    a_unread = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    a_archived = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    ActivityService.mark_read(db, activity_id=a_read.id, recipient_user_id=r.id)
    a_archived.archived_at = datetime.utcnow()
    db.flush()

    default = {x.id for x in ActivityService.list_for_recipient(db, recipient_user_id=r.id)}
    assert default == {a_read.id, a_unread.id}   # archived hidden by default

    unread_only = {x.id for x in ActivityService.list_for_recipient(db, recipient_user_id=r.id, unread_only=True)}
    assert unread_only == {a_unread.id}

    with_archived = {x.id for x in ActivityService.list_for_recipient(db, recipient_user_id=r.id, include_archived=True)}
    assert with_archived == {a_read.id, a_unread.id, a_archived.id}


def test_list_for_collective_scoped_to_collective(db, make_user, make_space):
    space_a = make_space()
    space_b = make_space()
    r = make_user()
    ActivityService.create(db, event_type=ActivityType.member_joined, recipient_user_id=r.id, collective_id=space_a.id)
    ActivityService.create(db, event_type=ActivityType.member_joined, recipient_user_id=r.id, collective_id=space_a.id)
    ActivityService.create(db, event_type=ActivityType.member_joined, recipient_user_id=r.id, collective_id=space_b.id)

    rows_a = ActivityService.list_for_collective(db, collective_id=space_a.id)
    rows_b = ActivityService.list_for_collective(db, collective_id=space_b.id)
    assert len(rows_a) == 2
    assert len(rows_b) == 1


# ---------------------------------------------------------------------------
# HTTP surface — route handlers called directly (no TestClient).
# ---------------------------------------------------------------------------


def test_route_list_activities_paginates(db, make_user):
    r = make_user()
    ids = []
    for i in range(3):
        a = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
        # Deterministic ordering.
        a.created_at = datetime.utcnow() - timedelta(minutes=(3 - i))
        ids.append(a.id)
    db.flush()

    resp = list_activities(
        unread_only=False,
        include_archived=False,
        limit=2,
        before=None,
        collective_id=None,
        recent_moments=False,
        current_user=r,
        db=db,
    )
    assert [a.id for a in resp.activities] == [ids[2], ids[1]]
    assert resp.next_before is not None

    page2 = list_activities(
        unread_only=False,
        include_archived=False,
        limit=2,
        before=resp.next_before,
        collective_id=None,
        recent_moments=False,
        current_user=r,
        db=db,
    )
    assert [a.id for a in page2.activities] == [ids[0]]
    assert page2.next_before is None


def test_route_unread_count(db, make_user):
    r = make_user()
    ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    assert get_unread_count(current_user=r, db=db).unread == 2


def test_route_mark_read_marks_and_returns_row(db, make_user):
    r = make_user()
    a = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    out = mark_activity_read(activity_id=a.id, current_user=r, db=db)
    assert out.id == a.id
    assert out.read_at is not None


def test_route_mark_read_404s_for_other_users_activity(db, make_user):
    owner = make_user()
    intruder = make_user()
    a = ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=owner.id)
    with pytest.raises(HTTPException) as excinfo:
        mark_activity_read(activity_id=a.id, current_user=intruder, db=db)
    assert excinfo.value.status_code == 404


def test_route_mark_all_read_returns_count(db, make_user):
    r = make_user()
    ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    ActivityService.create(db, event_type=ActivityType.reply_received, recipient_user_id=r.id)
    resp = mark_all_activities_read(current_user=r, db=db)
    assert resp.marked_read == 2
    # Second call → 0 (nothing left unread).
    resp2 = mark_all_activities_read(current_user=r, db=db)
    assert resp2.marked_read == 0


def test_route_collective_activity_requires_ownership(db, make_user, make_space):
    space = make_space()  # created with a fresh creator user by default
    intruder = make_user()  # non-admin, non-owner

    with pytest.raises(HTTPException) as excinfo:
        list_collective_activity(
            slug=space.slug,
            limit=30,
            before=None,
            current_user=intruder,
            db=db,
        )
    # 404, not 403 — never leak that the collective exists to a stranger.
    assert excinfo.value.status_code == 404


def test_route_collective_activity_returns_scoped_feed(db, make_user, make_space):
    space = make_space()
    # The creator of the space is the caller. We need to look up the
    # creator user; make_space assigns a fresh creator we can grab.
    creator = db.query(type(make_user())).filter_by(id=space.creator_id).one()
    member = make_user()

    ActivityService.create(
        db, event_type=ActivityType.member_joined, recipient_user_id=creator.id,
        collective_id=space.id,
        payload={"actor_name": "Emily"},
    )
    ActivityService.create(
        db, event_type=ActivityType.pathway_completed, recipient_user_id=creator.id,
        collective_id=space.id,
        payload={"actor_name": "Sarah", "pathway_title": "Week 4"},
    )
    # Noise on another collective — must not leak into this feed.
    other = make_space()
    ActivityService.create(
        db, event_type=ActivityType.member_joined, recipient_user_id=member.id,
        collective_id=other.id,
    )

    resp = list_collective_activity(
        slug=space.slug,
        limit=30,
        before=None,
        current_user=creator,
        db=db,
    )
    assert all(a.collective_id == space.id for a in resp.activities)
    assert len(resp.activities) == 2


def test_route_collective_activity_404s_on_unknown_slug(db, make_user):
    r = make_user()
    with pytest.raises(HTTPException) as excinfo:
        list_collective_activity(
            slug="does-not-exist",
            limit=30,
            before=None,
            current_user=r,
            db=db,
        )
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# ?collective_id= filter — powers the per-collective "Recent Moments" panel
# on the member-side sidebar without adding a second route.
# ---------------------------------------------------------------------------


def test_service_list_for_recipient_collective_filter(db, make_user, make_space):
    r = make_user()
    space_a = make_space()
    space_b = make_space()

    a1 = ActivityService.create(
        db, event_type=ActivityType.reply_received, recipient_user_id=r.id,
        collective_id=space_a.id,
    )
    a2 = ActivityService.create(
        db, event_type=ActivityType.reply_received, recipient_user_id=r.id,
        collective_id=space_a.id,
    )
    ActivityService.create(
        db, event_type=ActivityType.reply_received, recipient_user_id=r.id,
        collective_id=space_b.id,
    )
    # Also an unrelated activity for another user in space_a — must not
    # leak (filter is additive, recipient scope is preserved).
    other = make_user()
    ActivityService.create(
        db, event_type=ActivityType.reply_received, recipient_user_id=other.id,
        collective_id=space_a.id,
    )

    rows = ActivityService.list_for_recipient(
        db, recipient_user_id=r.id, collective_id=space_a.id,
    )
    assert {row.id for row in rows} == {a1.id, a2.id}


def test_route_list_activities_collective_filter(db, make_user, make_space):
    r = make_user()
    space_a = make_space()
    space_b = make_space()
    a_in = ActivityService.create(
        db, event_type=ActivityType.member_joined, recipient_user_id=r.id,
        collective_id=space_a.id,
    )
    ActivityService.create(
        db, event_type=ActivityType.member_joined, recipient_user_id=r.id,
        collective_id=space_b.id,
    )

    resp = list_activities(
        unread_only=False,
        include_archived=False,
        limit=20,
        before=None,
        collective_id=space_a.id,
        recent_moments=False,
        current_user=r,
        db=db,
    )
    assert [a.id for a in resp.activities] == [a_in.id]


def test_route_list_activities_without_collective_filter_returns_all(db, make_user, make_space):
    """Sanity: leaving ``collective_id`` unset preserves the pre-existing
    behaviour — the caller sees every activity across their world."""
    r = make_user()
    space_a = make_space()
    space_b = make_space()
    ActivityService.create(
        db, event_type=ActivityType.member_joined, recipient_user_id=r.id,
        collective_id=space_a.id,
    )
    ActivityService.create(
        db, event_type=ActivityType.member_joined, recipient_user_id=r.id,
        collective_id=space_b.id,
    )

    resp = list_activities(
        unread_only=False,
        include_archived=False,
        limit=20,
        before=None,
        collective_id=None,
        recent_moments=False,
        current_user=r,
        db=db,
    )
    assert len(resp.activities) == 2


# ---------------------------------------------------------------------------
# Recent Moments whitelist — the curated view of the ledger.
# ---------------------------------------------------------------------------


def test_recent_moments_whitelist_shape():
    """Regression: adding a new ActivityType should not accidentally
    surface it in Recent Moments. Every member of RECENT_MOMENTS must
    be a real ActivityType, and no attention-required event may sneak
    in."""
    assert all(isinstance(t, ActivityType) for t in RECENT_MOMENTS)
    # Spot-check the strictly-not-RM events approved in the design.
    for t in (
        ActivityType.payment_failed,
        ActivityType.payment_successful,
        ActivityType.gathering_reminder,
        ActivityType.gathering_changed,
        ActivityType.gathering_cancelled,
        ActivityType.subscription_started,
        ActivityType.subscription_renewed,
        ActivityType.subscription_cancelled,
        ActivityType.password_changed,
        ActivityType.creator_payout,
        ActivityType.invitation_received,
        ActivityType.private_message_received,
        ActivityType.reaction_received,
        ActivityType.conversation_followed,
        ActivityType.member_left,
        ActivityType.resource_updated,
    ):
        assert t not in RECENT_MOMENTS, f"{t.value} must not be in RECENT_MOMENTS"


def test_service_recent_moments_only_filter(db, make_user):
    r = make_user()
    # An RM event and a non-RM event.
    rm = ActivityService.create(
        db, event_type=ActivityType.member_joined, recipient_user_id=r.id,
    )
    ActivityService.create(
        db, event_type=ActivityType.payment_failed, recipient_user_id=r.id,
    )

    all_rows = ActivityService.list_for_recipient(db, recipient_user_id=r.id)
    assert len(all_rows) == 2

    rm_only = ActivityService.list_for_recipient(
        db, recipient_user_id=r.id, recent_moments_only=True,
    )
    assert [x.id for x in rm_only] == [rm.id]


def test_route_recent_moments_filter(db, make_user):
    r = make_user()
    rm = ActivityService.create(
        db, event_type=ActivityType.creator_announcement, recipient_user_id=r.id,
    )
    ActivityService.create(
        db, event_type=ActivityType.password_changed, recipient_user_id=r.id,
    )

    resp = list_activities(
        unread_only=False,
        include_archived=False,
        limit=20,
        before=None,
        collective_id=None,
        recent_moments=True,
        current_user=r,
        db=db,
    )
    assert [a.id for a in resp.activities] == [rm.id]
