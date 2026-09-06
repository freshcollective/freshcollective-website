#!/usr/bin/env python
"""One-shot selective import of authored EMBODY content from local dev
into a fresh production Collective.

Read-only against local dev. Writes to prod DB + prod R2. Defaults to
dry-run — will not touch prod unless ``--commit`` is passed.

Scope (locked, per approved plan):
  * EMBODY Space identity/settings — status forced to ``draft``
  * Single SpaceMembership row for the prod Lindsey user
  * ``embody-in-person-sessions`` and ``home-practice`` Pathways
    (both forced to ``draft``)
  * Their PathwaySections, PathwaySteps, PathwayStepBlocks,
    PathwayAboutBlocks
  * The published ``The story behind EMBODY`` SpaceResource + its PDF
  * Only CreatorMediaAssets actually referenced by the above
  * Collective cover + logo

Explicitly excluded (checked at every insert site):
  * PaymentOption, PaymentOptionSchedule, PaymentTransaction,
    PurchasePlan, PurchaseIntent
  * PathwayEntitlement, AccessPass
  * Event, EventSeries, EventBooking
  * SpaceMembership rows for anyone other than Lindsey
  * SpaceInvitation, SpaceAccessRequest, ManualMember
  * CommunityPost, PostComment, reactions
  * OfferPage
  * ``the-embody-practice``, ``nervous-system-foundations``,
    ``test`` pathways and their subtrees
  * Activity, MessageThread, DirectMessage
  * StepProgress, Enrollment, PathwayStepManualRelease
  * CreatorMediaAssets not referenced by migrated content
  * LibraryFolder (all folder_id references nulled)

The script prints a "Reference config for manual re-entry" block at
the end listing every local PaymentOption + PaymentOptionSchedule so
Lindsey can rebuild Awaken / Activate / Empower through the prod UI
after creating the real Term-4 EventSeries.

Usage — dry-run:
    .venv/bin/python scripts/import_embody_from_dev.py

Usage — commit:
    .venv/bin/python scripts/import_embody_from_dev.py --commit

Required env vars (for --commit):
    DATABASE_URL             local dev DB (already in backend/.env)
    PROD_DATABASE_URL        prod DB (from Render → fc-db External
                             Connection String — NEVER commit to .env)
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
from typing import Any, Iterable
from urllib.parse import urlparse
from uuid import uuid4

# Same bootstrap pattern as ``backfill_location_thumbnails.py``: put
# the backend root on the import path so ``import app.main`` resolves
# whether the script is invoked from ``backend/`` or from the repo root.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Load ``backend/.env`` so ``DATABASE_URL`` is available via
# ``os.environ`` — the app itself reads .env via pydantic-settings
# during Settings() init, but this script uses ``os.environ`` directly
# for prod-vs-local separation. ``PROD_DATABASE_URL`` and R2_* vars
# are deliberately NOT expected to live in .env — they must be
# exported into the shell for the run and disappear when it closes.
try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except ImportError:
    pass  # python-dotenv is a soft dep; env vars from the shell still work

# Prime the SQLAlchemy mapper by importing the app entry point — many
# relationship strings resolve through the shared registry, and
# importing individual models in isolation trips 'cannot locate name'
# errors on cross-file backrefs. Import lifespan handlers are only
# invoked when uvicorn drives the app; a plain import is inert.
import app.main  # noqa: F401,E402

from sqlalchemy import create_engine, inspect as sa_inspect, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.models.platform import (  # noqa: E402
    CreatorMediaAsset,
    Pathway,
    PathwayAboutBlock,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceResource,
    SpaceRole,
    SpaceStatus,
)
from app.models.payment_option import PaymentOption  # noqa: E402
from app.models.payment_option_schedule import PaymentOptionSchedule  # noqa: E402
from app.models.user import User  # noqa: E402


# ---------------------------------------------------------------------------
# Constants — the exact locked scope
# ---------------------------------------------------------------------------

SOURCE_SLUG = "embody"
INCLUDED_PATHWAY_SLUGS = {"embody-in-person-sessions", "home-practice"}
PROD_OWNER_EMAIL = "lindsey@hilliard.net.au"
INCLUDED_RESOURCE_TITLE = "The story behind EMBODY"

# Local uploads root — used to read bytes for R2 upload.
UPLOAD_DIR_LOCAL = Path(__file__).resolve().parent.parent / "uploads"


log = logging.getLogger("import_embody")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MigrationContext:
    """Holds everything the script needs after preflight succeeds."""
    local_session: Session
    prod_session: Session
    prod_lindsey_id: str
    r2_client: Any  # boto3 S3 client (typed loosely to avoid mypy pain)
    r2_bucket_private: str
    r2_bucket_public: str
    commit: bool
    yes_i_am_sure: bool


@dataclass
class MigrationPlan:
    """Enumerated source rows the script intends to migrate.

    Held as dicts (copied out of SQLAlchemy instances) rather than
    live ORM objects so nothing in the plan is bound to the local
    session — the plan is data, not attached state.
    """
    space: dict
    pathways: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    step_blocks: list[dict] = field(default_factory=list)
    about_blocks: list[dict] = field(default_factory=list)
    media_assets: list[dict] = field(default_factory=list)
    resources: list[dict] = field(default_factory=list)
    r2_keys: list[str] = field(default_factory=list)  # every key to upload


# ---------------------------------------------------------------------------
# Helpers — copy rows into detached dicts, apply overrides at insert time
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict:
    """Copy every mapped column off an ORM instance into a plain dict.

    Independent of the local session — the returned dict can be used
    to construct a fresh instance for prod insert without the row
    being 'attached' to the source session."""
    cols = [c.name for c in sa_inspect(row.__class__).columns]
    return {c: getattr(row, c) for c in cols}


def _key_from_url(url: str | None) -> str | None:
    """Extract the raw R2 key from a ``/api/uploads/{key}`` URL.
    External URLs (https, mailto, etc.) return None."""
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
    """Verify every safeguard the plan promised.

    Refuses to construct the context (raises ``PreflightError``) if any
    invariant fails. Order matters: cheapest checks first so an
    obviously-wrong invocation fails before establishing DB / R2
    connections."""

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
    # HEAD the private bucket to prove credentials work AND we can
    # reach R2 — no other side effects.
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

    return MigrationContext(
        local_session=local_session,
        prod_session=prod_session,
        prod_lindsey_id=prod_lindsey.id,
        r2_client=r2_client,
        r2_bucket_private=r2_vars["bucket_private"],
        r2_bucket_public=r2_vars["bucket_public"],
        commit=args.commit,
        yes_i_am_sure=args.yes_i_am_sure,
    )


def _load_r2_env() -> dict[str, str]:
    """Read every R2 env var. Every one must be set — matches the
    fc-api boot guard's contract."""
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
    """Construct a fresh boto3 S3 client against the R2 endpoint. Kept
    separate from ``app.core.storage._r2_client`` (which reads
    ``settings``) so the script can be tested in local dev where
    ``settings.is_r2_enabled`` is False."""
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
    """True if two DSNs resolve to the same host+database. Defence
    against pasting the local URL into PROD_DATABASE_URL by mistake."""
    a = urlparse(url_a)
    b = urlparse(url_b)
    return (a.hostname, a.port, a.path) == (b.hostname, b.port, b.path)


