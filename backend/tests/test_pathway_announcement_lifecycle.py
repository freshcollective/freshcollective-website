"""Members are told about a Pathway when it becomes available — once.

The live bug: a member of World Builders received "New step added: …"
emails while the Pathway was still a draft. ``POST .../steps`` queued
``trigger_new_step`` unconditionally, so authoring a draft announced
every section to everybody, each linking to content they could not
open.

Two lifecycle sources, fixed separately, and they are separate
notifications:

  * ``new_pathway_step`` / ``pathway.step_added`` — a later addition to
    an already-available Pathway. An intentional feature, kept, but now
    only fires when the parent is member-visible.
  * ``new_pathway`` / ``pathway.published`` — first availability. Had
    no live trigger at all; now emitted on the transition, keyed so it
    cannot repeat.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_pathway_announcement_lifecycle.py
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select, text

import app.models.community_care  # noqa: F401
from app.comms.models import CommunicationEvent
from app.models.platform import (
    Pathway,
    PathwayStatus,
    PathwayStep,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    StepContentType,
)
from app.services.pathway_announcement import (
    ANNOUNCEMENT_EVENT,
    announce_if_newly_available,
    announcement_dedupe_key,
    already_announced,
    is_member_visible,
    should_announce,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Recorder:
    """Stands in for BackgroundTasks, remembering what was queued.

    The point of these tests is *whether* a notification is created, so
    the queue is the observation point. The send function itself is not
    mocked — ``trigger_new_step`` is called for real in the tests that
    need it, against the test session.
    """

    def __init__(self) -> None:
        self.tasks: list[tuple] = []

    def add_task(self, fn, *args, **kwargs) -> None:
        self.tasks.append((fn, args, kwargs))

    def names(self) -> list[str]:
        return [getattr(fn, "__name__", str(fn)) for fn, _a, _k in self.tasks]


@pytest.fixture
def world_builders(db, make_user, make_space):
    """A Collective with a creator and two active members."""
    creator = make_user(role="creator")
    # Unique slug: ``world-builders`` is a real seeded Collective in the
    # test database, and the index on spaces.slug is unique.
    space = make_space(
        creator=creator,
        slug=f"world-builders-{uuid.uuid4().hex[:8]}",
        name="World Builders", status="active",
    )
    members = []
    for _ in range(2):
        m = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=m.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        members.append(m)
    db.flush()
    return creator, space, members


@pytest.fixture
def make_pathway(db):
    def _make(space, *, status=PathwayStatus.draft,
              ptype=PathwayType.guided_experience, title="A Pathway"):
        p = Pathway(
            id=_uid("pw"), space_id=space.id,
            slug=f"pw-{uuid.uuid4().hex[:6]}", title=title,
            status=status, pathway_type=ptype, position=0,
        )
        db.add(p)
        db.flush()
        return p
    return _make


@pytest.fixture
def make_step(db):
    def _make(pathway, title="A Step"):
        s = PathwayStep(
            id=_uid("st"), pathway_id=pathway.id,
            slug=f"st-{uuid.uuid4().hex[:6]}", title=title,
            content_type=StepContentType.text, position=0,
        )
        db.add(s)
        db.flush()
        return s
    return _make


def _events(db, pathway=None) -> list[CommunicationEvent]:
    stmt = select(CommunicationEvent).where(
        CommunicationEvent.event_type == ANNOUNCEMENT_EVENT,
    )
    if pathway is not None:
        stmt = stmt.where(
            CommunicationEvent.dedupe_key
            == announcement_dedupe_key(pathway.id, pathway.space_id)
        )
    return list(db.scalars(stmt).all())


def _notifications(db, user_ids, *, types=("new_pathway", "new_pathway_step")):
    rows = db.execute(text(
        "SELECT notification_type, title, url FROM notifications "
        "WHERE user_id = ANY(:u) AND notification_type = ANY(:t)"
    ), {"u": list(user_ids), "t": list(types)}).all()
    return rows


# ---------------------------------------------------------------------------
# Member visibility — the predicate the whole fix rests on
# ---------------------------------------------------------------------------

class TestMemberVisibility:
    def test_a_draft_is_not_member_visible(
        self, db, world_builders, make_pathway,
    ):
        _c, space, _m = world_builders
        assert is_member_visible(
            db, make_pathway(space, status=PathwayStatus.draft),
        ) is False

    def test_an_active_pathway_is(self, db, world_builders, make_pathway):
        _c, space, _m = world_builders
        assert is_member_visible(
            db, make_pathway(space, status=PathwayStatus.active),
        ) is True

    def test_archived_is_not(self, db, world_builders, make_pathway):
        _c, space, _m = world_builders
        assert is_member_visible(
            db, make_pathway(space, status=PathwayStatus.archived),
        ) is False

    def test_coming_soon_is_not_yet_announceable(
        self, db, world_builders, make_pathway,
    ):
        """Listed to members, but not open. "A new pathway is available"
        is not true of it, so the announcement waits for active."""
        _c, space, _m = world_builders
        assert is_member_visible(
            db, make_pathway(space, status=PathwayStatus.coming_soon),
        ) is False

    def test_a_pathway_in_a_draft_collective_is_not(
        self, db, make_user, make_space, make_pathway,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        assert is_member_visible(
            db, make_pathway(space, status=PathwayStatus.active),
        ) is False

    def test_a_pathway_in_an_archived_collective_is_not(
        self, db, make_user, make_space, make_pathway,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="archived")
        assert is_member_visible(
            db, make_pathway(space, status=PathwayStatus.active),
        ) is False


# ---------------------------------------------------------------------------
# Case A — draft authoring is silent
# ---------------------------------------------------------------------------

class TestDraftAuthoringIsSilent:
    def test_creating_a_draft_announces_nothing(
        self, db, world_builders, make_pathway,
    ):
        _c, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.draft)
        assert should_announce(db, pathway) is False
        assert _events(db, pathway) == []

    def test_adding_a_step_to_a_draft_queues_no_notification(
        self, db, world_builders, make_pathway,
    ):
        """The reported bug, at the route."""
        from app.creator.routes import create_step
        from app.creator.schemas import StepCreateRequest

        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.draft)
        db.commit()
        recorder = Recorder()

        create_step(
            slug=space.slug,
            pathway_slug=pathway.slug,
            body=StepCreateRequest(title="Section one"),
            background_tasks=recorder,
            db=db,
            current_user=creator,
        )

        assert recorder.names() == [], (
            "authoring a draft must queue no member notification"
        )

    def test_several_draft_steps_still_queue_nothing(
        self, db, world_builders, make_pathway,
    ):
        """The shape Lindsey saw: one email per section while writing."""
        from app.creator.routes import create_step
        from app.creator.schemas import StepCreateRequest

        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.draft)
        db.commit()
        recorder = Recorder()

        for n in range(4):
            create_step(
                slug=space.slug, pathway_slug=pathway.slug,
                body=StepCreateRequest(title=f"Section {n}"),
                background_tasks=recorder, db=db, current_user=creator,
            )

        assert recorder.names() == []

    def test_the_trigger_itself_refuses_a_draft(
        self, db, world_builders, make_pathway, make_step, monkeypatch,
    ):
        """Second line of defence: the task runs after the response, so
        the Pathway can be unpublished in the gap. Run for real, not
        mocked — only the session factory is redirected."""
        from app.services import notification_service

        _c, space, members = world_builders
        pathway = make_pathway(space, status=PathwayStatus.draft)
        step = make_step(pathway)
        db.commit()
        monkeypatch.setattr(notification_service, "SessionLocal", lambda: db)
        sent: list = []
        monkeypatch.setattr(
            notification_service.email_service, "send",
            lambda **kw: sent.append(kw),
        )

        notification_service.trigger_new_step(step.id, "someone-else")

        assert sent == [], "no email for a draft pathway"
        assert _notifications(db, [m.id for m in members]) == []


# ---------------------------------------------------------------------------
# Cases A/C/D — publication announces exactly once
# ---------------------------------------------------------------------------

class TestPublicationAnnouncesOnce:
    def test_publishing_announces(self, db, world_builders, make_pathway):
        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.draft)
        pathway.status = PathwayStatus.active
        db.flush()

        event = announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        )
        assert event is not None
        assert len(_events(db, pathway)) == 1

    def test_editing_after_publication_does_not_repeat(
        self, db, world_builders, make_pathway,
    ):
        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.active)
        announce_if_newly_available(db, pathway, actor_user_id=creator.id)

        pathway.title = "Renamed"
        db.flush()
        assert announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        ) is None
        assert len(_events(db, pathway)) == 1

    def test_unpublishing_and_republishing_does_not_repeat(
        self, db, world_builders, make_pathway,
    ):
        """Case D. There is no republish-announcement feature, and this
        must not accidentally become one."""
        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.active)
        announce_if_newly_available(db, pathway, actor_user_id=creator.id)

        pathway.status = PathwayStatus.draft
        db.flush()
        assert announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        ) is None

        pathway.status = PathwayStatus.active
        db.flush()
        assert announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        ) is None
        assert len(_events(db, pathway)) == 1

    def test_coming_soon_then_active_announces_once_at_the_end(
        self, db, world_builders, make_pathway,
    ):
        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.coming_soon)
        assert announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        ) is None

        pathway.status = PathwayStatus.active
        db.flush()
        assert announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        ) is not None
        assert len(_events(db, pathway)) == 1

    def test_publishing_does_not_backfill_step_announcements(
        self, db, world_builders, make_pathway, make_step,
    ):
        """Explicitly required: the sections written while draft must not
        each produce a "new step added" email at publication."""
        creator, space, members = world_builders
        pathway = make_pathway(space, status=PathwayStatus.draft)
        for n in range(3):
            make_step(pathway, title=f"Section {n}")

        pathway.status = PathwayStatus.active
        db.flush()
        announce_if_newly_available(db, pathway, actor_user_id=creator.id)
        db.flush()

        step_events = db.scalars(select(CommunicationEvent).where(
            CommunicationEvent.event_type == "pathway.step_added",
        )).all()
        assert list(step_events) == []
        assert _notifications(
            db, [m.id for m in members], types=("new_pathway_step",),
        ) == []
        assert len(_events(db, pathway)) == 1

    def test_should_announce_itself_goes_false_once_announced(
        self, db, world_builders, make_pathway,
    ):
        """The predicate, tested directly.

        The end-to-end assertions cannot see this: with the
        ``already_announced`` check removed, the second emit still
        produces no second row, because the partial unique index on
        ``(event_type, dedupe_key)`` rejects it and ``emit`` returns
        None. The behaviour is identical — which is worth knowing, since
        it means the database is the real guarantee — but it leaves the
        application-level guard unexercised, and a guard nothing tests
        is a guard that can be deleted by accident.
        """
        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.active)
        assert should_announce(db, pathway) is True

        announce_if_newly_available(db, pathway, actor_user_id=creator.id)
        db.flush()

        assert should_announce(db, pathway) is False
        assert already_announced(db, pathway) is True

    def test_the_guard_does_not_rely_on_an_exception_path(self, db):
        """``should_announce`` must consult ``already_announced``, not
        leave the duplicate to the index and an IntegrityError."""
        import inspect

        from app.services import pathway_announcement

        src = inspect.getsource(pathway_announcement.should_announce)
        assert "already_announced" in src

    def test_the_key_is_per_pathway_and_per_collective(
        self, db, world_builders, make_pathway,
    ):
        """Today a Pathway belongs to exactly one Collective, so the
        space half is constant — but the key already carries it, so a
        second Collective would get its own first announcement without
        the idempotency being redesigned."""
        _c, space, _m = world_builders
        pathway = make_pathway(space)
        key = announcement_dedupe_key(pathway.id, pathway.space_id)
        assert pathway.id in key
        assert pathway.space_id in key

    def test_two_pathways_announce_independently(
        self, db, world_builders, make_pathway,
    ):
        creator, space, _m = world_builders
        first = make_pathway(space, status=PathwayStatus.active, title="One")
        second = make_pathway(space, status=PathwayStatus.active, title="Two")

        assert announce_if_newly_available(
            db, first, actor_user_id=creator.id,
        ) is not None
        assert announce_if_newly_available(
            db, second, actor_user_id=creator.id,
        ) is not None
        assert len(_events(db, first)) == 1
        assert len(_events(db, second)) == 1


# ---------------------------------------------------------------------------
# The retained feature — a later step on a live Pathway
# ---------------------------------------------------------------------------

class TestLaterStepsOnALivePathway:
    def test_a_step_added_to_a_published_pathway_still_notifies(
        self, db, world_builders, make_pathway,
    ):
        """Deliberately kept. This was an intentional feature and the
        fix narrows when it fires rather than removing it."""
        from app.creator.routes import create_step
        from app.creator.schemas import StepCreateRequest

        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.active)
        db.commit()
        recorder = Recorder()

        create_step(
            slug=space.slug, pathway_slug=pathway.slug,
            body=StepCreateRequest(title="A genuinely new step"),
            background_tasks=recorder, db=db, current_user=creator,
        )

        assert recorder.names() == ["trigger_new_step"]

    def test_a_knowledge_guide_says_section_not_step(
        self, db, world_builders, make_pathway, make_step, monkeypatch,
    ):
        from app.services import notification_service

        creator, space, members = world_builders
        guide = make_pathway(
            space, status=PathwayStatus.active,
            ptype=PathwayType.knowledge_guide, title="The Guide",
        )
        step = make_step(guide, title="Chapter one")
        db.commit()
        monkeypatch.setattr(notification_service, "SessionLocal", lambda: db)
        sent: list = []
        monkeypatch.setattr(
            notification_service.email_service, "send",
            lambda **kw: sent.append(kw),
        )

        notification_service.trigger_new_step(step.id, creator.id)

        assert sent, "a live guide still announces"
        subject = sent[0]["subject"]
        assert "section" in subject.lower()
        assert "step" not in subject.lower()

    def test_a_guided_experience_still_says_step(
        self, db, world_builders, make_pathway, make_step, monkeypatch,
    ):
        from app.services import notification_service

        creator, space, _m = world_builders
        pathway = make_pathway(
            space, status=PathwayStatus.active,
            ptype=PathwayType.guided_experience,
        )
        step = make_step(pathway, title="Step one")
        db.commit()
        monkeypatch.setattr(notification_service, "SessionLocal", lambda: db)
        sent: list = []
        monkeypatch.setattr(
            notification_service.email_service, "send",
            lambda **kw: sent.append(kw),
        )

        notification_service.trigger_new_step(step.id, creator.id)

        assert sent
        assert "step" in sent[0]["subject"].lower()

    def test_a_guide_links_to_the_guide_not_a_step_route(
        self, db, world_builders, make_pathway, make_step, monkeypatch,
    ):
        """A Knowledge Guide is one continuous page with anchors; a
        per-step URL is not how the reader navigates it."""
        from app.services import notification_service

        creator, space, members = world_builders
        guide = make_pathway(
            space, status=PathwayStatus.active,
            ptype=PathwayType.knowledge_guide,
        )
        step = make_step(guide)
        db.commit()
        monkeypatch.setattr(notification_service, "SessionLocal", lambda: db)
        monkeypatch.setattr(
            notification_service.email_service, "send", lambda **kw: None,
        )

        notification_service.trigger_new_step(step.id, creator.id)

        rows = _notifications(
            db, [m.id for m in members], types=("new_pathway_step",),
        )
        assert rows
        assert all(r[2] == f"/spaces/{space.slug}/pathways/{guide.slug}"
                   for r in rows)


# ---------------------------------------------------------------------------
# Access safety
# ---------------------------------------------------------------------------

class TestAccessSafety:
    def test_nothing_is_announced_for_an_inaccessible_collective(
        self, db, make_user, make_space, make_pathway,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        pathway = make_pathway(space, status=PathwayStatus.active)
        assert announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        ) is None

    def test_already_announced_is_specific_to_the_pathway(
        self, db, world_builders, make_pathway,
    ):
        creator, space, _m = world_builders
        announced = make_pathway(space, status=PathwayStatus.active)
        other = make_pathway(space, status=PathwayStatus.active)
        announce_if_newly_available(db, announced, actor_user_id=creator.id)
        db.flush()

        assert already_announced(db, announced) is True
        assert already_announced(db, other) is False


# ---------------------------------------------------------------------------
# The live send path
# ---------------------------------------------------------------------------

class _NoClose:
    """Session wrapper whose ``close`` is a no-op, so routing can run
    inside the test's SAVEPOINT-scoped session."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self):
        pass


