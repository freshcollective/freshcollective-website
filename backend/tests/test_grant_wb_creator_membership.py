"""Tests for the World Builders creator-membership grant script.

Uses a fresh SQLite-in-memory session as physically-distinct "prod",
seeded with the shape the real prod carries: platform-owned World
Builders (creator_id=None, auto_grant_role='creator', slug=
'world-builders') plus a prod-Lindsey user matched by email.

Coverage:
  * Prod resolution / platform-contract guards (missing user, missing
    space, non-null creator_id, wrong auto_grant_role).
  * Refusal when a Lindsey/WB membership already exists — regardless
    of source (migration, auto_role, creator_owner, joined, whatever).
  * Insert produces exactly one row with the right role / status /
    source; Space.creator_id and Space.auto_grant_role unchanged.
  * insert_membership rechecks the platform contract and the
    (user, space) uniqueness at commit time and refuses on drift.
  * verify catches: wrong role, wrong status, wrong source, disturbed
    Space.creator_id, disturbed Space.auto_grant_role, missing row.
  * Rollback leaves prod untouched.
  * Unrelated data (other users, other spaces, other memberships) is
    left alone.
  * Module constants are locked.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import grant_wb_creator_membership as grant  # noqa: E402

from app.models.platform import (  # noqa: E402
    Pathway,
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
# SQLite prod builder
# ---------------------------------------------------------------------------


def _make_sqlite_prod(
    *,
    with_lindsey: bool = True,
    with_wb: bool = True,
    wb_creator_id: str | None = None,
    wb_auto_grant_role: str = "creator",
    include_existing_membership: dict | None = None,
    include_other_user: bool = False,
    include_other_space: bool = False,
) -> tuple[Session, str | None, str | None]:
    """Fresh in-memory 'prod' session in the shape the real prod
    carries. Returns (session, prod_lindsey_id, prod_wb_id).
    ``include_existing_membership`` lets a test seed a prior
    Lindsey/WB row (any source) to exercise the refuse-if-exists
    path."""
    engine = create_engine("sqlite:///:memory:", future=True)
    for model in [User, Space, SpaceMembership, Pathway]:
        model.__table__.create(engine)
    prod = sessionmaker(bind=engine, future=True)()

    prod_lindsey_id = None
    if with_lindsey:
        prod_lindsey_id = _uid("u")
        prod.add(User(
            id=prod_lindsey_id, email=grant.TARGET_USER_EMAIL,
            name="Lindsey Hilliard",
            password_hash="$2b$12$0" + "0" * 52,
            role="admin",
            email_verified_at=datetime.utcnow(),
        ))

    if include_other_user:
        prod.add(User(
            id=_uid("u"), email="someone.else@example.com",
            name="Someone Else",
            password_hash="$2b$12$0" + "0" * 52,
            role="creator",
            email_verified_at=datetime.utcnow(),
        ))

    prod_wb_id = None
    if with_wb:
        prod_wb_id = _uid("wb")
        prod.add(Space(
            id=prod_wb_id,
            slug="world-builders",
            name="World Builders",
            creator_id=wb_creator_id,
            auto_grant_role=wb_auto_grant_role,
            status=SpaceStatus.active,
            visibility="link",
            is_public=False,
            kind="standard",
            connection_style="online",
            themes=[],
            pricing_type="free",
            pricing_currency="AUD",
            has_paid_internal_content=False,
            timezone="Australia/Melbourne",
            island_artwork_status="not_started",
        ))

    other_space_id = None
    if include_other_space:
        other_space_id = _uid("other")
        prod.add(Space(
            id=other_space_id,
            slug="somewhere-else",
            name="Somewhere Else",
            creator_id=prod_lindsey_id,
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

    if include_existing_membership and prod_lindsey_id and prod_wb_id:
        prod.add(SpaceMembership(
            id=_uid("mem"),
            user_id=prod_lindsey_id,
            space_id=prod_wb_id,
            role=include_existing_membership.get("role", SpaceRole.learner),
            status=include_existing_membership.get(
                "status", SpaceMembershipStatus.active
            ),
            source=include_existing_membership.get("source", "auto_role"),
        ))

    prod.commit()
    return prod, prod_lindsey_id, prod_wb_id


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_target_space_slug(self) -> None:
        assert grant.TARGET_SPACE_SLUG == "world-builders"

    def test_target_user_email(self) -> None:
        assert grant.TARGET_USER_EMAIL == "lindsey@hilliard.net.au"

    def test_expected_creator_id_is_none(self) -> None:
        assert grant.EXPECTED_CREATOR_ID is None

    def test_expected_auto_grant_role(self) -> None:
        assert grant.EXPECTED_AUTO_GRANT_ROLE == "creator"

    def test_new_membership_shape(self) -> None:
        assert grant.NEW_MEMBERSHIP_ROLE == SpaceRole.creator
        assert grant.NEW_MEMBERSHIP_STATUS == SpaceMembershipStatus.active
        # source MUST NOT be 'auto_role' — the reconciler would treat
        # it as its own row and could sweep it on future eligibility
        # changes.
        assert grant.NEW_MEMBERSHIP_SOURCE == "migration"
        assert grant.NEW_MEMBERSHIP_SOURCE != "auto_role"


# ---------------------------------------------------------------------------
# _resolve_and_check — prod-side platform-contract guard
# ---------------------------------------------------------------------------


class TestResolveAndCheck:
    def test_success_returns_user_and_space_ids(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        got_user, got_space = grant._resolve_and_check(prod)
        assert got_user == lin_id
        assert got_space == wb_id

    def test_refuses_when_lindsey_missing(self) -> None:
        prod, _, _ = _make_sqlite_prod(with_lindsey=False)
        with pytest.raises(
            grant.PreflightError, match=grant.TARGET_USER_EMAIL,
        ):
            grant._resolve_and_check(prod)

    def test_refuses_when_wb_missing(self) -> None:
        prod, _, _ = _make_sqlite_prod(with_wb=False)
        with pytest.raises(
            grant.PreflightError, match=grant.TARGET_SPACE_SLUG,
        ):
            grant._resolve_and_check(prod)

    def test_refuses_when_wb_creator_id_is_non_null(self) -> None:
        prod, _, _ = _make_sqlite_prod(wb_creator_id="u_someone")
        with pytest.raises(grant.PreflightError, match="creator_id"):
            grant._resolve_and_check(prod)

    def test_refuses_when_wb_auto_grant_role_wrong(self) -> None:
        prod, _, _ = _make_sqlite_prod(wb_auto_grant_role="learner")
        with pytest.raises(grant.PreflightError, match="auto_grant_role"):
            grant._resolve_and_check(prod)


# ---------------------------------------------------------------------------
# _refuse_if_membership_exists — insert-only guard
# ---------------------------------------------------------------------------


class TestRefuseIfMembershipExists:
    def test_refuses_when_migration_source_row_exists(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod(
            include_existing_membership={
                "role": SpaceRole.creator,
                "status": SpaceMembershipStatus.active,
                "source": "migration",
            },
        )
        with pytest.raises(grant.PreflightError, match="already exists"):
            grant._refuse_if_membership_exists(prod, lin_id, wb_id)

    def test_refuses_when_auto_role_learner_exists(self) -> None:
        # Even a "harmless" auto-grant learner row means the script
        # should stop and let a human investigate — don't create a
        # second row (the DB unique constraint would catch it, but
        # we prefer the friendly refusal).
        prod, lin_id, wb_id = _make_sqlite_prod(
            include_existing_membership={
                "role": SpaceRole.learner,
                "status": SpaceMembershipStatus.active,
                "source": "auto_role",
            },
        )
        with pytest.raises(grant.PreflightError, match="already exists"):
            grant._refuse_if_membership_exists(prod, lin_id, wb_id)

    def test_refuses_when_creator_owner_source_row_exists(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod(
            include_existing_membership={
                "role": SpaceRole.creator,
                "status": SpaceMembershipStatus.active,
                "source": "creator_owner",
            },
        )
        with pytest.raises(grant.PreflightError, match="already exists"):
            grant._refuse_if_membership_exists(prod, lin_id, wb_id)

    def test_refuses_even_when_status_is_removed(self) -> None:
        # A soft-deleted row still occupies the (user, space) unique
        # slot; the script refuses so we don't silently insert a
        # second row (which the DB would reject anyway).
        prod, lin_id, wb_id = _make_sqlite_prod(
            include_existing_membership={
                "role": SpaceRole.learner,
                "status": SpaceMembershipStatus.removed,
                "source": "auto_role",
            },
        )
        with pytest.raises(grant.PreflightError, match="already exists"):
            grant._refuse_if_membership_exists(prod, lin_id, wb_id)

    def test_passes_when_no_membership_exists(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        # Must NOT raise.
        grant._refuse_if_membership_exists(prod, lin_id, wb_id)


# ---------------------------------------------------------------------------
# insert_membership — happy path + drift-at-commit-time guards
# ---------------------------------------------------------------------------


class TestInsertMembership:
    def test_happy_path_creates_exactly_one_row(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        new_id = grant.insert_membership(prod, lin_id, wb_id)
        prod.commit()

        rows = prod.query(SpaceMembership).filter(
            SpaceMembership.user_id == lin_id,
            SpaceMembership.space_id == wb_id,
        ).all()
        assert len(rows) == 1
        m = rows[0]
        assert m.id == new_id
        assert m.role == SpaceRole.creator
        assert m.status == SpaceMembershipStatus.active
        assert m.source == "migration"

    def test_platform_contract_preserved_after_insert(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        grant.insert_membership(prod, lin_id, wb_id)
        prod.commit()
        space = prod.query(Space).filter(Space.id == wb_id).first()
        assert space.creator_id is None
        assert space.auto_grant_role == "creator"

    def test_refuses_if_creator_id_drifts_between_preflight_and_commit(
        self,
    ) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        # Simulate a concurrent admin action that reparented WB
        # between preflight and insert.
        space = prod.query(Space).filter(Space.id == wb_id).first()
        space.creator_id = "u_intruder"
        prod.flush()
        with pytest.raises(RuntimeError, match="creator_id"):
            grant.insert_membership(prod, lin_id, wb_id)

    def test_refuses_if_auto_grant_role_drifts_between_preflight_and_commit(
        self,
    ) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        space = prod.query(Space).filter(Space.id == wb_id).first()
        space.auto_grant_role = "learner"
        prod.flush()
        with pytest.raises(RuntimeError, match="auto_grant_role"):
            grant.insert_membership(prod, lin_id, wb_id)

    def test_refuses_if_membership_appears_between_preflight_and_commit(
        self,
    ) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        # Simulate another actor creating the same (user, space)
        # row between preflight and our insert.
        prod.add(SpaceMembership(
            id=_uid("mem"),
            user_id=lin_id, space_id=wb_id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            source="auto_role",
        ))
        prod.flush()
        with pytest.raises(RuntimeError, match="Drift"):
            grant.insert_membership(prod, lin_id, wb_id)


# ---------------------------------------------------------------------------
# verify — must catch every post-commit drift
# ---------------------------------------------------------------------------


def _mk_ctx(prod: Session, lin_id: str, wb_id: str) -> grant.MaintenanceContext:
    return grant.MaintenanceContext(
        local_session=prod,       # unused by verify()
        prod_session=prod,
        prod_user_id=lin_id,
        prod_space_id=wb_id,
        commit=True,
        yes_i_am_sure=True,
    )


class TestVerify:
    def test_passes_on_clean_insert(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        new_id = grant.insert_membership(prod, lin_id, wb_id)
        prod.commit()
        ctx = _mk_ctx(prod, lin_id, wb_id)
        grant.verify(ctx, new_id)

    def test_catches_missing_row(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        new_id = grant.insert_membership(prod, lin_id, wb_id)
        prod.commit()
        # Delete the row we just inserted.
        prod.query(SpaceMembership).filter(
            SpaceMembership.user_id == lin_id,
            SpaceMembership.space_id == wb_id,
        ).delete()
        prod.commit()
        ctx = _mk_ctx(prod, lin_id, wb_id)
        with pytest.raises(RuntimeError, match="exactly 1"):
            grant.verify(ctx, new_id)

    def test_catches_wrong_role(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        new_id = grant.insert_membership(prod, lin_id, wb_id)
        prod.commit()
        m = prod.query(SpaceMembership).first()
        m.role = SpaceRole.learner
        prod.commit()
        ctx = _mk_ctx(prod, lin_id, wb_id)
        with pytest.raises(RuntimeError, match="role"):
            grant.verify(ctx, new_id)

    def test_catches_wrong_status(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        new_id = grant.insert_membership(prod, lin_id, wb_id)
        prod.commit()
        m = prod.query(SpaceMembership).first()
        m.status = SpaceMembershipStatus.paused
        prod.commit()
        ctx = _mk_ctx(prod, lin_id, wb_id)
        with pytest.raises(RuntimeError, match="status"):
            grant.verify(ctx, new_id)

    def test_catches_wrong_source(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        new_id = grant.insert_membership(prod, lin_id, wb_id)
        prod.commit()
        m = prod.query(SpaceMembership).first()
        m.source = "auto_role"     # ← would make the reconciler own it
        prod.commit()
        ctx = _mk_ctx(prod, lin_id, wb_id)
        with pytest.raises(RuntimeError, match="source"):
            grant.verify(ctx, new_id)

    def test_catches_disturbed_creator_id(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        new_id = grant.insert_membership(prod, lin_id, wb_id)
        prod.commit()
        space = prod.query(Space).filter(Space.id == wb_id).first()
        space.creator_id = "u_intruder"
        prod.commit()
        ctx = _mk_ctx(prod, lin_id, wb_id)
        with pytest.raises(RuntimeError, match="creator_id"):
            grant.verify(ctx, new_id)

    def test_catches_disturbed_auto_grant_role(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        new_id = grant.insert_membership(prod, lin_id, wb_id)
        prod.commit()
        space = prod.query(Space).filter(Space.id == wb_id).first()
        space.auto_grant_role = "learner"
        prod.commit()
        ctx = _mk_ctx(prod, lin_id, wb_id)
        with pytest.raises(RuntimeError, match="auto_grant_role"):
            grant.verify(ctx, new_id)


# ---------------------------------------------------------------------------
# Rollback on failure
# ---------------------------------------------------------------------------


class TestRollback:
    def test_db_rollback_leaves_no_membership(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod()
        try:
            grant.insert_membership(prod, lin_id, wb_id)
            raise RuntimeError("simulated post-insert failure")
        except Exception:
            prod.rollback()
        prod.expire_all()
        # No membership landed.
        assert prod.query(SpaceMembership).filter(
            SpaceMembership.user_id == lin_id,
            SpaceMembership.space_id == wb_id,
        ).count() == 0
        # Space itself is unchanged.
        space = prod.query(Space).filter(Space.id == wb_id).first()
        assert space.creator_id is None
        assert space.auto_grant_role == "creator"


# ---------------------------------------------------------------------------
# Preservation of unrelated data
# ---------------------------------------------------------------------------


class TestPreservesUnrelatedData:
    def test_other_users_and_spaces_untouched(self) -> None:
        prod, lin_id, wb_id = _make_sqlite_prod(
            include_other_user=True,
            include_other_space=True,
        )
        other_user_email = "someone.else@example.com"
        before_users = prod.query(User).count()
        before_spaces = prod.query(Space).count()
        # Also pre-insert a membership for the OTHER user on the OTHER
        # space to confirm nothing else in space_memberships shifts.
        other_user = prod.query(User).filter(
            User.email == other_user_email
        ).first()
        other_space = prod.query(Space).filter(
            Space.slug == "somewhere-else"
        ).first()
        prod.add(SpaceMembership(
            id=_uid("mem"),
            user_id=other_user.id, space_id=other_space.id,
            role=SpaceRole.moderator,
            status=SpaceMembershipStatus.active,
            source="joined",
        ))
        prod.commit()
        before_mems = prod.query(SpaceMembership).count()

        grant.insert_membership(prod, lin_id, wb_id)
        prod.commit()

        # Users + spaces counts unchanged; memberships bumped by 1.
        assert prod.query(User).count() == before_users
        assert prod.query(Space).count() == before_spaces
        assert prod.query(SpaceMembership).count() == before_mems + 1
        # Other user's membership still exactly as it was.
        other_mem = prod.query(SpaceMembership).filter(
            SpaceMembership.user_id == other_user.id,
            SpaceMembership.space_id == other_space.id,
        ).first()
        assert other_mem is not None
        assert other_mem.role == SpaceRole.moderator
        assert other_mem.source == "joined"

    def test_wb_pathways_untouched(self) -> None:
        """Sanity: WB's pathways (representing the migrated content)
        are not touched by this script even when they exist."""
        prod, lin_id, wb_id = _make_sqlite_prod()
        prod.add(Pathway(
            id=_uid("pw"), space_id=wb_id,
            slug="world-builders-start-here",
            title="🌍 World Builders - Start Here",
            status="draft", pathway_type=PathwayType.guided_experience,
            position=0,
        ))
        prod.add(Pathway(
            id=_uid("pw"), space_id=wb_id,
            slug="creating-your-collective",
            title="🏝️ Creating Your Collective",
            status="draft", pathway_type=PathwayType.guided_experience,
            position=1,
        ))
        prod.commit()
        before_pw = prod.query(Pathway).filter(
            Pathway.space_id == wb_id
        ).count()

        grant.insert_membership(prod, lin_id, wb_id)
        prod.commit()

        after_pw = prod.query(Pathway).filter(
            Pathway.space_id == wb_id
        ).count()
        assert after_pw == before_pw == 2


# ---------------------------------------------------------------------------
# main() dry-run path — no write regardless of prod state
# ---------------------------------------------------------------------------


class TestModuleImportsCleanly:
    def test_parse_args_defaults_to_dry_run(self) -> None:
        args = grant.parse_args([])
        assert args.commit is False
        assert args.yes_i_am_sure is False

    def test_parse_args_commit_flag(self) -> None:
        args = grant.parse_args(["--commit"])
        assert args.commit is True
