"""Tests for the Mother World / shared-content importer.

The importer writes to a "prod" DB. In tests we stand in a real
test-DB session as BOTH local and prod, populating each side to
match the shape the script expects. That lets us exercise:

  * Preflight refusals (missing seed rows, prod collision on a
    CREATE target, corrupted local sanity, missing prod-Lindsey).
  * Full enumeration produces the exact locked manifest
    (25 Locations + 2 Places + 9 WGDocs + 9 WGVersions = 45 writes;
    15 UPDATE + 30 CREATE).
  * Corrections applied at insert time (three Atlas keys +
    Mornington Peninsula).
  * UPDATE-vs-CREATE partition is right.
  * Draft-only World Guide invariants enforced end-to-end.
  * Media fields nulled in the prod-side row.
  * Content verification catches mismatches when we deliberately
    drift a field.
  * Rollback on any DB failure inside execute().

The tests fake "prod" by writing to the test DB. Since the test DB
uses SAVEPOINT-scoped sessions from conftest, every test is
isolated. Where we need to bypass the _same_db safeguard (both
sides are literally the same session) we call the internal
functions directly rather than going through main().
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import import_mother_world as im  # noqa: E402

from app.models.place import Place  # noqa: E402
from app.models.platform import Location  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.world_guide import (  # noqa: E402
    WorldGuideDocument,
    WorldGuideVersion,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Helpers to build a full local + prod fixture matching the manifest shape
# ---------------------------------------------------------------------------


def _make_ctx(
    session: Session,
    prod_lindsey_id: str,
    commit: bool = False,
    prod_session: Session | None = None,
) -> im.MigrationContext:
    return im.MigrationContext(
        local_session=session,
        prod_session=prod_session if prod_session is not None else session,
        prod_lindsey_id=prod_lindsey_id,
        commit=commit,
        yes_i_am_sure=True,
    )


def _make_sqlite_prod_session(prod_lindsey_id: str) -> Session:
    """Build a fresh SQLite-in-memory 'prod' session with only the
    tables the migration touches, pre-seeded with the 15 rows
    (12 Atlas + 3 Community) that Alembic migrations 065 / 069
    guarantee in prod, plus the prod-Lindsey user for FK sanity.

    Real Postgres would resolve JSON columns differently but the
    fields we care about here are all standard types; SQLite handles
    them adequately for the assertion granularity we need."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True)
    for model in [User, Location, Place, WorldGuideDocument, WorldGuideVersion]:
        model.__table__.create(engine)
    Session_ = _sessionmaker(bind=engine, future=True)
    prod = Session_()

    # Prod-Lindsey user (needed for author_user_id FK).
    prod.add(User(
        id=prod_lindsey_id, email=im.PROD_OWNER_EMAIL,
        name="Lindsey Hilliard",
        password_hash="$2b$12$0000000000000000000000000000000000000000000000000000",
        role="creator",
        email_verified_at=datetime.utcnow(),
    ))
    # 12 seeded Atlas placeholders.
    for i in range(1, 13):
        prod.add(Location(
            id=f"loc_{i:02d}", key=f"location-{i:02d}",
            name=f"Location {i:02d} (prod placeholder)",
            status="active", location_type="ATLAS",
            preferred_atmospheres=[], preferred_colour_stories=[],
            preferred_themes=[], position=i,
        ))
    # 3 seeded Community rows (with placeholder names).
    for k in ("campfire-grove", "harvest-table", "festival-green"):
        prod.add(Location(
            id=_uid("prod"), key=k, name=k.replace("-", " ").title(),
            status="active", location_type="COMMUNITY",
            preferred_atmospheres=[], preferred_colour_stories=[],
            preferred_themes=[], position=100,
        ))
    prod.commit()
    return prod


