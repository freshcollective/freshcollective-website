"""Tests for the Moonlit Circle selective importer.

Uses a real test-DB session as "local" (SAVEPOINT-scoped by conftest)
and a fresh SQLite-in-memory session as physically-distinct "prod".
The prod side is pre-seeded with the exact rows the Mother World
migration guarantees (Moon Lagoon Atlas Location under key
``location-05``, corrected Mornington Peninsula Place under slug
``mornington-peninsula``, and prod-Lindsey).

Coverage:
  * Preflight helpers resolve prod Location + Place, refusing loudly
    on missing rows (naming the local→prod slug rename in the error).
  * Enumerate walks the local fixture and captures the local
    ``mornington-penninsula`` slug in space_place_slugs.
  * Drift checks: missing/wrong local Location, missing/extra local
    SpacePlace slugs.
  * Insert remaps Space.location_id to prod, nulls action FKs, creates
    the single Lindsey membership, and writes SpacePlace with the prod
    Place.id — never the local UUID.
  * Verify enforces every invariant approved for this migration and
    catches drift on each.
  * The orphan "Side view moon lagoon" CreatorMediaAsset is excluded
    by the referenced-only media filter (identity check, not a
    special path).
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
import import_moonlit_from_dev as importer  # noqa: E402

from app.models.place import Place, SpacePlace  # noqa: E402
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
    with_location: bool = True,
    with_peninsula: bool = True,
    extra_place_slugs: tuple[str, ...] = (),
) -> tuple[Session, str, dict[str, str]]:
    """Fresh in-memory 'prod' session seeded with Moon Lagoon +
    corrected Mornington Peninsula + prod-Lindsey.

    Returns (session, prod_lindsey_id, prod_place_ids_by_local_slug).
    The returned mapping matches what preflight would produce for the
    approved LOCAL_TO_PROD_PLACE_SLUGS.
    """
    engine = create_engine("sqlite:///:memory:", future=True)
    for model in [
        User, Location, Place, SpacePlace,
        Space, SpaceMembership,
        CreatorMediaAsset,
        Pathway, PathwaySection, PathwayStep,
        PathwayStepBlock, PathwayAboutBlock,
    ]:
        model.__table__.create(engine)
    Session_ = sessionmaker(bind=engine, future=True)
    prod = Session_()

    prod_lindsey_id = _uid("u")
    prod.add(User(
        id=prod_lindsey_id, email=importer.PROD_OWNER_EMAIL,
        name="Lindsey Hilliard",
        password_hash="$2b$12$0" + "0" * 52,
        role="creator",
        email_verified_at=datetime.utcnow(),
    ))

    if with_location:
        prod.add(Location(
            id=_uid("prodloc"), key=importer.MOONLIT_LOCATION_KEY,
            name="Moon Lagoon", status="active", location_type="ATLAS",
            preferred_atmospheres=[], preferred_colour_stories=[],
            preferred_themes=[], position=5,
        ))

    prod_place_ids_by_local_slug: dict[str, str] = {}
    if with_peninsula:
        pid = _uid("prodpl")
        prod.add(Place(
            id=pid, slug="mornington-peninsula",
            name="Mornington Peninsula",
            country_code="AU", status="active",
        ))
        prod_place_ids_by_local_slug["mornington-penninsula"] = pid
    for slug in extra_place_slugs:
        pid = _uid("prodpl")
        prod.add(Place(
            id=pid, slug=slug, name=slug.title(),
            country_code="AU", status="active",
        ))
    prod.commit()
    return prod, prod_lindsey_id, prod_place_ids_by_local_slug


# ---------------------------------------------------------------------------
# Local fixture — mini Moonlit Circle
# ---------------------------------------------------------------------------


@pytest.fixture
def mini_moonlit(db: Session, make_user):
    """Build a local fixture matching the audited Moonlit Circle shape:
    one Atlas Location (key=location-05), one Place with the local
    typo, one Space, one SpacePlace, one draft Pathway (no subtree),
    one orphan CreatorMediaAsset (unreferenced)."""
    creator = make_user(role="creator")

    # Local Atlas Moon Lagoon Location.
    location = Location(
        id=_uid("loc"), key=importer.MOONLIT_LOCATION_KEY,
        name="🌙 Moon Lagoon", status="active", location_type="ATLAS",
        preferred_atmospheres=[], preferred_colour_stories=[],
        preferred_themes=[], position=5,
    )
    db.add(location)
    db.flush()

    # Local Place with the historic typo slug.
    place = Place(
        id=_uid("pl"), slug="mornington-penninsula",
        name="Mornington Penninsula",
        country_code="AU", status="draft",
    )
    db.add(place)
    db.flush()

    space = Space(
        id=_uid("s"),
        slug="moonlit-circle",
        name="Moonlit Circle",
        tagline="A place of calm in a world full of chaos",
        description="Reflective, spacious, midnight-toned.",
        identity_statement="A place of calm in a world full of chaos",
        welcome_message="You are welcome here. Take your time.",
        creator_id=creator.id,
        status=SpaceStatus.active,
        cover_image_url=None,
        logo_url="/api/uploads/logos/moonlit-circle/24b64ba4677a47ddb492110816c3d11a_MC_logo.png",
        location_id=location.id,
        colour_story_key="midnight",
        atmosphere_keys=["calm", "creative", "grounded", "reflective", "peaceful"],
        themes=["Inner Work", "Spirituality", "Reflection"],
        included_access_summary="Conversations and some online gatherings",
        paid_content_summary="Paid gatherings and pathways",
        has_paid_internal_content=True,
    )
    db.add(space)
    db.flush()

    db.add(SpacePlace(space_id=space.id, place_id=place.id))
    db.flush()

    pathway = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug="a-quiet-evening-reset",
        title="A Quiet Evening Reset",
        description="A short evening practice for winding down.",
        status="draft",
        pathway_type=PathwayType.guided_experience,
        access_type="included",
        pricing_mode="legacy",
        position=0,
    )
    db.add(pathway)
    db.flush()

    # Orphan media — MUST NOT be migrated (no block/about-block
    # references it).
    orphan = CreatorMediaAsset(
        id=_uid("cma"), space_id=space.id, uploaded_by_user_id=creator.id,
        title="Side view moon lagoon", original_filename="mool.png",
        stored_filename="uuid_mool.png",
        storage_path="media/moonlit-circle/uuid_mool.png",
        file_url="/api/uploads/media/moonlit-circle/uuid_mool.png",
        mime_type="image/png", media_type="image",
        file_size_bytes=100, extension=".png",
    )
    db.add(orphan)
    db.commit()

    return {
        "space": space,
        "location_id": location.id,
        "place_id_typo": place.id,
        "orphan_asset_id": orphan.id,
        "pathway_id": pathway.id,
        "creator_id": creator.id,
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestSameDb:
    def test_identical_urls_match(self) -> None:
        assert importer._same_db(
            "postgresql://a:b@host/db1",
            "postgresql://a:b@host/db1",
        )

    def test_different_credentials_same_host_match(self) -> None:
        assert importer._same_db(
            "postgresql://user1:pw1@host/db",
            "postgresql://user2:pw2@host/db",
        )

    def test_different_databases_do_not_match(self) -> None:
        assert not importer._same_db(
            "postgresql://a@host/db_local",
            "postgresql://a@host/db_prod",
        )


class TestKeyFromUrl:
    def test_upload_prefix_yields_key(self) -> None:
        assert (
            importer._key_from_url("/api/uploads/logos/moonlit-circle/x.png")
            == "logos/moonlit-circle/x.png"
        )

    def test_external_url_returns_none(self) -> None:
        assert importer._key_from_url("https://example.com/x") is None

    def test_none_returns_none(self) -> None:
        assert importer._key_from_url(None) is None


# ---------------------------------------------------------------------------
# Prod-side resolution helpers
# ---------------------------------------------------------------------------


class TestResolveProdLocation:
    def test_success_returns_moon_lagoon_id(self) -> None:
        prod, _, _ = _make_sqlite_prod()
        loc_id = importer._resolve_prod_location_id(prod)
        assert loc_id
        row = prod.query(Location).filter(Location.id == loc_id).first()
        assert row.key == importer.MOONLIT_LOCATION_KEY

    def test_refuses_when_missing(self) -> None:
        prod, _, _ = _make_sqlite_prod(with_location=False)
        with pytest.raises(
            importer.PreflightError, match=importer.MOONLIT_LOCATION_KEY,
        ):
            importer._resolve_prod_location_id(prod)


class TestResolveProdPlaces:
    def test_success_returns_local_slug_to_prod_id(self) -> None:
        prod, _, seeded = _make_sqlite_prod()
        mapping = importer._resolve_prod_place_ids(prod)
        assert mapping == {"mornington-penninsula": seeded["mornington-penninsula"]}

    def test_refuses_when_mapped_slug_missing_names_both_slugs(self) -> None:
        prod, _, _ = _make_sqlite_prod(with_peninsula=False)
        with pytest.raises(importer.PreflightError) as exc:
            importer._resolve_prod_place_ids(prod)
        # Both the local typo and the corrected prod slug appear in
        # the error message so the operator can see the intended rename.
        assert "mornington-peninsula" in str(exc.value)
        assert "mornington-penninsula" in str(exc.value)


# ---------------------------------------------------------------------------
# Enumerate plan — success + drift refusals
# ---------------------------------------------------------------------------


class TestEnumeratePlanSuccess:
    def test_captures_the_single_pathway(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        assert [p["slug"] for p in plan.pathways] == ["a-quiet-evening-reset"]

    def test_pathway_subtree_is_empty(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        assert plan.sections == []
        assert plan.steps == []
        assert plan.step_blocks == []
        assert plan.about_blocks == []

    def test_space_place_slugs_carries_local_typo(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        assert plan.space_place_slugs == ["mornington-penninsula"]

    def test_orphan_media_naturally_excluded(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        assert plan.media_assets == []
        assert mini_moonlit["orphan_asset_id"] not in [
            m.get("id") for m in plan.media_assets
        ]

    def test_r2_key_set_contains_only_the_logo(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        assert plan.r2_keys == [
            "logos/moonlit-circle/24b64ba4677a47ddb492110816c3d11a_MC_logo.png",
        ]


class TestEnumerateLocalDrift:
    def test_refuses_when_local_space_has_no_location(
        self, db: Session, mini_moonlit,
    ) -> None:
        space = db.query(Space).filter(Space.slug == "moonlit-circle").first()
        space.location_id = None
        db.flush()
        with pytest.raises(RuntimeError, match="no location_id"):
            importer.enumerate_plan(db)

    def test_refuses_when_local_location_key_is_wrong(
        self, db: Session, mini_moonlit,
    ) -> None:
        wrong = Location(
            id=_uid("loc"), key="canopy-reach", name="Canopy Reach",
            status="active", location_type="ATLAS",
            preferred_atmospheres=[], preferred_colour_stories=[],
            preferred_themes=[], position=1,
        )
        db.add(wrong)
        db.flush()
        space = db.query(Space).filter(Space.slug == "moonlit-circle").first()
        space.location_id = wrong.id
        db.flush()
        with pytest.raises(RuntimeError, match="canopy-reach"):
            importer.enumerate_plan(db)

    def test_refuses_when_local_spaceplace_missing(
        self, db: Session, mini_moonlit,
    ) -> None:
        db.query(SpacePlace).filter(
            SpacePlace.space_id == mini_moonlit["space"].id
        ).delete()
        db.flush()
        with pytest.raises(RuntimeError, match="do not match"):
            importer.enumerate_plan(db)

    def test_refuses_when_local_spaceplace_has_unexpected_slug(
        self, db: Session, mini_moonlit,
    ) -> None:
        other = Place(
            id=_uid("pl"), slug="hobart", name="Hobart",
            country_code="AU", status="active",
        )
        db.add(other)
        db.flush()
        db.add(SpacePlace(
            space_id=mini_moonlit["space"].id, place_id=other.id,
        ))
        db.flush()
        with pytest.raises(RuntimeError, match="hobart"):
            importer.enumerate_plan(db)


# ---------------------------------------------------------------------------
# Insert into prod — remap + null actions + membership + SpacePlace
# ---------------------------------------------------------------------------


class TestInsertProdRows:
    def test_space_uses_prod_location_and_forces_draft(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod, prod_lindsey_id, prod_places = _make_sqlite_prod()
        importer.insert_prod_rows(
            plan, prod, prod_lindsey_id,
            prod_location_id=importer._resolve_prod_location_id(prod),
            prod_place_ids_by_slug=prod_places,
        )
        prod.flush()

        prod_space = prod.query(Space).filter(
            Space.slug == "moonlit-circle"
        ).first()
        assert prod_space is not None
        assert prod_space.status == SpaceStatus.draft
        assert prod_space.creator_id == prod_lindsey_id
        # location_id is the PROD Moon Lagoon, not the local UUID.
        assert prod_space.location_id != mini_moonlit["location_id"]
        prod_loc = prod.query(Location).filter(
            Location.id == prod_space.location_id
        ).first()
        assert prod_loc.key == importer.MOONLIT_LOCATION_KEY

    def test_action_fks_are_nulled(
        self, db: Session, mini_moonlit,
    ) -> None:
        # Simulate a local Space that carries action FKs by dirtying
        # the enumerated plan dict directly (bypasses local FK
        # constraints).
        plan = importer.enumerate_plan(db)
        plan.space["closed_by_action_id"] = "cc_leaked_close"
        plan.space["frozen_by_action_id"] = "cc_leaked_freeze"

        prod, prod_lindsey_id, prod_places = _make_sqlite_prod()
        importer.insert_prod_rows(
            plan, prod, prod_lindsey_id,
            prod_location_id=importer._resolve_prod_location_id(prod),
            prod_place_ids_by_slug=prod_places,
        )
        prod.flush()
        prod_space = prod.query(Space).filter(
            Space.slug == "moonlit-circle"
        ).first()
        assert prod_space.closed_by_action_id is None
        assert prod_space.frozen_by_action_id is None

    def test_single_lindsey_creator_membership(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod, prod_lindsey_id, prod_places = _make_sqlite_prod()
        importer.insert_prod_rows(
            plan, prod, prod_lindsey_id,
            prod_location_id=importer._resolve_prod_location_id(prod),
            prod_place_ids_by_slug=prod_places,
        )
        prod.flush()
        prod_space = prod.query(Space).filter(
            Space.slug == "moonlit-circle"
        ).first()
        mems = prod.query(SpaceMembership).filter(
            SpaceMembership.space_id == prod_space.id
        ).all()
        assert len(mems) == 1
        assert mems[0].user_id == prod_lindsey_id
        assert mems[0].role == SpaceRole.creator
        assert mems[0].status == SpaceMembershipStatus.active

    def test_spaceplace_uses_prod_peninsula_id(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod, prod_lindsey_id, prod_places = _make_sqlite_prod()
        importer.insert_prod_rows(
            plan, prod, prod_lindsey_id,
            prod_location_id=importer._resolve_prod_location_id(prod),
            prod_place_ids_by_slug=prod_places,
        )
        prod.flush()
        prod_space = prod.query(Space).filter(
            Space.slug == "moonlit-circle"
        ).first()
        bridges = prod.query(SpacePlace).filter(
            SpacePlace.space_id == prod_space.id
        ).all()
        assert len(bridges) == 1
        assert bridges[0].place_id == prod_places["mornington-penninsula"]
        # Never the local typo Place UUID.
        assert bridges[0].place_id != mini_moonlit["place_id_typo"]
        # And the prod Place carries the CORRECTED slug.
        prod_pl = prod.query(Place).filter(
            Place.id == bridges[0].place_id
        ).first()
        assert prod_pl.slug == "mornington-peninsula"

    def test_pathway_forced_to_draft_and_no_subtree(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod, prod_lindsey_id, prod_places = _make_sqlite_prod()
        importer.insert_prod_rows(
            plan, prod, prod_lindsey_id,
            prod_location_id=importer._resolve_prod_location_id(prod),
            prod_place_ids_by_slug=prod_places,
        )
        prod.flush()
        prod_space = prod.query(Space).filter(
            Space.slug == "moonlit-circle"
        ).first()
        pws = prod.query(Pathway).filter(
            Pathway.space_id == prod_space.id
        ).all()
        assert len(pws) == 1
        pw = pws[0]
        assert pw.slug == "a-quiet-evening-reset"
        assert getattr(pw.status, "value", pw.status) == "draft"
        # No section/step/block/about-block was created.
        assert prod.query(PathwaySection).filter(
            PathwaySection.pathway_id == pw.id
        ).count() == 0
        assert prod.query(PathwayStep).filter(
            PathwayStep.pathway_id == pw.id
        ).count() == 0
        assert prod.query(PathwayAboutBlock).filter(
            PathwayAboutBlock.pathway_id == pw.id
        ).count() == 0

    def test_orphan_media_not_created_in_prod(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod, prod_lindsey_id, prod_places = _make_sqlite_prod()
        importer.insert_prod_rows(
            plan, prod, prod_lindsey_id,
            prod_location_id=importer._resolve_prod_location_id(prod),
            prod_place_ids_by_slug=prod_places,
        )
        prod.flush()
        # Zero CreatorMediaAsset rows created — orphan was excluded.
        assert prod.query(CreatorMediaAsset).count() == 0

    def test_logo_url_preserved_verbatim(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod, prod_lindsey_id, prod_places = _make_sqlite_prod()
        importer.insert_prod_rows(
            plan, prod, prod_lindsey_id,
            prod_location_id=importer._resolve_prod_location_id(prod),
            prod_place_ids_by_slug=prod_places,
        )
        prod.flush()
        prod_space = prod.query(Space).filter(
            Space.slug == "moonlit-circle"
        ).first()
        assert prod_space.logo_url == (
            "/api/uploads/logos/moonlit-circle/"
            "24b64ba4677a47ddb492110816c3d11a_MC_logo.png"
        )


# ---------------------------------------------------------------------------
# verify — must detect every drift on every invariant we promised
# ---------------------------------------------------------------------------


def _run_full_import(
    db: Session,
) -> tuple[Session, importer.MigrationPlan, str, dict[str, str], str]:
    plan = importer.enumerate_plan(db)
    prod, prod_lindsey_id, prod_places = _make_sqlite_prod()
    prod_location_id = importer._resolve_prod_location_id(prod)
    importer.insert_prod_rows(
        plan, prod, prod_lindsey_id,
        prod_location_id=prod_location_id,
        prod_place_ids_by_slug=prod_places,
    )
    prod.commit()
    return prod, plan, prod_location_id, prod_places, prod_lindsey_id


class TestVerify:
    def test_passes_on_clean_import(
        self, db: Session, mini_moonlit,
    ) -> None:
        prod, plan, loc_id, places, lin_id = _run_full_import(db)
        importer.verify(
            plan, prod, MagicMock(),
            "priv", "pub",
            loc_id, places, lin_id,
        )

    def test_catches_wrong_location_id(
        self, db: Session, mini_moonlit,
    ) -> None:
        prod, plan, loc_id, places, lin_id = _run_full_import(db)
        s = prod.query(Space).filter(Space.slug == "moonlit-circle").first()
        s.location_id = "loc_wrong"
        prod.flush()
        with pytest.raises(RuntimeError, match="location_id"):
            importer.verify(
                plan, prod, MagicMock(),
                "priv", "pub",
                loc_id, places, lin_id,
            )

    def test_catches_non_null_closed_action(
        self, db: Session, mini_moonlit,
    ) -> None:
        prod, plan, loc_id, places, lin_id = _run_full_import(db)
        s = prod.query(Space).filter(Space.slug == "moonlit-circle").first()
        s.closed_by_action_id = "cc_leaked"
        prod.flush()
        with pytest.raises(RuntimeError, match="closed_by_action_id"):
            importer.verify(
                plan, prod, MagicMock(),
                "priv", "pub",
                loc_id, places, lin_id,
            )

    def test_catches_non_null_frozen_action(
        self, db: Session, mini_moonlit,
    ) -> None:
        prod, plan, loc_id, places, lin_id = _run_full_import(db)
        s = prod.query(Space).filter(Space.slug == "moonlit-circle").first()
        s.frozen_by_action_id = "cc_leaked"
        prod.flush()
        with pytest.raises(RuntimeError, match="frozen_by_action_id"):
            importer.verify(
                plan, prod, MagicMock(),
                "priv", "pub",
                loc_id, places, lin_id,
            )

    def test_catches_missing_spaceplace(
        self, db: Session, mini_moonlit,
    ) -> None:
        prod, plan, loc_id, places, lin_id = _run_full_import(db)
        s = prod.query(Space).filter(Space.slug == "moonlit-circle").first()
        prod.query(SpacePlace).filter(SpacePlace.space_id == s.id).delete()
        prod.flush()
        with pytest.raises(RuntimeError, match="SpacePlace"):
            importer.verify(
                plan, prod, MagicMock(),
                "priv", "pub",
                loc_id, places, lin_id,
            )

    def test_catches_extra_spaceplace(
        self, db: Session, mini_moonlit,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod, prod_lindsey_id, prod_places = _make_sqlite_prod(
            extra_place_slugs=("hobart",),
        )
        prod_location_id = importer._resolve_prod_location_id(prod)
        importer.insert_prod_rows(
            plan, prod, prod_lindsey_id,
            prod_location_id=prod_location_id,
            prod_place_ids_by_slug=prod_places,
        )
        # Attach an extra unauthorised SpacePlace.
        prod_space = prod.query(Space).filter(
            Space.slug == "moonlit-circle"
        ).first()
        hobart = prod.query(Place).filter(Place.slug == "hobart").first()
        prod.add(SpacePlace(space_id=prod_space.id, place_id=hobart.id))
        prod.commit()

        with pytest.raises(RuntimeError, match="SpacePlace"):
            importer.verify(
                plan, prod, MagicMock(),
                "priv", "pub",
                prod_location_id, prod_places, prod_lindsey_id,
            )

    def test_catches_extra_pathway(
        self, db: Session, mini_moonlit,
    ) -> None:
        prod, plan, loc_id, places, lin_id = _run_full_import(db)
        s = prod.query(Space).filter(Space.slug == "moonlit-circle").first()
        prod.add(Pathway(
            id=_uid("extra"), space_id=s.id, slug="stowaway",
            title="Stowaway", status="draft",
            pathway_type=PathwayType.guided_experience, position=1,
        ))
        prod.commit()
        with pytest.raises(RuntimeError, match="exactly 1 Pathway"):
            importer.verify(
                plan, prod, MagicMock(),
                "priv", "pub",
                loc_id, places, lin_id,
            )

    def test_catches_extra_media_asset(
        self, db: Session, mini_moonlit,
    ) -> None:
        prod, plan, loc_id, places, lin_id = _run_full_import(db)
        s = prod.query(Space).filter(Space.slug == "moonlit-circle").first()
        prod.add(CreatorMediaAsset(
            id=_uid("smug"), space_id=s.id, uploaded_by_user_id=lin_id,
            title="Smuggled", original_filename="s.png",
            stored_filename="uuid_s.png",
            storage_path="media/moonlit-circle/uuid_s.png",
            file_url="/api/uploads/media/moonlit-circle/uuid_s.png",
            mime_type="image/png", media_type="image",
            file_size_bytes=1, extension=".png",
        ))
        prod.commit()
        with pytest.raises(RuntimeError, match="orphan upload must be excluded"):
            importer.verify(
                plan, prod, MagicMock(),
                "priv", "pub",
                loc_id, places, lin_id,
            )

    def test_catches_logo_url_drift(
        self, db: Session, mini_moonlit,
    ) -> None:
        prod, plan, loc_id, places, lin_id = _run_full_import(db)
        s = prod.query(Space).filter(Space.slug == "moonlit-circle").first()
        s.logo_url = "/api/uploads/logos/moonlit-circle/other.png"
        prod.flush()
        with pytest.raises(RuntimeError, match="logo_url"):
            importer.verify(
                plan, prod, MagicMock(),
                "priv", "pub",
                loc_id, places, lin_id,
            )

    def test_catches_r2_head_failure(
        self, db: Session, mini_moonlit,
    ) -> None:
        prod, plan, loc_id, places, lin_id = _run_full_import(db)
        client = MagicMock()
        client.head_object.side_effect = RuntimeError("not found")
        with pytest.raises(RuntimeError, match="R2 HEAD failed"):
            importer.verify(
                plan, prod, client,
                "priv", "pub",
                loc_id, places, lin_id,
            )


# ---------------------------------------------------------------------------
# R2 upload — routing + rollback
# ---------------------------------------------------------------------------


@pytest.fixture
def upload_source(monkeypatch, tmp_path):
    monkeypatch.setattr(importer, "UPLOAD_DIR_LOCAL", tmp_path)
    (tmp_path / "logos" / "moonlit-circle").mkdir(parents=True)
    (tmp_path / "logos" / "moonlit-circle" / "logo.png").write_bytes(b"LOGOBYTES")
    return tmp_path


class TestR2Upload:
    def test_uploads_logo_to_private_bucket(self, upload_source) -> None:
        client = MagicMock()
        uploaded = importer.upload_r2_objects(
            keys=["logos/moonlit-circle/logo.png"],
            r2_client=client,
            bucket_private="priv",
            bucket_public="pub",
        )
        assert uploaded == [("priv", "logos/moonlit-circle/logo.png")]
        assert client.put_object.call_args.kwargs["Bucket"] == "priv"
        assert client.put_object.call_args.kwargs["Body"] == b"LOGOBYTES"
        client.head_object.assert_called()

    def test_raises_when_local_file_missing(self, upload_source) -> None:
        client = MagicMock()
        with pytest.raises(importer.R2UploadError, match="missing"):
            importer.upload_r2_objects(
                keys=["logos/moonlit-circle/nope.png"],
                r2_client=client,
                bucket_private="priv", bucket_public="pub",
            )

    def test_rollback_deletes_uploaded_set(self) -> None:
        client = MagicMock()
        importer.rollback_r2(
            uploaded=[("priv", "logos/moonlit-circle/logo.png")],
            r2_client=client,
        )
        client.delete_object.assert_called_once_with(
            Bucket="priv", Key="logos/moonlit-circle/logo.png",
        )

    def test_rollback_swallows_delete_errors(self) -> None:
        client = MagicMock()
        client.delete_object.side_effect = RuntimeError("gone")
        # Must NOT raise — rollback is best-effort.
        importer.rollback_r2([("priv", "x")], client)


# ---------------------------------------------------------------------------
# Module import sanity
# ---------------------------------------------------------------------------


class TestModuleImportsCleanly:
    def test_constants_are_locked(self) -> None:
        assert importer.SOURCE_SLUG == "moonlit-circle"
        assert importer.INCLUDED_PATHWAY_SLUGS == {"a-quiet-evening-reset"}
        assert importer.PROD_OWNER_EMAIL == "lindsey@hilliard.net.au"
        assert importer.MOONLIT_LOCATION_KEY == "location-05"
        assert importer.LOCAL_TO_PROD_PLACE_SLUGS == {
            "mornington-penninsula": "mornington-peninsula",
        }