def _sanitised_url(url: str) -> str:
    """Show host+db but never the password."""
    p = urlparse(url)
    host = p.hostname or "?"
    port = f":{p.port}" if p.port else ""
    db = p.path
    return f"{p.scheme}://{p.username or '?'}@{host}{port}{db}"


# ---------------------------------------------------------------------------
# Enumerate — build the MigrationPlan from local dev
# ---------------------------------------------------------------------------


def enumerate_plan(local_session: Session) -> MigrationPlan:
    """Read every row the migration will touch from local dev. Returns
    a fully-populated MigrationPlan.

    Also collects the R2 key set — the union of Space cover/logo,
    every included Pathway/Section/Step banner, every included
    PathwayStepBlock and PathwayAboutBlock ``embed_url``, every
    included CreatorMediaAsset.storage_path, and every included
    SpaceResource file URL."""

    space = local_session.query(Space).filter(Space.slug == SOURCE_SLUG).first()
    if not space:
        raise RuntimeError(
            f"Local Space {SOURCE_SLUG!r} not found — nothing to migrate."
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

    # SpaceResource — only the specific published guide by title.
    # A stricter filter than "everything published" so a future
    # additional resource isn't quietly swept in.
    resources = local_session.query(SpaceResource).filter(
        SpaceResource.space_id == space.id,
        SpaceResource.title == INCLUDED_RESOURCE_TITLE,
    ).all()

    # Media assets — collect the exact set referenced by any of the
    # above, plus the Space cover/logo. Reads the local IDs; the
    # actual CreatorMediaAsset rows come from a follow-up query so
    # we can copy every column.
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
    for r in resources:
        _add_key(r.url)

    media_assets = []
    if referenced_media_ids:
        media_assets = local_session.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id.in_(referenced_media_ids)
        ).all()
        for a in media_assets:
            # storage_path is the raw R2 key already — no /api/uploads/ prefix.
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
        resources=[_row_to_dict(r) for r in resources],
        r2_keys=sorted(referenced_r2_keys),
    )