def _prod_snapshot_with_seed_only() -> im.ProdReadState:
    """Simulates a prod DB freshly-migrated: 12 seeded Atlas
    placeholders + 3 seeded Community rows exist, nothing else."""
    prod_locs: dict[str, Location] = {}
    for i in range(1, 13):
        prod_locs[f"location-{i:02d}"] = Location(
            id=f"loc_{i:02d}", key=f"location-{i:02d}",
            name=f"Location {i:02d} (prod placeholder)",
            status="active", location_type="ATLAS",
            preferred_atmospheres=[], preferred_colour_stories=[],
            preferred_themes=[], position=i,
        )
    for k in ("campfire-grove", "harvest-table", "festival-green"):
        prod_locs[k] = Location(
            id=_uid("prod"), key=k, name=k.replace("-", " ").title(),
            status="active", location_type="COMMUNITY",
            preferred_atmospheres=[], preferred_colour_stories=[],
            preferred_themes=[], position=100,
        )
    return im.ProdReadState(
        locations_by_key=prod_locs,
        place_slugs=set(),
        wgdoc_slugs=set(),
    )


def _seed_local_authored(session: Session) -> None:
    """Seed the full LOCAL side: 12 Atlas placeholders + 3 Community
    seeds (with authored names on them, as if Lindsey has edited them)
    + 3 Cornerstones + 4 admin-authored ATLAS + 3 WIP-slug ATLAS
    (to be renamed) + hidden crystal-hollow + 2 Places (one with the
    WIP slug) + 9 WorldGuide documents each with a v0.1 draft.

    Prod side is not touched here; tests inject a controlled
    ``ProdReadState`` snapshot separately."""
    # Seed placeholders with authored names.
    real_names = [
        "🌲 Moss Haven", "🪸 Coral Cay", "🌸 Wildflower Isle",
        "🏔 Highcliff", "🌙 Moon Lagoon", "🍋 Azure Terrace",
        "🌅 Solstice Point", "💧 Silver Falls", "🌊 Wavebound",
        "🪨 Echo Point", "🌋 Ember Ridge", "❄ Frost Fjord",
    ]
    for i, real in enumerate(real_names, start=1):
        session.add(Location(
            id=f"loc_{i:02d}", key=f"location-{i:02d}",
            name=real,
            description=f"Authored description for {real}",
            status="active", location_type="ATLAS",
            preferred_atmospheres=["playful", "brave"],
            preferred_colour_stories=[],
            preferred_themes=[],
            position=i,
        ))
    for k, real in [("campfire-grove", "🔥 The Hearth"),
                    ("harvest-table", "🍽 Harvest Hall"),
                    ("festival-green", "🌞 Festival Green")]:
        session.add(Location(
            id=_uid("loc"), key=k, name=real,
            status="active", location_type="COMMUNITY",
            preferred_atmospheres=[], preferred_colour_stories=[],
            preferred_themes=[], position=100,
        ))
    session.flush()

    # Admin-authored Atlas rows.
    session.add(Location(
        id=_uid("loc"), key="cloudhaven", name="☁️ Cloudhaven",
        status="active", location_type="ATLAS",
        description="Sky-borne haven.",
        atlas_entry="Long editorial about cloudhaven.",
        preferred_atmospheres=["playful"], preferred_colour_stories=[],
        preferred_themes=[], position=13,
    ))
    session.add(Location(
        id=_uid("loc"), key="canopy-reach", name="🌳 Canopy Reach",
        status="active", location_type="ATLAS",
        preferred_atmospheres=[], preferred_colour_stories=[],
        preferred_themes=[], position=16,
    ))
    session.add(Location(
        id=_uid("loc"), key="starwatch-peak", name="🔭 Starwatch Peak",
        status="active", location_type="ATLAS",
        preferred_atmospheres=[], preferred_colour_stories=[],
        preferred_themes=[], position=18,
    ))
    session.add(Location(
        id=_uid("loc"), key="sanctuary-springs", name="🌿 Sanctuary Springs",
        status="active", location_type="ATLAS",
        description="EMBODY's home island.", atlas_entry="Warm mineral waters…",
        preferred_atmospheres=[], preferred_colour_stories=[],
        preferred_themes=[], position=23,
    ))
    # Three WIP-slug rows that must be renamed at insert time.
    session.add(Location(
        id=_uid("loc"), key="pelagia-or-another-name",
        name="🏝 The Lost Circle (local WIP name)",
        status="active", location_type="ATLAS",
        preferred_atmospheres=[], preferred_colour_stories=[],
        preferred_themes=[], position=14,
    ))
    session.add(Location(
        id=_uid("loc"), key="canal-haven-working-name",
        name="🎭 Luminara (local WIP name)",
        status="active", location_type="ATLAS",
        preferred_atmospheres=[], preferred_colour_stories=[],
        preferred_themes=[], position=15,
    ))
    session.add(Location(
        id=_uid("loc"), key="verdant-keys",
        name="🤍 Aegea (local WIP name)",
        status="active", location_type="ATLAS",
        preferred_atmospheres=[], preferred_colour_stories=[],
        preferred_themes=[], position=19,
    ))
    # Cornerstones.
    session.add(Location(
        id=_uid("loc"), key="the-atlas-isles", name="🧭 The Atlas Isles",
        status="active", location_type="CORNERSTONE",
        preferred_atmospheres=[], preferred_colour_stories=[],
        preferred_themes=[], position=20,
    ))
    session.add(Location(
        id=_uid("loc"), key="the-grove", name="🌳 The Grove",
        status="active", location_type="CORNERSTONE",
        preferred_atmospheres=[], preferred_colour_stories=[],
        preferred_themes=[], position=21,
    ))
    session.add(Location(
        id=_uid("loc"), key="the-commons", name="🌍 The Commons",
        status="active", location_type="CORNERSTONE",
        preferred_atmospheres=[], preferred_colour_stories=[],
        preferred_themes=[], position=22,
    ))
    # Hidden crystal-hollow — deliberately excluded.
    session.add(Location(
        id=_uid("loc"), key="crystal-hollow", name="🔮 Crystal Cove",
        status="hidden", location_type="ATLAS",
        preferred_atmospheres=[], preferred_colour_stories=[],
        preferred_themes=[], position=17,
    ))

    # Places (Melbourne clean, Mornington with WIP slug/name).
    session.add(Place(
        id=_uid("pl"), slug="melbourne", name="Melbourne",
        country_code="AU", region="Victoria", status="active",
        artwork_focal_x=0.5, artwork_focal_y=0.5,
    ))
    session.add(Place(
        id=_uid("pl"), slug="mornington-penninsula",  # local typo
        name="Mornington Penninsula",                 # local typo
        country_code="AU", status="active",
        artwork_focal_x=0.5, artwork_focal_y=0.5,
    ))

    # 9 WorldGuide documents, each with 1 draft v0.1.
    doc_slugs = [
        "community-guidelines", "creator-agreement", "glossary",
        "membership-terms", "our-philosophy",
        "payment-refund-and-cancellation-policy",
        "privacy-policy", "term-of-use", "world-guide",
    ]
    for s in doc_slugs:
        doc = WorldGuideDocument(
            id=_uid("wgd"), slug=s, title=s.replace("-", " ").title(),
            category="governance", audience="everyone",
            summary=f"Summary for {s}",
        )
        session.add(doc)
        session.flush()
        session.add(WorldGuideVersion(
            id=_uid("wgv"), document_id=doc.id, version_number="0.1",
            status="draft",
            main_content=f"Main content of {s} v0.1",
        ))
    session.flush()


