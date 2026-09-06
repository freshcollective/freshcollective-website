#!/usr/bin/env python
"""One-shot selective import of the World Builders authored content
from local dev into the EXISTING production World Builders Space.

Unlike the EMBODY / Moonlit importers, this script does NOT create a
new Space. The production World Builders Space is platform-owned
(``creator_id=None``, ``auto_grant_role='creator'``) and was seeded by
a platform migration. This importer:

  * UPDATES the existing prod parent Space's authored fields (explicit
    allowlist), leaving every platform-owned / seed-managed field
    untouched. NEVER-TOUCH fields are snapshotted at preflight and
    refetched immediately before the UPDATE — any drift aborts.
  * INSERTS the two substantive local pathways
    (``world-builders-start-here`` and ``creating-your-collective``)
    with their sections/steps/blocks/about-blocks, both forced to
    draft. Refuses if either target slug already exists in prod.
  * INSERTS only the CreatorMediaAssets actually referenced by those
    two pathways (orphan uploads excluded).

Explicitly excluded from this migration:

  * Parent decorative island artwork (``island_artwork_url`` /
    ``island_artwork_status`` NOT updated; NOT uploaded to R2).
    ``island_artwork_prompt`` IS updated because it is authored text.
  * All seven empty placeholder pathways (``pathways``, ``gatherings``,
    ``members``, ``conversations``, ``payments``, ``privacy``,
    ``growing-your-collective``).
  * All 13 orphan / unreferenced CreatorMediaAssets on the local Space.
  * SpaceMembership rows (World Builders uses ``auto_grant_role``).
  * Default ConversationChannels (the platform recreates
    "Start Here" / "Common Room" on first entry).
  * SpaceResource / LibraryFolder / SpaceInvitation /
    SpaceAccessRequest / ManualMember / SpaceMemberNotificationPrefs /
    CommunityPost / PostComment / reactions / Poll / Event /
    EventSeries / EventBooking / OfferPage / PaymentOption /
    PaymentOptionSchedule / PaymentOptionGrant / AccessPass /
    PathwayEntitlement / PaymentTransaction / PurchaseIntent /
    PurchasePlan / StepProgress / Enrollment /
    PathwayStepManualRelease / StepResource / StepComment.

Shared-reference remapping (never copy local UUIDs):

  * ``Space.location_id`` → resolved by prod ``Location.key='the-commons'``
    (the Cornerstone Location for World Builders).
  * ``CreatorMediaAsset.uploaded_by_user_id`` → prod Lindsey by email.
  * All pathway/section/step/block/about-block IDs are freshly
    generated and remapped through ``IdMaps``.

Usage — dry-run:
    .venv/bin/python -m scripts.import_world_builders_from_dev

Usage — commit:
    .venv/bin/python -m scripts.import_world_builders_from_dev --commit

Required env vars (for --commit):
    DATABASE_URL             local dev DB (already in backend/.env)
    PROD_DATABASE_URL        prod DB (Render fc-db External Connection
                             String — NEVER commit to .env)
    R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY
    R2_BUCKET_PRIVATE / R2_BUCKET_PUBLIC / R2_PUBLIC_BASE_URL
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except ImportError:
    pass

import app.main  # noqa: F401,E402

from sqlalchemy import create_engine, inspect as sa_inspect, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.models.platform import (  # noqa: E402
    CreatorMediaAsset,
    Location,
    Pathway,
    PathwayAboutBlock,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
    Space,
)
from app.models.user import User  # noqa: E402


# ---------------------------------------------------------------------------
# Constants — the exact locked scope
# ---------------------------------------------------------------------------

SOURCE_SLUG = "world-builders"

SUBSTANTIVE_PATHWAY_SLUGS: tuple[str, ...] = (
    "world-builders-start-here",
    "creating-your-collective",
)

# These 7 exist locally but carry no authored content and are NOT
# migrated. Verified during verify() to make sure none of them
# accidentally landed in prod.
PLACEHOLDER_PATHWAY_SLUGS: tuple[str, ...] = (
    "pathways",
    "gatherings",
    "members",
    "conversations",
    "payments",
    "privacy",
    "growing-your-collective",
)

PROD_OWNER_EMAIL = "lindsey@hilliard.net.au"

# The Cornerstone Location the platform assigns to World Builders.
# Natural key stable across environments (both Mother World seeded it
# in prod under the same key that local carries).
WB_LOCATION_KEY = "the-commons"

# Parent Space fields the importer is allowed to overwrite from the
# local authored copy. Deliberately opt-in — everything not listed
# here is treated as NEVER-TOUCH.
#
# NOTE: island_artwork_url and island_artwork_status are DELIBERATELY
# excluded from this list (see the docstring). island_artwork_prompt
# IS included because it is authored text.
PARENT_UPDATABLE_FIELDS: tuple[str, ...] = (
    "tagline",
    "description",
    "about_content",
    "identity_statement",
    "welcome_message",
    "included_access_summary",
    "paid_content_summary",
    "pricing_note",
    "guidance_start_title",
    "guidance_start_body",
    "guidance_focus_title",
    "guidance_focus_body",
    "guidance_links_title",
    "guidance_links_body",
    "island_artwork_prompt",
    "themes",
    "atmosphere_keys",
    "colour_story_key",
    "landscape_key",
    "element_keys",
    "archipelago_hint",
    "cover_image_url",
    "logo_url",
)

# location_id is special-cased: resolved to the prod Location keyed
# ``the-commons`` at preflight; never copied verbatim from local.

# Fields snapshotted at preflight and refetched immediately before the
# UPDATE. Any drift aborts. Also verified after commit to prove nothing
# platform-owned was disturbed. Timestamps are excluded (DB-managed).
PARENT_NEVER_TOUCH_FIELDS: tuple[str, ...] = (
    "id",
    "slug",
    "name",
    "status",
    "creator_id",
    "auto_grant_role",
    "kind",
    "connection_style",
    "visibility",
    "is_public",
    "pricing_type",
    "pricing_amount_cents",
    "pricing_currency",
    "has_paid_internal_content",
    "show_member_directory",
    "timezone",
    "island_artwork_url",
    "island_artwork_status",
    "island_artwork_version",
    "island_artwork_generated_at",
    "suspended_at",
    "suspended_until",
    "suspension_reason",
    "closed_at",
    "closure_reason",
    "closed_by_action_id",
    "frozen_at",
    "frozen_until",
    "freeze_reason",
    "frozen_by_action_id",
)

UPLOAD_DIR_LOCAL = Path(__file__).resolve().parent.parent / "uploads"

log = logging.getLogger("import_world_builders")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MigrationContext:
    local_session: Session
    prod_session: Session
    prod_lindsey_id: str
    prod_wb_space_id: str        # existing prod WB Space id (never recreated)
    prod_the_commons_id: str     # resolved via Location.key='the-commons'
    parent_never_touch_snapshot: dict[str, Any]
    r2_client: Any
    r2_bucket_private: str
    r2_bucket_public: str
    commit: bool
    yes_i_am_sure: bool


@dataclass
class MigrationPlan:
    """Rows the script intends to migrate, held as detached dicts."""
    local_space: dict
    parent_updates: dict[str, Any]                # column → value for prod UPDATE
    pathways: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    step_blocks: list[dict] = field(default_factory=list)
    about_blocks: list[dict] = field(default_factory=list)
    media_assets: list[dict] = field(default_factory=list)
    r2_keys: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict:
    cols = [c.name for c in sa_inspect(row.__class__).columns]
    return {c: getattr(row, c) for c in cols}


def _key_from_url(url: str | None) -> str | None:
    if not url:
        return None
    prefix = "/api/uploads/"
    if url.startswith(prefix):
        return url[len(prefix):]
    return None


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


class PreflightError(RuntimeError):
    """A preflight check failed — script must not proceed to writes."""


def preflight(args: argparse.Namespace) -> MigrationContext:
    local_url = os.environ.get("DATABASE_URL")
    if not local_url:
        raise PreflightError("DATABASE_URL is not set (need local dev DB).")
    prod_url = os.environ.get("PROD_DATABASE_URL")
    if not prod_url:
        raise PreflightError(
            "PROD_DATABASE_URL is not set — export it from the Render "
            "fc-db External Connection String for this shell only."
        )
    if _same_db(local_url, prod_url):
        raise PreflightError(
            "DATABASE_URL and PROD_DATABASE_URL resolve to the same "
            "host+database. Refusing to run."
        )

    r2_vars = _load_r2_env()

    log.info("Connecting to local DB %s", _sanitised_url(local_url))
    local_engine = create_engine(local_url, future=True)
    local_session = sessionmaker(bind=local_engine, future=True)()
    local_session.execute(select(1)).scalar_one()

    log.info("Connecting to prod DB %s", _sanitised_url(prod_url))
    prod_engine = create_engine(prod_url, future=True)
    prod_session = sessionmaker(bind=prod_engine, future=True)()
    prod_session.execute(select(1)).scalar_one()

    r2_client = _build_r2_client(r2_vars)
    r2_client.head_bucket(Bucket=r2_vars["bucket_private"])

    prod_lindsey = prod_session.query(User).filter(
        User.email == PROD_OWNER_EMAIL
    ).first()
    if not prod_lindsey:
        raise PreflightError(
            f"Prod user with email {PROD_OWNER_EMAIL!r} not found."
        )

    prod_wb_space_id, snapshot = _validate_and_snapshot_prod_wb(prod_session)
    prod_the_commons_id = _resolve_prod_location_id(prod_session)

    return MigrationContext(
        local_session=local_session,
        prod_session=prod_session,
        prod_lindsey_id=prod_lindsey.id,
        prod_wb_space_id=prod_wb_space_id,
        prod_the_commons_id=prod_the_commons_id,
        parent_never_touch_snapshot=snapshot,
        r2_client=r2_client,
        r2_bucket_private=r2_vars["bucket_private"],
        r2_bucket_public=r2_vars["bucket_public"],
        commit=args.commit,
        yes_i_am_sure=args.yes_i_am_sure,
    )


def _validate_and_snapshot_prod_wb(
    prod_session: Session,
) -> tuple[str, dict[str, Any]]:
    """WB-specific prod checks. Refuses on missing Space, non-null
    creator_id, or a pre-existing substantive pathway slug. Returns
    the prod Space id and the NEVER-TOUCH snapshot."""
    prod_wb = prod_session.query(Space).filter(
        Space.slug == SOURCE_SLUG
    ).first()
    if prod_wb is None:
        raise PreflightError(
            f"Prod Space with slug {SOURCE_SLUG!r} not found. This "
            "importer does not create the parent — it updates an "
            "existing platform-managed World Builders Space. Aborting."
        )
    if prod_wb.creator_id is not None:
        raise PreflightError(
            f"Prod Space {SOURCE_SLUG!r} has creator_id="
            f"{prod_wb.creator_id!r} — expected NULL (platform-owned). "
            "Refusing to migrate into a reparented Space."
        )
    if prod_wb.auto_grant_role != "creator":
        raise PreflightError(
            f"Prod Space {SOURCE_SLUG!r} has auto_grant_role="
            f"{prod_wb.auto_grant_role!r} — expected 'creator' "
            "(platform contract). Refusing."
        )
    for slug in SUBSTANTIVE_PATHWAY_SLUGS:
        existing = prod_session.query(Pathway).filter(
            Pathway.space_id == prod_wb.id,
            Pathway.slug == slug,
        ).first()
        if existing is not None:
            raise PreflightError(
                f"Prod Pathway with slug {slug!r} already exists in the "
                f"prod World Builders Space (id={existing.id}). This "
                "importer is insert-only. Delete the conflicting row "
                "and rerun."
            )
    snapshot = _snapshot_never_touch(prod_wb)
    return prod_wb.id, snapshot


def _resolve_prod_location_id(prod_session: Session) -> str:
    loc = prod_session.query(Location).filter(
        Location.key == WB_LOCATION_KEY
    ).first()
    if loc is None:
        raise PreflightError(
            f"Prod Location with key {WB_LOCATION_KEY!r} not found. "
            "Run the Mother World migration first."
        )
    return loc.id


def _snapshot_never_touch(space: Space) -> dict[str, Any]:
    return {f: getattr(space, f) for f in PARENT_NEVER_TOUCH_FIELDS}


def _load_r2_env() -> dict[str, str]:
    keys = (
        "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_PRIVATE", "R2_BUCKET_PUBLIC", "R2_PUBLIC_BASE_URL",
    )
    values = {k: os.environ.get(k) for k in keys}
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise PreflightError(
            "Missing R2 env vars: " + ", ".join(missing)
        )
    return {
        "account_id": values["R2_ACCOUNT_ID"] or "",
        "access_key_id": values["R2_ACCESS_KEY_ID"] or "",
        "secret_access_key": values["R2_SECRET_ACCESS_KEY"] or "",
        "bucket_private": values["R2_BUCKET_PRIVATE"] or "",
        "bucket_public": values["R2_BUCKET_PUBLIC"] or "",
        "public_base_url": values["R2_PUBLIC_BASE_URL"] or "",
    }


def _build_r2_client(r2_vars: dict[str, str]) -> Any:
    import boto3
    endpoint = f"https://{r2_vars['account_id']}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=r2_vars["access_key_id"],
        aws_secret_access_key=r2_vars["secret_access_key"],
        region_name="auto",
    )


def _same_db(url_a: str, url_b: str) -> bool:
    a = urlparse(url_a); b = urlparse(url_b)
    return (a.hostname, a.port, a.path) == (b.hostname, b.port, b.path)


def _sanitised_url(url: str) -> str:
    p = urlparse(url)
    host = p.hostname or "?"
    port = f":{p.port}" if p.port else ""
    return f"{p.scheme}://{p.username or '?'}@{host}{port}{p.path}"


# ---------------------------------------------------------------------------
# Enumerate — build the MigrationPlan from local dev
# ---------------------------------------------------------------------------


def enumerate_plan(
    local_session: Session,
    prod_the_commons_id: str,
) -> MigrationPlan:
    """Read every row the migration will touch from local dev. Runs the
    drift checks and returns a fully-populated MigrationPlan.

    ``prod_the_commons_id`` is threaded through so the plan carries the
    correct remapped ``location_id`` at construction time — no post-hoc
    mutation of the plan needed."""
    space = local_session.query(Space).filter(Space.slug == SOURCE_SLUG).first()
    if not space:
        raise RuntimeError(f"Local Space {SOURCE_SLUG!r} not found.")

    if not space.location_id:
        raise RuntimeError(
            f"Local Space {SOURCE_SLUG!r} has no location_id — expected "
            f"the Cornerstone Location {WB_LOCATION_KEY!r}."
        )
    local_loc = local_session.query(Location).filter(
        Location.id == space.location_id
    ).first()
    if local_loc is None or local_loc.key != WB_LOCATION_KEY:
        actual = local_loc.key if local_loc else "<missing>"
        raise RuntimeError(
            f"Local Space {SOURCE_SLUG!r} location_id resolves to "
            f"Location.key={actual!r}, expected {WB_LOCATION_KEY!r}."
        )

    pathways = local_session.query(Pathway).filter(
        Pathway.space_id == space.id,
        Pathway.slug.in_(SUBSTANTIVE_PATHWAY_SLUGS),
    ).all()
    if len(pathways) != len(SUBSTANTIVE_PATHWAY_SLUGS):
        found = {p.slug for p in pathways}
        missing = set(SUBSTANTIVE_PATHWAY_SLUGS) - found
        raise RuntimeError(
            f"Expected substantive pathways "
            f"{sorted(SUBSTANTIVE_PATHWAY_SLUGS)!r} not all found "
            f"locally; missing: {sorted(missing)!r}."
        )
    pathway_ids = [p.id for p in pathways]

    sections = local_session.query(PathwaySection).filter(
        PathwaySection.pathway_id.in_(pathway_ids)
    ).all()
    steps = local_session.query(PathwayStep).filter(
        PathwayStep.pathway_id.in_(pathway_ids)
    ).all()
    step_ids = [s.id for s in steps]
    step_blocks = local_session.query(PathwayStepBlock).filter(
        PathwayStepBlock.step_id.in_(step_ids)
    ).all() if step_ids else []
    about_blocks = local_session.query(PathwayAboutBlock).filter(
        PathwayAboutBlock.pathway_id.in_(pathway_ids)
    ).all()

    referenced_media_ids: set[str] = set()
    referenced_r2_keys: set[str] = set()

    def _add_key(url: str | None) -> None:
        k = _key_from_url(url)
        if k:
            referenced_r2_keys.add(k)

    for p in pathways:
        _add_key(p.cover_image_url)
    for sec in sections:
        _add_key(sec.banner_image_url)
    for stp in steps:
        _add_key(stp.banner_image_url)
    for b in step_blocks:
        _add_key(b.embed_url)
        if b.media_asset_id:
            referenced_media_ids.add(b.media_asset_id)
    for ab in about_blocks:
        _add_key(ab.embed_url)
        if ab.media_asset_id:
            referenced_media_ids.add(ab.media_asset_id)

    media_assets: list = []
    if referenced_media_ids:
        media_assets = local_session.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id.in_(referenced_media_ids)
        ).all()
        for a in media_assets:
            if a.storage_path:
                referenced_r2_keys.add(a.storage_path)

    parent_updates: dict[str, Any] = {
        f: getattr(space, f) for f in PARENT_UPDATABLE_FIELDS
    }
    # location_id is the one special-cased field — it's resolved to the
    # prod Cornerstone Location by natural key, never copied verbatim
    # from local.
    parent_updates["location_id"] = prod_the_commons_id

    return MigrationPlan(
        local_space=_row_to_dict(space),
        parent_updates=parent_updates,
        pathways=[_row_to_dict(p) for p in pathways],
        sections=[_row_to_dict(s) for s in sections],
        steps=[_row_to_dict(s) for s in steps],
        step_blocks=[_row_to_dict(b) for b in step_blocks],
        about_blocks=[_row_to_dict(b) for b in about_blocks],
        media_assets=[_row_to_dict(a) for a in media_assets],
        r2_keys=sorted(referenced_r2_keys),
    )


# ---------------------------------------------------------------------------
# Summary / confirmation
# ---------------------------------------------------------------------------


def _describe_value(v: Any) -> str:
    if v is None:
        return "<None>"
    if isinstance(v, str):
        if len(v) > 60:
            return f"str[len={len(v)}]"
        return repr(v)
    if isinstance(v, list):
        return f"list[len={len(v)}] {v!r}" if len(v) <= 8 else f"list[len={len(v)}]"
    if isinstance(v, dict):
        return f"dict[len={len(v)}]"
    return repr(v)


def print_summary(plan: MigrationPlan, ctx: MigrationContext) -> None:
    mode = "COMMIT" if ctx.commit else "DRY RUN — no writes will occur"
    print("=" * 74)
    print(f"World Builders selective import — {mode}")
    print("=" * 74)
    print(f"  UPDATE mode:       existing prod Space (NOT creating a new one)")
    print(f"  Prod Space id:     {ctx.prod_wb_space_id}")
    print(f"  Platform contract: creator_id remains NULL, "
          f"auto_grant_role remains 'creator'")
    print(f"  Prod Lindsey:      {PROD_OWNER_EMAIL} → id={ctx.prod_lindsey_id}")
    print(f"                     (used only as uploaded_by on CreatorMediaAsset rows)")
    print(f"  Prod Location:     {WB_LOCATION_KEY!r} → id={ctx.prod_the_commons_id}")
    print(f"  Prod R2 buckets:   {ctx.r2_bucket_private} (private) / "
          f"{ctx.r2_bucket_public} (public)")
    print()

    prod_space = ctx.prod_session.query(Space).filter(
        Space.id == ctx.prod_wb_space_id
    ).first()

    print(f"Parent Space fields to UPDATE ({len(plan.parent_updates)} fields):")
    for f in sorted(plan.parent_updates):
        new_val = plan.parent_updates[f]
        old_val = getattr(prod_space, f)
        print(f"    {f:26s}: {_describe_value(old_val)}  →  {_describe_value(new_val)}")
    print()

    print(f"Parent Space fields NEVER touched "
          f"({len(PARENT_NEVER_TOUCH_FIELDS)} fields, snapshotted at preflight):")
    for f in PARENT_NEVER_TOUCH_FIELDS:
        v = ctx.parent_never_touch_snapshot[f]
        print(f"    {f:26s}: {_describe_value(v)}")
    print()

    print("Parent decorative island artwork — EXCLUDED (per approved scope):")
    print(f"  island_artwork_url:    NOT UPDATED "
          f"(remains {ctx.parent_never_touch_snapshot['island_artwork_url']!r})")
    print(f"  island_artwork_status: NOT UPDATED "
          f"(remains {ctx.parent_never_touch_snapshot['island_artwork_status']!r})")
    print(f"  island_artwork_prompt: UPDATED (authored text)")
    print()

    print("Would INSERT in prod (single transaction):")
    print(f"  Pathway              {len(plan.pathways)} rows (both forced to draft)")
    for p in plan.pathways:
        print(f"      - {p['slug']!r}  ({p['title']!r})")
    print(f"  PathwaySection       {len(plan.sections)} rows")
    print(f"  PathwayStep          {len(plan.steps)} rows")
    print(f"  PathwayStepBlock     {len(plan.step_blocks)} rows")
    print(f"  PathwayAboutBlock    {len(plan.about_blocks)} rows")
    print(f"  CreatorMediaAsset    {len(plan.media_assets)} rows (referenced subset)")
    print()

    total = 0
    missing = []
    for k in plan.r2_keys:
        path = UPLOAD_DIR_LOCAL / k
        if path.is_file():
            total += path.stat().st_size
        else:
            missing.append(k)
    print(f"Would upload to R2:  {len(plan.r2_keys)} keys "
          f"(~{total/(1024*1024):.2f} MB)")
    for k in plan.r2_keys:
        print(f"    {k}")
    if missing:
        print()
        print("!! MISSING LOCAL FILES:")
        for k in missing:
            print(f"     {k}")
        raise PreflightError(
            f"{len(missing)} referenced R2 object(s) missing on local disk."
        )
    print()

    print("Exclusions:")
    print(f"  - 7 placeholder pathways: {list(PLACEHOLDER_PATHWAY_SLUGS)}")
    print(f"  - orphan / unreferenced CreatorMediaAssets")
    print(f"  - parent decorative island artwork R2 object")
    print(f"  - SpaceMembership rows (auto_grant_role handles it)")
    print(f"  - default ConversationChannels (platform recreates)")
    print(f"  - SpaceResource / LibraryFolder / invitations / access-requests /")
    print(f"    community posts / events / offer-pages / payment-options /")
    print(f"    access passes / entitlements / progress / transactional state / etc.")
    print()


def confirm_interactive() -> None:
    print("Type 'y' to commit to prod, anything else to abort: ",
          end="", flush=True)
    ans = sys.stdin.readline().strip().lower()
    if ans != "y":
        raise SystemExit("Aborted by operator.")


# ---------------------------------------------------------------------------
# R2 upload
# ---------------------------------------------------------------------------


class R2UploadError(RuntimeError):
    pass


def upload_r2_objects(
    keys: list[str],
    r2_client: Any,
    bucket_private: str,
    bucket_public: str,
) -> list[tuple[str, str]]:
    uploaded: list[tuple[str, str]] = []
    for key in keys:
        path = UPLOAD_DIR_LOCAL / key
        if not path.is_file():
            raise R2UploadError(f"Local source file missing for key {key!r}")
        bucket = bucket_public if key.startswith("platform-artwork/") else bucket_private
        try:
            with path.open("rb") as fh:
                r2_client.put_object(Bucket=bucket, Key=key, Body=fh.read())
            r2_client.head_object(Bucket=bucket, Key=key)
        except Exception as e:
            raise R2UploadError(
                f"R2 upload failed for {key!r} → bucket {bucket!r}: {e}"
            ) from e
        uploaded.append((bucket, key))
        log.info("[R2 %s] uploaded %s", bucket, key)
    return uploaded


def rollback_r2(uploaded: list[tuple[str, str]], r2_client: Any) -> None:
    for bucket, key in uploaded:
        try:
            r2_client.delete_object(Bucket=bucket, Key=key)
            log.info("[R2 %s] rollback deleted %s", bucket, key)
        except Exception as e:  # noqa: BLE001
            log.warning("[R2 %s] rollback FAILED for %s: %s", bucket, key, e)


# ---------------------------------------------------------------------------
# DB insert — parent UPDATE + child INSERTs, single transaction
# ---------------------------------------------------------------------------


@dataclass
class IdMaps:
    pathway: dict[str, str] = field(default_factory=dict)
    section: dict[str, str] = field(default_factory=dict)
    step: dict[str, str] = field(default_factory=dict)
    media_asset: dict[str, str] = field(default_factory=dict)


def insert_prod_rows(
    plan: MigrationPlan,
    prod_session: Session,
    prod_wb_space_id: str,
    prod_lindsey_id: str,
    never_touch_snapshot: dict[str, Any],
) -> IdMaps:
    """Apply the parent UPDATE and every child INSERT. Refetches the
    prod Space and refuses if any NEVER-TOUCH value has drifted from
    the preflight snapshot. Caller wraps in try/rollback — this
    function does NOT commit."""
    maps = IdMaps()

    # 0. Refetch NEVER-TOUCH values and refuse on drift.
    fresh = prod_session.query(Space).filter(
        Space.id == prod_wb_space_id
    ).first()
    if fresh is None:
        raise RuntimeError(
            f"Prod Space id={prod_wb_space_id!r} disappeared between "
            "preflight and insert. Aborting."
        )
    drifts: list[tuple[str, Any, Any]] = []
    for f in PARENT_NEVER_TOUCH_FIELDS:
        current = getattr(fresh, f)
        snap = never_touch_snapshot[f]
        if current != snap:
            drifts.append((f, snap, current))
    if drifts:
        detail = "; ".join(f"{f}: snapshot={s!r}, now={c!r}" for f, s, c in drifts)
        raise RuntimeError(
            "NEVER-TOUCH drift detected on prod Space between preflight "
            f"and commit — refusing. Fields: {detail}"
        )

    # 1. Parent UPDATE — allowlisted fields only.
    for f, v in plan.parent_updates.items():
        setattr(fresh, f, v)
    prod_session.flush()
    log.info("Parent Space UPDATE applied (%d fields)", len(plan.parent_updates))

    # 2. CreatorMediaAsset — before anything that FKs at them.
    for asset_data in plan.media_assets:
        local_id = asset_data["id"]
        prod_id = str(uuid4())
        maps.media_asset[local_id] = prod_id
        data = dict(asset_data)
        data["id"] = prod_id
        data["space_id"] = prod_wb_space_id
        data["uploaded_by_user_id"] = prod_lindsey_id
        data["folder_id"] = None
        prod_session.add(CreatorMediaAsset(**data))
    prod_session.flush()
    log.info("CreatorMediaAsset — inserted %d rows", len(plan.media_assets))

    # 3. Pathways — fresh IDs, status forced to draft.
    for pw_data in plan.pathways:
        local_id = pw_data["id"]
        prod_id = str(uuid4())
        maps.pathway[local_id] = prod_id
        data = dict(pw_data)
        data["id"] = prod_id
        data["space_id"] = prod_wb_space_id
        data["status"] = "draft"
        prod_session.add(Pathway(**data))
    prod_session.flush()
    log.info("Pathway — inserted %d rows (all draft)", len(plan.pathways))

    # 4. Sections
    for sec_data in plan.sections:
        prod_id = str(uuid4())
        maps.section[sec_data["id"]] = prod_id
        data = dict(sec_data)
        data["id"] = prod_id
        data["pathway_id"] = maps.pathway[sec_data["pathway_id"]]
        prod_session.add(PathwaySection(**data))
    prod_session.flush()
    log.info("PathwaySection — inserted %d rows", len(plan.sections))

    # 5. Steps
    for step_data in plan.steps:
        prod_id = str(uuid4())
        maps.step[step_data["id"]] = prod_id
        data = dict(step_data)
        data["id"] = prod_id
        data["pathway_id"] = maps.pathway[step_data["pathway_id"]]
        if step_data.get("section_id"):
            data["section_id"] = maps.section[step_data["section_id"]]
        prod_session.add(PathwayStep(**data))
    prod_session.flush()
    log.info("PathwayStep — inserted %d rows", len(plan.steps))

    # 6. StepBlocks
    for blk_data in plan.step_blocks:
        prod_id = str(uuid4())
        data = dict(blk_data)
        data["id"] = prod_id
        data["step_id"] = maps.step[blk_data["step_id"]]
        data["media_asset_id"] = _remap_optional(
            blk_data.get("media_asset_id"), maps.media_asset,
            "PathwayStepBlock.media_asset_id",
        )
        data["resource_id"] = None  # SpaceResource excluded by scope
        prod_session.add(PathwayStepBlock(**data))
    prod_session.flush()
    log.info("PathwayStepBlock — inserted %d rows", len(plan.step_blocks))

    # 7. AboutBlocks
    for ab_data in plan.about_blocks:
        prod_id = str(uuid4())
        data = dict(ab_data)
        data["id"] = prod_id
        data["pathway_id"] = maps.pathway[ab_data["pathway_id"]]
        if ab_data.get("owner_kind") == "pathway" and ab_data.get("owner_id"):
            data["owner_id"] = maps.pathway[ab_data["owner_id"]]
        data["media_asset_id"] = _remap_optional(
            ab_data.get("media_asset_id"), maps.media_asset,
            "PathwayAboutBlock.media_asset_id",
        )
        data["resource_id"] = None
        prod_session.add(PathwayAboutBlock(**data))
    prod_session.flush()
    log.info("PathwayAboutBlock — inserted %d rows", len(plan.about_blocks))

    return maps


def _remap_optional(
    value: str | None,
    id_map: dict[str, str],
    field_name: str,
) -> str | None:
    if value is None:
        return None
    if value not in id_map:
        raise RuntimeError(
            f"{field_name}={value!r} references a row not in the "
            "migration plan. Enumeration is inconsistent — aborting."
        )
    return id_map[value]


# ---------------------------------------------------------------------------
# Verification (post-commit)
# ---------------------------------------------------------------------------


def verify(
    plan: MigrationPlan,
    ctx: MigrationContext,
    r2_client: Any,
    bucket_private: str,
    bucket_public: str,
) -> None:
    fresh = ctx.prod_session.query(Space).filter(
        Space.id == ctx.prod_wb_space_id
    ).first()
    if fresh is None:
        raise RuntimeError("VERIFY: prod Space disappeared after commit.")

    # Parent identity preserved.
    if fresh.slug != SOURCE_SLUG:
        raise RuntimeError(
            f"VERIFY: slug drift {fresh.slug!r} != {SOURCE_SLUG!r}"
        )
    if fresh.creator_id is not None:
        raise RuntimeError(
            f"VERIFY: creator_id must remain NULL; got {fresh.creator_id!r}"
        )
    if fresh.auto_grant_role != "creator":
        raise RuntimeError(
            f"VERIFY: auto_grant_role={fresh.auto_grant_role!r}, "
            "expected 'creator'"
        )

    # NEVER-TOUCH invariant — every snapshot value unchanged.
    for f in PARENT_NEVER_TOUCH_FIELDS:
        snap = ctx.parent_never_touch_snapshot[f]
        current = getattr(fresh, f)
        if current != snap:
            raise RuntimeError(
                f"VERIFY: NEVER-TOUCH field {f!r} drifted: "
                f"snapshot={snap!r}, current={current!r}"
            )

    # UPDATABLE — every applied value must equal the plan exactly.
    for f, expected in plan.parent_updates.items():
        current = getattr(fresh, f)
        if current != expected:
            raise RuntimeError(
                f"VERIFY: UPDATED field {f!r} does not match plan: "
                f"expected={expected!r}, current={current!r}"
            )

    # Belt-and-braces: island artwork explicit checks (spec-mandated).
    if fresh.island_artwork_url is not None:
        raise RuntimeError(
            f"VERIFY: island_artwork_url should remain NULL; "
            f"got {fresh.island_artwork_url!r}"
        )
    if fresh.island_artwork_status != "not_started":
        raise RuntimeError(
            f"VERIFY: island_artwork_status should remain 'not_started'; "
            f"got {fresh.island_artwork_status!r}"
        )

    # Pathways — exactly the substantive set, both draft.
    pws = ctx.prod_session.query(Pathway).filter(
        Pathway.space_id == ctx.prod_wb_space_id
    ).all()
    if len(pws) != len(SUBSTANTIVE_PATHWAY_SLUGS):
        raise RuntimeError(
            f"VERIFY: expected {len(SUBSTANTIVE_PATHWAY_SLUGS)} pathways, "
            f"found {len(pws)}"
        )
    slugs = {p.slug for p in pws}
    if slugs != set(SUBSTANTIVE_PATHWAY_SLUGS):
        raise RuntimeError(
            f"VERIFY: pathway slugs {sorted(slugs)!r} != expected "
            f"{sorted(SUBSTANTIVE_PATHWAY_SLUGS)!r}"
        )
    for p in pws:
        status_val = getattr(p.status, "value", p.status)
        if status_val != "draft":
            raise RuntimeError(
                f"VERIFY: pathway {p.slug!r} status={p.status!r} != 'draft'"
            )

    # None of the 7 placeholder slugs should have been created.
    for slug in PLACEHOLDER_PATHWAY_SLUGS:
        got = ctx.prod_session.query(Pathway).filter(
            Pathway.space_id == ctx.prod_wb_space_id,
            Pathway.slug == slug,
        ).first()
        if got is not None:
            raise RuntimeError(
                f"VERIFY: placeholder pathway {slug!r} was created "
                f"(id={got.id}); should not have been."
            )

    # Subtree counts.
    pw_ids = [p.id for p in pws]
    sec_count = ctx.prod_session.query(PathwaySection).filter(
        PathwaySection.pathway_id.in_(pw_ids)
    ).count() if pw_ids else 0
    stp_count = ctx.prod_session.query(PathwayStep).filter(
        PathwayStep.pathway_id.in_(pw_ids)
    ).count() if pw_ids else 0
    blk_count = ctx.prod_session.query(PathwayStepBlock).join(
        PathwayStep, PathwayStep.id == PathwayStepBlock.step_id
    ).filter(PathwayStep.pathway_id.in_(pw_ids)).count() if pw_ids else 0
    ab_count = ctx.prod_session.query(PathwayAboutBlock).filter(
        PathwayAboutBlock.pathway_id.in_(pw_ids)
    ).count() if pw_ids else 0
    for label, actual, expected in (
        ("PathwaySection", sec_count, len(plan.sections)),
        ("PathwayStep", stp_count, len(plan.steps)),
        ("PathwayStepBlock", blk_count, len(plan.step_blocks)),
        ("PathwayAboutBlock", ab_count, len(plan.about_blocks)),
    ):
        if actual != expected:
            raise RuntimeError(
                f"VERIFY: {label} count {actual} != expected {expected}"
            )

    # CreatorMediaAsset — exactly the referenced set on this Space.
    media_count = ctx.prod_session.query(CreatorMediaAsset).filter(
        CreatorMediaAsset.space_id == ctx.prod_wb_space_id
    ).count()
    if media_count != len(plan.media_assets):
        raise RuntimeError(
            f"VERIFY: CreatorMediaAsset count {media_count} != "
            f"expected {len(plan.media_assets)}"
        )

    # HEAD every promised R2 key.
    for key in plan.r2_keys:
        bucket = bucket_public if key.startswith("platform-artwork/") else bucket_private
        try:
            r2_client.head_object(Bucket=bucket, Key=key)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"VERIFY: R2 HEAD failed for {bucket}/{key}: {e}"
            ) from e

    log.info(
        "Verification: ✓ platform contract preserved, authored parent "
        "updated, 2 substantive pathways inserted (draft), no placeholders, "
        "no orphan media, no parent island artwork, R2 objects present."
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Selective World Builders authored-content importer "
                    "(updates the existing platform-owned prod Space).",
    )
    p.add_argument("--commit", action="store_true",
                   help="Actually write to prod. Default is dry-run.")
    p.add_argument("--yes-i-am-sure", action="store_true",
                   help="Skip the interactive confirmation prompt.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
    )
    args = parse_args(argv)

    try:
        ctx = preflight(args)
    except PreflightError as e:
        print(f"PREFLIGHT: {e}", file=sys.stderr)
        return 2

    try:
        plan = enumerate_plan(ctx.local_session, ctx.prod_the_commons_id)
    except Exception as e:
        print(f"ENUMERATE: {e}", file=sys.stderr)
        return 3

    try:
        print_summary(plan, ctx)
    except PreflightError as e:
        print(f"PREFLIGHT: {e}", file=sys.stderr)
        return 2

    if not ctx.commit:
        print("Dry-run complete. Pass --commit to actually migrate.")
        return 0

    if not ctx.yes_i_am_sure:
        confirm_interactive()

    uploaded: list[tuple[str, str]] = []
    try:
        uploaded = upload_r2_objects(
            plan.r2_keys, ctx.r2_client,
            ctx.r2_bucket_private, ctx.r2_bucket_public,
        )
        insert_prod_rows(
            plan, ctx.prod_session,
            ctx.prod_wb_space_id, ctx.prod_lindsey_id,
            ctx.parent_never_touch_snapshot,
        )
        ctx.prod_session.commit()
    except Exception as e:
        ctx.prod_session.rollback()
        print(f"\nWRITE FAILED: {e}", file=sys.stderr)
        print("Rolling back R2 uploads…", file=sys.stderr)
        rollback_r2(uploaded, ctx.r2_client)
        print("Rollback complete. Prod DB unchanged.", file=sys.stderr)
        return 4

    try:
        verify(plan, ctx, ctx.r2_client,
               ctx.r2_bucket_private, ctx.r2_bucket_public)
    except Exception as e:
        print(f"\nVERIFY FAILED (commit already landed): {e}", file=sys.stderr)
        print("Manual admin intervention required — the platform-owned "
              "World Builders Space cannot be deleted via Danger Zone.",
              file=sys.stderr)
        return 5

    print()
    print("=" * 74)
    print("MIGRATION COMPLETE — parent updated, 2 substantive pathways "
          "inserted (draft), 15 media inserted.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