def _route(db, event_id: str) -> None:
    """Drive the routing layer against the test session.

    The pattern ``test_creator_purchase_notification_routing.py``
    established: routing opens its own ``SessionLocal``, which cannot
    see SAVEPOINT-scoped rows, so both the rollout module and the
    in-app provider are pointed at this session for the call.
    """
    from unittest.mock import patch

    from app.comms.providers import get as _get_provider
    from app.comms.rollout import _route_event_bg

    inapp = _get_provider("in_app")
    original = inapp._session_factory
    inapp._session_factory = lambda: _NoClose(db)
    try:
        with patch("app.comms.rollout.SessionLocal", return_value=_NoClose(db)):
            _route_event_bg(event_id, "live")
    finally:
        inapp._session_factory = original


def _intents(db, event_id: str):
    from app.comms.models import CommunicationIntent

    return db.query(CommunicationIntent).filter(
        CommunicationIntent.event_id == event_id,
    ).all()


@pytest.fixture(autouse=True)
def _no_real_email():
    """The provider round-trip is not the subject; intents are."""
    from unittest.mock import MagicMock, patch

    with patch("resend.Emails.send", new_callable=MagicMock), \
         patch("resend.api_key", create=True), \
         patch(
             "app.services.email_service.email_service.send",
             new_callable=MagicMock,
         ):
        yield