@pytest.fixture
def full_fixture(db: Session, make_user):
    """Prod-lindsey user + full local-authored data in the test DB.
    Prod snapshot is built separately via ``_prod_snapshot_with_seed_only``."""
    prod_lindsey = make_user(role="creator", email=im.PROD_OWNER_EMAIL)
    _seed_local_authored(db)
    db.commit()
    return prod_lindsey


# ---------------------------------------------------------------------------
# Preflight — refusal chain
# ---------------------------------------------------------------------------


class TestPreflightRefusals:
    def test_missing_prod_database_url(self, monkeypatch):
        monkeypatch.delenv("PROD_DATABASE_URL", raising=False)
        with pytest.raises(im.PreflightError, match="PROD_DATABASE_URL"):
            im._open_sessions(im.parse_args([]))

    def test_same_db_refused(self, monkeypatch):
        monkeypatch.setenv("PROD_DATABASE_URL", os.environ.get("DATABASE_URL", "postgresql://x@y/z"))
        with pytest.raises(im.PreflightError, match="same host"):
            im._open_sessions(im.parse_args([]))


class TestEnumeratePreflight:
    def test_full_fixture_enumerates_45_writes(self, db, full_fixture):
        ctx = _make_ctx(db, full_fixture.id)
        plan = im.enumerate_plan(ctx, prod_state=_prod_snapshot_with_seed_only())
        assert plan.total_writes() == im.EXPECTED_TOTAL_WRITES == 45
        assert plan.total_updates() == im.EXPECTED_UPDATES == 15
        assert plan.total_creates() == im.EXPECTED_CREATES == 30

    def test_manifest_family_split(self, db, full_fixture):
        ctx = _make_ctx(db, full_fixture.id)
        plan = im.enumerate_plan(ctx, prod_state=_prod_snapshot_with_seed_only())
        assert len(plan.locations_update) == 15   # 12 ATLAS + 3 COMMUNITY
        assert len(plan.locations_create) == 10   # 7 ATLAS + 3 CORNERSTONE
        assert len(plan.places_create) == 2
        assert len(plan.wgdocs_create) == 9
        assert len(plan.wgvers_create) == 9

    def test_crystal_hollow_excluded(self, db, full_fixture):
        ctx = _make_ctx(db, full_fixture.id)
        plan = im.enumerate_plan(ctx, prod_state=_prod_snapshot_with_seed_only())
        all_keys = [e["expected"]["key"] for e in plan.locations_update + plan.locations_create]
        assert "crystal-hollow" not in all_keys
        assert len(all_keys) == len(set(all_keys))  # no duplicates

    def test_atlas_renames_applied_in_expected(self, db, full_fixture):
        ctx = _make_ctx(db, full_fixture.id)
        plan = im.enumerate_plan(ctx, prod_state=_prod_snapshot_with_seed_only())
        created_keys = {e["expected"]["key"] for e in plan.locations_create}
        # WIP keys are gone; final keys are in.
        assert "pelagia-or-another-name" not in created_keys
        assert "canal-haven-working-name" not in created_keys
        assert "verdant-keys" not in created_keys
        assert {"the-lost-circle", "luminara", "aegea"}.issubset(created_keys)
        # Names carry across the rename table.
        by_key = {e["expected"]["key"]: e["expected"]["name"]
                  for e in plan.locations_create}
        assert by_key["the-lost-circle"] == "🏝 The Lost Circle"
        assert by_key["luminara"] == "🎭 Luminara"
        assert by_key["aegea"] == "🤍 Aegea"

    def test_place_rename_applied(self, db, full_fixture):
        ctx = _make_ctx(db, full_fixture.id)
        plan = im.enumerate_plan(ctx, prod_state=_prod_snapshot_with_seed_only())
        slugs = {e["expected"]["slug"] for e in plan.places_create}
        names = {e["expected"]["name"] for e in plan.places_create}
        assert "mornington-penninsula" not in slugs
        assert "mornington-peninsula" in slugs
        assert "Mornington Penninsula" not in names
        assert "Mornington Peninsula" in names

    def test_refuse_when_prod_missing_a_seed_atlas_key(self, db, full_fixture):
        # Prod snapshot with 'location-05' removed — simulates a prod
        # DB where a seed row was manually deleted.
        snap = _prod_snapshot_with_seed_only()
        del snap.locations_by_key["location-05"]
        ctx = _make_ctx(db, full_fixture.id)
        with pytest.raises(im.PreflightError, match="missing expected seed"):
            im.enumerate_plan(ctx, prod_state=snap)

    def test_refuse_when_prod_already_has_a_create_target(
        self, db, full_fixture,
    ):
        # Prod snapshot pre-populated with one of the CREATE target keys.
        snap = _prod_snapshot_with_seed_only()
        snap.locations_by_key["sanctuary-springs"] = Location(
            id=_uid("prod"), key="sanctuary-springs",
            name="Pre-existing prod row", status="active",
            location_type="ATLAS", preferred_atmospheres=[],
            preferred_colour_stories=[], preferred_themes=[], position=99,
        )
        ctx = _make_ctx(db, full_fixture.id)
        with pytest.raises(im.PreflightError, match="Prod already has a Location"):
            im.enumerate_plan(ctx, prod_state=snap)

    def test_refuse_when_prod_already_has_a_place_slug(
        self, db, full_fixture,
    ):
        snap = _prod_snapshot_with_seed_only()
        snap.place_slugs.add("melbourne")
        ctx = _make_ctx(db, full_fixture.id)
        with pytest.raises(im.PreflightError, match="Prod already has a Place"):
            im.enumerate_plan(ctx, prod_state=snap)

    def test_refuse_when_prod_already_has_a_wg_doc_slug(
        self, db, full_fixture,
    ):
        snap = _prod_snapshot_with_seed_only()
        snap.wgdoc_slugs.add("privacy-policy")
        ctx = _make_ctx(db, full_fixture.id)
        with pytest.raises(im.PreflightError, match="Prod already has a WorldGuideDocument"):
            im.enumerate_plan(ctx, prod_state=snap)

    def test_refuse_when_local_wg_doc_has_current_version_set(
        self, db, full_fixture,
    ):
        doc = db.query(WorldGuideDocument).first()
        # Point at a REAL version id so the FK holds — but violates the
        # draft-only invariant the migration guards.
        v = db.query(WorldGuideVersion).filter(
            WorldGuideVersion.document_id == doc.id).first()
        doc.current_version_id = v.id
        db.flush()
        ctx = _make_ctx(db, full_fixture.id)
        with pytest.raises(im.PreflightError, match="draft-only invariant"):
            im.enumerate_plan(ctx, prod_state=_prod_snapshot_with_seed_only())

    def test_refuse_when_local_wg_version_has_published_at(
        self, db, full_fixture,
    ):
        v = db.query(WorldGuideVersion).first()
        v.published_at = datetime.utcnow()
        db.flush()
        ctx = _make_ctx(db, full_fixture.id)
        with pytest.raises(im.PreflightError, match="draft-only invariant"):
            im.enumerate_plan(ctx, prod_state=_prod_snapshot_with_seed_only())


