#!/usr/bin/env python
"""One-shot selective import of the Moonlit Circle Collective from
local dev into production.

Moonlit Circle is a deliberate worked-example / demo Collective used
in the World Builders creator-support material. It is preserved, not
disposable test data. Read-only against local dev; writes to prod DB +
prod R2 only when ``--commit`` is passed.

Modelled closely on ``import_embody_from_dev.py`` (the verified
selective importer used for EMBODY). Kept as a separate script rather
than parameterising EMBODY so a completed migration is never
refactored for a new one — two focused one-shots are cheaper than one
parameterised script we then have to re-verify.

Scope (locked, per approved plan):
  * Moonlit Space identity/settings — status forced to ``draft``
  * Single SpaceMembership for the prod Lindsey user
  * ``a-quiet-evening-reset`` Pathway (currently draft locally,
    forced to draft anyway)
  * Its (currently empty) subtree of sections/steps/blocks/about-blocks
  * The Moonlit Circle logo image (1 private R2 object)
  * The EMBODY-style CreatorMediaAsset "referenced only" filter
    naturally excludes the orphan "Side view moon lagoon" upload.

Shared-reference remapping (never copy local UUIDs):
  * ``Space.location_id`` resolves to the prod Atlas Location keyed
    ``location-05`` (🌙 Moon Lagoon) — natural key ``Location.key``.
  * SpacePlace.place_id resolves via an approved local→prod SLUG
    RENAME map so the local typo ``mornington-penninsula`` becomes the
    corrected prod slug ``mornington-peninsula``. This is the audit
    trail — the operator sees both slugs in the dry-run summary.
  * ``Space.closed_by_action_id`` and ``Space.frozen_by_action_id`` are
    defensively nulled — community-care actions are environment-
    specific.

Explicitly excluded:
  * The orphan CreatorMediaAsset ``Side view moon lagoon`` — not
    referenced by any block/about-block (matches EMBODY's
    "referenced only" media filter).
  * Auto-created ConversationChannels (the platform recreates
    "Start Here" / "Common Room" on any new Space).
  * PaymentOption/Schedule/Transaction, PurchasePlan/PurchaseIntent,
    PathwayEntitlement/AccessPass, OfferPage, Event/EventSeries/
    EventBooking, CommunityPost/PostComment/reactions, Poll rows,
    SpaceInvitation/SpaceAccessRequest/ManualMember, StepProgress/
    Enrollment/PathwayStepManualRelease/StepResource/StepComment,
    LibraryFolder (all zero locally, and out-of-scope by policy).
  * Any SpaceMembership other than the single fresh Lindsey creator
    row.

Usage — dry-run:
    .venv/bin/python -m scripts.import_moonlit_from_dev

Usage — commit:
    .venv/bin/python -m scripts.import_moonlit_from_dev --commit

Required env vars (for --commit):
    DATABASE_URL             local dev DB (already in backend/.env)
    PROD_DATABASE_URL        prod DB (Render fc-db External Connection
                             String — NEVER commit to .env)
    R2_ACCOUNT_ID            prod R2 account
    R2_ACCESS_KEY_ID         prod R2 access key
    R2_SECRET_ACCESS_KEY     prod R2 secret
    R2_BUCKET_PRIVATE        'fc-media'
    R2_BUCKET_PUBLIC         'fc-media-public'
    R2_PUBLIC_BASE_URL       prod public R2 URL
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
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    SpaceStatus,
)
from app.models.place import Place, SpacePlace  # noqa: E402
from app.models.user import User  # noqa: E402


# ---------------------------------------------------------------------------
# Constants — the exact locked scope
# ---------------------------------------------------------------------------

SOURCE_SLUG = "moonlit-circle"
INCLUDED_PATHWAY_SLUGS = {"a-quiet-evening-reset"}
PROD_OWNER_EMAIL = "lindsey@hilliard.net.au"

# The Atlas Location Moonlit Circle sits inside. Same natural key in
# local and prod (Mother World UPDATE-in-place preserved the placeholder
# key ``location-05``). We never copy the local Location UUID.
MOONLIT_LOCATION_KEY = "location-05"

# Approved local→prod SLUG RENAME for Places. Local dev still carries
# the historic typo ``mornington-penninsula``; the Mother World
# migration created the corrected prod row ``mornington-peninsula``.
# This map is the audit trail — the operator sees "local → prod" in
# the dry-run summary before typing 'y'.
LOCAL_TO_PROD_PLACE_SLUGS: dict[str, str] = {
    "mornington-penninsula": "mornington-peninsula",
}

# Local uploads root — used to read bytes for R2 upload.
UPLOAD_DIR_LOCAL = Path(__file__).resolve().parent.parent / "uploads"


log = logging.getLogger("import_moonlit")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MigrationContext:
    """Holds everything the script needs after preflight succeeds."""
    local_session: Session
    prod_session: Session
    prod_lindsey_id: str
    # Resolved by natural key against prod during preflight.
    prod_location_id: str
    # Keyed by LOCAL slug → prod Place.id. Insert-time SpacePlace rows
    # look up by the local slug carried in ``plan.space_place_slugs``.
    prod_place_ids_by_slug: dict[str, str]
    r2_client: Any
    r2_bucket_private: str
    r2_bucket_public: str
    commit: bool
    yes_i_am_sure: bool


@dataclass
class MigrationPlan:
    """Rows the script intends to migrate, held as detached dicts."""
    space: dict
    pathways: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    step_blocks: list[dict] = field(default_factory=list)
    about_blocks: list[dict] = field(default_factory=list)
    media_assets: list[dict] = field(default_factory=list)
    # Local Place slugs found on Moonlit's SpacePlace rows. Every slug
    # here must be a key in ``LOCAL_TO_PROD_PLACE_SLUGS``.
    space_place_slugs: list[str] = field(default_factory=list)
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
    """Verify every safeguard the plan promised, then construct the
    MigrationContext. Refuses (PreflightError) if any invariant fails."""

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
            "host+database. Refusing to run — this would rewrite local "
            "dev over itself."
        )

    r2_vars = _load_r2_env()

    log.info("Connecting to local DB %s", _sanitised_url(local_url))
    local_engine = create_engine(local_url, future=True)
    LocalSession = sessionmaker(bind=local_engine, future=True)
    local_session = LocalSession()
    local_session.execute(select(1)).scalar_one()

    log.info("Connecting to prod DB %s", _sanitised_url(prod_url))
    prod_engine = create_engine(prod_url, future=True)
    ProdSession = sessionmaker(bind=prod_engine, future=True)
    prod_session = ProdSession()
    prod_session.execute(select(1)).scalar_one()

    r2_client = _build_r2_client(r2_vars)
    r2_client.head_bucket(Bucket=r2_vars["bucket_private"])

    prod_lindsey = prod_session.query(User).filter(
        User.email == PROD_OWNER_EMAIL
    ).first()
    if not prod_lindsey:
        raise PreflightError(
            f"Prod user with email {PROD_OWNER_EMAIL!r} not found. "
            "Cannot migrate — refusing to invent an owner."
        )

    existing_prod_space = prod_session.query(Space).filter(
        Space.slug == SOURCE_SLUG
    ).first()
    if existing_prod_space is not None:
        raise PreflightError(
            f"Prod Space with slug {SOURCE_SLUG!r} already exists. "
            "Delete it via Creator Studio → Collective Settings → "
            "Danger Zone, then rerun. (This script is one-shot only.)"
        )

    prod_location_id = _resolve_prod_location_id(prod_session)
    prod_place_ids_by_slug = _resolve_prod_place_ids(prod_session)

    return MigrationContext(
        local_session=local_session,
        prod_session=prod_session,
        prod_lindsey_id=prod_lindsey.id,
        prod_location_id=prod_location_id,
        prod_place_ids_by_slug=prod_place_ids_by_slug,
        r2_client=r2_client,
        r2_bucket_private=r2_vars["bucket_private"],
        r2_bucket_public=r2_vars["bucket_public"],
        commit=args.commit,
        yes_i_am_sure=args.yes_i_am_sure,
    )


def _resolve_prod_location_id(prod_session: Session) -> str:
    """Look up the prod Location by ``MOONLIT_LOCATION_KEY``. Refuse if
    missing — never copies the local UUID."""
    loc = prod_session.query(Location).filter(
        Location.key == MOONLIT_LOCATION_KEY
    ).first()
    if loc is None:
        raise PreflightError(
            f"Prod Location with key {MOONLIT_LOCATION_KEY!r} not found. "
            "Run the Mother World migration first, then rerun."
        )
    return loc.id


def _resolve_prod_place_ids(prod_session: Session) -> dict[str, str]:
    """For every LOCAL slug in ``LOCAL_TO_PROD_PLACE_SLUGS``, translate
    to the prod slug via the map and resolve to the prod Place.id.
    Refuse if any mapped slug is missing (naming both the local and
    prod slug so the operator can see the intended rename)."""
    found: dict[str, str] = {}
    for local_slug, prod_slug in sorted(LOCAL_TO_PROD_PLACE_SLUGS.items()):
        place = prod_session.query(Place).filter(Place.slug == prod_slug).first()
        if place is None:
            raise PreflightError(
                f"Prod Place with slug {prod_slug!r} (mapped from local "
                f"{local_slug!r}) not found. Run the Mother World "
                "migration first, then rerun."
            )
        found[local_slug] = place.id
    return found


def _load_r2_env() -> dict[str, str]:
    keys = (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_PRIVATE",
        "R2_BUCKET_PUBLIC",
        "R2_PUBLIC_BASE_URL",
    )
    values = {k: os.environ.get(k) for k in keys}
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise PreflightError(
            "Missing R2 env vars: " + ", ".join(missing) +
            ". Set them from Render fc-api Environment for this shell only."
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
    a = urlparse(url_a)
    b = urlparse(url_b)
    return (a.hostname, a.port, a.path) == (b.hostname, b.port, b.path)


def _sanitised_url(url: str) -> str:
    p = urlparse(url)
    host = p.hostname or "?"
    port = f":{p.port}" if p.port else ""
    return f"{p.scheme}://{p.username or '?'}@{host}{port}{p.path}"


# ---------------------------------------------------------------------------
# Enumerate — build the MigrationPlan from local dev
# ---------------------------------------------------------------------------


def enumerate_plan(local_session: Session) -> MigrationPlan:
    """Read every row the migration will touch from local dev, run the
    drift checks, and return a fully-populated MigrationPlan."""

    space = local_session.query(Space).filter(Space.slug == SOURCE_SLUG).first()
    if not space:
        raise RuntimeError(
            f"Local Space {SOURCE_SLUG!r} not found — nothing to migrate."
        )

    # Drift check — local Space.location_id must resolve to the Moon
    # Lagoon Atlas Location. Catches local dev drift.
    if not space.location_id:
        raise RuntimeError(
            f"Local Space {SOURCE_SLUG!r} has no location_id — expected "
            f"the Atlas Location {MOONLIT_LOCATION_KEY!r}. Refusing to "
            "migrate a Space that has drifted from the plan."
        )
    local_loc = local_session.query(Location).filter(
        Location.id == space.location_id
    ).first()
    if local_loc is None or local_loc.key != MOONLIT_LOCATION_KEY:
        actual = local_loc.key if local_loc else "<missing>"
        raise RuntimeError(
            f"Local Space {SOURCE_SLUG!r} location_id resolves to "
            f"Location.key={actual!r}, expected {MOONLIT_LOCATION_KEY!r}. "
            "Refusing to migrate — local drift detected."
        )

    # Drift check — the local SpacePlace slug set must exactly equal
    # the local keys of LOCAL_TO_PROD_PLACE_SLUGS. Catches both loss
    # of the Mornington association AND unauthorised additions.
    local_space_places = local_session.query(SpacePlace).filter(
        SpacePlace.space_id == space.id
    ).all()
    local_place_slugs: list[str] = []
    for sp in local_space_places:
        place = local_session.query(Place).filter(Place.id == sp.place_id).first()
        if place is None:
            raise RuntimeError(
                f"Local SpacePlace(space={space.id}, place={sp.place_id}) "
                "references a Place that doesn't exist locally."
            )
        local_place_slugs.append(place.slug)
    expected_local_slugs = set(LOCAL_TO_PROD_PLACE_SLUGS.keys())
    if set(local_place_slugs) != expected_local_slugs:
        raise RuntimeError(
            f"Local Moonlit SpacePlace slugs {sorted(local_place_slugs)!r} "
            f"do not match the approved local scope "
            f"{sorted(expected_local_slugs)!r}. Refusing to migrate — "
            "local drift detected."
        )

    pathways = (
        local_session.query(Pathway)
        .filter(Pathway.space_id == space.id)
        .filter(Pathway.slug.in_(INCLUDED_PATHWAY_SLUGS))
        .all()
    )
    if len(pathways) != len(INCLUDED_PATHWAY_SLUGS):
        found = {p.slug for p in pathways}
        missing = INCLUDED_PATHWAY_SLUGS - found
        raise RuntimeError(
            f"Expected pathways {INCLUDED_PATHWAY_SLUGS} not all found; "
            f"missing: {missing}"
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

    # Media — only those referenced by an included block/about-block,
    # matching the EMBODY pattern. The orphan "Side view moon lagoon"
    # upload is naturally excluded because no block references it.
    referenced_media_ids: set[str] = set()
    referenced_r2_keys: set[str] = set()

    def _add_key(url: str | None) -> None:
        k = _key_from_url(url)
        if k:
            referenced_r2_keys.add(k)

    _add_key(space.cover_image_url)
    _add_key(space.logo_url)
    for p in pathways:
        _add_key(p.cover_image_url)
    for s in sections:
        _add_key(s.banner_image_url)
    for s in steps:
        _add_key(s.banner_image_url)
    for b in step_blocks:
        _add_key(b.embed_url)
        if b.media_asset_id:
            referenced_media_ids.add(b.media_asset_id)
    for b in about_blocks:
        _add_key(b.embed_url)
        if b.media_asset_id:
            referenced_media_ids.add(b.media_asset_id)

    media_assets: list = []
    if referenced_media_ids:
        media_assets = local_session.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id.in_(referenced_media_ids)
        ).all()
        for a in media_assets:
            if a.storage_path:
                referenced_r2_keys.add(a.storage_path)

    return MigrationPlan(
        space=_row_to_dict(space),
        pathways=[_row_to_dict(p) for p in pathways],
        sections=[_row_to_dict(s) for s in sections],
        steps=[_row_to_dict(s) for s in steps],
        step_blocks=[_row_to_dict(b) for b in step_blocks],
        about_blocks=[_row_to_dict(b) for b in about_blocks],
        media_assets=[_row_to_dict(a) for a in media_assets],
        space_place_slugs=sorted(local_place_slugs),
        r2_keys=sorted(referenced_r2_keys),
    )


# ---------------------------------------------------------------------------
# Summary / confirmation
# ---------------------------------------------------------------------------


def print_summary(plan: MigrationPlan, ctx: MigrationContext) -> None:
    mode = "COMMIT" if ctx.commit else "DRY RUN — no writes will occur"
    print("=" * 70)
    print(f"Moonlit Circle selective import — {mode}")
    print("=" * 70)
    print(f"  Source Space:      {plan.space['slug']!r} "
          f"({plan.space['name']!r})")
    print(f"  Prod owner:        {PROD_OWNER_EMAIL} → id={ctx.prod_lindsey_id}")
    print(f"  Prod Location:     {MOONLIT_LOCATION_KEY!r} → "
          f"id={ctx.prod_location_id}")
    print(f"  Prod Places (LOCAL slug → PROD slug → id):")
    for local_slug in sorted(LOCAL_TO_PROD_PLACE_SLUGS):
        prod_slug = LOCAL_TO_PROD_PLACE_SLUGS[local_slug]
        print(f"    {local_slug!r} → {prod_slug!r} → "
              f"id={ctx.prod_place_ids_by_slug[local_slug]}")
    print(f"  Prod R2 buckets:   {ctx.r2_bucket_private} (private) / "
          f"{ctx.r2_bucket_public} (public)")
    print()
    print("Would create in prod:")
    print(f"  Space                   1 row  (status forced to draft, "
          f"action FKs nulled)")
    print(f"  SpaceMembership         1 row  (Lindsey / creator / active)")
    print(f"  SpacePlace              {len(plan.space_place_slugs)} rows  "
          f"(local slugs: {plan.space_place_slugs!r})")
    print(f"  Pathway                 {len(plan.pathways)} rows (forced to draft)")
    print(f"  PathwaySection          {len(plan.sections)} rows")
    print(f"  PathwayStep             {len(plan.steps)} rows")
    print(f"  PathwayStepBlock        {len(plan.step_blocks)} rows")
    print(f"  PathwayAboutBlock       {len(plan.about_blocks)} rows")
    print(f"  CreatorMediaAsset       {len(plan.media_assets)} rows (referenced subset)")
    print()
    print(f"Would upload to R2:  {len(plan.r2_keys)} keys")
    total = 0
    missing = []
    for k in plan.r2_keys:
        path = UPLOAD_DIR_LOCAL / k
        if path.is_file():
            total += path.stat().st_size
        else:
            missing.append(k)
    print(f"  Total bytes:       ~{total / (1024 * 1024):.2f} MB")
    for k in plan.r2_keys:
        print(f"    {k}")
    if missing:
        print()
        print("!! MISSING LOCAL FILES (referenced but not on disk):")
        for k in missing:
            print(f"     {k}")
        raise PreflightError(
            f"{len(missing)} referenced media file(s) missing on local disk. "
            "Investigate before rerunning."
        )
    print()


def confirm_interactive() -> None:
    print("Type 'y' to commit to prod, anything else to abort: ", end="", flush=True)
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
    """Upload every key from local disk to prod R2. Returns the
    (bucket, key) pairs successfully uploaded so the caller can
    rollback on later failure. HEAD after each PUT verifies the object
    landed."""
    uploaded: list[tuple[str, str]] = []
    for key in keys:
        path = UPLOAD_DIR_LOCAL / key
        if not path.is_file():
            raise R2UploadError(f"Local source file missing for key {key!r}")
        bucket = bucket_public if key.startswith("platform-artwork/") else bucket_private
        try:
            with path.open("rb") as fh:
                r2_client.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=fh.read(),
                )
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
# DB insert — fresh IDs, FK remap, owner remap, action-FK nulling
# ---------------------------------------------------------------------------


@dataclass
class IdMaps:
    space: dict[str, str] = field(default_factory=dict)
    pathway: dict[str, str] = field(default_factory=dict)
    section: dict[str, str] = field(default_factory=dict)
    step: dict[str, str] = field(default_factory=dict)
    media_asset: dict[str, str] = field(default_factory=dict)


def insert_prod_rows(
    plan: MigrationPlan,
    prod_session: Session,
    prod_lindsey_id: str,
    prod_location_id: str,
    prod_place_ids_by_slug: dict[str, str],
) -> IdMaps:
    """Insert every plan row into prod. Assumes R2 uploads already
    succeeded. Caller wraps in try/except with rollback — this
    function does NOT commit."""
    maps = IdMaps()

    # 1. Space — fresh id, status forced to draft, creator = prod-Lindsey,
    # location_id remapped to the prod Moon Lagoon, community-care
    # action FKs defensively nulled.
    local_space_id = plan.space["id"]
    prod_space_id = str(uuid4())
    maps.space[local_space_id] = prod_space_id
    space_data = dict(plan.space)
    space_data["id"] = prod_space_id
    space_data["creator_id"] = prod_lindsey_id
    space_data["status"] = SpaceStatus.draft
    space_data["location_id"] = prod_location_id
    space_data["closed_by_action_id"] = None
    space_data["frozen_by_action_id"] = None
    prod_session.add(Space(**space_data))
    prod_session.flush()
    log.info("Space inserted (prod_id=%s, location_id=%s)",
             prod_space_id, prod_location_id)

    # 2. Single SpaceMembership row — Lindsey as creator.
    prod_session.add(SpaceMembership(
        id=str(uuid4()),
        user_id=prod_lindsey_id,
        space_id=prod_space_id,
        role=SpaceRole.creator,
        status=SpaceMembershipStatus.active,
        source="migration",
    ))
    log.info("SpaceMembership inserted (Lindsey / creator / active)")

    # 2b. SpacePlace bridge rows — resolve each LOCAL slug to the prod
    # Place.id via the map preflight built. Never a local UUID.
    for local_slug in plan.space_place_slugs:
        prod_place_id = prod_place_ids_by_slug.get(local_slug)
        if prod_place_id is None:
            raise RuntimeError(
                f"SpacePlace local slug {local_slug!r} has no resolved "
                "prod Place.id. Preflight and enumeration are inconsistent "
                "— aborting."
            )
        prod_session.add(SpacePlace(
            space_id=prod_space_id, place_id=prod_place_id,
        ))
    prod_session.flush()
    log.info("SpacePlace — inserted %d rows", len(plan.space_place_slugs))

    # 3. Media assets — before anything that FKs at them (zero for
    # Moonlit, but the loop is symmetric with EMBODY).
    for asset_data in plan.media_assets:
        local_id = asset_data["id"]
        prod_id = str(uuid4())
        maps.media_asset[local_id] = prod_id
        data = dict(asset_data)
        data["id"] = prod_id
        data["space_id"] = prod_space_id
        data["uploaded_by_user_id"] = prod_lindsey_id
        data["folder_id"] = None
        prod_session.add(CreatorMediaAsset(**data))
    prod_session.flush()
    log.info("CreatorMediaAsset — inserted %d rows", len(plan.media_assets))

    # 4. Pathways — fresh IDs, status forced to draft.
    for pw_data in plan.pathways:
        local_id = pw_data["id"]
        prod_id = str(uuid4())
        maps.pathway[local_id] = prod_id
        data = dict(pw_data)
        data["id"] = prod_id
        data["space_id"] = prod_space_id
        data["status"] = "draft"
        prod_session.add(Pathway(**data))
    prod_session.flush()
    log.info("Pathway — inserted %d rows (all draft)", len(plan.pathways))

    # 5. Sections
    for sec_data in plan.sections:
        local_id = sec_data["id"]
        prod_id = str(uuid4())
        maps.section[local_id] = prod_id
        data = dict(sec_data)
        data["id"] = prod_id
        data["pathway_id"] = maps.pathway[sec_data["pathway_id"]]
        prod_session.add(PathwaySection(**data))
    prod_session.flush()
    log.info("PathwaySection — inserted %d rows", len(plan.sections))

    # 6. Steps
    for step_data in plan.steps:
        local_id = step_data["id"]
        prod_id = str(uuid4())
        maps.step[local_id] = prod_id
        data = dict(step_data)
        data["id"] = prod_id
        data["pathway_id"] = maps.pathway[step_data["pathway_id"]]
        if step_data.get("section_id"):
            data["section_id"] = maps.section[step_data["section_id"]]
        prod_session.add(PathwayStep(**data))
    prod_session.flush()
    log.info("PathwayStep — inserted %d rows", len(plan.steps))

    # 7. StepBlocks
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

    # 8. AboutBlocks
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
        data["resource_id"] = None  # SpaceResource excluded by scope
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
    prod_session: Session,
    r2_client: Any,
    bucket_private: str,
    bucket_public: str,
    prod_location_id: str,
    prod_place_ids_by_slug: dict[str, str],
    prod_lindsey_id: str,
) -> None:
    """Assert every post-write invariant against prod. Raises on any
    mismatch."""
    prod_spaces = prod_session.query(Space).filter(
        Space.slug == SOURCE_SLUG
    ).all()
    if len(prod_spaces) != 1:
        raise RuntimeError(
            f"VERIFY: expected exactly 1 prod Space with slug "
            f"{SOURCE_SLUG!r}; found {len(prod_spaces)}."
        )
    prod_space = prod_spaces[0]

    if prod_space.status != SpaceStatus.draft:
        raise RuntimeError(
            f"VERIFY: prod Space status is {prod_space.status!r} — "
            "expected 'draft'."
        )
    if prod_space.creator_id != prod_lindsey_id:
        raise RuntimeError(
            f"VERIFY: prod Space.creator_id={prod_space.creator_id!r} "
            f"!= prod-Lindsey id {prod_lindsey_id!r}."
        )
    if prod_space.location_id != prod_location_id:
        raise RuntimeError(
            f"VERIFY: prod Space.location_id={prod_space.location_id!r} "
            f"does not match expected prod_location_id={prod_location_id!r}."
        )
    if prod_space.closed_by_action_id is not None:
        raise RuntimeError(
            f"VERIFY: prod Space.closed_by_action_id="
            f"{prod_space.closed_by_action_id!r} — expected NULL."
        )
    if prod_space.frozen_by_action_id is not None:
        raise RuntimeError(
            f"VERIFY: prod Space.frozen_by_action_id="
            f"{prod_space.frozen_by_action_id!r} — expected NULL."
        )
    # Logo URL preserved verbatim from the local plan (no rewriting;
    # the R2 upload put the same key at the same location).
    if prod_space.logo_url != plan.space["logo_url"]:
        raise RuntimeError(
            f"VERIFY: prod Space.logo_url={prod_space.logo_url!r} does "
            f"not match plan logo_url={plan.space['logo_url']!r}."
        )

    # Membership — exactly one, Lindsey creator/active.
    mems = prod_session.query(SpaceMembership).filter(
        SpaceMembership.space_id == prod_space.id
    ).all()
    if len(mems) != 1:
        raise RuntimeError(
            f"VERIFY: expected exactly 1 SpaceMembership, found {len(mems)}."
        )
    m = mems[0]
    if m.user_id != prod_lindsey_id:
        raise RuntimeError(
            f"VERIFY: membership user_id={m.user_id!r} != prod-Lindsey."
        )
    if m.role != SpaceRole.creator:
        raise RuntimeError(f"VERIFY: membership role={m.role!r} != creator.")
    if m.status != SpaceMembershipStatus.active:
        raise RuntimeError(f"VERIFY: membership status={m.status!r} != active.")

    # SpacePlace — the prod slugs must equal the mapped set.
    expected_prod_slugs = {
        LOCAL_TO_PROD_PLACE_SLUGS[s] for s in plan.space_place_slugs
    }
    actual_prod_slugs: set[str] = set()
    for sp in prod_session.query(SpacePlace).filter(
        SpacePlace.space_id == prod_space.id
    ).all():
        place = prod_session.query(Place).filter(Place.id == sp.place_id).first()
        if place is None:
            raise RuntimeError(
                f"VERIFY: SpacePlace(place_id={sp.place_id!r}) does not "
                "resolve to a prod Place."
            )
        actual_prod_slugs.add(place.slug)
    if actual_prod_slugs != expected_prod_slugs:
        raise RuntimeError(
            f"VERIFY: SpacePlace prod slug set {sorted(actual_prod_slugs)!r}"
            f" != expected {sorted(expected_prod_slugs)!r}."
        )

    # Pathway — exactly one, right slug, draft, no subtree.
    pws = prod_session.query(Pathway).filter(
        Pathway.space_id == prod_space.id
    ).all()
    if len(pws) != 1:
        raise RuntimeError(
            f"VERIFY: expected exactly 1 Pathway, found {len(pws)}."
        )
    pw = pws[0]
    (expected_slug,) = INCLUDED_PATHWAY_SLUGS
    if pw.slug != expected_slug:
        raise RuntimeError(
            f"VERIFY: pathway slug={pw.slug!r} != expected {expected_slug!r}."
        )
    if str(pw.status) != "PathwayStatus.draft" and pw.status != "draft":
        # PathwayStatus is an Enum; compare by value.
        status_val = getattr(pw.status, "value", pw.status)
        if status_val != "draft":
            raise RuntimeError(
                f"VERIFY: pathway status={pw.status!r} != 'draft'."
            )

    sec_count = prod_session.query(PathwaySection).filter(
        PathwaySection.pathway_id == pw.id
    ).count()
    stp_count = prod_session.query(PathwayStep).filter(
        PathwayStep.pathway_id == pw.id
    ).count()
    blk_count = prod_session.query(PathwayStepBlock).join(
        PathwayStep, PathwayStep.id == PathwayStepBlock.step_id,
    ).filter(PathwayStep.pathway_id == pw.id).count()
    ab_count = prod_session.query(PathwayAboutBlock).filter(
        PathwayAboutBlock.pathway_id == pw.id
    ).count()
    for label, actual in (
        ("sections", sec_count),
        ("steps", stp_count),
        ("step_blocks", blk_count),
        ("about_blocks", ab_count),
    ):
        if actual != 0:
            raise RuntimeError(
                f"VERIFY: expected 0 {label}, found {actual}."
            )

    # Orphan CreatorMediaAsset must NOT have been created — we only
    # migrate referenced media, and Moonlit has none.
    media_count = prod_session.query(CreatorMediaAsset).filter(
        CreatorMediaAsset.space_id == prod_space.id
    ).count()
    if media_count != len(plan.media_assets):
        raise RuntimeError(
            f"VERIFY: media count {media_count} != expected "
            f"{len(plan.media_assets)} (orphan upload must be excluded)."
        )

    # HEAD every expected R2 key.
    for key in plan.r2_keys:
        bucket = bucket_public if key.startswith("platform-artwork/") else bucket_private
        try:
            r2_client.head_object(Bucket=bucket, Key=key)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"VERIFY: R2 HEAD failed for {bucket}/{key}: {e}"
            ) from e

    log.info(
        "Verification: ✓ Space, membership, SpacePlace, pathway (draft, "
        "no subtree), zero orphan media, R2 logo — all match plan."
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Selective import of Moonlit Circle from local dev.",
    )
    p.add_argument(
        "--commit", action="store_true",
        help="Actually write to prod. Default is dry-run (safe).",
    )
    p.add_argument(
        "--yes-i-am-sure", action="store_true",
        help="Skip the interactive confirmation prompt (implies --commit).",
    )
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
        plan = enumerate_plan(ctx.local_session)
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
            plan, ctx.prod_session, ctx.prod_lindsey_id,
            ctx.prod_location_id, ctx.prod_place_ids_by_slug,
        )
        ctx.prod_session.commit()
    except Exception as e:
        ctx.prod_session.rollback()
        print(f"\nWRITE FAILED: {e}", file=sys.stderr)
        print("Rolling back R2 uploads…", file=sys.stderr)
        rollback_r2(uploaded, ctx.r2_client)
        print("Rollback complete. Prod DB is unchanged.", file=sys.stderr)
        return 4

    try:
        verify(
            plan, ctx.prod_session, ctx.r2_client,
            ctx.r2_bucket_private, ctx.r2_bucket_public,
            ctx.prod_location_id, ctx.prod_place_ids_by_slug,
            ctx.prod_lindsey_id,
        )
    except Exception as e:
        print(f"\nVERIFY FAILED (commit already landed): {e}", file=sys.stderr)
        print(
            "Use Creator Studio → Danger Zone to delete and retry.",
            file=sys.stderr,
        )
        return 5

    print()
    print("=" * 70)
    print("MIGRATION COMPLETE — prod Collective 'moonlit-circle' is "
          "draft, owned by Lindsey.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