class TestTheTopicIsLive:
    def test_pathway_published_is_a_live_event(self):
        """Without this the event is created, a shadow intent is
        recorded, and no member is ever emailed."""
        from app.comms.rollout import is_event_live

        assert is_event_live("pathway.published") is True

    def test_the_step_announcement_is_unaffected_by_the_promotion(self):
        """``trigger_new_step`` carries no ``is_event_live`` guard, and
        nothing emits ``pathway.step_added`` — so promoting the topic
        does not silence the legacy new-section announcement."""
        import inspect

        from app.services import notification_service

        src = inspect.getsource(notification_service.trigger_new_step)
        assert "_rollout_is_live" not in src


class TestPublicationDelivers:
    def test_publishing_routes_intents_to_the_members(
        self, db, world_builders, make_pathway,
    ):
        creator, space, members = world_builders
        pathway = make_pathway(space, status=PathwayStatus.active)
        event = announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        )
        db.flush()
        assert _intents(db, event.id) == [], "emit alone sends nothing"

        _route(db, event.id)

        intents = _intents(db, event.id)
        assert intents, "routing produced nothing — no member can be reached"
        recipients = {i.recipient_user_id for i in intents}
        assert recipients == {m.id for m in members}, (
            "every active member, and nobody else"
        )

    def test_the_creator_is_not_a_recipient_of_their_own_publication(
        self, db, world_builders, make_pathway,
    ):
        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.active)
        event = announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        )
        db.flush()
        _route(db, event.id)

        # The creator has no active membership row in this fixture, so
        # they are not resolved. Asserted rather than assumed.
        assert creator.id not in {
            i.recipient_user_id for i in _intents(db, event.id)
        }

    def test_an_unpublished_pathway_routes_to_nobody(
        self, db, world_builders, make_pathway,
    ):
        """Routing runs after the response. If the Pathway went back to
        draft in the gap, nobody should be emailed a link to it."""
        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.active)
        event = announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        )
        db.flush()

        pathway.status = PathwayStatus.draft
        db.flush()
        _route(db, event.id)

        assert _intents(db, event.id) == [], (
            "a draft pathway must reach no recipients"
        )

    def test_a_closed_collective_routes_to_nobody(
        self, db, world_builders, make_pathway,
    ):
        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.active)
        event = announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        )
        db.flush()

        space.status = "archived"
        db.flush()
        _route(db, event.id)

        assert _intents(db, event.id) == []

    def test_republishing_cannot_produce_a_second_send(
        self, db, world_builders, make_pathway,
    ):
        """No duplicate email, guaranteed one level up.

        Routing idempotency is the comms layer's own property with its
        own tests. What this work is responsible for is that there is
        never a *second event* to route — so republishing cannot reach
        the delivery path at all, whatever routing would do with it.
        """
        creator, space, _members = world_builders
        pathway = make_pathway(space, status=PathwayStatus.active)
        assert announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        ) is not None
        db.flush()

        # No routing needed to show this: the guarantee is that there is
        # nothing left to route.
        # Unpublish, republish, and try again.
        pathway.status = PathwayStatus.draft
        db.flush()
        pathway.status = PathwayStatus.active
        db.flush()

        assert announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        ) is None, "no second event, so nothing more can be delivered"
        assert len(_events(db, pathway)) == 1