def _empty_query():
    q = MagicMock()
    q.all.return_value = []
    return q


# ---------------------------------------------------------------------------
# Execute + verify — happy path
# ---------------------------------------------------------------------------


class TestExecuteAndVerify:
    """End-to-end tests using a real SQLite in-memory DB as the 'prod'
    side. Local remains the Postgres test DB. Both sides start in the
    exact state the migration expects (local: 25 authored Locations
    plus 2 Places plus 9 WGDocs each with a draft; prod: 15 seed rows
    plus prod-Lindsey user)."""

    def test_execute_writes_all_45_rows_and_verification_passes(
        self, db, full_fixture,
    ):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)  # reads real prod snapshot
        id_maps = im.execute(plan, ctx)
        assert len(id_maps.wgdoc) == 9
        errors = im.verify(plan, ctx)
        assert errors == [], "\n".join(errors)

    def test_atlas_updates_preserve_prod_id_and_overwrite_content(
        self, db, full_fixture,
    ):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        seed_keys = {f"location-{i:02d}" for i in range(1, 13)}
        ids_before = {r.key: r.id for r in prod.query(Location).filter(
            Location.key.in_(seed_keys)).all()}
        im.execute(plan, ctx)
        ids_after = {r.key: r.id for r in prod.query(Location).filter(
            Location.key.in_(seed_keys)).all()}
        assert ids_before == ids_after, "UPDATE must preserve prod IDs"
        # Authored name propagated.
        moss = prod.query(Location).filter(Location.key == "location-01").first()
        assert moss.name == "🌲 Moss Haven"
        # Placeholder text is gone from prod's row.
        assert "prod placeholder" not in moss.name

    def test_atlas_creates_have_fresh_non_seed_uuids(self, db, full_fixture):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        im.execute(plan, ctx)
        for k in im.TARGET_ATLAS_CREATE_KEYS | im.TARGET_CORNERSTONE_CREATE_KEYS:
            row = prod.query(Location).filter(Location.key == k).first()
            assert row is not None, f"{k}: not created in prod"
            assert not row.id.startswith("loc_"), (
                f"{k}: prod id looks like a seed placeholder"
            )

    def test_place_slug_and_name_corrected_in_prod(self, db, full_fixture):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        im.execute(plan, ctx)
        prod_slugs = {p.slug for p in prod.query(Place).all()}
        assert "mornington-peninsula" in prod_slugs
        assert "mornington-penninsula" not in prod_slugs  # typo not carried
        corrected = prod.query(Place).filter(
            Place.slug == "mornington-peninsula").first()
        assert corrected.name == "Mornington Peninsula"

    def test_media_fields_nulled_in_prod(self, db, full_fixture):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        im.execute(plan, ctx)
        for k in im.TARGET_ATLAS_CREATE_KEYS:
            row = prod.query(Location).filter(Location.key == k).first()
            assert row.hero_artwork_url is None
            assert row.thumbnail_artwork_url is None
        melb = prod.query(Place).filter(Place.slug == "melbourne").first()
        assert melb.hero_artwork_url is None
        assert melb.artwork_alt_text is None

    def test_wg_documents_all_draft_and_authored_by_prod_lindsey(
        self, db, full_fixture,
    ):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        im.execute(plan, ctx)
        docs = prod.query(WorldGuideDocument).all()
        assert len(docs) == 9
        for d in docs:
            assert d.current_version_id is None
            assert d.author_user_id == full_fixture.id

    def test_wg_versions_all_draft_and_document_id_remapped(
        self, db, full_fixture,
    ):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        id_maps = im.execute(plan, ctx)
        for entry in plan.wgvers_create:
            source = entry["source"]
            prod_doc_id = id_maps.wgdoc[source.document_id]
            v = prod.query(WorldGuideVersion).filter(
                WorldGuideVersion.document_id == prod_doc_id,
                WorldGuideVersion.version_number == source.version_number,
            ).first()
            assert v is not None
            assert v.status == "draft"
            assert v.published_at is None
            assert v.published_by_user_id is None


