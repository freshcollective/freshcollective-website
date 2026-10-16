"""Scheduled posts actually publish.

``publish_due_posts`` had no direct test, and that is exactly how
FC-API-8 shipped: a function-local ``from app.models.platform import
CommunityPost`` inside the function made the name a local for the
whole body, so the module-level import was shadowed and the *first*
statement to touch it raised ``UnboundLocalError``. Every call failed,
on every path, for twelve hours. Nothing published.

The failure was invisible from both sides. The background loop catches
and retries, so the process stayed up; the read-path caller wraps it
in ``try/except: pass``, so no member ever saw an error. Only Sentry
knew.

Phase 1's tests covered the producer this function calls and never the
function itself, which is the gap these close: the first test here
exercises the real entry point, and fails with the original
``UnboundLocalError`` if the import is put back.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.models.activity import Activity
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    SpaceStatus,
)
from app.services.scheduled_publisher import publish_due_posts


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _channel(db, space, *, archived=False) -> ConversationChannel:
    c = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="Room",
        slug=f"ch-{uuid.uuid4().hex[:8]}", channel_type="open",
        is_archived=archived,
    )
    db.add(c); db.flush()
    return c


def _scheduled(db, space, channel, author, *, when=None) -> CommunityPost:
    p = CommunityPost(
        id=_uid("cp"), space_id=space.id, channel_id=channel.id,
        author_id=author.id, title="Scheduled thread", body="hello",
        publication_status="scheduled",
        scheduled_for=when or (datetime.utcnow() - timedelta(minutes=5)),
    )
    db.add(p); db.flush()
    return p


def _status(db, post_id: str) -> str:
    db.expire_all()
    return (
        db.query(CommunityPost)
        .filter(CommunityPost.id == post_id)
        .first()
        .publication_status
    )


# ---------------------------------------------------------------------------
# 1 · The regression itself
# ---------------------------------------------------------------------------

class TestADuePostPublishes:
    def test_a_post_past_its_time_is_published(self, db, make_space, make_user):
        """FC-API-8. Against the original code this raises
        ``UnboundLocalError`` before selecting anything."""
        space = make_space(); author = make_user()
        ch = _channel(db, space)
        post = _scheduled(db, space, ch, author)
        db.commit()

        published = publish_due_posts(db)
        db.commit()

        assert published == [post.id]
        assert _status(db, post.id) == "published"

    def test_publishing_stamps_the_processed_marker(
        self, db, make_space, make_user,
    ):
        """``notifications_processed_at`` is the duplicate guard, so it
        has to be set by the same statement that publishes."""
        space = make_space(); author = make_user()
        ch = _channel(db, space)
        post = _scheduled(db, space, ch, author)
        db.commit()

        publish_due_posts(db)
        db.commit(); db.expire_all()

        row = db.query(CommunityPost).filter(CommunityPost.id == post.id).first()
        assert row.notifications_processed_at is not None
        assert row.published_at is not None

    def test_it_records_exactly_one_shared_activity_row(
        self, db, make_space, make_user,
    ):
        """The Phase 1 producer hook lives inside this function — the
        very code the shadowed import was added for."""
        space = make_space(); author = make_user()
        ch = _channel(db, space)
        post = _scheduled(db, space, ch, author)
        db.commit()

        publish_due_posts(db)
        db.commit()

        rows = db.query(Activity).filter(
            Activity.conversation_id == post.id,
            Activity.recipient_user_id.is_(None),
        ).all()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# 2 · Nothing publishes twice
# ---------------------------------------------------------------------------

class TestDuplicatePrevention:
    def test_a_second_pass_publishes_nothing_further(
        self, db, make_space, make_user,
    ):
        space = make_space(); author = make_user()
        ch = _channel(db, space)
        post = _scheduled(db, space, ch, author)
        db.commit()

        first = publish_due_posts(db); db.commit()
        second = publish_due_posts(db); db.commit()

        assert first == [post.id]
        assert second == [], "the post was published a second time"

    def test_a_second_pass_adds_no_further_activity(
        self, db, make_space, make_user,
    ):
        space = make_space(); author = make_user()
        ch = _channel(db, space)
        post = _scheduled(db, space, ch, author)
        db.commit()

        publish_due_posts(db); db.commit()
        publish_due_posts(db); db.commit()

        assert db.query(Activity).filter(
            Activity.conversation_id == post.id
        ).count() == 1


# ---------------------------------------------------------------------------
# 3 · What must be left alone
# ---------------------------------------------------------------------------

class TestWhatIsSkipped:
    def test_a_future_post_is_not_touched(self, db, make_space, make_user):
        space = make_space(); author = make_user()
        ch = _channel(db, space)
        post = _scheduled(
            db, space, ch, author, when=datetime.utcnow() + timedelta(hours=2),
        )
        db.commit()

        assert publish_due_posts(db) == []
        assert _status(db, post.id) == "scheduled"

    def test_a_post_in_an_archived_channel_waits(self, db, make_space, make_user):
        """The caretaker decides — restore, cancel or reschedule. The
        row stays scheduled and resumes automatically on restore."""
        space = make_space(); author = make_user()
        ch = _channel(db, space, archived=True)
        post = _scheduled(db, space, ch, author)
        db.commit()

        assert publish_due_posts(db) == []
        assert _status(db, post.id) == "scheduled"

        ch.is_archived = False
        db.commit()
        assert publish_due_posts(db) == [post.id]

    def test_a_post_in_an_inactive_collective_waits(
        self, db, make_space, make_user,
    ):
        space = make_space(); author = make_user()
        ch = _channel(db, space)
        post = _scheduled(db, space, ch, author)
        space.status = SpaceStatus.archived
        db.commit()

        assert publish_due_posts(db) == []
        assert _status(db, post.id) == "scheduled"

        space.status = SpaceStatus.active
        db.commit()
        assert publish_due_posts(db) == [post.id], (
            "it must resume once the Collective is active again"
        )

    def test_an_already_published_post_is_ignored(self, db, make_space, make_user):
        space = make_space(); author = make_user()
        ch = _channel(db, space)
        p = CommunityPost(
            id=_uid("cp"), space_id=space.id, channel_id=ch.id,
            author_id=author.id, title="Already out", body="x",
            publication_status="published",
            scheduled_for=datetime.utcnow() - timedelta(hours=1),
            published_at=datetime.utcnow() - timedelta(hours=1),
        )
        db.add(p); db.commit()

        assert publish_due_posts(db) == []


# ---------------------------------------------------------------------------
# 4 · The shape that caused it
# ---------------------------------------------------------------------------

class TestNoShadowedModuleImports:
    """A source check, because the behavioural tests above only catch
    this for ``CommunityPost``. The same mistake with any other
    module-level name would be just as invisible and just as total."""

    def test_no_function_reimports_a_name_the_module_already_imports(self):
        import ast
        import inspect

        from app.services import scheduled_publisher

        tree = ast.parse(inspect.getsource(scheduled_publisher))

        module_level: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_level |= {a.asname or a.name.split(".")[0] for a in node.names}

        offenders: list[str] = []
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for node in ast.walk(fn):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for a in node.names:
                        name = a.asname or a.name.split(".")[0]
                        if name in module_level:
                            offenders.append(f"{fn.name}() re-imports {name}")

        assert not offenders, (
            "a local import shadows a module-level name for the whole "
            f"function — the FC-API-8 shape: {offenders}"
        )