# ---------------------------------------------------------------------------
# Summary / confirmation
# ---------------------------------------------------------------------------


def print_summary(plan: MigrationPlan, ctx: MigrationContext) -> None:
    mode = "COMMIT" if ctx.commit else "DRY RUN — no writes will occur"
    print("=" * 70)
    print(f"EMBODY selective import — {mode}")
    print("=" * 70)
    print(f"  Source Space:      {plan.space['slug']!r} "
          f"({plan.space['name']!r})")
    print(f"  Prod owner:        {PROD_OWNER_EMAIL} → id={ctx.prod_lindsey_id}")
    print(f"  Prod R2 buckets:   {ctx.r2_bucket_private} (private) / "
          f"{ctx.r2_bucket_public} (public)")
    print()
    print("Would create in prod:")
    print(f"  Space                   1 row  (status forced to draft)")
    print(f"  SpaceMembership         1 row  (Lindsey / creator / active)")
    print(f"  Pathway                 {len(plan.pathways)} rows (both forced to draft)")
    print(f"  PathwaySection          {len(plan.sections)} rows")
    print(f"  PathwayStep             {len(plan.steps)} rows")
    print(f"  PathwayStepBlock        {len(plan.step_blocks)} rows")
    print(f"  PathwayAboutBlock       {len(plan.about_blocks)} rows")
    print(f"  CreatorMediaAsset       {len(plan.media_assets)} rows (referenced subset)")
    print(f"  SpaceResource           {len(plan.resources)} rows")
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
    print(f"  Total bytes:       ~{total / (1024 * 1024):.1f} MB")
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
    """Interactive stop-and-verify prompt before any prod write."""
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
    """Upload every key from local disk to prod R2. Returns the list of
    (bucket, key) pairs successfully uploaded — used for rollback if a
    later DB step fails.

    Bucket choice mirrors ``core/storage._bucket_for_key``:
    ``platform-artwork/*`` → public bucket, everything else →
    private. In this migration set no keys are ``platform-artwork/*``
    (Space cover/logo/pathway media are all private-bucket), but the
    routing is kept symmetric with the rest of the codebase in case
    a future migration includes public artwork.

    Ordering: uploads are done sequentially so we can accurately
    rollback the set-uploaded-so-far on any failure. HEAD after each
    PUT to verify the object landed.
    """
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
        except Exception as e:  # boto3 / network / auth failure
            raise R2UploadError(
                f"R2 upload failed for {key!r} → bucket {bucket!r}: {e}"
            ) from e
        uploaded.append((bucket, key))
        log.info("[R2 %s] uploaded %s", bucket, key)
    return uploaded