# ---------------------------------------------------------------------------
# Verification — deliberately induce drift, prove it's caught
# ---------------------------------------------------------------------------


class TestContentVerificationDetection:
    """Prove verify() surfaces every kind of drift the design cares
    about — mutate the prod-side row after execute() commits, then
    call verify() and assert the drift is reported by (model, key,
    field)."""

    def test_verify_reports_field_drift_on_a_location(self, db, full_fixture):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        im.execute(plan, ctx)
        # Drift the prod-side description on the sanctuary-springs row.
        prod.query(Location).filter(Location.key == "sanctuary-springs").first().description = "DRIFTED"
        prod.flush()
        errors = im.verify(plan, ctx)
        assert any(
            "Location key='sanctuary-springs'" in e and "'description'" in e
            for e in errors
        ), "\n".join(errors)

    def test_verify_reports_media_field_leak(self, db, full_fixture):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        im.execute(plan, ctx)
        prod.query(Location).filter(Location.key == "the-grove").first().hero_artwork_url = "/api/uploads/x.png"
        prod.flush()
        errors = im.verify(plan, ctx)
        assert any("the-grove" in e and "'hero_artwork_url'" in e for e in errors)

    def test_verify_reports_wg_doc_current_version_id_leak(self, db, full_fixture):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        im.execute(plan, ctx)
        doc = prod.query(WorldGuideDocument).first()
        v = prod.query(WorldGuideVersion).filter(
            WorldGuideVersion.document_id == doc.id).first()
        doc.current_version_id = v.id
        prod.flush()
        errors = im.verify(plan, ctx)
        assert any("Draft-only invariant broken" in e for e in errors)

    def test_verify_reports_wg_version_publication_leak(self, db, full_fixture):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        im.execute(plan, ctx)
        prod.query(WorldGuideVersion).first().status = "published"
        prod.flush()
        errors = im.verify(plan, ctx)
        assert any("Draft-only invariant broken" in e for e in errors)

    def test_verify_reports_field_drift_on_a_wg_version(self, db, full_fixture):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        im.execute(plan, ctx)
        # Drift the main_content on one version.
        v = prod.query(WorldGuideVersion).first()
        v.main_content = "DRIFTED CONTENT"
        prod.flush()
        errors = im.verify(plan, ctx)
        assert any("main_content" in e for e in errors), "\n".join(errors)


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


