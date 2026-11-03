"""Archiving a Pathway, and bringing it back as a draft.

Both already worked: the Settings status dropdown has always written
``archived``, and the creator gallery has always offered Restore, which
PATCHes the status to ``draft``. What changed is where archived
Pathways are shown — their own page rather than a group on the main
gallery — and that gave the behaviour underneath no new code but a new
dependency on it.

So this pins the behaviour the archive page now relies on, and the
promises it makes to a creator pressing Restore:

* Restore lands in ``draft``, never ``active``. A silent re-publish is
  not ours to assume, and it is what makes the button safe to press.
* Nothing else moves. Not a step, not a block, not a member's progress
  or reflection, not an enrolment, not an entitlement, not a channel
  membership.
* Archiving is always deliberate. Nothing here derives a status from a
  date, so no Pathway ages into the archive and none leaves it on its
  own.
* Republishing after a restore announces nothing: the dedupe row from
  the first publication is still there.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_pathway_archive_restore.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import (
    get_creator_user,
    get_current_user,
    get_verified_creator_user,
)
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    Enrollment,
    Pathway,
    PathwayEntitlement,
    PathwaySection,
    PathwayStatus,
    PathwayStep,
    PathwayStepBlock,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    StepBlockType,
    StepProgress,
    StepResource,
)
from app.models.user import User


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def space(make_space):
    return make_space()


@pytest.fixture
def owner(db, space):
    return db.query(User).filter(User.id == space.creator_id).one()


@pytest.fixture
def client(db, owner):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_creator_user] = lambda: owner
    app.dependency_overrides[get_verified_creator_user] = lambda: owner
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(db, user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_creator_user] = lambda: user
    app.dependency_overrides[get_verified_creator_user] = lambda: user
    return TestClient(app)


def make_pathway(db, space, title="Know Yourself", status=PathwayStatus.active):
    row = Pathway(
        id=_uid("pw"), space_id=space.id, title=title,
        slug=f"p-{uuid.uuid4().hex[:8]}", status=status, position=0,
        description="A journey.",
    )
    db.add(row)
    db.flush()
    return row


def list_url(space) -> str:
    return f"/api/creator/spaces/{space.slug}/pathways"


def pathway_url(space, pathway) -> str:
    return f"{list_url(space)}/{pathway.slug}"


def set_status(client, space, pathway, status: str):
    return client.patch(pathway_url(space, pathway), json={"status": status})


def listed(client, space) -> list[dict]:
    r = client.get(list_url(space))
    assert r.status_code == 200, r.text
    return r.json()


def statuses(rows: list[dict]) -> dict[str, str]:
    return {row["title"]: row["status"] for row in rows}


# ---------------------------------------------------------------------------
# Archiving
# ---------------------------------------------------------------------------


class TestArchiving:
    def test_a_published_pathway_can_be_archived(self, client, db, space):
        pathway = make_pathway(db, space)
        db.commit()
        r = set_status(client, space, pathway, "archived")
        assert r.status_code == 200, r.text
        db.expire_all()
        assert db.get(Pathway, pathway.id).status == PathwayStatus.archived

    def test_a_draft_pathway_can_be_archived(self, client, db, space):
        pathway = make_pathway(db, space, status=PathwayStatus.draft)
        db.commit()
        assert set_status(client, space, pathway, "archived").status_code == 200
        db.expire_all()
        assert db.get(Pathway, pathway.id).status == PathwayStatus.archived

    def test_a_coming_soon_pathway_can_be_archived(self, client, db, space):
        pathway = make_pathway(db, space, status=PathwayStatus.coming_soon)
        db.commit()
        assert set_status(client, space, pathway, "archived").status_code == 200

    def test_the_list_still_returns_it(self, client, db, space):
        """Which is why the archive page needs no new endpoint — and why
        an archived Pathway was never lost, only hard to find."""
        pathway = make_pathway(db, space, title="Archived One")
        db.commit()
        set_status(client, space, pathway, "archived")
        assert statuses(listed(client, space))["Archived One"] == "archived"

    def test_nothing_is_archived_by_age(self, client, db, space):
        """Unlike a Gathering Series, no Pathway status is derived from
        a date. Asserted because the archive page's whole filter rests
        on it."""
        old = make_pathway(db, space, title="Years Old")
        old.created_at = datetime.utcnow() - timedelta(days=1500)
        db.commit()
        assert statuses(listed(client, space))["Years Old"] == "active"
        # And reading the list changes nothing.
        db.expire_all()
        assert db.get(Pathway, old.id).status == PathwayStatus.active


# ---------------------------------------------------------------------------
# Restoring
# ---------------------------------------------------------------------------


class TestRestoringToDraft:
    def test_restore_lands_in_draft(self, client, db, space):
        pathway = make_pathway(db, space, status=PathwayStatus.archived)
        db.commit()
        r = set_status(client, space, pathway, "draft")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "draft"
        db.expire_all()
        assert db.get(Pathway, pathway.id).status == PathwayStatus.draft

    def test_restore_never_publishes(self, client, db, space):
        """The promise that makes the button safe to press."""
        pathway = make_pathway(db, space, status=PathwayStatus.archived)
        db.commit()
        set_status(client, space, pathway, "draft")
        db.expire_all()
        assert db.get(Pathway, pathway.id).status != PathwayStatus.active

    def test_a_restored_pathway_is_in_building_not_archives(
        self, client, db, space,
    ):
        pathway = make_pathway(db, space, title="Restored",
                               status=PathwayStatus.archived)
        db.commit()
        set_status(client, space, pathway, "draft")
        assert statuses(listed(client, space))["Restored"] == "draft"

    def test_restoring_twice_is_harmless(self, client, db, space):
        """The second press is a no-op PATCH to the status it already
        has, not an error — a creator double-clicking must not see a
        failure."""
        pathway = make_pathway(db, space, status=PathwayStatus.archived)
        db.commit()
        assert set_status(client, space, pathway, "draft").status_code == 200
        assert set_status(client, space, pathway, "draft").status_code == 200
        db.expire_all()
        assert db.get(Pathway, pathway.id).status == PathwayStatus.draft

    def test_the_round_trip_returns_to_where_it_started(
        self, client, db, space,
    ):
        """Archive, restore, publish — the full lifecycle a creator
        runs, ending where they chose rather than where we put them."""
        pathway = make_pathway(db, space)
        db.commit()
        set_status(client, space, pathway, "archived")
        set_status(client, space, pathway, "draft")
        db.expire_all()
        assert db.get(Pathway, pathway.id).status == PathwayStatus.draft
        set_status(client, space, pathway, "active")
        db.expire_all()
        assert db.get(Pathway, pathway.id).status == PathwayStatus.active


# ---------------------------------------------------------------------------
# What must not move
# ---------------------------------------------------------------------------


class TestContentAndRecordsSurvive:
    @pytest.fixture
    def furnished(self, db, space, make_user):
        """A Pathway with the things a creator would hate to lose, and
        a member who has used it."""
        pathway = make_pathway(db, space, status=PathwayStatus.archived)
        section = PathwaySection(
            id=_uid("sec"), pathway_id=pathway.id, title="Module One",
            position=0,
        )
        db.add(section)
        db.flush()
        step = PathwayStep(
            id=_uid("st"), pathway_id=pathway.id, slug="s-one",
            title="Understanding Your Patterns", position=0,
            section_id=section.id, section_position=0,
            content_body="# A heading\n\nSome **markdown**.",
            banner_image_url="https://cdn.test/b.jpg",
        )
        db.add(step)
        db.flush()
        blocks = [
            PathwayStepBlock(
                id=_uid("blk"), step_id=step.id, position=i,
                block_type=bt, content=f"Block {i}",
            )
            for i, bt in enumerate([
                StepBlockType.text, StepBlockType.reflection_prompt,
                StepBlockType.exercise,
            ])
        ]
        for b in blocks:
            db.add(b)
        db.add(StepResource(
            id=_uid("sr"), step_id=step.id, title="Workbook",
            resource_type="pdf", url="uploads/w.pdf", position=0,
        ))

        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.add(StepProgress(
            id=_uid("sp"), user_id=member.id, step_id=step.id,
            completed_at=datetime.utcnow(),
            reflection_text="What I noticed was…",
        ))
        db.add(Enrollment(
            id=_uid("en"), user_id=member.id, pathway_id=pathway.id,
        ))
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=member.id, pathway_id=pathway.id,
            space_id=space.id, source="one_time_purchase",
        ))
        db.flush()
        db.commit()
        return pathway, section, step, blocks, member

    def test_sections_and_steps_survive(self, client, db, space, furnished):
        pathway, section, step, _blocks, _member = furnished
        set_status(client, space, pathway, "draft")
        db.expire_all()
        assert db.get(PathwaySection, section.id) is not None
        reloaded = db.get(PathwayStep, step.id)
        assert reloaded is not None
        assert reloaded.title == "Understanding Your Patterns"
        assert reloaded.content_body.startswith("# A heading")
        assert reloaded.section_id == section.id
        assert reloaded.banner_image_url == "https://cdn.test/b.jpg"

    def test_content_blocks_keep_their_ids_and_order(
        self, client, db, space, furnished,
    ):
        """No new records — a restore is a status change, so a member's
        exercise answers stay attached to the blocks they answered."""
        pathway, _section, step, blocks, _member = furnished
        before = [(b.id, b.position) for b in blocks]
        set_status(client, space, pathway, "draft")
        db.expire_all()
        after = [
            (b.id, b.position) for b in db.query(PathwayStepBlock)
            .filter(PathwayStepBlock.step_id == step.id)
            .order_by(PathwayStepBlock.position).all()
        ]
        assert after == before

    def test_resources_survive(self, client, db, space, furnished):
        pathway, _section, step, _blocks, _member = furnished
        set_status(client, space, pathway, "draft")
        db.expire_all()
        resources = db.query(StepResource).filter(
            StepResource.step_id == step.id).all()
        assert [r.title for r in resources] == ["Workbook"]
        assert resources[0].url == "uploads/w.pdf"

    def test_member_progress_and_reflection_survive(
        self, client, db, space, furnished,
    ):
        pathway, _section, step, _blocks, member = furnished
        set_status(client, space, pathway, "draft")
        db.expire_all()
        progress = db.query(StepProgress).filter(
            StepProgress.step_id == step.id,
            StepProgress.user_id == member.id,
        ).one()
        assert progress.reflection_text == "What I noticed was…"
        assert progress.completed_at is not None

    def test_enrolments_and_entitlements_survive_untouched(
        self, client, db, space, furnished,
    ):
        """And no new ones appear. Restoring must not broaden access."""
        pathway, _section, _step, _blocks, member = furnished
        before_enrol = db.query(Enrollment).filter(
            Enrollment.pathway_id == pathway.id).count()
        before_ent = db.query(PathwayEntitlement).filter(
            PathwayEntitlement.pathway_id == pathway.id).count()

        set_status(client, space, pathway, "draft")
        db.expire_all()

        assert db.query(Enrollment).filter(
            Enrollment.pathway_id == pathway.id).count() == before_enrol
        entitlements = db.query(PathwayEntitlement).filter(
            PathwayEntitlement.pathway_id == pathway.id).all()
        assert len(entitlements) == before_ent == 1
        assert entitlements[0].user_id == member.id
        assert entitlements[0].source.value == "one_time_purchase"

    def test_no_new_member_gains_access(
        self, client, db, space, furnished, make_user,
    ):
        """A second member who never bought it has nothing before or
        after."""
        pathway, _section, _step, _blocks, _member = furnished
        stranger = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=stranger.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.commit()
        set_status(client, space, pathway, "draft")
        db.expire_all()
        assert db.query(PathwayEntitlement).filter(
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.user_id == stranger.id,
        ).count() == 0

    def test_no_duplicate_pathway_is_created(
        self, client, db, space, furnished,
    ):
        pathway, _section, _step, _blocks, _member = furnished
        before = db.query(Pathway).filter(Pathway.space_id == space.id).count()
        set_status(client, space, pathway, "draft")
        db.expire_all()
        assert db.query(Pathway).filter(
            Pathway.space_id == space.id).count() == before

    def test_channel_links_and_memberships_are_untouched(
        self, client, db, space, furnished,
    ):
        from sqlalchemy import text as _sql

        pathway, _section, _step, _blocks, _member = furnished
        before = db.execute(
            _sql("SELECT count(*) FROM channel_experience_links "
                 "WHERE pathway_id = :id"), {"id": pathway.id},
        ).scalar()
        memberships = db.execute(
            _sql("SELECT count(*) FROM channel_memberships"),
        ).scalar()
        set_status(client, space, pathway, "draft")
        db.expire_all()
        assert db.execute(
            _sql("SELECT count(*) FROM channel_experience_links "
                 "WHERE pathway_id = :id"), {"id": pathway.id},
        ).scalar() == before
        assert db.execute(
            _sql("SELECT count(*) FROM channel_memberships"),
        ).scalar() == memberships


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------


class TestAnnouncements:
    def test_restoring_announces_nothing(self, client, db, space):
        from app.comms.models import CommunicationEvent

        pathway = make_pathway(db, space, status=PathwayStatus.archived)
        db.commit()
        before = db.query(CommunicationEvent).count()
        assert set_status(client, space, pathway, "draft").status_code == 200
        assert db.query(CommunicationEvent).count() == before

    def test_archiving_announces_nothing(self, client, db, space):
        from app.comms.models import CommunicationEvent

        pathway = make_pathway(db, space)
        db.commit()
        before = db.query(CommunicationEvent).count()
        set_status(client, space, pathway, "archived")
        assert db.query(CommunicationEvent).count() == before

    def test_republishing_does_not_announce_a_second_time(
        self, client, db, space, owner, make_user,
    ):
        """The reason the dedupe key matters here. A Pathway archived
        and restored has been published before, and its members have
        already been told."""
        from app.comms.models import CommunicationEvent
        from app.services.pathway_announcement import (
            announce_if_newly_available,
        )

        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        pathway = make_pathway(db, space)
        db.flush()
        # Its first publication, as it happened originally.
        first = announce_if_newly_available(db, pathway, actor_user_id=owner.id)
        assert first is not None
        db.commit()
        after_first = db.query(CommunicationEvent).count()

        set_status(client, space, pathway, "archived")
        set_status(client, space, pathway, "draft")
        set_status(client, space, pathway, "active")
        db.commit()

        assert db.query(CommunicationEvent).count() == after_first, (
            "republishing after a restore announced the Pathway again"
        )

    def test_the_original_announcement_record_is_kept(
        self, client, db, space, owner,
    ):
        """It is what makes the dedupe work, so archiving must not
        tidy it away."""
        from app.comms.models import CommunicationEvent
        from app.services.pathway_announcement import (
            announce_if_newly_available,
            announcement_dedupe_key,
        )

        pathway = make_pathway(db, space)
        db.flush()
        announce_if_newly_available(db, pathway, actor_user_id=owner.id)
        db.commit()
        key = announcement_dedupe_key(pathway.id, space.id)

        set_status(client, space, pathway, "archived")
        set_status(client, space, pathway, "draft")
        db.commit()

        assert db.query(CommunicationEvent).filter(
            CommunicationEvent.dedupe_key == key).count() == 1

    def test_notification_preferences_are_untouched(
        self, client, db, space, make_user,
    ):
        from app.comms.models import CommunicationPreference

        pathway = make_pathway(db, space, status=PathwayStatus.archived)
        db.commit()
        before = db.query(CommunicationPreference).count()
        set_status(client, space, pathway, "draft")
        assert db.query(CommunicationPreference).count() == before


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_a_stranger_cannot_restore(self, db, space, make_user):
        pathway = make_pathway(db, space, status=PathwayStatus.archived)
        db.commit()
        outsider = make_user(role="creator")
        try:
            r = as_user(db, outsider).patch(
                pathway_url(space, pathway), json={"status": "draft"})
            assert r.status_code in (403, 404), r.status_code
            db.expire_all()
            assert db.get(Pathway, pathway.id).status == PathwayStatus.archived
        finally:
            app.dependency_overrides.clear()

    def test_an_ordinary_member_cannot_restore(self, db, space, make_user):
        pathway = make_pathway(db, space, status=PathwayStatus.archived)
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.commit()
        try:
            r = as_user(db, member).patch(
                pathway_url(space, pathway), json={"status": "draft"})
            assert r.status_code in (403, 404), r.status_code
        finally:
            app.dependency_overrides.clear()

    def test_an_ordinary_member_cannot_list_the_archive(
        self, db, space, make_user,
    ):
        make_pathway(db, space, status=PathwayStatus.archived)
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.commit()
        try:
            r = as_user(db, member).get(list_url(space))
            assert r.status_code in (403, 404), r.status_code
        finally:
            app.dependency_overrides.clear()

    def test_a_moderator_may_restore(self, db, space, make_user):
        pathway = make_pathway(db, space, status=PathwayStatus.archived)
        moderator = make_user(role="creator")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=moderator.id, space_id=space.id,
            role=SpaceRole.moderator, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.commit()
        try:
            r = as_user(db, moderator).patch(
                pathway_url(space, pathway), json={"status": "draft"})
            assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.clear()

    def test_another_collectives_pathway_is_not_found(
        self, client, db, space, make_space,
    ):
        other = make_space()
        theirs = make_pathway(db, other, title="Theirs",
                              status=PathwayStatus.archived)
        db.commit()
        r = client.patch(
            f"{list_url(space)}/{theirs.slug}", json={"status": "draft"})
        assert r.status_code == 404
        db.expire_all()
        assert db.get(Pathway, theirs.id).status == PathwayStatus.archived

    def test_another_collectives_archive_is_not_listed(
        self, client, db, space, make_space,
    ):
        other = make_space()
        make_pathway(db, other, title="Theirs", status=PathwayStatus.archived)
        make_pathway(db, space, title="Mine", status=PathwayStatus.archived)
        db.commit()
        titles = statuses(listed(client, space))
        assert "Mine" in titles
        assert "Theirs" not in titles

    def test_a_missing_pathway_is_not_found(self, client, db, space):
        db.commit()
        r = client.patch(
            f"{list_url(space)}/no-such-pathway", json={"status": "draft"})
        assert r.status_code == 404

    def test_an_archived_pathway_is_not_publicly_discoverable(
        self, db, make_space, make_user,
    ):
        """Creator archive management and member-facing visibility stay
        separate concerns."""
        from app.auth.dependencies import get_optional_user

        public_space = make_space(
            is_public=True, area_policies={"areas": {"pathways": "public"}},
        )
        pathway = make_pathway(db, public_space, title="Put Away",
                               status=PathwayStatus.archived)
        db.commit()

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: None
        try:
            client = TestClient(app)
            rows = client.get(f"/api/spaces/{public_space.slug}/pathways")
            if rows.status_code == 200:
                assert "Put Away" not in str(rows.json())
            detail = client.get(
                f"/api/spaces/{public_space.slug}/pathways/{pathway.slug}")
            # 401 because the member Pathway endpoint requires a
            # session at all; the point is that it is not 200.
            assert detail.status_code in (401, 403, 404), detail.status_code
        finally:
            app.dependency_overrides.clear()