def rollback_r2(
    uploaded: list[tuple[str, str]],
    r2_client: Any,
) -> None:
    """Best-effort — remove every R2 object the script uploaded during
    a failed run. Errors are logged and swallowed (the caller has
    already failed; there's nothing better to do)."""
    for bucket, key in uploaded:
        try:
            r2_client.delete_object(Bucket=bucket, Key=key)
            log.info("[R2 %s] rollback deleted %s", bucket, key)
        except Exception as e:  # noqa: BLE001
            log.warning("[R2 %s] rollback FAILED for %s: %s", bucket, key, e)


# ---------------------------------------------------------------------------
# DB insert — fresh IDs, FK remap, owner remap
# ---------------------------------------------------------------------------


@dataclass
class IdMaps:
    """local_id → prod_id per table with children."""
    space: dict[str, str] = field(default_factory=dict)
    pathway: dict[str, str] = field(default_factory=dict)
    section: dict[str, str] = field(default_factory=dict)
    step: dict[str, str] = field(default_factory=dict)
    media_asset: dict[str, str] = field(default_factory=dict)
    resource: dict[str, str] = field(default_factory=dict)


def insert_prod_rows(
    plan: MigrationPlan,
    prod_session: Session,
    prod_lindsey_id: str,
) -> IdMaps:
    """Insert every plan row into prod. Assumes R2 uploads already
    succeeded (URLs in the plan are then valid).

    Caller is responsible for wrapping this in a try/except with
    ``prod_session.rollback()`` on failure — this function does NOT
    commit."""
    maps = IdMaps()

    # 1. Space — fresh id, status forced to draft, creator = prod-Lindsey.
    local_space_id = plan.space["id"]
    prod_space_id = str(uuid4())
    maps.space[local_space_id] = prod_space_id
    space_data = dict(plan.space)
    space_data["id"] = prod_space_id
    space_data["creator_id"] = prod_lindsey_id
    space_data["status"] = SpaceStatus.draft
    # ``location_id`` FK — if the local Space picked an Atlas Location,
    # the corresponding row must exist in prod (World Builders seeds
    # every Atlas Location as part of Alembic migrations, so the FK
    # is preserved verbatim without a lookup).
    prod_session.add(Space(**space_data))
    prod_session.flush()
    log.info("Space inserted (prod_id=%s)", prod_space_id)

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

    # 3. Media assets — before anything that FKs at them.
    for asset_data in plan.media_assets:
        local_id = asset_data["id"]
        prod_id = str(uuid4())
        maps.media_asset[local_id] = prod_id
        data = dict(asset_data)
        data["id"] = prod_id
        data["space_id"] = prod_space_id
        data["uploaded_by_user_id"] = prod_lindsey_id
        # LibraryFolder is out of scope — null every folder_id.
        data["folder_id"] = None
        prod_session.add(CreatorMediaAsset(**data))
    prod_session.flush()
    log.info("CreatorMediaAsset — inserted %d rows", len(plan.media_assets))

    # 4. Space resource(s) — no folder, no pathway attachment (legacy
    # v1 field), space_resource_pathways bridge deliberately empty
    # (the linked pathways would need their own remap, and the two
    # migrated pathways don't currently reference this resource).
    for res_data in plan.resources:
        local_id = res_data["id"]
        prod_id = str(uuid4())
        maps.resource[local_id] = prod_id
        data = dict(res_data)
        data["id"] = prod_id
        data["space_id"] = prod_space_id
        data["created_by_id"] = prod_lindsey_id
        data["folder_id"] = None
        data["pathway_id"] = None  # legacy Resources v1 field
        prod_session.add(SpaceResource(**data))
    prod_session.flush()
    log.info("SpaceResource — inserted %d rows", len(plan.resources))

    # 5. Pathways — fresh IDs, status forced to draft.
    for pw_data in plan.pathways:
        local_id = pw_data["id"]
        prod_id = str(uuid4())
        maps.pathway[local_id] = prod_id
        data = dict(pw_data)
        data["id"] = prod_id
        data["space_id"] = prod_space_id
        data["status"] = "draft"  # Pathway.status is a plain String column
        prod_session.add(Pathway(**data))
    prod_session.flush()
    log.info("Pathway — inserted %d rows (all draft)", len(plan.pathways))

    # 6. Sections
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

    # 7. Steps — remap pathway_id AND section_id.
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

    # 8. StepBlocks — remap step_id, media_asset_id, resource_id.
    for blk_data in plan.step_blocks:
        prod_id = str(uuid4())
        data = dict(blk_data)
        data["id"] = prod_id
        data["step_id"] = maps.step[blk_data["step_id"]]
        data["media_asset_id"] = _remap_optional(
            blk_data.get("media_asset_id"), maps.media_asset,
            "PathwayStepBlock.media_asset_id",
        )
        data["resource_id"] = _remap_optional(
            blk_data.get("resource_id"), maps.resource,
            "PathwayStepBlock.resource_id",
        )
        prod_session.add(PathwayStepBlock(**data))
    prod_session.flush()
    log.info("PathwayStepBlock — inserted %d rows", len(plan.step_blocks))

    # 9. AboutBlocks — remap pathway_id, owner_id (=pathway_id for
    # pathway-scoped rows), media_asset_id, resource_id.
    for ab_data in plan.about_blocks:
        prod_id = str(uuid4())
        data = dict(ab_data)
        data["id"] = prod_id
        # pathway_id (legacy) — always remap.
        data["pathway_id"] = maps.pathway[ab_data["pathway_id"]]
        # owner_id (polymorphic) — pathway-scoped rows have
        # owner_kind='pathway' and owner_id = pathway_id.
        if ab_data.get("owner_kind") == "pathway" and ab_data.get("owner_id"):
            data["owner_id"] = maps.pathway[ab_data["owner_id"]]
        data["media_asset_id"] = _remap_optional(
            ab_data.get("media_asset_id"), maps.media_asset,
            "PathwayAboutBlock.media_asset_id",
        )
        data["resource_id"] = _remap_optional(
            ab_data.get("resource_id"), maps.resource,
            "PathwayAboutBlock.resource_id",
        )
        prod_session.add(PathwayAboutBlock(**data))
    prod_session.flush()
    log.info("PathwayAboutBlock — inserted %d rows", len(plan.about_blocks))

    return maps