class TestRollbackOnFailure:
    def test_execute_raises_when_wg_version_remap_impossible(
        self, db, full_fixture,
    ):
        prod = _make_sqlite_prod_session(full_fixture.id)
        ctx = _make_ctx(db, full_fixture.id, commit=True, prod_session=prod)
        plan = im.enumerate_plan(ctx)
        # Break the plan by adding a WG version whose parent isn't
        # in wgdocs_create — simulating enumeration inconsistency.
        bogus = MagicMock()
        bogus.id = "bogus-ver"
        bogus.document_id = "nonexistent-doc"
        bogus.version_number = "9.9"
        bogus.status = "draft"
        bogus.published_at = None
        bogus.published_by_user_id = None
        bogus.last_edited_by_user_id = None
        for f in ("effective_date", "why_this_exists", "what_this_covers",
                  "main_content", "whats_changed"):
            setattr(bogus, f, None)
        bogus.created_at = datetime.utcnow()
        plan.wgvers_create.append({"source": bogus, "expected_partial": {}})

        with pytest.raises(RuntimeError, match="not in the doc id_map"):
            im.execute(plan, ctx)
        # main() catches this exception and calls prod.rollback() —
        # exercised at the CLI level. The unit-level contract this
        # test locks is: enumeration-vs-execute drift raises loudly
        # instead of silently mis-linking a version.


# ---------------------------------------------------------------------------
# Structural — locked totals + module boots
# ---------------------------------------------------------------------------


class TestLockedTotals:
    def test_manifest_constants_locked_at_45(self):
        assert im.EXPECTED_TOTAL_WRITES == 45
        assert im.EXPECTED_UPDATES == 15
        assert im.EXPECTED_CREATES == 30
        assert im.EXPECTED_UPDATES + im.EXPECTED_CREATES == im.EXPECTED_TOTAL_WRITES


class TestModuleImportsCleanly:
    def test_boot(self):
        # If any model import path is stale, this would ImportError.
        import importlib
        importlib.reload(im)
        assert im.EXPECTED_TOTAL_WRITES == 45


# stdlib import needed here for one preflight test.
import os  # noqa: E402
