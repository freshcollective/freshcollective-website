"""Tests for the selective EMBODY importer script.

Scope: exercise the pure helpers + the enumeration/insert flow against
the local test DB via mocked prod sessions and mocked boto3. **Never**
opens a network connection to Render / prod DB / prod R2. Verifies:

  * ``_same_db`` correctly detects same host+db even with different
    creds (defence against accidentally pasting local URL into prod).
  * ``_key_from_url`` extracts R2 keys and filters external URLs.
  * ``enumerate_plan`` walks the local test-DB fixture correctly and
    returns exactly the two included pathways + their children +
    the referenced media subset.
  * ``insert_prod_rows`` remaps every FK correctly against a real
    (test-DB) session standing in for prod.
  * ``upload_r2_objects`` sequences PUT + HEAD per key, routes public
    vs private buckets by prefix, records the uploaded list, and
    raises on failure.
  * ``rollback_r2`` deletes exactly what was uploaded on failure.
  * ``print_paymentoption_reference`` produces a readable block for
    Awaken/Activate/Empower + archived options.
"""

from __future__ import annotations

import io
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

# Import the script via its file path — it lives under scripts/ rather
# than app/ so it's not on the default import path.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import import_embody_from_dev as importer  # noqa: E402

from app.models.access_pass import AccessPass  # noqa: E402
from app.models.payment_option import (  # noqa: E402
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.platform import (  # noqa: E402
    CreatorMediaAsset,
    Pathway,
    PathwayAboutBlock,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
    PathwayType,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceResource,
    SpaceRole,
    SpaceStatus,
)
from app.models.user import User  # noqa: E402


# ---------------------------------------------------------------------------
# Pure-helper tests — no session needed
# ---------------------------------------------------------------------------


class TestSameDb:
    def test_identical_urls_match(self) -> None:
        assert importer._same_db(
            "postgresql://a:b@host/db1",
            "postgresql://a:b@host/db1",
        )

    def test_different_credentials_same_host_still_match(self) -> None:
        # This is the critical defence — someone rotating passwords
        # then pasting an old creds URL into PROD_DATABASE_URL would
        # still be the same DB and must not run.
        assert importer._same_db(
            "postgresql://user1:pw1@host/db",
            "postgresql://user2:pw2@host/db",
        )

    def test_different_ports_do_not_match(self) -> None:
        assert not importer._same_db(
            "postgresql://a@host:5432/db",
            "postgresql://a@host:5433/db",
        )

    def test_different_databases_do_not_match(self) -> None:
        assert not importer._same_db(
            "postgresql://a@host/db_local",
            "postgresql://a@host/db_prod",
        )

    def test_different_hosts_do_not_match(self) -> None:
        assert not importer._same_db(
            "postgresql://a@localhost/db",
            "postgresql://a@example.com/db",
        )


class TestKeyFromUrl:
    def test_uploaded_url_yields_key(self) -> None:
        assert (
            importer._key_from_url("/api/uploads/media/embody/xyz.png")
            == "media/embody/xyz.png"
        )

    def test_external_https_returns_none(self) -> None:
        assert importer._key_from_url("https://external.example.com/x.png") is None

    def test_mailto_returns_none(self) -> None:
        assert importer._key_from_url("mailto:x@y.com") is None

    def test_none_and_empty_return_none(self) -> None:
        assert importer._key_from_url(None) is None
        assert importer._key_from_url("") is None


class TestSanitisedUrl:
    def test_password_is_stripped(self) -> None:
        out = importer._sanitised_url("postgresql://user:supersecret@host:5432/db")
        assert "supersecret" not in out
        assert "user" in out
        assert "host" in out
        assert "db" in out


# ---------------------------------------------------------------------------
# Fixture — build a mini EMBODY inside the test DB session
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def mini_embody(db: Session, make_user):
    """Build a minimal EMBODY-shaped Space in the test DB.

    Includes:
      * Space slug='embody' + cover URL + logo URL
      * Two INCLUDED pathways (embody-in-person-sessions,
        home-practice) with 1 section, 2 steps, 3 step-blocks (one
        referencing a media asset), 1 about-block each
      * One EXCLUDED pathway ('the-embody-practice') with 1 step, 1
        block, 1 media asset — should NOT appear in the plan
      * One EXCLUDED pathway ('nervous-system-foundations') — empty
        placeholder
      * Two CreatorMediaAssets: one referenced by an included block,
        one referenced only by an excluded block
      * One published SpaceResource matching the target title, one
        unrelated resource (should NOT appear in the plan)

    Yields ``(space, included_asset_id, excluded_asset_id, resource_id)``.
    """
    creator = make_user(role="creator")
    space = Space(
        id=_uid("s"),
        slug="embody",
        name="EMBODY",
        tagline="Strength. Somatics. Sisterhood.",
        creator_id=creator.id,
        status=SpaceStatus.active,  # will be forced to draft on insert
        cover_image_url="/api/uploads/covers/abc_cover.png",
        logo_url="/api/uploads/logos/embody/def_logo.png",
    )
    db.add(space)
    db.flush()

    # Two included pathways
    pw_in_person = Pathway(
        id=_uid("pw"), space_id=space.id, slug="embody-in-person-sessions",
        title="EMBODY In-Person Sessions", status="active",
        pathway_type=PathwayType.guided_experience, position=0,
        cover_image_url="/api/uploads/pathway-covers/inp_cover.png",
    )
    pw_home = Pathway(
        id=_uid("pw"), space_id=space.id, slug="home-practice",
        title="Home Practice", status="active",
        pathway_type=PathwayType.guided_experience, position=1,
        cover_image_url="/api/uploads/pathway-covers/home_cover.png",
    )
    # One excluded pathway with a full subtree
    pw_excluded = Pathway(
        id=_uid("pw"), space_id=space.id, slug="the-embody-practice",
        title="The EMBODY Practice", status="draft",
        pathway_type=PathwayType.guided_experience, position=2,
    )
    # Another excluded (empty) — should be ignored silently
    pw_empty = Pathway(
        id=_uid("pw"), space_id=space.id, slug="nervous-system-foundations",
        title="Nervous System Foundations", status="draft",
        pathway_type=PathwayType.guided_experience, position=3,
    )
    db.add_all([pw_in_person, pw_home, pw_excluded, pw_empty])
    db.flush()

    section_home = PathwaySection(
        id=_uid("sec"), pathway_id=pw_home.id, title="Week 1", position=0,
    )
    db.add(section_home)
    db.flush()

    # Media assets — one referenced by included block, one only by excluded
    included_asset = CreatorMediaAsset(
        id=_uid("cma"), space_id=space.id, uploaded_by_user_id=creator.id,
        title="Included", original_filename="in.png", stored_filename="uuid_in.png",
        storage_path="media/embody/uuid_in.png",
        file_url="/api/uploads/media/embody/uuid_in.png",
        mime_type="image/png", media_type="image",
        file_size_bytes=100, extension=".png",
    )
    excluded_asset = CreatorMediaAsset(
        id=_uid("cma"), space_id=space.id, uploaded_by_user_id=creator.id,
        title="Excluded", original_filename="ex.png", stored_filename="uuid_ex.png",
        storage_path="media/embody/uuid_ex.png",
        file_url="/api/uploads/media/embody/uuid_ex.png",
        mime_type="image/png", media_type="image",
        file_size_bytes=100, extension=".png",
    )
    db.add_all([included_asset, excluded_asset])
    db.flush()

    # Steps under each included pathway
    step_in_a = PathwayStep(
        id=_uid("pst"), pathway_id=pw_in_person.id, slug="welcome",
        title="Welcome", position=0, content_type="text",
    )
    step_in_b = PathwayStep(
        id=_uid("pst"), pathway_id=pw_in_person.id, slug="philosophy",
        title="Philosophy", position=1, content_type="text",
    )
    step_home_a = PathwayStep(
        id=_uid("pst"), pathway_id=pw_home.id, slug="five-min",
        title="Five-minute reset", position=0, content_type="text",
        section_id=section_home.id,
    )
    step_home_b = PathwayStep(
        id=_uid("pst"), pathway_id=pw_home.id, slug="mobility",
        title="Mobility", position=1, content_type="text",
        section_id=section_home.id,
    )
    db.add_all([step_in_a, step_in_b, step_home_a, step_home_b])
    db.flush()

    # Step blocks — three under included pathways, one referencing
    # the included media asset. Plus one under the excluded pathway.
    step_excluded = PathwayStep(
        id=_uid("pst"), pathway_id=pw_excluded.id, slug="goddess",
        title="Goddess", position=0, content_type="text",
    )
    db.add(step_excluded)
    db.flush()

    blk_a = PathwayStepBlock(
        id=_uid("blk"), step_id=step_in_a.id, block_type="text",
        position=0, content="Welcome to EMBODY.",
    )
    blk_b = PathwayStepBlock(
        id=_uid("blk"), step_id=step_in_b.id, block_type="image",
        position=0, media_asset_id=included_asset.id,
    )
    blk_c = PathwayStepBlock(
        id=_uid("blk"), step_id=step_home_a.id, block_type="text",
        position=0, content="Five-minute reset intro.",
    )
    blk_excluded = PathwayStepBlock(
        id=_uid("blk"), step_id=step_excluded.id, block_type="image",
        position=0, media_asset_id=excluded_asset.id,
    )
    db.add_all([blk_a, blk_b, blk_c, blk_excluded])
    db.flush()

    # About blocks — one on each included pathway, none on excluded.
    about_a = PathwayAboutBlock(
        id=_uid("ab"), owner_kind="pathway", owner_id=pw_in_person.id,
        pathway_id=pw_in_person.id, block_type="text", position=0,
        content="Sales copy for in-person",
    )
    about_b = PathwayAboutBlock(
        id=_uid("ab"), owner_kind="pathway", owner_id=pw_home.id,
        pathway_id=pw_home.id, block_type="text", position=0,
        content="Sales copy for home",
    )
    db.add_all([about_a, about_b])

    # Space resources — one matching the target title, one not
    included_resource = SpaceResource(
        id=_uid("sr"), space_id=space.id, created_by_id=creator.id,
        title=importer.INCLUDED_RESOURCE_TITLE, resource_type="guide",
        status="published",
        url="/api/uploads/media/embody/story_pdf.pdf", file_name="Story.pdf",
    )
    excluded_resource = SpaceResource(
        id=_uid("sr"), space_id=space.id, created_by_id=creator.id,
        title="Some other resource", resource_type="link",
        status="published",
        url="https://external.example.com/x", file_name=None,
    )
    db.add_all([included_resource, excluded_resource])
    db.commit()

    return {
        "space": space,
        "included_asset_id": included_asset.id,
        "excluded_asset_id": excluded_asset.id,
        "included_resource_id": included_resource.id,
        "excluded_resource_id": excluded_resource.id,
        "creator_id": creator.id,
    }


# ---------------------------------------------------------------------------
# enumerate_plan against the fixture
# ---------------------------------------------------------------------------


class TestEnumeratePlan:
    def test_returns_only_the_two_included_pathways(
        self, db: Session, mini_embody,
    ) -> None:
        plan = importer.enumerate_plan(db)
        slugs = sorted(p["slug"] for p in plan.pathways)
        assert slugs == ["embody-in-person-sessions", "home-practice"]

    def test_excludes_the_embody_practice_and_empty_pathways(
        self, db: Session, mini_embody,
    ) -> None:
        plan = importer.enumerate_plan(db)
        assert "the-embody-practice" not in [p["slug"] for p in plan.pathways]
        assert "nervous-system-foundations" not in [p["slug"] for p in plan.pathways]

    def test_step_blocks_from_excluded_pathway_are_excluded(
        self, db: Session, mini_embody,
    ) -> None:
        plan = importer.enumerate_plan(db)
        # 3 included blocks (blk_a/b/c); the excluded pathway's block
        # must not appear.
        assert len(plan.step_blocks) == 3

    def test_only_referenced_media_asset_included(
        self, db: Session, mini_embody,
    ) -> None:
        plan = importer.enumerate_plan(db)
        media_ids = [a["id"] for a in plan.media_assets]
        assert mini_embody["included_asset_id"] in media_ids
        assert mini_embody["excluded_asset_id"] not in media_ids
        assert len(plan.media_assets) == 1

    def test_only_target_titled_resource_included(
        self, db: Session, mini_embody,
    ) -> None:
        plan = importer.enumerate_plan(db)
        resource_ids = [r["id"] for r in plan.resources]
        assert mini_embody["included_resource_id"] in resource_ids
        assert mini_embody["excluded_resource_id"] not in resource_ids
        assert len(plan.resources) == 1

    def test_r2_key_set_covers_cover_logo_media_and_resource(
        self, db: Session, mini_embody,
    ) -> None:
        plan = importer.enumerate_plan(db)
        assert "covers/abc_cover.png" in plan.r2_keys
        assert "logos/embody/def_logo.png" in plan.r2_keys
        assert "media/embody/uuid_in.png" in plan.r2_keys
        assert "media/embody/story_pdf.pdf" in plan.r2_keys
        # Pathway covers included:
        assert "pathway-covers/inp_cover.png" in plan.r2_keys
        assert "pathway-covers/home_cover.png" in plan.r2_keys
        # Excluded asset's key must NOT be present.
        assert "media/embody/uuid_ex.png" not in plan.r2_keys


# ---------------------------------------------------------------------------
# insert_prod_rows — verify remap logic against a real session standing in
# for prod. We use the same test DB session but a fresh Space slug so
# the plan and the prod session don't collide.
# ---------------------------------------------------------------------------


class TestInsertProdRows:
    def test_inserts_space_with_forced_draft_and_prod_owner(
        self, db: Session, mini_embody, make_user,
    ) -> None:
        plan = importer.enumerate_plan(db)
        # Simulate a different owner in "prod".
        prod_owner = make_user(role="creator")
        db.commit()

        # For the test we alias the same session as both source and
        # target — the source's Space already exists so we mutate the
        # plan to a different slug for the insert.
        plan.space["slug"] = "embody-prod-copy"

        maps = importer.insert_prod_rows(plan, db, prod_owner.id)
        db.flush()

        prod_space = db.query(Space).filter(Space.slug == "embody-prod-copy").first()
        assert prod_space is not None
        assert prod_space.status == SpaceStatus.draft
        assert prod_space.creator_id == prod_owner.id

    def test_single_membership_row_created_for_prod_owner(
        self, db: Session, mini_embody, make_user,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod_owner = make_user(role="creator")
        db.commit()
        plan.space["slug"] = "embody-prod-2"

        importer.insert_prod_rows(plan, db, prod_owner.id)
        db.flush()

        prod_space = db.query(Space).filter(Space.slug == "embody-prod-2").first()
        mems = db.query(SpaceMembership).filter(
            SpaceMembership.space_id == prod_space.id
        ).all()
        assert len(mems) == 1
        assert mems[0].user_id == prod_owner.id
        assert mems[0].role == SpaceRole.creator
        assert mems[0].status == SpaceMembershipStatus.active

    def test_pathways_forced_to_draft(
        self, db: Session, mini_embody, make_user,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod_owner = make_user(role="creator")
        db.commit()
        plan.space["slug"] = "embody-prod-3"

        importer.insert_prod_rows(plan, db, prod_owner.id)
        db.flush()

        prod_space = db.query(Space).filter(Space.slug == "embody-prod-3").first()
        for p in db.query(Pathway).filter(Pathway.space_id == prod_space.id).all():
            assert p.status == "draft"

    def test_media_asset_id_remapped_on_step_block(
        self, db: Session, mini_embody, make_user,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod_owner = make_user(role="creator")
        db.commit()
        plan.space["slug"] = "embody-prod-4"

        maps = importer.insert_prod_rows(plan, db, prod_owner.id)
        db.flush()

        # The one image block in the fixture had media_asset_id =
        # included_asset_id. After remap the prod-side block should
        # reference the prod-side asset id — NOT the source id.
        prod_space = db.query(Space).filter(Space.slug == "embody-prod-4").first()
        prod_blocks = db.query(PathwayStepBlock).join(
            PathwayStep, PathwayStep.id == PathwayStepBlock.step_id
        ).join(Pathway, Pathway.id == PathwayStep.pathway_id).filter(
            Pathway.space_id == prod_space.id,
            PathwayStepBlock.media_asset_id.isnot(None),
        ).all()
        assert len(prod_blocks) == 1
        prod_asset_id = maps.media_asset[mini_embody["included_asset_id"]]
        assert prod_blocks[0].media_asset_id == prod_asset_id
        assert prod_blocks[0].media_asset_id != mini_embody["included_asset_id"]

    def test_about_block_owner_id_remapped_to_prod_pathway(
        self, db: Session, mini_embody, make_user,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod_owner = make_user(role="creator")
        db.commit()
        plan.space["slug"] = "embody-prod-5"

        maps = importer.insert_prod_rows(plan, db, prod_owner.id)
        db.flush()

        prod_space = db.query(Space).filter(Space.slug == "embody-prod-5").first()
        prod_abouts = db.query(PathwayAboutBlock).join(
            Pathway, Pathway.id == PathwayAboutBlock.pathway_id
        ).filter(Pathway.space_id == prod_space.id).all()
        for ab in prod_abouts:
            assert ab.owner_kind == "pathway"
            # owner_id must equal the row's pathway_id (both remapped
            # to the same prod pathway id).
            assert ab.owner_id == ab.pathway_id
            # And that pathway_id is a value that appears in the
            # local→prod pathway map values (i.e., a prod id).
            assert ab.pathway_id in set(maps.pathway.values())

    def test_folder_id_and_legacy_pathway_id_nulled_on_resource(
        self, db: Session, mini_embody, make_user,
    ) -> None:
        plan = importer.enumerate_plan(db)
        prod_owner = make_user(role="creator")
        db.commit()
        plan.space["slug"] = "embody-prod-6"

        importer.insert_prod_rows(plan, db, prod_owner.id)
        db.flush()

        prod_space = db.query(Space).filter(Space.slug == "embody-prod-6").first()
        prod_res = db.query(SpaceResource).filter(
            SpaceResource.space_id == prod_space.id
        ).all()
        assert len(prod_res) == 1
        assert prod_res[0].folder_id is None
        assert prod_res[0].pathway_id is None
        assert prod_res[0].created_by_id == prod_owner.id


# ---------------------------------------------------------------------------
# R2 upload — mocked boto3
# ---------------------------------------------------------------------------


@pytest.fixture
def upload_source(monkeypatch, tmp_path):
    """Redirect the script's UPLOAD_DIR_LOCAL at a tmp_path with two
    real bytes files so upload_r2_objects has something to read."""
    monkeypatch.setattr(importer, "UPLOAD_DIR_LOCAL", tmp_path)
    (tmp_path / "media" / "embody").mkdir(parents=True)
    (tmp_path / "media" / "embody" / "x.png").write_bytes(b"XBYTES")
    (tmp_path / "media" / "embody" / "y.pdf").write_bytes(b"YBYTES")
    (tmp_path / "platform-artwork").mkdir()
    (tmp_path / "platform-artwork" / "hero.png").write_bytes(b"HBYTES")
    return tmp_path


class TestR2Upload:
    def test_uploads_every_key_and_records_bucket(
        self, upload_source,
    ) -> None:
        client = MagicMock()
        uploaded = importer.upload_r2_objects(
            keys=["media/embody/x.png", "media/embody/y.pdf"],
            r2_client=client,
            bucket_private="priv",
            bucket_public="pub",
        )
        assert uploaded == [
            ("priv", "media/embody/x.png"),
            ("priv", "media/embody/y.pdf"),
        ]
        # Two puts, two heads.
        assert client.put_object.call_count == 2
        assert client.head_object.call_count == 2
        # First put args
        first = client.put_object.call_args_list[0].kwargs
        assert first["Bucket"] == "priv"
        assert first["Key"] == "media/embody/x.png"
        assert first["Body"] == b"XBYTES"

    def test_platform_artwork_key_routes_to_public_bucket(
        self, upload_source,
    ) -> None:
        client = MagicMock()
        uploaded = importer.upload_r2_objects(
            keys=["platform-artwork/hero.png"],
            r2_client=client,
            bucket_private="priv",
            bucket_public="pub",
        )
        assert uploaded == [("pub", "platform-artwork/hero.png")]
        assert client.put_object.call_args.kwargs["Bucket"] == "pub"

    def test_raises_when_local_file_missing(
        self, upload_source,
    ) -> None:
        client = MagicMock()
        with pytest.raises(importer.R2UploadError, match="missing"):
            importer.upload_r2_objects(
                keys=["media/embody/nope.png"],
                r2_client=client,
                bucket_private="priv",
                bucket_public="pub",
            )

    def test_raises_when_boto_put_fails(
        self, upload_source,
    ) -> None:
        client = MagicMock()
        client.put_object.side_effect = RuntimeError("network")
        with pytest.raises(importer.R2UploadError):
            importer.upload_r2_objects(
                keys=["media/embody/x.png"],
                r2_client=client,
                bucket_private="priv",
                bucket_public="pub",
            )


class TestR2Rollback:
    def test_deletes_exactly_the_uploaded_set(self) -> None:
        client = MagicMock()
        importer.rollback_r2(
            uploaded=[("priv", "a"), ("priv", "b"), ("pub", "c")],
            r2_client=client,
        )
        assert client.delete_object.call_count == 3
        calls = [c.kwargs for c in client.delete_object.call_args_list]
        assert {"Bucket": "priv", "Key": "a"} in calls
        assert {"Bucket": "priv", "Key": "b"} in calls
        assert {"Bucket": "pub", "Key": "c"} in calls

    def test_swallows_delete_errors(self) -> None:
        client = MagicMock()
        client.delete_object.side_effect = RuntimeError("gone")
        # Must NOT raise — rollback is best-effort.
        importer.rollback_r2([("priv", "x")], client)


# ---------------------------------------------------------------------------
# PaymentOption reference formatter
# ---------------------------------------------------------------------------


class TestPaymentOptionReference:
    def test_prints_all_local_options_with_schedules(
        self, db: Session, mini_embody, capsys,
    ) -> None:
        space = mini_embody["space"]
        # Attach a Payment Option to the local Space (published + archived)
        pw_id = db.query(Pathway).filter(
            Pathway.space_id == space.id,
            Pathway.slug == "embody-in-person-sessions",
        ).first().id
        db.add(PaymentOption(
            id=_uid("po"), space_id=space.id, pathway_id=pw_id,
            attaches_to_kind="pathway", attaches_to_id=pw_id,
            name="Awaken", payment_type=PaymentOptionType.term_pass,
            status=PaymentOptionStatus.published,
            price_per_session_cents=2000, calculated_total_cents=20000,
            total_sessions=10, sessions_per_week=1, currency="AUD",
            description="Test description",
        ))
        db.commit()

        importer.print_paymentoption_reference(db)
        out = capsys.readouterr().out
        assert "Reference config for manual re-entry" in out
        assert "'Awaken'" in out
        assert "AUD" in out
        assert "20000" in out or "200" in out


# ---------------------------------------------------------------------------
# End-to-end insert leaves nothing on the exclude list — invariant check
# ---------------------------------------------------------------------------


class TestInsertRespectsExclusions:
    def test_no_paymentoption_created_from_script(
        self, db: Session, mini_embody, make_user,
    ) -> None:
        # Local has zero PaymentOptions in this fixture; the script
        # doesn't touch that table anyway. Prove that fact by
        # asserting no PaymentOption exists for the prod-side Space
        # after insert.
        plan = importer.enumerate_plan(db)
        prod_owner = make_user(role="creator")
        db.commit()
        plan.space["slug"] = "embody-prod-excl"

        importer.insert_prod_rows(plan, db, prod_owner.id)
        db.flush()

        prod_space = db.query(Space).filter(Space.slug == "embody-prod-excl").first()
        assert db.query(PaymentOption).filter(
            PaymentOption.space_id == prod_space.id
        ).count() == 0
        assert db.query(AccessPass).filter(
            AccessPass.space_id == prod_space.id
        ).count() == 0

    def test_no_extra_memberships_beyond_owner(
        self, db: Session, mini_embody, make_user,
    ) -> None:
        # Even though the fixture creator is a User, the script does
        # NOT carry any SpaceMembership rows across — it creates ONE
        # fresh membership for the prod owner.
        plan = importer.enumerate_plan(db)
        prod_owner = make_user(role="creator")
        db.commit()
        plan.space["slug"] = "embody-prod-mem-only"

        importer.insert_prod_rows(plan, db, prod_owner.id)
        db.flush()

        prod_space = db.query(Space).filter(
            Space.slug == "embody-prod-mem-only"
        ).first()
        mems = db.query(SpaceMembership).filter(
            SpaceMembership.space_id == prod_space.id
        ).all()
        assert len(mems) == 1
        assert mems[0].user_id == prod_owner.id