class TestTheRenderedEmail:
    def _render(self, db, pathway, creator, space):
        from app.comms.routing.resolvers.pathways import (
            PathwayPublishedResolver,
        )
        from app.comms.templates.pathways import PathwayPublishedEmailTemplate

        event = announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        )
        db.flush()
        recipients = PathwayPublishedResolver().resolve(db, event)
        assert recipients, "no recipients resolved"
        return PathwayPublishedEmailTemplate().render(db, event, recipients[0])

    def test_it_has_a_subject_and_a_cta_to_the_pathway(
        self, db, world_builders, make_pathway,
    ):
        """The template previously said "No CTA: this event's
        template_context carries no pathway URL" — it announced a
        Pathway and gave the reader nothing to press."""
        creator, space, _m = world_builders
        pathway = make_pathway(
            space, status=PathwayStatus.active, title="Finding Your Ground",
        )
        payload = self._render(db, pathway, creator, space)

        assert "Finding Your Ground" in payload.subject
        assert space.name in payload.subject
        expected = f"/spaces/{space.slug}/pathways/{pathway.slug}"
        assert expected in payload.body_text
        assert expected in (payload.body_html or "")

    def test_a_knowledge_guide_email_never_says_step(
        self, db, world_builders, make_pathway,
    ):
        creator, space, _m = world_builders
        guide = make_pathway(
            space, status=PathwayStatus.active,
            ptype=PathwayType.knowledge_guide, title="The Reference",
        )
        payload = self._render(db, guide, creator, space)

        blob = " ".join([
            payload.subject, payload.body_text or "", payload.body_html or "",
        ]).lower()
        for word in ("step", "steps", "complete", "progress"):
            assert word not in blob, f"guide email mentions {word!r}"

    def test_the_in_app_notification_is_clickable(
        self, db, world_builders, make_pathway,
    ):
        from app.comms.routing.resolvers.pathways import (
            PathwayPublishedResolver,
        )
        from app.comms.templates.pathways import PathwayPublishedInAppTemplate

        creator, space, _m = world_builders
        pathway = make_pathway(space, status=PathwayStatus.active)
        event = announce_if_newly_available(
            db, pathway, actor_user_id=creator.id,
        )
        db.flush()
        recipient = PathwayPublishedResolver().resolve(db, event)[0]
        payload = PathwayPublishedInAppTemplate().render(db, event, recipient)

        assert payload.metadata["url"] == (
            f"/spaces/{space.slug}/pathways/{pathway.slug}"
        )
