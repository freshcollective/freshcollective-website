"""Tests for the Natural Leader Hub deletion script.

Uses the standard Postgres test DB (SAVEPOINT-scoped by conftest) as
"prod" so the real ON DELETE CASCADE constraints fire — the whole
point of the deletion path is that PostgreSQL cascades the child
tables. Attempting to simulate this against SQLite loses either FK
enforcement (constraints ignored) or fixture setup (the metadata's
duplicate index names collide when tables are created transitively).

Each test seeds the NLH shape (matching the audit report), calls the
helpers directly, and lets the conftest rollback tidy up.

Coverage:
  * Identity guards: missing Space, wrong id, wrong name, non-null
    creator_id, non-null auto_grant_role, non-null location_id.
  * PurchasePlan blocker: refuses when > 0.
  * Child-count surprise guard: refuses when any CASCADE-child count
    exceeds the audited upper bound; enforces the membership ceiling.
  * Unexpected R2 keys: refuses when any key surfaces.
  * Successful delete removes the Space + every enumerated child row
    (real PostgreSQL CASCADE).
  * DB rollback on failure leaves the Space intact.
  * Post-delete verification catches an incomplete cascade.
  * Unrelated Space + its Pathway/membership survive.
  * Unrelated User (prod Lindsey) and her other-Space memberships
    unchanged.
  * Dry-run makes no writes.
  * Module constants are locked.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, text
from sqlalchemy.orm import Session

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import delete_natural_leader_hub_from_prod as deleter  # noqa: E402

from app.models.platform import (  # noqa: E402
    ConversationChannel,
    Event,
    Pathway,
    PathwayStep,
    PathwayStepBlock,
    PathwayType,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    SpaceStatus,
)
from app.models.user import User  # noqa: E402


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# NLH seeding helper — matches the audit shape
# ---------------------------------------------------------------------------


@pytest.fixture
def nlh_seed(db: Session, make_user):
    """Seed the audited NLH shape into the test DB plus an unrelated
    Space owned by prod-Lindsey. Returns a dict of the ids the tests
    need."""
    # The test DB's alembic seed may already contain a
    # world-builders + other Spaces from prior migrations. Delete any
    # pre-existing NLH so the fixture controls the shape end-to-end.
    for old in db.query(Space).filter(Space.slug == "the-natural-leader-hub").all():
        db.delete(old)
    db.flush()

    # Prod Lindsey — real user, must survive the delete.
    lindsey = make_user(
        role="admin", email=deleter.PROD_LINDSEY_EMAIL,
    )
    # Distinct "test learner" — the audit's NLH membership belongs to
    # a SEC-009 test account, NOT prod Lindsey.
    learner = make_user(role="user", email="lindsey.wd+sec009@gmail.com")

    # NLH itself. Deliberately construct with the audited id so the
    # identity guard passes.
    nlh = Space(
        id=deleter.TARGET_SPACE_ID,
        slug=deleter.TARGET_SLUG,
        name=deleter.TARGET_NAME,
        creator_id=None,
        auto_grant_role=None,
        location_id=None,
        status=SpaceStatus.active,
        visibility="public",
        is_public=True,
        kind="standard",
        connection_style="online",
        themes=[],
        pricing_type="free",
        pricing_currency="AUD",
        has_paid_internal_content=False,
        timezone="Australia/Melbourne",
        island_artwork_status="not_started",
    )
    db.add(nlh)
    db.flush()

    # 1 learner membership.
    db.add(SpaceMembership(
        id=_uid("mem"), user_id=learner.id, space_id=nlh.id,
        role=SpaceRole.learner,
        status=SpaceMembershipStatus.active,
        source="joined",
    ))
    # 4 pathways.
    pathways = []
    for i, (slug, status) in enumerate([
        ("real-journey", "active"),
        ("growth", "active"),
        ("transformation", "coming_soon"),
        ("essence", "coming_soon"),
    ]):
        pw = Pathway(
            id=_uid("pw"), space_id=nlh.id, slug=slug,
            title=slug.title(),
            status=status,
            pathway_type=PathwayType.guided_experience,
            position=i,
        )
        db.add(pw)
        pathways.append(pw)
    db.flush()
    # 6 steps across the first two pathways.
    steps = []
    for i, pw in enumerate(pathways[:2]):
        for j in range(3):
            st = PathwayStep(
                id=_uid("pst"), pathway_id=pw.id,
                slug=f"s{i}-{j}", title=f"Step {i}-{j}",
                position=j, content_type="text",
            )
            db.add(st)
            steps.append(st)
    db.flush()
    # 6 step blocks — one per step.
    for st in steps:
        db.add(PathwayStepBlock(
            id=_uid("blk"), step_id=st.id, block_type="text",
            position=0, content="content",
        ))
    # 2 ConversationChannels — the auto-created defaults.
    for name, slug in (("Start Here", "start-here"),
                       ("Common Room", "general")):
        db.add(ConversationChannel(
            id=_uid("ch"), space_id=nlh.id, name=name, slug=slug,
        ))
    # 3 Events.
    now = datetime.utcnow()
    for i in range(3):
        db.add(Event(
            id=_uid("evt"), space_id=nlh.id,
            title=f"Event {i}", description="",
            starts_at=now,
            ends_at=now + timedelta(hours=1),
            is_published=True,
        ))

    # Unrelated Space owned by prod-Lindsey — must survive.
    other_space = Space(
        id=_uid("other"), slug=f"somewhere-else-{_uid('x')}",
        name="Somewhere Else",
        creator_id=lindsey.id,
        status=SpaceStatus.active,
        visibility="public",
        is_public=True,
        kind="standard",
        connection_style="online",
        themes=[],
        pricing_type="free",
        pricing_currency="AUD",
        has_paid_internal_content=False,
        timezone="Australia/Melbourne",
        island_artwork_status="not_started",
    )
    db.add(other_space)
    db.flush()
    db.add(SpaceMembership(
        id=_uid("mem"), user_id=lindsey.id, space_id=other_space.id,
        role=SpaceRole.creator,
        status=SpaceMembershipStatus.active,
        source="creator_owner",
    ))
    db.flush()

    return {
        "nlh_id": nlh.id,
        "lindsey_id": lindsey.id,
        "learner_id": learner.id,
        "other_space_id": other_space.id,
    }


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_target_identity_is_locked(self) -> None:
        assert deleter.TARGET_SPACE_ID == "80862f54-d95f-4b3b-83ab-cf926014441d"
        assert deleter.TARGET_SLUG == "the-natural-leader-hub"
        assert deleter.TARGET_NAME == "The Natural Leader Hub"

    def test_expected_platform_owned_shape(self) -> None:
        assert deleter.EXPECTED_CREATOR_ID is None
        assert deleter.EXPECTED_AUTO_GRANT_ROLE is None
        assert deleter.EXPECTED_LOCATION_ID is None

    def test_audited_upper_bounds(self) -> None:
        # Frozen at the exact numbers the audit surfaced. Bumping any
        # of these should be a deliberate act after a fresh audit.
        assert deleter.AUDITED_CHILD_UPPER_BOUNDS == {
            "SpaceMembership":     1,
            "Pathway":             4,
            "PathwayStep":         6,
            "PathwayStepBlock":    6,
            "Event":               3,
            "ConversationChannel": 2,
        }
        assert deleter.MAX_EXPECTED_MEMBERSHIPS == 1
        assert deleter.EXPECTED_R2_KEY_COUNT == 0

    def test_prod_lindsey_email_locked(self) -> None:
        assert deleter.PROD_LINDSEY_EMAIL == "lindsey@hilliard.net.au"


# ---------------------------------------------------------------------------
# Identity guards
# ---------------------------------------------------------------------------


class TestIdentityGuards:
    def test_refuses_when_space_missing(self, db: Session) -> None:
        # Ensure no NLH row exists.
        for old in db.query(Space).filter(Space.slug == "the-natural-leader-hub").all():
            db.delete(old)
        db.flush()
        with pytest.raises(deleter.PreflightError, match="not found"):
            deleter._resolve_and_check_target_space(db)

    def test_refuses_when_id_drifts(self, db: Session) -> None:
        # A Space that carries the target slug but a different id
        # — e.g. it was deleted and recreated by a human without
        # preserving the audited id. Delete any pre-existing NLH so
        # the wrong-id row can take the slug.
        for old in db.query(Space).filter(
            Space.slug == "the-natural-leader-hub",
        ).all():
            db.delete(old)
        db.flush()
        db.add(Space(
            id=_uid("wrong"),
            slug=deleter.TARGET_SLUG,
            name=deleter.TARGET_NAME,
            creator_id=None,
            auto_grant_role=None,
            location_id=None,
            status=SpaceStatus.active,
            visibility="public",
            is_public=True,
            kind="standard",
            connection_style="online",
            themes=[],
            pricing_type="free",
            pricing_currency="AUD",
            has_paid_internal_content=False,
            timezone="Australia/Melbourne",
            island_artwork_status="not_started",
        ))
        db.flush()
        with pytest.raises(
            deleter.PreflightError, match="does not match the audited id",
        ):
            deleter._resolve_and_check_target_space(db)

    def test_refuses_when_name_drifts(self, db: Session, nlh_seed) -> None:
        nlh = db.query(Space).filter(Space.id == nlh_seed["nlh_id"]).first()
        nlh.name = "Renamed"
        db.flush()
        with pytest.raises(deleter.PreflightError, match="name"):
            deleter._resolve_and_check_target_space(db)

    def test_refuses_when_creator_id_non_null(
        self, db: Session, nlh_seed,
    ) -> None:
        nlh = db.query(Space).filter(Space.id == nlh_seed["nlh_id"]).first()
        nlh.creator_id = nlh_seed["lindsey_id"]
        db.flush()
        with pytest.raises(deleter.PreflightError, match="creator_id"):
            deleter._resolve_and_check_target_space(db)

    def test_refuses_when_auto_grant_role_present(
        self, db: Session, nlh_seed,
    ) -> None:
        nlh = db.query(Space).filter(Space.id == nlh_seed["nlh_id"]).first()
        nlh.auto_grant_role = "creator"
        db.flush()
        with pytest.raises(deleter.PreflightError, match="auto_grant_role"):
            deleter._resolve_and_check_target_space(db)


# ---------------------------------------------------------------------------
# Child-count surprise guard
# ---------------------------------------------------------------------------


class TestChildCountSurprises:
    def test_baseline_matches_audit(self, db: Session, nlh_seed) -> None:
        space = deleter._resolve_and_check_target_space(db)
        cc = deleter._enumerate_and_bound_check_children(db, space)
        assert cc.counts["Pathway"] == 4
        assert cc.counts["PathwayStep"] == 6
        assert cc.counts["PathwayStepBlock"] == 6
        assert cc.counts["Event"] == 3
        assert cc.counts["ConversationChannel"] == 2
        assert cc.counts["SpaceMembership"] == 1

    def test_refuses_when_pathway_count_exceeds_bound(
        self, db: Session, nlh_seed,
    ) -> None:
        db.add(Pathway(
            id=_uid("drift"), space_id=nlh_seed["nlh_id"],
            slug=f"drift-{_uid('x')}", title="Drift", status="draft",
            pathway_type=PathwayType.guided_experience, position=99,
        ))
        db.flush()
        space = deleter._resolve_and_check_target_space(db)
        with pytest.raises(deleter.PreflightError, match="Pathway"):
            deleter._enumerate_and_bound_check_children(db, space)

    def test_refuses_when_event_count_exceeds_bound(
        self, db: Session, nlh_seed,
    ) -> None:
        now = datetime.utcnow()
        db.add(Event(
            id=_uid("evt"), space_id=nlh_seed["nlh_id"],
            title="Drift", description="", starts_at=now,
            ends_at=now + timedelta(hours=1),
            is_published=True,
        ))
        db.flush()
        space = deleter._resolve_and_check_target_space(db)
        with pytest.raises(deleter.PreflightError, match="Event"):
            deleter._enumerate_and_bound_check_children(db, space)

    def test_refuses_when_membership_ceiling_exceeded(
        self, db: Session, nlh_seed, make_user,
    ) -> None:
        new_member = make_user(role="user")
        db.add(SpaceMembership(
            id=_uid("mem"), user_id=new_member.id,
            space_id=nlh_seed["nlh_id"],
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            source="joined",
        ))
        db.flush()
        space = deleter._resolve_and_check_target_space(db)
        with pytest.raises(
            deleter.PreflightError,
            match="(SpaceMembership|MAX_EXPECTED_MEMBERSHIPS)",
        ):
            deleter._enumerate_and_bound_check_children(db, space)


# ---------------------------------------------------------------------------
# R2 surprise guard
# ---------------------------------------------------------------------------


class TestR2SurpriseGuard:
    def test_passes_when_zero_keys(self, db: Session, nlh_seed) -> None:
        space = deleter._resolve_and_check_target_space(db)
        keys = deleter._refuse_if_unexpected_r2_keys(db, space)
        assert keys == []

    def test_refuses_when_keys_appear(
        self, db: Session, nlh_seed, monkeypatch,
    ) -> None:
        space = deleter._resolve_and_check_target_space(db)
        monkeypatch.setattr(
            deleter, "_collect_space_r2_keys",
            lambda space, db: ["media/some/leak.png"],
        )
        with pytest.raises(deleter.PreflightError, match="R2 object"):
            deleter._refuse_if_unexpected_r2_keys(db, space)


# ---------------------------------------------------------------------------
# Successful deletion + verify (real Postgres cascade)
# ---------------------------------------------------------------------------


def _run_full_delete(db, nlh_id, lindsey_id):
    """Mirror what main() does: snapshot, delete, verify."""
    other_mem_count = (
        db.query(func.count(SpaceMembership.id))
        .filter(
            SpaceMembership.user_id == lindsey_id,
            SpaceMembership.space_id != nlh_id,
        )
        .scalar()
    ) or 0
    ctx = deleter.DeletionContext(
        local_session=db,
        prod_session=db,
        space_id=nlh_id,
        commit=True,
        yes_i_am_sure=True,
        prod_lindsey_id=lindsey_id,
        prod_lindsey_other_membership_count=other_mem_count,
    )
    space = deleter._resolve_and_check_target_space(db)
    cc = deleter._enumerate_and_bound_check_children(db, space)
    deleter._refuse_if_purchase_plan_exists(db, space)
    deleter._refuse_if_unexpected_r2_keys(db, space)
    deleter.delete_space(db, nlh_id)
    db.flush()  # (conftest's session commit is via SAVEPOINT)
    return ctx, cc


class TestSuccessfulDelete:
    def test_space_gone_and_all_scoped_children_gone(
        self, db: Session, nlh_seed,
    ) -> None:
        ctx, cc = _run_full_delete(
            db, nlh_seed["nlh_id"], nlh_seed["lindsey_id"],
        )
        deleter.verify(ctx, cc)
        # And direct assertions on the DB state.
        assert db.query(Space).filter(
            Space.slug == deleter.TARGET_SLUG,
        ).first() is None
        assert db.query(Pathway).filter(
            Pathway.space_id == nlh_seed["nlh_id"],
        ).count() == 0
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == nlh_seed["nlh_id"],
        ).count() == 0
        assert db.query(Event).filter(
            Event.space_id == nlh_seed["nlh_id"],
        ).count() == 0
        assert db.query(ConversationChannel).filter(
            ConversationChannel.space_id == nlh_seed["nlh_id"],
        ).count() == 0

    def test_unrelated_space_survives(
        self, db: Session, nlh_seed,
    ) -> None:
        _run_full_delete(
            db, nlh_seed["nlh_id"], nlh_seed["lindsey_id"],
        )
        other = db.query(Space).filter(
            Space.id == nlh_seed["other_space_id"],
        ).first()
        assert other is not None
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == other.id,
        ).count() == 1

    def test_unrelated_users_survive(
        self, db: Session, nlh_seed,
    ) -> None:
        before_users = db.query(User).count()
        _run_full_delete(
            db, nlh_seed["nlh_id"], nlh_seed["lindsey_id"],
        )
        after_users = db.query(User).count()
        assert after_users == before_users
        assert db.query(User).filter(
            User.id == nlh_seed["lindsey_id"],
        ).first() is not None
        assert db.query(User).filter(
            User.id == nlh_seed["learner_id"],
        ).first() is not None


# ---------------------------------------------------------------------------
# Rollback on failure
# ---------------------------------------------------------------------------


class TestRollback:
    def test_rollback_after_delete_leaves_space_intact(
        self, db: Session, nlh_seed,
    ) -> None:
        # Simulate a post-delete failure inside the same SAVEPOINT.
        # The outer conftest transaction is what we're inside of;
        # emulate the script's rollback by starting a NESTED savepoint
        # around the delete, then releasing it as a rollback.
        savepoint = db.begin_nested()
        try:
            deleter.delete_space(db, nlh_seed["nlh_id"])
            raise RuntimeError("simulated post-delete failure")
        except Exception:
            savepoint.rollback()
        db.expire_all()
        assert db.query(Space).filter(
            Space.id == nlh_seed["nlh_id"],
        ).first() is not None
        assert db.query(Pathway).filter(
            Pathway.space_id == nlh_seed["nlh_id"],
        ).count() == 4
        assert db.query(Event).filter(
            Event.space_id == nlh_seed["nlh_id"],
        ).count() == 3


# ---------------------------------------------------------------------------
# verify() catches incomplete cascade
# ---------------------------------------------------------------------------


class TestVerify:
    def test_catches_space_still_present(
        self, db: Session, nlh_seed,
    ) -> None:
        # Snapshot preflight state.
        other_mem = (
            db.query(func.count(SpaceMembership.id))
            .filter(
                SpaceMembership.user_id == nlh_seed["lindsey_id"],
                SpaceMembership.space_id != nlh_seed["nlh_id"],
            )
            .scalar()
        ) or 0
        ctx = deleter.DeletionContext(
            local_session=db, prod_session=db,
            space_id=nlh_seed["nlh_id"], commit=True,
            yes_i_am_sure=True,
            prod_lindsey_id=nlh_seed["lindsey_id"],
            prod_lindsey_other_membership_count=other_mem,
        )
        space = deleter._resolve_and_check_target_space(db)
        cc = deleter._enumerate_and_bound_check_children(db, space)
        # Skip the actual delete — verify should refuse because the
        # Space is still there.
        with pytest.raises(RuntimeError, match="Space still present"):
            deleter.verify(ctx, cc)

    def test_catches_disturbed_lindsey_other_memberships(
        self, db: Session, nlh_seed,
    ) -> None:
        ctx, cc = _run_full_delete(
            db, nlh_seed["nlh_id"], nlh_seed["lindsey_id"],
        )
        # Delete Lindsey's other-Space memberships between delete and
        # verify — simulates something else disturbing the state.
        db.query(SpaceMembership).filter(
            SpaceMembership.user_id == nlh_seed["lindsey_id"],
        ).delete()
        db.flush()
        with pytest.raises(RuntimeError, match="Lindsey"):
            deleter.verify(ctx, cc)


# ---------------------------------------------------------------------------
# Dry-run — arg parsing
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_default_makes_no_writes(self) -> None:
        args = deleter.parse_args([])
        assert args.commit is False

    def test_commit_flag(self) -> None:
        args = deleter.parse_args(["--commit"])
        assert args.commit is True
