"""Which Pathway emails the category default may switch on.

The `pathways` category carries three events and only one of them
should ever email the Collective:

    pathway.published             the announcement
    pathway.step_added            must NOT email everyone
    pathway.enrolment.completed   personal, to the completing member

Turning the category default on is safe because of a structural fact
rather than a convention: the other two have no templates registered
on any channel, and the decision pipeline skips an intent entirely
when no template exists for the (event, channel) pair. These tests pin
that fact, so the default cannot quietly start delivering something
new if a template is added later without the preference question being
revisited.

The step announcement that *did* reach inboxes never went through this
category at all — it went through the legacy `trigger_new_step`, on
the legacy per-space `new_pathway_email` flag, which is also covered
here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.comms.categories import (
    CATEGORY_PATHWAYS,
    CHANNEL_EMAIL_TRANSACTIONAL,
    CHANNEL_IN_APP,
)
from app.comms.registry import get_event_definition
from app.comms.templates.registry import get_template_for
from app.models.platform import (
    Pathway,
    PathwayStep,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


class TestOnlyThePublicationEventCanEmail:
    """The structural claim the migration rests on."""

    def test_published_has_both_templates(self):
        assert get_template_for("pathway.published", CHANNEL_IN_APP)
        assert get_template_for("pathway.published", CHANNEL_EMAIL_TRANSACTIONAL)

    @pytest.mark.parametrize(
        "event_type", ["pathway.step_added", "pathway.enrolment.completed"],
    )
    def test_the_other_two_have_no_templates_at_all(self, event_type):
        """If this ever fails, the category default has started
        delivering something new and the preference question above
        needs answering again before it ships."""
        for channel in (CHANNEL_IN_APP, CHANNEL_EMAIL_TRANSACTIONAL):
            assert get_template_for(event_type, channel) is None, (
                f"{event_type} gained a {channel} template — turning the "
                "pathways category on now emails it too"
            )

    def test_all_three_share_the_one_category(self):
        """Which is why the above matters: a category-level default
        cannot distinguish them."""
        from app.comms.categories import TOPIC_TO_CATEGORY

        for event_type in (
            "pathway.published",
            "pathway.step_added",
            "pathway.enrolment.completed",
        ):
            definition = get_event_definition(event_type)
            assert definition is not None, event_type
            assert TOPIC_TO_CATEGORY[definition.topic] == CATEGORY_PATHWAYS


class TestTheDefaultResolves:
    def test_a_member_with_no_preference_row_gets_immediate(
        self, db, make_user,
    ):
        """Migration 179. Before it, this resolved to `silent` and the
        announcement was recorded rather than sent."""
        from app.comms.preferences import get_effective_preference

        priority, _locked, origin = get_effective_preference(
            db, user_id=make_user().id, category_key=CATEGORY_PATHWAYS,
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
        )
        assert (priority, origin) == ("immediate", "default")

    def test_an_explicit_opt_out_still_wins(self, db, make_user):
        from app.comms.preferences import (
            get_effective_preference, set_preference,
        )

        member = make_user()
        set_preference(
            db, user_id=member.id, category_key=CATEGORY_PATHWAYS,
            channel=CHANNEL_EMAIL_TRANSACTIONAL, priority="silent",
        )
        db.flush()

        priority, _locked, origin = get_effective_preference(
            db, user_id=member.id, category_key=CATEGORY_PATHWAYS,
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
        )
        assert (priority, origin) == ("silent", "override")

    def test_the_member_can_still_opt_out(self, db):
        """`is_locked` stays false — this is an announcement, not a
        receipt."""
        from app.comms.models import CommunicationChannelDefault

        row = (
            db.query(CommunicationChannelDefault)
            .filter(
                CommunicationChannelDefault.category_key == CATEGORY_PATHWAYS,
                CommunicationChannelDefault.channel
                == CHANNEL_EMAIL_TRANSACTIONAL,
            )
            .one()
        )
        assert row.default_enabled is True
        assert row.is_locked is False


class TestStepAddedDoesNotEmail:
    """§3 — a new section is not an announcement."""

    @pytest.fixture
    def pathway(self, db, make_space, make_user):
        space = make_space()
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        row = Pathway(
            id=_uid("pw"), space_id=space.id, title="Know Yourself",
            slug=f"ky-{uuid.uuid4().hex[:8]}",
            status="active", access_type="free",
        )
        db.add(row)
        db.flush()
        return row, space, member

    def test_the_legacy_trigger_sends_no_email(
        self, db, pathway, monkeypatch,
    ):
        """It used to email every active member, on the same flag as
        "a new Pathway was published"."""
        from app.services import notification_service

        sent: list[dict] = []
        monkeypatch.setattr(
            notification_service.email_service, "send",
            lambda **kw: sent.append(kw),
        )

        row, space, member = pathway
        step = PathwayStep(
            id=_uid("ps"), pathway_id=row.id, title="Step one",
            slug=f"s-{uuid.uuid4().hex[:6]}", position=1,
        )
        db.add(step)
        db.commit()

        notification_service.trigger_new_step(step.id, space.creator_id)
        assert sent == [], "a new section emailed the Collective"

    def test_the_source_no_longer_emails_for_steps(self):
        """Asserted against the source as well, because the behaviour
        test passes trivially if the function returns early for an
        unrelated reason."""
        import inspect

        from app.services import notification_service

        source = inspect.getsource(notification_service.trigger_new_step)
        assert "email_service.send" not in source, (
            "trigger_new_step sends email again"
        )
        assert "create_notification" in source, (
            "the in-app notification was removed too — §3 asks for it "
            "to be preserved"
        )

    def test_a_draft_pathway_announces_nothing_at_all(
        self, db, pathway, monkeypatch,
    ):
        """Unchanged safeguard, re-asserted: the gate is upstream of
        the email question."""
        from app.services import notification_service
        from app.services.pathway_announcement import is_member_visible

        row, space, _ = pathway
        row.status = "draft"
        db.flush()
        assert is_member_visible(db, row) is False

        created: list[str] = []
        monkeypatch.setattr(
            notification_service, "create_notification",
            lambda **kw: created.append(kw["recipient_id"]),
        )
        step = PathwayStep(
            id=_uid("ps"), pathway_id=row.id, title="Draft step",
            slug=f"s-{uuid.uuid4().hex[:6]}", position=1,
        )
        db.add(step)
        db.commit()

        notification_service.trigger_new_step(step.id, space.creator_id)
        assert created == [], "a draft announced a section"


class TestCompletionIsNotImplemented:
    """§4 — reported rather than assumed.

    `pathway.enrolment.completed` is a registered event with no
    emitter and no templates, so no completion notification exists on
    any channel. There is nothing to verify and nothing to preserve;
    this pins the absence so a future implementation is a deliberate
    addition rather than a surprise.
    """

    def test_the_event_is_registered_but_never_emitted(self):
        assert get_event_definition("pathway.enrolment.completed") is not None

    def test_nothing_emits_it(self):
        from pathlib import Path

        app_dir = Path(__file__).resolve().parent.parent / "app"
        emitters = [
            path for path in app_dir.rglob("*.py")
            if "pathway.enrolment.completed" in path.read_text()
            and "registry.py" not in path.name
            and "config.py" not in path.name
        ]
        assert emitters == [], (
            f"an emitter appeared: {emitters}. Completion notifications "
            "now need the recipient, dedupe and preference questions "
            "answered."
        )


class TestNothingIsAnnouncedRetroactively:
    """§11 — the risk the migration's backfill exists for.

    ``should_announce`` is "member-visible now AND never announced".
    A Pathway published before the comms event existed has no dedupe
    row, so an ordinary edit reads as a first publication. That was
    harmless while Pathway email was off — the intent was recorded and
    nothing sent — and is not harmless now, so migration 179 marks
    every already-live Pathway as announced before it flips the
    default.
    """

    @pytest.fixture
    def live_pathway(self, db, make_space, make_user):
        space = make_space()
        row = Pathway(
            id=_uid("pw"), space_id=space.id, title="Published Long Ago",
            slug=f"old-{uuid.uuid4().hex[:8]}",
            status="active", access_type="free",
        )
        db.add(row)
        db.flush()
        return row, space

    def test_an_already_live_pathway_with_a_dedupe_row_stays_quiet(
        self, db, live_pathway,
    ):
        """What the backfill produces."""
        from app.comms.models import CommunicationEvent
        from app.services.pathway_announcement import (
            announcement_dedupe_key, should_announce,
        )

        row, space = live_pathway
        db.add(CommunicationEvent(
            id=_uid("evt"), event_type="pathway.published",
            topic_key="pathways", category_key="pathways",
            source_type="fresh_collective", priority_hint="silent",
            subject_type="pathway", subject_id=row.id,
            context={"space_id": space.id, "backfilled": True},
            payload={},
            dedupe_key=announcement_dedupe_key(row.id, space.id),
        ))
        db.flush()

        assert should_announce(db, row) is False

    def test_without_the_dedupe_row_it_would_announce(
        self, db, live_pathway,
    ):
        """The failure mode, stated so the backfill's purpose is not
        mistaken for belt-and-braces. If this ever returns False the
        backfill has become unnecessary — and if it returns True
        against production data after 179, something skipped it."""
        from app.services.pathway_announcement import should_announce

        row, _space = live_pathway
        assert should_announce(db, row) is True

    def test_the_migration_backfills_every_live_pathway(self):
        """The SQL's shape, asserted so a later edit cannot narrow it
        without the question being asked again."""
        from pathlib import Path

        migration = (
            Path(__file__).resolve().parent.parent
            / "alembic" / "versions" / "179_pathways_email_default_on.py"
        ).read_text()
        assert "INSERT INTO communication_events" in migration
        assert "ON CONFLICT DO NOTHING" in migration
        assert "p.status = 'active'" in migration
        # The insert must come before the flip, or the window it closes
        # is still open while the migration runs.
        assert (
            migration.index("INSERT INTO communication_events")
            < migration.index("SET default_enabled = true")
        )


class TestThePublishingCreatorIsExcluded:
    """§D — the creator does not receive their own announcement.

    The Gathering and Series resolvers were written with this
    exclusion; the Pathway one predated them and mailed the creator
    their own publication.
    """

    @pytest.fixture
    def published(self, db, make_space, make_user):
        from app.comms.models import CommunicationEvent

        creator = make_user(role="creator")
        space = make_space(creator=creator)
        members = [make_user() for _ in range(2)]
        for who in (creator, *members):
            db.add(SpaceMembership(
                id=_uid("sm"), user_id=who.id, space_id=space.id,
                role=SpaceRole.learner, status=SpaceMembershipStatus.active,
                joined_at=datetime.utcnow(),
            ))
        pathway = Pathway(
            id=_uid("pw"), space_id=space.id, title="Know Yourself",
            slug=f"ky-{uuid.uuid4().hex[:8]}",
            status="active", access_type="free",
        )
        db.add(pathway)
        db.flush()
        event = CommunicationEvent(
            id=_uid("evt"), event_type="pathway.published",
            topic_key="pathways", category_key="pathways",
            source_type="creator", source_id=creator.id,
            priority_hint="immediate",
            actor_user_id=creator.id,
            subject_type="pathway", subject_id=pathway.id,
            context={"space_id": space.id, "collective_name": space.name},
            payload={
                "pathway_id": pathway.id,
                "pathway_slug": pathway.slug,
                "pathway_title": pathway.title,
            },
            dedupe_key=f"{pathway.id}:{space.id}",
        )
        db.add(event)
        db.flush()
        return event, creator, members

    def _resolve(self, db, event):
        from app.comms.routing.resolvers.pathways import (
            PathwayPublishedResolver,
        )

        return PathwayPublishedResolver().resolve(db, event)

    def test_the_creator_is_not_a_recipient(self, db, published):
        event, creator, _members = published
        ids = {r.user_id for r in self._resolve(db, event)}
        assert creator.id not in ids

    def test_the_other_members_still_are(self, db, published):
        event, _creator, members = published
        ids = {r.user_id for r in self._resolve(db, event)}
        assert ids == {m.id for m in members}

    def test_the_announcement_still_carries_its_destination(
        self, db, published,
    ):
        """Excluding somebody must not disturb the payload."""
        event, _creator, _members = published
        recipients = self._resolve(db, event)
        assert recipients
        assert recipients[0].template_context["pathway_url"], (
            "the CTA destination went missing"
        )
