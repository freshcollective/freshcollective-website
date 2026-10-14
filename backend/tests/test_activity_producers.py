"""Phase 1 — shared Collective activity producers.

One row per piece of content, no recipient, no email, and nothing at
all for content a member cannot reach. These tests exist because every
one of those properties has a cheap way to go wrong:

  * a retry or a double-click writing two rows;
  * a draft announcing itself, which has happened here before — see
    ``services/pathway_announcement.py`` for the incident that module
    was written to fix;
  * a Series with twenty occurrences producing twenty indicators;
  * a general producer reaching an email channel.

The last one is asserted against the source rather than behaviour: the
guarantee wanted is that the capability is absent, not merely unused.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from sqlalchemy.exc import IntegrityError

from app.models.activity import Activity, ActivityType
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    Event,
    EventSeries,
    Pathway,
    PathwayStatus,
    PathwayStep,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import activity_producers as ap
from app.services.activity_service import CATEGORY_OF, ActivityService



#: Substring, not equality: ``notification_service`` and
#: ``email_service`` are the realistic names, and neither equals the
#: bare word. Matching per path segment rather than against the whole
#: dotted name keeps ``app.models.platform`` from matching on nothing
#: while still catching a segment that merely contains the word.
_MESSAGING_WORDS = ("comms", "email", "notification", "mail", "resend", "digest")


def _is_messaging(module: str) -> bool:
    return any(
        word in part
        for part in module.split(".")
        for word in _MESSAGING_WORDS
    )


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _member(db, user, space, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id, role=role,
        status=SpaceMembershipStatus.active, joined_at=datetime.utcnow(),
    ))
    db.flush()


def _pathway(db, space, *, status=PathwayStatus.active) -> Pathway:
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="A Pathway", status=status, access_type="free",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p); db.flush()
    return p


def _step(db, pathway, *, release_type="immediate") -> PathwayStep:
    s = PathwayStep(
        id=_uid("st"), pathway_id=pathway.id, slug=f"st-{uuid.uuid4().hex[:8]}",
        title="A step", position=1, release_type=release_type,
    )
    db.add(s); db.flush()
    return s


def _gathering(db, space, *, series_id=None, published=True, status="active") -> Event:
    e = Event(
        id=_uid("e"), space_id=space.id, series_id=series_id,
        created_by_id=space.creator_id, title="A Gathering",
        starts_at=datetime.utcnow() + timedelta(days=7),
        ends_at=datetime.utcnow() + timedelta(days=7, hours=1),
        is_published=published, status=status, requires_booking=True,
        capacity=20, gathering_type="circle", attendance_format="online",
    )
    db.add(e); db.flush()
    return e


def _series(db, space, *, status="published") -> EventSeries:
    s = EventSeries(
        id=_uid("es"), space_id=space.id, slug=f"es-{uuid.uuid4().hex[:8]}",
        title="A Series", starts_at=datetime.utcnow(),
        ends_at=datetime.utcnow() + timedelta(days=60), status=status,
    )
    db.add(s); db.flush()
    return s


def _channel(db, space, *, channel_type="open") -> ConversationChannel:
    c = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="General",
        slug=f"ch-{uuid.uuid4().hex[:8]}", channel_type=channel_type,
    )
    db.add(c); db.flush()
    return c


def _post(db, space, channel, author, *, status="published") -> CommunityPost:
    p = CommunityPost(
        id=_uid("cp"), space_id=space.id, channel_id=channel.id,
        author_id=author.id, title="A thread", body="hello",
        publication_status=status,
    )
    db.add(p); db.flush()
    return p


def _rows(db) -> list[Activity]:
    return db.query(Activity).all()


# ---------------------------------------------------------------------------
# One row per piece of content
# ---------------------------------------------------------------------------

class TestExactlyOneRow:
    def test_publishing_a_pathway_records_one_shared_row(self, db, make_space, make_user):
        space = make_space(); creator = make_user()
        pw = _pathway(db, space); db.commit()

        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()

        rows = _rows(db)
        assert len(rows) == 1
        r = rows[0]
        assert r.recipient_user_id is None, "a shared row has no recipient"
        assert r.collective_id == space.id
        assert r.pathway_id == pw.id
        assert r.category == "pathways"
        assert r.payload.get("title") and r.payload.get("url")

    def test_publishing_a_thread_records_one_row(self, db, make_space, make_user):
        space = make_space(); author = make_user()
        ch = _channel(db, space); post = _post(db, space, ch, author); db.commit()

        ap.record_thread_created(db, post, actor_user_id=author.id)
        db.commit()

        rows = _rows(db)
        assert len(rows) == 1
        assert rows[0].category == "conversations"
        assert rows[0].conversation_id == post.id

    def test_publishing_a_single_gathering_records_one_row(self, db, make_space, make_user):
        space = make_space(); creator = make_user()
        ev = _gathering(db, space); db.commit()

        ap.record_gathering_published(db, ev, actor_user_id=creator.id)
        db.commit()

        rows = _rows(db)
        assert len(rows) == 1
        assert rows[0].category == "gatherings"
        assert rows[0].gathering_id == ev.id


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_republishing_a_pathway_writes_nothing_further(self, db, make_space, make_user):
        space = make_space(); creator = make_user()
        pw = _pathway(db, space); db.commit()

        for _ in range(4):
            ap.record_pathway_published(db, pw, actor_user_id=creator.id)
            db.commit()

        assert len(_rows(db)) == 1, "a retried publish must not duplicate"

    def test_a_repeated_thread_publish_writes_once(self, db, make_space, make_user):
        space = make_space(); author = make_user()
        ch = _channel(db, space); post = _post(db, space, ch, author); db.commit()

        ap.record_thread_created(db, post, actor_user_id=author.id)
        db.commit()
        ap.record_thread_created(db, post, actor_user_id=author.id)
        db.commit()

        assert len(_rows(db)) == 1

    def test_a_failed_dedupe_does_not_poison_the_transaction(self, db, make_space, make_user):
        """The savepoint matters: a repeat publish still has to be able
        to commit whatever else its request did."""
        space = make_space(); creator = make_user()
        pw = _pathway(db, space); db.commit()
        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()

        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        other = _pathway(db, space)          # unrelated work in the same tx
        db.commit()

        assert db.query(Pathway).filter(Pathway.id == other.id).first() is not None

    def test_a_second_step_does_produce_new_activity(self, db, make_space, make_user):
        """Keyed on the step, not the Pathway — publishing more steps
        into a live Pathway must keep producing activity."""
        space = make_space(); creator = make_user()
        pw = _pathway(db, space)
        s1, s2 = _step(db, pw), _step(db, pw); db.commit()

        ap.record_step_published(db, s1, actor_user_id=creator.id)
        ap.record_step_published(db, s2, actor_user_id=creator.id)
        db.commit()

        assert len(_rows(db)) == 2

    def test_a_series_produces_one_row_not_one_per_occurrence(self, db, make_space, make_user):
        space = make_space(); creator = make_user()
        series = _series(db, space)
        occurrences = [_gathering(db, space, series_id=series.id) for _ in range(20)]
        db.commit()

        ap.record_series_published(db, series, actor_user_id=creator.id)
        for occ in occurrences:
            ap.record_gathering_published(db, occ, actor_user_id=creator.id)
        db.commit()

        rows = _rows(db)
        assert len(rows) == 1, "twenty occurrences are one offering"
        assert rows[0].series_id == series.id
        assert rows[0].gathering_id is None


# ---------------------------------------------------------------------------
# Nothing for content members cannot reach
# ---------------------------------------------------------------------------

class TestNothingForUnavailableContent:
    @pytest.mark.parametrize("status", [PathwayStatus.draft, PathwayStatus.archived])
    def test_a_draft_or_archived_pathway_announces_nothing(
        self, db, make_space, make_user, status,
    ):
        space = make_space(); creator = make_user()
        pw = _pathway(db, space, status=status); db.commit()

        ap.record_pathway_published(db, pw, actor_user_id=creator.id)
        db.commit()

        assert _rows(db) == []

    def test_a_step_in_a_draft_pathway_announces_nothing(self, db, make_space, make_user):
        space = make_space(); creator = make_user()
        pw = _pathway(db, space, status=PathwayStatus.draft)
        st = _step(db, pw); db.commit()

        ap.record_step_published(db, st, actor_user_id=creator.id)
        db.commit()

        assert _rows(db) == []

    @pytest.mark.parametrize(
        "release_type", ["days_after_enrollment", "after_previous", "manual", "fixed_date"],
    )
    def test_a_per_member_or_scheduled_release_produces_nothing_yet(
        self, db, make_space, make_user, release_type,
    ):
        """Deferred by design. These open at a different moment for each
        member (or at a moment nothing watches for), so a shared row
        cannot honestly describe them."""
        space = make_space(); creator = make_user()
        pw = _pathway(db, space)
        st = _step(db, pw, release_type=release_type); db.commit()

        ap.record_step_published(db, st, actor_user_id=creator.id)
        db.commit()

        assert _rows(db) == []

    def test_a_scheduled_thread_announces_nothing_until_published(
        self, db, make_space, make_user,
    ):
        space = make_space(); author = make_user()
        ch = _channel(db, space)
        post = _post(db, space, ch, author, status="scheduled"); db.commit()

        ap.record_thread_created(db, post, actor_user_id=author.id)
        db.commit()
        assert _rows(db) == []

        post.publication_status = "published"
        db.flush()
        ap.record_thread_created(db, post, actor_user_id=author.id)
        db.commit()
        assert len(_rows(db)) == 1, "it announces when it actually appears"

    def test_an_unpublished_gathering_announces_nothing(self, db, make_space, make_user):
        space = make_space(); creator = make_user()
        ev = _gathering(db, space, published=False); db.commit()

        ap.record_gathering_published(db, ev, actor_user_id=creator.id)
        db.commit()

        assert _rows(db) == []

    def test_a_draft_series_announces_nothing(self, db, make_space, make_user):
        space = make_space(); creator = make_user()
        series = _series(db, space, status="draft"); db.commit()

        ap.record_series_published(db, series, actor_user_id=creator.id)
        db.commit()

        assert _rows(db) == []


# ---------------------------------------------------------------------------
# A producer must never break a publish, and never send an email
# ---------------------------------------------------------------------------

class TestProducerSafety:
    def test_a_producer_never_raises(self, db, make_space):
        """Recording activity is a side effect of publishing. It must
        not be able to fail the thing that triggered it."""
        space = make_space()
        broken = Pathway(id=_uid("pw"), space_id="does-not-exist",
                         slug="x", title="x", status=PathwayStatus.active,
                         access_type="free", pathway_type=PathwayType.guided_experience)
        ap.record_pathway_published(db, broken, actor_user_id=None)  # must not raise

    def test_no_producer_imports_a_messaging_module(self):
        """The guarantee wanted is that the capability is *absent*, not
        merely unused, so this reads the module's imports rather than
        searching its text for names. A denylist of strings both misses
        ``from app import comms; comms.dispatch(...)`` and trips over
        the word appearing in a docstring; the import graph does
        neither.

        Function-local imports count — the producers use them to avoid
        import cycles, so a messaging call would most naturally arrive
        that way.
        """
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(ap))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)

        offenders = sorted(m for m in imported if _is_messaging(m))
        assert not offenders, (
            f"a producer can reach a messaging module: {offenders}"
        )

    def test_the_import_guard_would_notice_a_messaging_import(self):
        """The test above passes trivially if its own parsing is wrong.
        This proves it reacts to the thing it claims to detect."""
        import ast

        tree = ast.parse(
            "def f():\n"
            "    from app.comms.dispatcher import dispatch\n"
            "    return dispatch\n"
        )
        imported = {
            n.module
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module
        }
        assert any(_is_messaging(m) for m in imported)

    @pytest.mark.parametrize(
        "module",
        [
            "app.comms.dispatcher",
            "app.services.notification_service",
            "app.services.email_service",
            "app.services.pathway_announcement_email",
            "app.notifications.triggers",
        ],
    )
    def test_the_import_guard_recognises_each_messaging_module(self, module):
        """Named explicitly because the near-miss is the whole risk:
        `notification_service` is not the string `notification`, and an
        equality check on path segments lets it straight through."""
        assert _is_messaging(module)

    @pytest.mark.parametrize(
        "module",
        [
            "app.models.platform",
            "app.services.activity_service",
            "sqlalchemy.orm",
            "app.spaces.area_access",
        ],
    )
    def test_the_import_guard_allows_ordinary_modules(self, module):
        assert not _is_messaging(module)


class TestCreateSharedRejectsUnsafeCalls:
    """``create_shared`` has exactly one idempotency mechanism. A
    caller that omits the key gets no protection at all, and the
    failure is silent — every retry writes another row. The guard
    turns that into a loud error at the call site instead."""

    def test_an_empty_dedupe_key_is_refused(self, db, make_space):
        space = make_space()
        db.commit()
        for bad in ("", None):
            with pytest.raises(ValueError, match="dedupe_key"):
                ActivityService.create_shared(
                    db,
                    event_type=ActivityType.pathway_published,
                    dedupe_key=bad,
                    collective_id=space.id,
                )
        assert db.query(Activity).count() == 0, "nothing is written on refusal"

    def test_a_non_activity_type_event_is_refused(self, db, make_space):
        space = make_space()
        db.commit()
        with pytest.raises(TypeError, match="ActivityType"):
            ActivityService.create_shared(
                db,
                event_type="pathway_published",  # a bare string
                dedupe_key="pathway:x",
                collective_id=space.id,
            )
        assert db.query(Activity).count() == 0

    def test_the_category_comes_from_the_event_type(self, db, make_space):
        """Category drives which rows a member-facing feed reads, so a
        row filed under the wrong one either vanishes or surfaces where
        it does not belong."""
        space = make_space()
        db.flush()
        row = ActivityService.create_shared(
            db,
            event_type=ActivityType.pathway_published,
            dedupe_key="pathway:cat-check",
            collective_id=space.id,
        )
        db.flush()
        assert row.category == CATEGORY_OF[ActivityType.pathway_published].value
        assert row.category == "pathways"


class TestOnlyARepeatCountsAsARepeat:
    """``create_shared`` swallows the duplicate-key conflict because a
    repeat publish is expected. Every other integrity failure means the
    row was wrong, and must not be filed under the same quiet branch.
    """

    def test_a_duplicate_returns_none(self, db, make_space):
        space = make_space(); db.flush()
        first = ActivityService.create_shared(
            db, event_type=ActivityType.pathway_published,
            dedupe_key="dup-key", collective_id=space.id,
        )
        db.flush()
        second = ActivityService.create_shared(
            db, event_type=ActivityType.pathway_published,
            dedupe_key="dup-key", collective_id=space.id,
        )
        assert first is not None and second is None
        assert db.query(Activity).count() == 1

    def test_a_bad_collective_raises_instead_of_looking_like_a_repeat(
        self, db, make_space,
    ):
        """A foreign key that does not resolve is an IntegrityError too.
        Before this was narrowed it returned None and logged 'already
        recorded', so the row silently never existed."""
        make_space(); db.flush()
        with pytest.raises(IntegrityError):
            ActivityService.create_shared(
                db, event_type=ActivityType.pathway_published,
                dedupe_key="fk-violation",
                collective_id="space_does_not_exist",
            )

    def test_the_session_still_works_after_that_failure(self, db, make_space):
        """The savepoint has to release the failed statement, or the
        publish that called the producer could not commit."""
        space = make_space(); db.flush()
        with pytest.raises(IntegrityError):
            ActivityService.create_shared(
                db, event_type=ActivityType.pathway_published,
                dedupe_key="fk-violation-2",
                collective_id="space_does_not_exist",
            )
        # The caller's transaction must still be usable.
        ok = ActivityService.create_shared(
            db, event_type=ActivityType.pathway_published,
            dedupe_key="after-failure", collective_id=space.id,
        )
        db.flush()
        assert ok is not None
        assert db.query(Activity).count() == 1

    def test_a_producer_reports_it_as_an_error_not_as_a_repeat(
        self, db, make_space, monkeypatch,
    ):
        """End to end: the producer still protects the publish, but an
        integrity failure is now reported at ERROR — which Sentry turns
        into an issue — rather than through the quiet "already
        recorded" branch.

        The logger object is replaced rather than captured with
        ``caplog``: the ``db`` fixture runs Alembic, whose ``fileConfig``
        call disables every logger that already exists in the process,
        so log records vanish here for reasons that have nothing to do
        with this code. Production never runs Alembic in the app
        process, so this is a harness artefact only — but it would make
        a ``caplog`` assertion pass whatever the producer did.
        """
        space = make_space()
        pw = Pathway(
            id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
            title="T", status=PathwayStatus.active, access_type="free",
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pw); db.commit()

        seen: list[str] = []

        class RecordingLogger:
            def exception(self, msg, *a, **k):
                seen.append(("exception", str(msg)))

            def info(self, msg, *a, **k):
                seen.append(("info", str(msg)))

            def warning(self, msg, *a, **k):
                seen.append(("warning", str(msg)))

        def boom(*a, **k):
            raise IntegrityError("INSERT", {}, Exception("fk violation"))

        monkeypatch.setattr(ActivityService, "create_shared", staticmethod(boom))
        monkeypatch.setattr(ap, "logger", RecordingLogger())

        ap.record_pathway_published(db, pw, actor_user_id=None)

        assert seen, "the failure must be reported"
        assert [lvl for lvl, _ in seen] == ["exception"], (
            f"expected a single ERROR-level report, got {seen}"
        )
        assert not any("already recorded" in m for _, m in seen)

        # And the publish it was called from is still committable.
        db.commit()
        assert db.query(Pathway).filter(Pathway.id == pw.id).first() is not None