def _remap_optional(
    value: str | None,
    id_map: dict[str, str],
    field_name: str,
) -> str | None:
    """Remap an optional FK. None → None. Present → must be in the
    map (else the enumeration is inconsistent — abort loudly)."""
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
) -> None:
    """Run every post-write invariant against prod. Raises on any
    mismatch (rare — the transaction just committed; more of a smoke
    test than a full audit)."""
    prod_space = prod_session.query(Space).filter(
        Space.slug == SOURCE_SLUG
    ).first()
    if not prod_space:
        raise RuntimeError("VERIFY: prod Space not found after commit.")
    if prod_space.status != SpaceStatus.draft:
        raise RuntimeError(
            f"VERIFY: prod Space status is {prod_space.status!r} — "
            "expected 'draft'."
        )

    pw_count = prod_session.query(Pathway).filter(
        Pathway.space_id == prod_space.id
    ).count()
    if pw_count != len(plan.pathways):
        raise RuntimeError(
            f"VERIFY: pathway count {pw_count} != expected {len(plan.pathways)}"
        )

    step_count = prod_session.query(PathwayStep).join(
        Pathway, Pathway.id == PathwayStep.pathway_id
    ).filter(Pathway.space_id == prod_space.id).count()
    if step_count != len(plan.steps):
        raise RuntimeError(
            f"VERIFY: step count {step_count} != expected {len(plan.steps)}"
        )

    block_count = prod_session.query(PathwayStepBlock).join(
        PathwayStep, PathwayStep.id == PathwayStepBlock.step_id
    ).join(Pathway, Pathway.id == PathwayStep.pathway_id).filter(
        Pathway.space_id == prod_space.id
    ).count()
    if block_count != len(plan.step_blocks):
        raise RuntimeError(
            f"VERIFY: step-block count {block_count} != expected "
            f"{len(plan.step_blocks)}"
        )

    media_count = prod_session.query(CreatorMediaAsset).filter(
        CreatorMediaAsset.space_id == prod_space.id
    ).count()
    if media_count != len(plan.media_assets):
        raise RuntimeError(
            f"VERIFY: media count {media_count} != expected "
            f"{len(plan.media_assets)}"
        )

    # HEAD every expected R2 key — proves upload landed AND the key
    # matches the DB's expectation.
    for key in plan.r2_keys:
        bucket = bucket_public if key.startswith("platform-artwork/") else bucket_private
        try:
            r2_client.head_object(Bucket=bucket, Key=key)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"VERIFY: R2 HEAD failed for {bucket}/{key}: {e}"
            ) from e

    log.info("Verification: ✓ Space, pathways, steps, blocks, media, R2 all match plan.")


