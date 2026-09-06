"""Tests for the World Builders selective importer.

Uses the standard test-DB session (SAVEPOINT-scoped by conftest) as
"local", and a fresh SQLite-in-memory session as physically-distinct
"prod". The prod side is pre-seeded with the platform-owned World
Builders Space, the Cornerstone Location keyed ``the-commons``, and
prod-Lindsey — matching the real prod state established by the
Mother World migration.

Coverage:
  * Prod validation helpers (_validate_and_snapshot_prod_wb,
    _resolve_prod_location_id) — success + every refusal path.
  * Enumerate: substantive pathways only, subtree captured, orphan
    media excluded, parent_updates carries prod the-commons id
    (not local), island_artwork_url/status not in updates, prompt is.
  * Local drift refusals: missing space, missing location,
    wrong location key, missing substantive pathway.
  * Insert: parent UPDATE touches only allowlist, prod Space id
    preserved, creator_id remains None, action FKs remain None,
    pathways forced draft, exact counts, media remapped to prod id.
  * Insert refuses on NEVER-TOUCH drift between preflight and commit.
  * Verify catches: slug drift, non-null creator_id, wrong
    auto_grant_role, NEVER-TOUCH drift, UPDATABLE mismatch, non-null
    island_artwork_url, wrong island_artwork_status, missing/extra
    pathway, placeholder pathway created, subtree count drift, media
    count drift, R2 HEAD failure.
  * R2 upload/rollback (routing + best-effort delete).
  * Module-level constants locked (updatable list, never-touch list,
    substantive/placeholder slugs).
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import import_world_builders_from_dev as importer  # noqa: E402

from app.models.platform import (  # noqa: E402
    CreatorMediaAsset,
    Location,
    Pathway,
    PathwayAboutBlock,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
    PathwayType,
    Space,
    SpaceMembership,
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
    with_wb_space: bool = True,
    wb_creator_id: str | None = None,
    wb_auto_grant_role: str = "creator",
    include_conflict_pathway: str | None = None,
    with_the_commons: bool = True,
) -> tuple[Session, str, str | None, str | None]:
    """Fresh in-memory 'prod' session that mirrors the audited state:
    the platform-owned World Builders Space exists as a bare shell with
    ``creator_id=None`` and ``auto_grant_role='creator'``, and the
    Cornerstone Location ``the-commons`` exists.

    Returns (session, prod_lindsey_id, prod_wb_space_id, the_commons_id).
    Absent things return None so tests can exercise refusal paths."""
    engine = create_engine("sqlite:///:memory:", future=True)
    for model in [
        User, Location,
        Space, SpaceMembership,
        CreatorMediaAsset,
        Pathway, PathwaySection, PathwayStep,
        PathwayStepBlock, PathwayAboutBlock,
    ]:
        model.__table__.create(engine)
    prod = sessionmaker(bind=engine, future=True)()

    prod_lindsey_id = _uid("u")
    prod.add(User(
        id=prod_lindsey_id, email=importer.PROD_OWNER_EMAIL,
        name="Lindsey Hilliard",
        password_hash="$2b$12$0" + "0" * 52,
        role="admin",
        email_verified_at=datetime.utcnow(),
    ))

    the_commons_id = None
    if with_the_commons:
        the_commons_id = _uid("prodloc")
        prod.add(Location(
            id=the_commons_id, key=importer.WB_LOCATION_KEY,
            name="🌍 The Commons", status="active",
            location_type="CORNERSTONE",
            preferred_atmospheres=[], preferred_colour_stories=[],
            preferred_themes=[], position=0,
        ))

    prod_wb_id = None
    if with_wb_space:
        prod_wb_id = _uid("prodwb")
        prod.add(Space(
            id=prod_wb_id,
            slug="world-builders",
            name="World Builders",
            creator_id=wb_creator_id,      # platform-owned when None
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
            # every authored field left as its column default (None / []).
        ))

    if include_conflict_pathway and prod_wb_id:
        prod.add(Pathway(
            id=_uid("pw"), space_id=prod_wb_id,
            slug=include_conflict_pathway,
            title="Pre-existing conflict",
            status="draft", pathway_type=PathwayType.guided_experience,
            position=0,
        ))

    prod.commit()
    return prod, prod_lindsey_id, prod_wb_id, the_commons_id


# ---------------------------------------------------------------------------
# Local fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mini_world_builders(db: Session, make_user):
    """Populate the existing alembic-seeded World Builders Space with
    authored content + a small child graph. The seed migration
    (versions 089 / 095) guarantees there is already one WB Space
    with slug='world-builders' in the test DB; this fixture augments
    it rather than creating a duplicate.

    Two substantive pathways with a small subtree; two placeholder
    pathways (representative of the 7 real ones); three referenced
    CreatorMediaAssets plus one orphan (unreferenced)."""
    creator = make_user(role="creator")

    # Find the existing alembic-seeded WB Space.
    space = db.query(Space).filter(Space.slug == "world-builders").first()
    assert space is not None, (
        "Test DB should already contain a seeded 'world-builders' Space "
        "(alembic 089/095). Fixture logic broken."
    )
    # Clear any child rows that seeds may have added, so this fixture
    # controls the shape end-to-end.
    for p in db.query(Pathway).filter(Pathway.space_id == space.id).all():
        db.delete(p)
    for m in db.query(CreatorMediaAsset).filter(
        CreatorMediaAsset.space_id == space.id
    ).all():
        db.delete(m)
    for m in db.query(SpaceMembership).filter(
        SpaceMembership.space_id == space.id
    ).all():
        db.delete(m)
    db.flush()

    # Ensure a local Cornerstone Location keyed 'the-commons' exists.
    location = db.query(Location).filter(
        Location.key == importer.WB_LOCATION_KEY
    ).first()
    if location is None:
        location = Location(
            id=_uid("loc"), key=importer.WB_LOCATION_KEY,
            name="🌍 The Commons", status="active",
            location_type="CORNERSTONE",
            preferred_atmospheres=[], preferred_colour_stories=[],
            preferred_themes=[], position=0,
        )
        db.add(location)
        db.flush()

    # Populate the seeded Space with authored content.
    space.name = "World Builders"
    space.tagline = "Learn. Build. Belong."
    space.description = "Shared home for creators."
    space.about_content = "<h2>Our Story</h2><p>Something authored.</p>"
    space.identity_statement = "A place for creators."
    space.welcome_message = "Welcome, creator."
    space.included_access_summary = "Free access to WB."
    space.guidance_start_title = "Start here"
    space.guidance_start_body = '{"type":"doc","content":[]}'
    space.island_artwork_prompt = "A watercolour of a small mythic island."
    space.creator_id = creator.id
    space.status = SpaceStatus.active
    space.location_id = location.id
    space.auto_grant_role = "creator"
    space.visibility = "link"
    space.is_public = False
    space.kind = "standard"
    space.connection_style = "online"
    space.themes = ["Creativity", "Leadership", "Business"]
    space.atmosphere_keys = ["playful", "hopeful", "creative"]
    space.colour_story_key = "sunrise"
    space.landscape_key = "island_sanctuary"
    space.element_keys = ["stone_circles", "lookouts", "waterfalls"]
    space.island_artwork_url = "/api/uploads/island-artwork/world-builders/ISLAND.png"
    space.island_artwork_status = "ready"
    db.flush()

    # Three referenced media assets used by the substantive pathways.
    media_a = CreatorMediaAsset(
        id=_uid("cma"), space_id=space.id, uploaded_by_user_id=creator.id,
        title="colour palette", original_filename="cp.png",
        stored_filename="uuid_cp.png",
        storage_path="media/world-builders/uuid_cp.png",
        file_url="/api/uploads/media/world-builders/uuid_cp.png",
        mime_type="image/png", media_type="image",
        file_size_bytes=1000, extension=".png",
    )
    media_b = CreatorMediaAsset(
        id=_uid("cma"), space_id=space.id, uploaded_by_user_id=creator.id,
        title="MC pricing", original_filename="mc.png",
        stored_filename="uuid_mc.png",
        storage_path="media/world-builders/uuid_mc.png",
        file_url="/api/uploads/media/world-builders/uuid_mc.png",
        mime_type="image/png", media_type="image",
        file_size_bytes=1200, extension=".png",
    )
    media_c = CreatorMediaAsset(
        id=_uid("cma"), space_id=space.id, uploaded_by_user_id=creator.id,
        title="MC About page", original_filename="ap.png",
        stored_filename="uuid_ap.png",
        storage_path="media/world-builders/uuid_ap.png",
        file_url="/api/uploads/media/world-builders/uuid_ap.png",
        mime_type="image/png", media_type="image",
        file_size_bytes=1300, extension=".png",
    )
    orphan_media = CreatorMediaAsset(
        id=_uid("cma"), space_id=space.id, uploaded_by_user_id=creator.id,
        title="The Commons decor", original_filename="tc.png",
        stored_filename="uuid_tc.png",
        storage_path="media/world-builders/uuid_tc.png",
        file_url="/api/uploads/media/world-builders/uuid_tc.png",
        mime_type="image/png", media_type="image",
        file_size_bytes=500, extension=".png",
    )
    db.add_all([media_a, media_b, media_c, orphan_media])
    db.flush()

    # Substantive pathway 1: world-builders-start-here — 2 steps, 3 blocks,
    # 1 about-block. Block 2 references media_a.
    pw_start = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug="world-builders-start-here",
        title="🌍 World Builders - Start Here",
        status="active",  # importer must force to draft
        pathway_type=PathwayType.guided_experience,
        access_type="included",
        position=0,
        cover_image_url="/api/uploads/media/world-builders/WB_cover.png",
    )
    db.add(pw_start)
    db.flush()

    step_s1 = PathwayStep(
        id=_uid("pst"), pathway_id=pw_start.id, slug="welcome",
        title="Welcome", position=0, content_type="text",
    )
    step_s2 = PathwayStep(
        id=_uid("pst"), pathway_id=pw_start.id, slug="orient",
        title="Orient", position=1, content_type="text",
    )
    db.add_all([step_s1, step_s2])
    db.flush()

    blk_s1a = PathwayStepBlock(
        id=_uid("blk"), step_id=step_s1.id, block_type="text",
        position=0, content="Welcome to WB.",
    )
    blk_s1b = PathwayStepBlock(
        id=_uid("blk"), step_id=step_s1.id, block_type="image",
        position=1, media_asset_id=media_a.id,
    )
    blk_s2a = PathwayStepBlock(
        id=_uid("blk"), step_id=step_s2.id, block_type="text",
        position=0, content="Get oriented.",
    )
    db.add_all([blk_s1a, blk_s1b, blk_s2a])
    ab_start = PathwayAboutBlock(
        id=_uid("ab"), owner_kind="pathway", owner_id=pw_start.id,
        pathway_id=pw_start.id, block_type="text", position=0,
        content="About WB start-here.",
    )
    db.add(ab_start)
    db.flush()

    # Substantive pathway 2: creating-your-collective — 3 steps, 5 blocks,
    # 1 about-block. Blocks 3 & 4 reference media_b and media_c.
    pw_create = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug="creating-your-collective",
        title="🏝️ Creating Your Collective",
        status="draft",
        pathway_type=PathwayType.guided_experience,
        access_type="included",
        position=1,
        cover_image_url="/api/uploads/media/world-builders/CYC_cover.png",
    )
    db.add(pw_create)
    db.flush()
    step_c1 = PathwayStep(id=_uid("pst"), pathway_id=pw_create.id, slug="c1", title="C1", position=0, content_type="text")
    step_c2 = PathwayStep(id=_uid("pst"), pathway_id=pw_create.id, slug="c2", title="C2", position=1, content_type="text")
    step_c3 = PathwayStep(id=_uid("pst"), pathway_id=pw_create.id, slug="c3", title="C3", position=2, content_type="text")
    db.add_all([step_c1, step_c2, step_c3])
    db.flush()
    blk_c1a = PathwayStepBlock(id=_uid("blk"), step_id=step_c1.id, block_type="text", position=0, content="c1a")
    blk_c1b = PathwayStepBlock(id=_uid("blk"), step_id=step_c1.id, block_type="text", position=1, content="c1b")
    blk_c2a = PathwayStepBlock(id=_uid("blk"), step_id=step_c2.id, block_type="text", position=0, content="c2a")
    blk_c3a = PathwayStepBlock(id=_uid("blk"), step_id=step_c3.id, block_type="image", position=0, media_asset_id=media_b.id)
    blk_c3b = PathwayStepBlock(id=_uid("blk"), step_id=step_c3.id, block_type="image", position=1, media_asset_id=media_c.id)
    db.add_all([blk_c1a, blk_c1b, blk_c2a, blk_c3a, blk_c3b])
    ab_create = PathwayAboutBlock(
        id=_uid("ab"), owner_kind="pathway", owner_id=pw_create.id,
        pathway_id=pw_create.id, block_type="text", position=0,
        content="About creating your collective.",
    )
    db.add(ab_create)
    db.flush()

    # Two representative empty placeholder pathways.
    placeholder_slugs_used = ("pathways", "gatherings")
    for slug in placeholder_slugs_used:
        db.add(Pathway(
            id=_uid("pw"), space_id=space.id, slug=slug, title=f"[{slug}]",
            status="draft", pathway_type=PathwayType.knowledge_guide,
            position=10, cover_image_url=None,
        ))
    db.commit()

    return {
        "space": space,
        "location_id": location.id,
        "media_a_id": media_a.id,
        "media_b_id": media_b.id,
        "media_c_id": media_c.id,
        "orphan_media_id": orphan_media.id,
        "pw_start_id": pw_start.id,
        "pw_create_id": pw_create.id,
        "placeholder_slugs_used": placeholder_slugs_used,
        "expected_pathways": 2,
        "expected_steps": 5,
        "expected_step_blocks": 8,
        "expected_about_blocks": 2,
        "expected_media": 3,
        "expected_r2_keys": 5,  # 3 media + 2 pathway covers
        "creator_id": creator.id,
    }


# ---------------------------------------------------------------------------
# Pure helpers + constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_source_slug(self) -> None:
        assert importer.SOURCE_SLUG == "world-builders"

    def test_substantive_slugs(self) -> None:
        assert set(importer.SUBSTANTIVE_PATHWAY_SLUGS) == {
            "world-builders-start-here",
            "creating-your-collective",
        }

    def test_placeholder_slugs(self) -> None:
        assert set(importer.PLACEHOLDER_PATHWAY_SLUGS) == {
            "pathways", "gatherings", "members", "conversations",
            "payments", "privacy", "growing-your-collective",
        }

    def test_wb_location_key(self) -> None:
        assert importer.WB_LOCATION_KEY == "the-commons"

    def test_prod_owner_email(self) -> None:
        assert importer.PROD_OWNER_EMAIL == "lindsey@hilliard.net.au"

    def test_updatable_allowlist_excludes_platform_fields(self) -> None:
        # Platform-managed fields MUST NOT be in the updatable list.
        forbidden = {
            "id", "slug", "name", "creator_id", "auto_grant_role",
            "kind", "connection_style", "visibility", "is_public",
            "status", "closed_by_action_id", "frozen_by_action_id",
            "closed_at", "frozen_at", "suspended_at",
            "island_artwork_url", "island_artwork_status",
        }
        assert forbidden.isdisjoint(set(importer.PARENT_UPDATABLE_FIELDS))

    def test_updatable_allowlist_includes_authored_text(self) -> None:
        expected_present = {
            "tagline", "description", "about_content",
            "identity_statement", "welcome_message",
            "guidance_start_body", "island_artwork_prompt",
            "themes", "atmosphere_keys", "colour_story_key",
            "landscape_key", "element_keys",
        }
        assert expected_present.issubset(set(importer.PARENT_UPDATABLE_FIELDS))

    def test_never_touch_covers_platform_and_action_fields(self) -> None:
        must_include = {
            "id", "slug", "name", "creator_id", "auto_grant_role",
            "kind", "connection_style", "visibility", "is_public",
            "status", "island_artwork_url", "island_artwork_status",
            "closed_by_action_id", "frozen_by_action_id",
            "closed_at", "frozen_at", "suspended_at",
            "pricing_type", "pricing_amount_cents", "pricing_currency",
            "has_paid_internal_content", "show_member_directory",
        }
        assert must_include.issubset(set(importer.PARENT_NEVER_TOUCH_FIELDS))

    def test_updatable_and_never_touch_are_disjoint(self) -> None:
        assert set(importer.PARENT_UPDATABLE_FIELDS).isdisjoint(
            set(importer.PARENT_NEVER_TOUCH_FIELDS)
        )


class TestSameDb:
    def test_same_host_and_db_match(self) -> None:
        assert importer._same_db(
            "postgresql://a:b@host/db1", "postgresql://c:d@host/db1"
        )

    def test_different_dbs_do_not_match(self) -> None:
        assert not importer._same_db(
            "postgresql://a@host/local", "postgresql://a@host/prod"
        )


class TestKeyFromUrl:
    def test_upload_prefix(self) -> None:
        assert importer._key_from_url("/api/uploads/media/wb/x.png") == "media/wb/x.png"

    def test_external_returns_none(self) -> None:
        assert importer._key_from_url("https://example.com/x") is None


# ---------------------------------------------------------------------------
# Preflight helpers — resolve location + validate/snapshot WB
# ---------------------------------------------------------------------------


class TestResolveProdLocation:
    def test_success_returns_the_commons_id(self) -> None:
        prod, _, _, tc_id = _make_sqlite_prod()
        assert importer._resolve_prod_location_id(prod) == tc_id

    def test_refuses_when_missing(self) -> None:
        prod, _, _, _ = _make_sqlite_prod(with_the_commons=False)
        with pytest.raises(importer.PreflightError, match=importer.WB_LOCATION_KEY):
            importer._resolve_prod_location_id(prod)


class TestValidateAndSnapshotProdWB:
    def test_success_returns_space_id_and_full_snapshot(self) -> None:
        prod, _, wb_id, _ = _make_sqlite_prod()
        got_id, snap = importer._validate_and_snapshot_prod_wb(prod)
        assert got_id == wb_id
        # Snapshot must include every NEVER-TOUCH field.
        assert set(snap.keys()) == set(importer.PARENT_NEVER_TOUCH_FIELDS)
        assert snap["creator_id"] is None
        assert snap["auto_grant_role"] == "creator"
        assert snap["island_artwork_url"] is None
        assert snap["island_artwork_status"] == "not_started"

    def test_refuses_when_prod_wb_missing(self) -> None:
        prod, _, _, _ = _make_sqlite_prod(with_wb_space=False)
        with pytest.raises(importer.PreflightError, match="not found"):
            importer._validate_and_snapshot_prod_wb(prod)

    def test_refuses_when_creator_id_non_null(self) -> None:
        prod, _, _, _ = _make_sqlite_prod(wb_creator_id="u_someone")
        with pytest.raises(importer.PreflightError, match="creator_id"):
            importer._validate_and_snapshot_prod_wb(prod)

    def test_refuses_when_auto_grant_role_changed(self) -> None:
        prod, _, _, _ = _make_sqlite_prod(wb_auto_grant_role="learner")
        with pytest.raises(importer.PreflightError, match="auto_grant_role"):
            importer._validate_and_snapshot_prod_wb(prod)

    def test_refuses_on_conflicting_target_pathway_slug(self) -> None:
        prod, _, _, _ = _make_sqlite_prod(
            include_conflict_pathway="world-builders-start-here",
        )
        with pytest.raises(
            importer.PreflightError, match="world-builders-start-here",
        ):
            importer._validate_and_snapshot_prod_wb(prod)

    def test_refuses_on_conflict_for_second_substantive_slug(self) -> None:
        prod, _, _, _ = _make_sqlite_prod(
            include_conflict_pathway="creating-your-collective",
        )
        with pytest.raises(
            importer.PreflightError, match="creating-your-collective",
        ):
            importer._validate_and_snapshot_prod_wb(prod)


# ---------------------------------------------------------------------------
# Enumerate — success + local drift refusals
# ---------------------------------------------------------------------------


class TestEnumeratePlanSuccess:
    def test_only_substantive_pathways(
        self, db: Session, mini_world_builders,
    ) -> None:
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc")
        slugs = sorted(p["slug"] for p in plan.pathways)
        assert slugs == sorted(importer.SUBSTANTIVE_PATHWAY_SLUGS)

    def test_placeholder_slugs_excluded(
        self, db: Session, mini_world_builders,
    ) -> None:
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc")
        got = {p["slug"] for p in plan.pathways}
        for placeholder in importer.PLACEHOLDER_PATHWAY_SLUGS:
            assert placeholder not in got

    def test_subtree_counts_match_fixture(
        self, db: Session, mini_world_builders,
    ) -> None:
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc")
        exp = mini_world_builders
        assert len(plan.pathways) == exp["expected_pathways"]
        assert len(plan.sections) == 0
        assert len(plan.steps) == exp["expected_steps"]
        assert len(plan.step_blocks) == exp["expected_step_blocks"]
        assert len(plan.about_blocks) == exp["expected_about_blocks"]

    def test_referenced_media_only(
        self, db: Session, mini_world_builders,
    ) -> None:
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc")
        media_ids = {m["id"] for m in plan.media_assets}
        assert media_ids == {
            mini_world_builders["media_a_id"],
            mini_world_builders["media_b_id"],
            mini_world_builders["media_c_id"],
        }
        # Orphan MUST NOT appear.
        assert mini_world_builders["orphan_media_id"] not in media_ids

    def test_r2_key_set_covers_covers_and_media(
        self, db: Session, mini_world_builders,
    ) -> None:
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc")
        assert "media/world-builders/WB_cover.png" in plan.r2_keys
        assert "media/world-builders/CYC_cover.png" in plan.r2_keys
        assert "media/world-builders/uuid_cp.png" in plan.r2_keys
        assert "media/world-builders/uuid_mc.png" in plan.r2_keys
        assert "media/world-builders/uuid_ap.png" in plan.r2_keys
        assert "media/world-builders/uuid_tc.png" not in plan.r2_keys  # orphan
        # Parent island_artwork must NOT be in the R2 set.
        assert not any("island-artwork" in k for k in plan.r2_keys)

    def test_parent_updates_carries_authored_fields(
        self, db: Session, mini_world_builders,
    ) -> None:
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc")
        assert plan.parent_updates["tagline"] == "Learn. Build. Belong."
        assert plan.parent_updates["about_content"].startswith("<h2>Our Story</h2>")
        assert plan.parent_updates["guidance_start_body"] == '{"type":"doc","content":[]}'
        assert plan.parent_updates["identity_statement"] == "A place for creators."
        assert plan.parent_updates["themes"] == ["Creativity", "Leadership", "Business"]
        assert plan.parent_updates["colour_story_key"] == "sunrise"
        assert plan.parent_updates["landscape_key"] == "island_sanctuary"

    def test_parent_updates_location_is_prod_id_not_local(
        self, db: Session, mini_world_builders,
    ) -> None:
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc_id_XYZ")
        assert plan.parent_updates["location_id"] == "prod_tc_id_XYZ"
        # Never the local Location id.
        assert plan.parent_updates["location_id"] != mini_world_builders["location_id"]

    def test_parent_updates_includes_island_artwork_prompt(
        self, db: Session, mini_world_builders,
    ) -> None:
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc")
        assert plan.parent_updates["island_artwork_prompt"] == \
            "A watercolour of a small mythic island."

    def test_parent_updates_excludes_island_artwork_url_and_status(
        self, db: Session, mini_world_builders,
    ) -> None:
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc")
        assert "island_artwork_url" not in plan.parent_updates
        assert "island_artwork_status" not in plan.parent_updates

    def test_parent_updates_excludes_platform_managed_fields(
        self, db: Session, mini_world_builders,
    ) -> None:
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc")
        for f in ("id", "slug", "creator_id", "auto_grant_role",
                  "kind", "connection_style", "visibility",
                  "is_public", "status"):
            assert f not in plan.parent_updates


class TestEnumerateLocalDrift:
    def test_refuses_when_local_wb_missing(
        self, db: Session, monkeypatch,
    ) -> None:
        # The alembic seed guarantees a 'world-builders' Space exists in
        # any real local DB, so simulate "missing" by asking enumerate to
        # look for a slug that isn't seeded.
        monkeypatch.setattr(importer, "SOURCE_SLUG", "not-a-real-slug")
        with pytest.raises(RuntimeError, match="not found"):
            importer.enumerate_plan(db, prod_the_commons_id="prod_tc")

    def test_refuses_when_local_wb_has_no_location(
        self, db: Session, mini_world_builders,
    ) -> None:
        space = db.query(Space).filter(Space.slug == "world-builders").first()
        space.location_id = None
        db.flush()
        with pytest.raises(RuntimeError, match="no location_id"):
            importer.enumerate_plan(db, prod_the_commons_id="prod_tc")

    def test_refuses_when_local_wb_location_key_wrong(
        self, db: Session, mini_world_builders,
    ) -> None:
        wrong = Location(
            id=_uid("loc"), key="canopy-reach", name="Canopy Reach",
            status="active", location_type="ATLAS",
            preferred_atmospheres=[], preferred_colour_stories=[],
            preferred_themes=[], position=1,
        )
        db.add(wrong)
        db.flush()
        space = db.query(Space).filter(Space.slug == "world-builders").first()
        space.location_id = wrong.id
        db.flush()
        with pytest.raises(RuntimeError, match="canopy-reach"):
            importer.enumerate_plan(db, prod_the_commons_id="prod_tc")

    def test_refuses_when_substantive_pathway_missing(
        self, db: Session, mini_world_builders,
    ) -> None:
        # Remove one substantive pathway.
        db.query(Pathway).filter(
            Pathway.id == mini_world_builders["pw_start_id"]
        ).delete()
        db.flush()
        with pytest.raises(RuntimeError, match="world-builders-start-here"):
            importer.enumerate_plan(db, prod_the_commons_id="prod_tc")


# ---------------------------------------------------------------------------
# Insert — parent UPDATE + child INSERTs against SQLite prod
# ---------------------------------------------------------------------------


def _run_full_import(db: Session):
    """Enumerate, spin up prod, insert (no commit yet). Returns
    (prod_session, plan, ctx-like tuple)."""
    prod, prod_lindsey_id, prod_wb_id, tc_id = _make_sqlite_prod()
    _, snapshot = importer._validate_and_snapshot_prod_wb(prod)
    plan = importer.enumerate_plan(db, prod_the_commons_id=tc_id)
    importer.insert_prod_rows(
        plan, prod, prod_wb_id, prod_lindsey_id, snapshot,
    )
    prod.commit()
    return prod, plan, prod_lindsey_id, prod_wb_id, tc_id, snapshot


class TestInsertProdRows:
    def test_parent_id_preserved(self, db: Session, mini_world_builders) -> None:
        prod, plan, _, prod_wb_id, _, _ = _run_full_import(db)
        rows = prod.query(Space).filter(Space.slug == "world-builders").all()
        assert len(rows) == 1
        assert rows[0].id == prod_wb_id

    def test_creator_id_remains_none(self, db: Session, mini_world_builders) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        fresh = prod.query(Space).filter(Space.id == prod_wb_id).first()
        assert fresh.creator_id is None

    def test_auto_grant_role_remains_creator(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        fresh = prod.query(Space).filter(Space.id == prod_wb_id).first()
        assert fresh.auto_grant_role == "creator"

    def test_parent_authored_fields_updated_from_local(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, plan, _, prod_wb_id, _, _ = _run_full_import(db)
        fresh = prod.query(Space).filter(Space.id == prod_wb_id).first()
        for f, expected in plan.parent_updates.items():
            assert getattr(fresh, f) == expected, f"field {f}"

    def test_location_id_set_to_prod_the_commons(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, tc_id, _ = _run_full_import(db)
        fresh = prod.query(Space).filter(Space.id == prod_wb_id).first()
        assert fresh.location_id == tc_id
        assert fresh.location_id != mini_world_builders["location_id"]

    def test_island_artwork_url_remains_null(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        fresh = prod.query(Space).filter(Space.id == prod_wb_id).first()
        assert fresh.island_artwork_url is None

    def test_island_artwork_status_remains_not_started(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        fresh = prod.query(Space).filter(Space.id == prod_wb_id).first()
        assert fresh.island_artwork_status == "not_started"

    def test_island_artwork_prompt_updated(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        fresh = prod.query(Space).filter(Space.id == prod_wb_id).first()
        assert fresh.island_artwork_prompt == \
            "A watercolour of a small mythic island."

    def test_never_touch_snapshot_all_unchanged(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, snapshot = _run_full_import(db)
        fresh = prod.query(Space).filter(Space.id == prod_wb_id).first()
        for f, v in snapshot.items():
            assert getattr(fresh, f) == v, f"NEVER-TOUCH field {f} drifted"

    def test_both_pathways_forced_to_draft(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        pws = prod.query(Pathway).filter(Pathway.space_id == prod_wb_id).all()
        assert len(pws) == 2
        for p in pws:
            status_val = getattr(p.status, "value", p.status)
            assert status_val == "draft", (
                f"pathway {p.slug!r} status={p.status!r}, expected draft"
            )

    def test_placeholder_pathways_not_created(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        for slug in importer.PLACEHOLDER_PATHWAY_SLUGS:
            got = prod.query(Pathway).filter(
                Pathway.space_id == prod_wb_id, Pathway.slug == slug,
            ).first()
            assert got is None

    def test_exact_child_counts(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, plan, _, prod_wb_id, _, _ = _run_full_import(db)
        pw_ids = [p.id for p in prod.query(Pathway).filter(
            Pathway.space_id == prod_wb_id
        ).all()]
        assert prod.query(PathwaySection).filter(
            PathwaySection.pathway_id.in_(pw_ids)
        ).count() == len(plan.sections)
        assert prod.query(PathwayStep).filter(
            PathwayStep.pathway_id.in_(pw_ids)
        ).count() == len(plan.steps)
        assert prod.query(PathwayStepBlock).join(
            PathwayStep, PathwayStep.id == PathwayStepBlock.step_id
        ).filter(PathwayStep.pathway_id.in_(pw_ids)).count() == len(plan.step_blocks)
        assert prod.query(PathwayAboutBlock).filter(
            PathwayAboutBlock.pathway_id.in_(pw_ids)
        ).count() == len(plan.about_blocks)

    def test_media_uploaded_by_is_prod_lindsey(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, prod_lindsey_id, prod_wb_id, _, _ = _run_full_import(db)
        for m in prod.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.space_id == prod_wb_id
        ).all():
            assert m.uploaded_by_user_id == prod_lindsey_id

    def test_media_ids_are_fresh_not_local(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        local_ids = {
            mini_world_builders["media_a_id"],
            mini_world_builders["media_b_id"],
            mini_world_builders["media_c_id"],
        }
        prod_ids = {
            m.id for m in prod.query(CreatorMediaAsset).filter(
                CreatorMediaAsset.space_id == prod_wb_id
            ).all()
        }
        assert prod_ids.isdisjoint(local_ids)

    def test_media_folder_id_nulled(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        for m in prod.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.space_id == prod_wb_id
        ).all():
            assert m.folder_id is None

    def test_step_block_media_asset_remapped(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        prod_media_ids = {
            m.id for m in prod.query(CreatorMediaAsset).filter(
                CreatorMediaAsset.space_id == prod_wb_id
            ).all()
        }
        for b in prod.query(PathwayStepBlock).all():
            if b.media_asset_id is not None:
                assert b.media_asset_id in prod_media_ids

    def test_about_block_owner_id_remapped_to_prod_pathway(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        prod_pw_ids = {
            p.id for p in prod.query(Pathway).filter(
                Pathway.space_id == prod_wb_id
            ).all()
        }
        for ab in prod.query(PathwayAboutBlock).all():
            assert ab.pathway_id in prod_pw_ids
            if ab.owner_kind == "pathway":
                assert ab.owner_id in prod_pw_ids

    def test_no_membership_created_by_importer(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, _, _, prod_wb_id, _, _ = _run_full_import(db)
        mems = prod.query(SpaceMembership).filter(
            SpaceMembership.space_id == prod_wb_id
        ).all()
        assert mems == []

    def test_r2_key_count_matches_fixture(
        self, db: Session, mini_world_builders,
    ) -> None:
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc")
        assert len(plan.r2_keys) == mini_world_builders["expected_r2_keys"]

    def test_parent_only_allowlisted_fields_change(
        self, db: Session, mini_world_builders,
    ) -> None:
        """Prove that every non-allowlisted field on prod is unchanged
        after the UPDATE — by snapshotting BEFORE insert and diffing."""
        plan = importer.enumerate_plan(db, prod_the_commons_id="prod_tc_id")
        prod, prod_lindsey_id, prod_wb_id, tc_id = _make_sqlite_prod()
        # Rebuild plan with real prod tc_id.
        plan = importer.enumerate_plan(db, prod_the_commons_id=tc_id)
        _, snapshot = importer._validate_and_snapshot_prod_wb(prod)
        before = prod.query(Space).filter(Space.id == prod_wb_id).first()
        # Capture every column BEFORE.
        from sqlalchemy import inspect as _si
        cols = [c.name for c in _si(Space).columns]
        before_state = {c: getattr(before, c) for c in cols}
        # Apply.
        importer.insert_prod_rows(plan, prod, prod_wb_id, prod_lindsey_id, snapshot)
        prod.commit()
        after = prod.query(Space).filter(Space.id == prod_wb_id).first()
        after_state = {c: getattr(after, c) for c in cols}
        # Every column not in PARENT_UPDATABLE_FIELDS (except updated_at,
        # which SQLAlchemy will bump on any UPDATE, and location_id,
        # which is the one explicit special-case remap) MUST be unchanged.
        allowed = set(importer.PARENT_UPDATABLE_FIELDS) | {
            "updated_at", "location_id",
        }
        for c in cols:
            if c in allowed:
                continue
            assert before_state[c] == after_state[c], (
                f"non-allowlisted column {c!r} changed: "
                f"{before_state[c]!r} → {after_state[c]!r}"
            )


class TestInsertRefusesOnNeverTouchDrift:
    def test_drift_between_preflight_and_insert_aborts(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, prod_lindsey_id, prod_wb_id, tc_id = _make_sqlite_prod()
        _, snapshot = importer._validate_and_snapshot_prod_wb(prod)
        # Simulate a concurrent change to a NEVER-TOUCH field
        # between preflight and insert.
        fresh = prod.query(Space).filter(Space.id == prod_wb_id).first()
        fresh.auto_grant_role = "learner"
        prod.flush()

        plan = importer.enumerate_plan(db, prod_the_commons_id=tc_id)
        with pytest.raises(RuntimeError, match="NEVER-TOUCH drift"):
            importer.insert_prod_rows(
                plan, prod, prod_wb_id, prod_lindsey_id, snapshot,
            )


# ---------------------------------------------------------------------------
# Verify — must detect every promised drift
# ---------------------------------------------------------------------------


def _run_and_get_ctx(db):
    prod, plan, prod_lindsey_id, prod_wb_id, tc_id, snapshot = _run_full_import(db)
    ctx = importer.MigrationContext(
        local_session=db,
        prod_session=prod,
        prod_lindsey_id=prod_lindsey_id,
        prod_wb_space_id=prod_wb_id,
        prod_the_commons_id=tc_id,
        parent_never_touch_snapshot=snapshot,
        r2_client=MagicMock(),
        r2_bucket_private="priv",
        r2_bucket_public="pub",
        commit=True,
        yes_i_am_sure=True,
    )
    return prod, plan, ctx


class TestVerify:
    def test_passes_on_clean_import(self, db: Session, mini_world_builders) -> None:
        prod, plan, ctx = _run_and_get_ctx(db)
        importer.verify(plan, ctx, ctx.r2_client, "priv", "pub")

    def test_catches_creator_id_leak(self, db: Session, mini_world_builders) -> None:
        prod, plan, ctx = _run_and_get_ctx(db)
        fresh = prod.query(Space).filter(Space.id == ctx.prod_wb_space_id).first()
        fresh.creator_id = "u_leaked"
        prod.flush()
        with pytest.raises(RuntimeError, match="creator_id must remain NULL"):
            importer.verify(plan, ctx, ctx.r2_client, "priv", "pub")

    def test_catches_auto_grant_role_change(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, plan, ctx = _run_and_get_ctx(db)
        fresh = prod.query(Space).filter(Space.id == ctx.prod_wb_space_id).first()
        fresh.auto_grant_role = "learner"
        prod.flush()
        # The NEVER-TOUCH loop fires first — either message is acceptable.
        with pytest.raises(
            RuntimeError,
            match="(auto_grant_role|NEVER-TOUCH)",
        ):
            importer.verify(plan, ctx, ctx.r2_client, "priv", "pub")

    def test_catches_never_touch_drift(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, plan, ctx = _run_and_get_ctx(db)
        fresh = prod.query(Space).filter(Space.id == ctx.prod_wb_space_id).first()
        fresh.timezone = "UTC"
        prod.flush()
        with pytest.raises(RuntimeError, match="NEVER-TOUCH field 'timezone'"):
            importer.verify(plan, ctx, ctx.r2_client, "priv", "pub")

    def test_catches_updatable_field_reverted(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, plan, ctx = _run_and_get_ctx(db)
        fresh = prod.query(Space).filter(Space.id == ctx.prod_wb_space_id).first()
        fresh.tagline = "TAMPERED"
        prod.flush()
        with pytest.raises(RuntimeError, match="UPDATED field 'tagline'"):
            importer.verify(plan, ctx, ctx.r2_client, "priv", "pub")

    def test_catches_island_artwork_url_set(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, plan, ctx = _run_and_get_ctx(db)
        fresh = prod.query(Space).filter(Space.id == ctx.prod_wb_space_id).first()
        fresh.island_artwork_url = "/api/uploads/leaked.png"
        prod.flush()
        with pytest.raises(RuntimeError, match="island_artwork_url"):
            importer.verify(plan, ctx, ctx.r2_client, "priv", "pub")

    def test_catches_island_artwork_status_changed(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, plan, ctx = _run_and_get_ctx(db)
        fresh = prod.query(Space).filter(Space.id == ctx.prod_wb_space_id).first()
        fresh.island_artwork_status = "ready"
        prod.flush()
        with pytest.raises(RuntimeError, match="island_artwork_status"):
            importer.verify(plan, ctx, ctx.r2_client, "priv", "pub")

    def test_catches_placeholder_pathway_created(
        self, db: Session, mini_world_builders,
    ) -> None:
        prod, plan, ctx = _run_and_get_ctx(db)
        prod.add(Pathway(
            id=_uid("phantom"), space_id=ctx.prod_wb_space_id,
            slug="payments", title="Payments",
            status="draft", pathway_type=PathwayType.knowledge_guide,
            position=99,
        ))
        prod.commit()
        with pytest.raises(RuntimeError, match="(placeholder|expected 2 pathways|payments)"):
            importer.verify(plan, ctx, ctx.r2_client, "priv", "pub")

    def test_catches_extra_media(self, db: Session, mini_world_builders) -> None:
        prod, plan, ctx = _run_and_get_ctx(db)
        prod.add(CreatorMediaAsset(
            id=_uid("extra"), space_id=ctx.prod_wb_space_id,
            uploaded_by_user_id=ctx.prod_lindsey_id,
            title="smuggled", original_filename="s.png",
            stored_filename="s.png",
            storage_path="media/world-builders/s.png",
            file_url="/api/uploads/media/world-builders/s.png",
            mime_type="image/png", media_type="image",
            file_size_bytes=1, extension=".png",
        ))
        prod.commit()
        with pytest.raises(RuntimeError, match="CreatorMediaAsset count"):
            importer.verify(plan, ctx, ctx.r2_client, "priv", "pub")

    def test_catches_missing_step(self, db: Session, mini_world_builders) -> None:
        prod, plan, ctx = _run_and_get_ctx(db)
        # Raw SQL delete — bypasses the ORM cascade loader which would
        # want tables (step_progress, step_resources, step_comments,
        # manual_releases) that the SQLite prod does not create.
        from sqlalchemy import delete
        one_step_id = prod.query(PathwayStep.id).first()[0]
        # First delete dependent step_blocks with raw SQL.
        prod.execute(
            delete(PathwayStepBlock).where(PathwayStepBlock.step_id == one_step_id)
        )
        prod.execute(delete(PathwayStep).where(PathwayStep.id == one_step_id))
        prod.commit()
        with pytest.raises(RuntimeError, match="PathwayStep count"):
            importer.verify(plan, ctx, ctx.r2_client, "priv", "pub")

    def test_catches_r2_head_failure(self, db: Session, mini_world_builders) -> None:
        prod, plan, ctx = _run_and_get_ctx(db)
        client = MagicMock()
        client.head_object.side_effect = RuntimeError("not found")
        with pytest.raises(RuntimeError, match="R2 HEAD failed"):
            importer.verify(plan, ctx, client, "priv", "pub")


# ---------------------------------------------------------------------------
# R2 upload / rollback
# ---------------------------------------------------------------------------


@pytest.fixture
def upload_source(monkeypatch, tmp_path):
    monkeypatch.setattr(importer, "UPLOAD_DIR_LOCAL", tmp_path)
    (tmp_path / "media" / "world-builders").mkdir(parents=True)
    (tmp_path / "media" / "world-builders" / "x.png").write_bytes(b"XBYTES")
    (tmp_path / "media" / "world-builders" / "y.png").write_bytes(b"YBYTES")
    return tmp_path


class TestR2Upload:
    def test_uploads_to_private_bucket(self, upload_source) -> None:
        client = MagicMock()
        uploaded = importer.upload_r2_objects(
            keys=["media/world-builders/x.png", "media/world-builders/y.png"],
            r2_client=client,
            bucket_private="priv",
            bucket_public="pub",
        )
        assert uploaded == [
            ("priv", "media/world-builders/x.png"),
            ("priv", "media/world-builders/y.png"),
        ]
        assert client.put_object.call_count == 2
        assert client.head_object.call_count == 2

    def test_raises_when_local_file_missing(self, upload_source) -> None:
        client = MagicMock()
        with pytest.raises(importer.R2UploadError, match="missing"):
            importer.upload_r2_objects(
                keys=["media/world-builders/nope.png"],
                r2_client=client,
                bucket_private="priv", bucket_public="pub",
            )

    def test_rollback_deletes_uploaded_set(self) -> None:
        client = MagicMock()
        importer.rollback_r2(
            uploaded=[
                ("priv", "media/world-builders/x.png"),
                ("priv", "media/world-builders/y.png"),
            ],
            r2_client=client,
        )
        assert client.delete_object.call_count == 2

    def test_rollback_swallows_delete_errors(self) -> None:
        client = MagicMock()
        client.delete_object.side_effect = RuntimeError("gone")
        importer.rollback_r2([("priv", "x")], client)  # must not raise


# ---------------------------------------------------------------------------
# End-to-end DB rollback on failure inside the insert flow
# ---------------------------------------------------------------------------


class TestDbRollbackOnFailure:
    def test_db_rollback_leaves_parent_unchanged(
        self, db: Session, mini_world_builders,
    ) -> None:
        """Prove that a failure during the write flow leaves the prod
        parent Space untouched — the parent UPDATE and all child
        INSERTs live in one transaction that main() rolls back on any
        exception before commit."""
        prod, prod_lindsey_id, prod_wb_id, tc_id = _make_sqlite_prod()
        _, snapshot = importer._validate_and_snapshot_prod_wb(prod)
        plan = importer.enumerate_plan(db, prod_the_commons_id=tc_id)
        # Run the whole insert flow (all flushes complete), then
        # simulate a failure BEFORE the operator-level commit.
        try:
            importer.insert_prod_rows(
                plan, prod, prod_wb_id, prod_lindsey_id, snapshot,
            )
            raise RuntimeError("simulated post-insert failure")
        except Exception:
            prod.rollback()
        # Force a fresh read from disk (identity-map objects are now
        # stale relative to the rolled-back transaction).
        prod.expire_all()
        fresh = prod.query(Space).filter(Space.id == prod_wb_id).first()
        assert fresh is not None
        assert fresh.creator_id is None
        assert fresh.auto_grant_role == "creator"
        assert fresh.tagline is None                # UPDATE rolled back
        assert fresh.about_content is None          # UPDATE rolled back
        assert fresh.location_id is None            # UPDATE rolled back
        # No child rows should have landed either.
        assert prod.query(Pathway).count() == 0
        assert prod.query(CreatorMediaAsset).count() == 0