# ---------------------------------------------------------------------------
# PaymentOption reference — print at end so Lindsey has copy-paste
# ---------------------------------------------------------------------------


def print_paymentoption_reference(local_session: Session) -> None:
    """Format local PaymentOption + PaymentOptionSchedule rows into a
    manual-recreate reference. Called after a successful commit so
    Lindsey has the exact names/prices/descriptions when rebuilding
    Awaken / Activate / Empower through the prod Payment Options UI."""
    space = local_session.query(Space).filter(Space.slug == SOURCE_SLUG).first()
    if not space:
        return
    options = local_session.query(PaymentOption).filter(
        PaymentOption.space_id == space.id
    ).order_by(PaymentOption.status.desc(), PaymentOption.name).all()

    if not options:
        return

    print()
    print("=" * 70)
    print("Reference config for manual re-entry in prod")
    print("=" * 70)
    print(
        "The following PaymentOptions + schedules are NOT migrated. "
        "Recreate the three published options (Awaken/Activate/Empower) "
        "through the prod Payment Options UI once you've created the "
        "real Term-4 EventSeries. The archived options are shown for "
        "reference; you probably don't need to recreate them."
    )
    print()

    for opt in options:
        print(f"[{opt.status}] {opt.name!r}")
        for field_name in (
            "payment_type", "attaches_to_kind", "description",
            "total_sessions", "sessions_per_week",
            "price_per_session_cents", "calculated_total_cents", "currency",
            "term_start_date", "term_end_date",
        ):
            v = getattr(opt, field_name, None)
            if v is not None:
                print(f"    {field_name}: {v}")

        schedules = local_session.query(PaymentOptionSchedule).filter(
            PaymentOptionSchedule.payment_option_id == opt.id
        ).order_by(PaymentOptionSchedule.schedule_type).all()
        for sch in schedules:
            print(f"    ─ schedule [{sch.status}] {sch.name!r} "
                  f"({sch.schedule_type})")
            for field_name in (
                "description", "total_amount_cents", "installments_expected",
                "stripe_interval", "stripe_interval_count", "currency",
            ):
                v = getattr(sch, field_name, None)
                if v is not None:
                    print(f"        {field_name}: {v}")
        print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Selective import of EMBODY authored content from local dev.",
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
        insert_prod_rows(plan, ctx.prod_session, ctx.prod_lindsey_id)
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
        )
    except Exception as e:
        # Do NOT rollback here — the commit already landed. Just alert
        # and let Lindsey delete via Danger Zone if she wants to redo.
        print(f"\nVERIFY FAILED (commit already landed): {e}", file=sys.stderr)
        print(
            "Use Creator Studio → Danger Zone to delete and retry.",
            file=sys.stderr,
        )
        return 5

    print_paymentoption_reference(ctx.local_session)

    print()
    print("=" * 70)
    print("MIGRATION COMPLETE — prod Collective 'embody' is draft, "
          "owned by Lindsey.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
