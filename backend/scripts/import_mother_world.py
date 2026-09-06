#!/usr/bin/env python
"""Mother World / shared-content migration — local → prod, one-shot.

Scope (locked to the approved manifest — 45 database writes total,
15 UPDATE + 30 CREATE):

  * 25 Locations
      12 UPDATE — Atlas placeholders `location-01`..`location-12`
                  (seed IDs deterministic → prod already has them)
       3 UPDATE — Community `campfire-grove`, `harvest-table`,
                  `festival-green` (seed keys stable → prod has them)
       3 CREATE — Cornerstones `the-atlas-isles`, `the-grove`,
                  `the-commons`
       7 CREATE — admin-authored Atlas: `cloudhaven`,
                  `canopy-reach`, `starwatch-peak`,
                  `sanctuary-springs`, plus the 3 corrected
                  Atlas keys `the-lost-circle` (was
                  `pelagia-or-another-name`), `luminara` (was
                  `canal-haven-working-name`), `aegea` (was
                  `verdant-keys`).
      0 rows for `crystal-hollow` — deliberately excluded.

  * 2 Places
       2 CREATE — `melbourne` and `mornington-peninsula` (slug
                  and name corrected from the local `Penninsula`
                  typo at insert time).

  * 9 WorldGuideDocuments — all CREATE, all preserved as drafts;
                            ``current_version_id`` left NULL by
                            design.

  * 9 WorldGuideVersions   — all CREATE, all `status='draft'`,
                            all `published_at=NULL`,
                            `published_by_user_id=NULL`. FK
                            ``document_id`` remapped via the
                            per-run local→prod document ID map.

Safety
------
  * Default: DRY RUN. --commit required for any write.
  * Interactive confirmation prompt before writes. --yes-i-am-sure
    skips prompt.
  * Single prod transaction — every write commits together or
    rolls back together. No R2 operations.
  * Refuses if DATABASE_URL and PROD_DATABASE_URL resolve to the
    same host+database.
  * Refuses if prod already has any of the 10 target CREATE keys
    for Locations, either target CREATE slug for Places, or any
    of the 9 target CREATE slugs for WorldGuideDocument.
  * Refuses if any of the 15 UPDATE seed keys/slugs is missing
    from prod (prod migrations not at head, or a seed row was
    manually deleted).
  * Refuses if the local source violates the draft-only World
    Guide invariant (any document has current_version_id set,
    or any version has published_at set).
  * Refuses if any expected local row is missing or if crystal-
    hollow doesn't exist as the excluded hidden row.

Content verification
--------------------
After commit, re-reads every migrated row from prod and compares
each carried authored field against the expected value derived
from the local source + approved transformations. Exact equality;
mismatch reports model, natural key, and field. Timestamps
(created_at / updated_at) are metadata and are excluded from
content verification — the design documents their handling
separately.

Usage
-----
    cd backend
    .venv/bin/python scripts/import_mother_world.py                 # dry run
    .venv/bin/python scripts/import_mother_world.py --commit        # writes
    .venv/bin/python scripts/import_mother_world.py --commit \
                     --yes-i-am-sure                                # skip prompt

Required env vars
-----------------
    DATABASE_URL          local dev DB
    PROD_DATABASE_URL     prod DB (from Render → fc-db External Connection String)

No R2 credentials required — this migration touches zero media.
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

# Same bootstrap pattern as our other backend scripts.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except ImportError:
    pass

import app.main  # noqa: F401,E402

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.models.place import Place  # noqa: E402
from app.models.platform import Location  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.world_guide import (  # noqa: E402
    WorldGuideDocument,
    WorldGuideVersion,
)


log = logging.getLogger("import_mother_world")


PROD_OWNER_EMAIL = "lindsey@hilliard.net.au"

# Locked totals — used everywhere in operator output.
EXPECTED_TOTAL_WRITES = 45
EXPECTED_UPDATES = 15
EXPECTED_CREATES = 30

# ---------------------------------------------------------------------------
# Corrections applied at insert time
# ---------------------------------------------------------------------------

# Atlas key + name corrections. Applied when reading source row before
# any target-key comparison or insert.
RENAMES_ATLAS: dict[str, dict[str, str]] = {
    "pelagia-or-another-name":  {"key": "the-lost-circle", "name": "🏝 The Lost Circle"},
    "canal-haven-working-name": {"key": "luminara",        "name": "🎭 Luminara"},
    "verdant-keys":             {"key": "aegea",           "name": "🤍 Aegea"},
}

# Place slug + name correction.
RENAMES_PLACE: dict[str, dict[str, str]] = {
    "mornington-penninsula": {"slug": "mornington-peninsula", "name": "Mornington Peninsula"},
}

# The hidden Atlas row — deliberately excluded from migration.
EXCLUDED_ATLAS_KEY = "crystal-hollow"

# Seed keys that MUST exist in prod at run time (UPDATE targets).
EXPECTED_SEED_ATLAS_KEYS = {f"location-{i:02d}" for i in range(1, 13)}
EXPECTED_SEED_COMMUNITY_KEYS = {"campfire-grove", "harvest-table", "festival-green"}

# Target keys for CREATE — refuse if any already exist in prod.
TARGET_ATLAS_CREATE_KEYS = {
    "cloudhaven", "canopy-reach", "starwatch-peak", "sanctuary-springs",
    "the-lost-circle", "luminara", "aegea",
}
TARGET_CORNERSTONE_CREATE_KEYS = {"the-atlas-isles", "the-grove", "the-commons"}
TARGET_PLACE_CREATE_SLUGS = {"melbourne", "mornington-peninsula"}
# WorldGuide document slugs — verified against local at preflight.

# Fields to carry / null / reset per model.
LOCATION_CARRY_FIELDS = (
    "description", "atlas_entry", "status", "location_type",
    "biome", "archipelago",
    "preferred_atmospheres", "preferred_colour_stories", "preferred_themes",
    "position",
)
LOCATION_NULLED_FIELDS = ("hero_artwork_url", "thumbnail_artwork_url")

PLACE_CARRY_FIELDS = (
    "country_code", "region", "blurb", "admin_note",
    "artwork_focal_x", "artwork_focal_y",
    "latitude", "longitude", "timezone",
    "provider_place_id", "status",
)
PLACE_NULLED_FIELDS = ("hero_artwork_url", "artwork_alt_text")

WGDOC_CARRY_FIELDS = (
    "title", "category", "audience", "summary",
    "reading_time_minutes", "archived_at",
)
# `author_user_id` is REMAPPED to prod-Lindsey.
# `current_version_id` is FORCED to NULL (draft-only invariant).

WGVER_CARRY_FIELDS = (
    "version_number", "status", "effective_date",
    "why_this_exists", "what_this_covers", "main_content", "whats_changed",
)
# `document_id`               — REMAPPED via id_map.
# `last_edited_by_user_id`    — REMAPPED to prod-Lindsey when source non-null.
# `published_at`              — FORCED to NULL.
# `published_by_user_id`      — FORCED to NULL.


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class PreflightError(RuntimeError):
    """Refuse-to-proceed condition detected before any write."""


class VerificationError(RuntimeError):
    """Post-commit content verification found a mismatch."""


@dataclass
class ExpectedRow:
    """Snapshot of what a row should look like in prod after the
    migration. Comparison unit for content verification."""
    natural_key: str
    fields: dict[str, Any]


@dataclass
class MigrationPlan:
    # Locations
    locations_update: list[dict]      = field(default_factory=list)  # {row: source, expected: dict}
    locations_create: list[dict]      = field(default_factory=list)
    # Places
    places_create: list[dict]         = field(default_factory=list)
    # World Guide
    wgdocs_create: list[dict]         = field(default_factory=list)
    wgvers_create: list[dict]         = field(default_factory=list)  # keyed by (source_doc_id, version_number)

    def total_writes(self) -> int:
        return (
            len(self.locations_update) + len(self.locations_create)
            + len(self.places_create)
            + len(self.wgdocs_create) + len(self.wgvers_create)
        )

    def total_updates(self) -> int:
        return len(self.locations_update)

    def total_creates(self) -> int:
        return (
            len(self.locations_create) + len(self.places_create)
            + len(self.wgdocs_create) + len(self.wgvers_create)
        )


@dataclass
class MigrationContext:
    local_session: Session
    prod_session: Session
    prod_lindsey_id: str
    commit: bool
    yes_i_am_sure: bool


@dataclass
class ProdReadState:
    """Prod-side snapshot captured before enumeration. Kept as an
    explicit value so tests can inject a curated prod view without
    having to spin up a second physical database."""
    locations_by_key: dict[str, Any]
    place_slugs: set[str]
    wgdoc_slugs: set[str]


def _read_prod_state(prod: Session) -> ProdReadState:
    return ProdReadState(
        locations_by_key={l.key: l for l in prod.query(Location).all()},
        place_slugs={p.slug for p in prod.query(Place).all()},
        wgdoc_slugs={d.slug for d in prod.query(WorldGuideDocument).all()},
    )


# ---------------------------------------------------------------------------
# Preflight / safety
# ---------------------------------------------------------------------------


def _sanitised_url(url: str) -> str:
    p = urlparse(url)
    host = p.hostname or "?"
    port = f":{p.port}" if p.port else ""
    return f"{p.scheme}://{p.username or '?'}@{host}{port}{p.path}"


def _same_db(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.hostname, pa.port, pa.path) == (pb.hostname, pb.port, pb.path)


def _open_sessions(args: argparse.Namespace) -> MigrationContext:
    local_url = os.environ.get("DATABASE_URL")
    if not local_url:
        raise PreflightError("DATABASE_URL not set.")
    prod_url = os.environ.get("PROD_DATABASE_URL")
    if not prod_url:
        raise PreflightError(
            "PROD_DATABASE_URL not set. Export from Render → fc-db "
            "External Connection String for this shell only."
        )
    if _same_db(local_url, prod_url):
        raise PreflightError(
            "DATABASE_URL and PROD_DATABASE_URL resolve to the same "
            "host+database. Refusing — this migration writes to prod."
        )

    local_engine = create_engine(local_url, future=True)
    prod_engine = create_engine(prod_url, future=True)
    LocalSession = sessionmaker(bind=local_engine, future=True)
    ProdSession = sessionmaker(bind=prod_engine, future=True)
    local = LocalSession()
    prod = ProdSession()
    local.execute(select(1)).scalar_one()
    prod.execute(select(1)).scalar_one()

    prod_lindsey = prod.query(User).filter(User.email == PROD_OWNER_EMAIL).first()
    if not prod_lindsey:
        raise PreflightError(
            f"Prod user with email {PROD_OWNER_EMAIL!r} not found. "
            "Cannot set author_user_id / last_edited_by_user_id."
        )

    return MigrationContext(
        local_session=local,
        prod_session=prod,
        prod_lindsey_id=prod_lindsey.id,
        commit=args.commit,
        yes_i_am_sure=args.yes_i_am_sure,
    )


# ---------------------------------------------------------------------------
# Enumeration + expected-state builder
# ---------------------------------------------------------------------------


def _atlas_key_and_name(source_row: Location) -> tuple[str, str]:
    """Apply the Atlas rename table. Returns (final_key, final_name)."""
    if source_row.key in RENAMES_ATLAS:
        r = RENAMES_ATLAS[source_row.key]
        return r["key"], r["name"]
    return source_row.key, source_row.name


def _place_slug_and_name(source_row: Place) -> tuple[str, str]:
    """Apply the Place rename table."""
    if source_row.slug in RENAMES_PLACE:
        r = RENAMES_PLACE[source_row.slug]
        return r["slug"], r["name"]
    return source_row.slug, source_row.name


def _location_expected(source_row: Location) -> dict[str, Any]:
    """Expected prod state for a Location after this migration —
    every carried field, every nulled field."""
    key, name = _atlas_key_and_name(source_row)
    expected: dict[str, Any] = {"key": key, "name": name}
    for f in LOCATION_CARRY_FIELDS:
        expected[f] = getattr(source_row, f)
    for f in LOCATION_NULLED_FIELDS:
        expected[f] = None
    return expected


def _place_expected(source_row: Place) -> dict[str, Any]:
    slug, name = _place_slug_and_name(source_row)
    expected: dict[str, Any] = {"slug": slug, "name": name}
    for f in PLACE_CARRY_FIELDS:
        expected[f] = getattr(source_row, f)
    for f in PLACE_NULLED_FIELDS:
        expected[f] = None
    return expected


def _wgdoc_expected(source_row: WorldGuideDocument, prod_lindsey_id: str) -> dict[str, Any]:
    expected: dict[str, Any] = {"slug": source_row.slug}
    for f in WGDOC_CARRY_FIELDS:
        expected[f] = getattr(source_row, f)
    expected["author_user_id"] = prod_lindsey_id
    expected["current_version_id"] = None  # draft-only invariant
    return expected


def _wgver_expected(
    source_row: WorldGuideVersion,
    prod_doc_id: str,
    prod_lindsey_id: str,
) -> dict[str, Any]:
    expected: dict[str, Any] = {}
    for f in WGVER_CARRY_FIELDS:
        expected[f] = getattr(source_row, f)
    expected["document_id"] = prod_doc_id
    expected["published_at"] = None
    expected["published_by_user_id"] = None
    expected["last_edited_by_user_id"] = (
        prod_lindsey_id if source_row.last_edited_by_user_id else None
    )
    return expected


def enumerate_plan(
    ctx: MigrationContext,
    prod_state: ProdReadState | None = None,
) -> MigrationPlan:
    """Read local + prod, build the write plan + expected-state manifests.

    Also runs several sanity assertions along the way — refuses on
    anything that looks wrong before enumerating further.

    ``prod_state`` is injectable for tests. Production callers pass
    ``None`` and we read from ``ctx.prod_session`` directly."""
    local = ctx.local_session
    if prod_state is None:
        prod_state = _read_prod_state(ctx.prod_session)
    plan = MigrationPlan()

    # ----- Locations --------------------------------------------------------
    local_locs = local.query(Location).all()

    # Sanity: exactly 1 hidden, and it MUST be crystal-hollow.
    hidden = [l for l in local_locs if l.status == "hidden"]
    if not (len(hidden) == 1 and hidden[0].key == EXCLUDED_ATLAS_KEY):
        raise PreflightError(
            f"Local sanity: expected exactly 1 hidden Location "
            f"({EXCLUDED_ATLAS_KEY!r}); got "
            f"{[l.key for l in hidden]}"
        )

    # Sanity: all 12 seed placeholder keys exist locally (as ATLAS type).
    local_atlas_keys = {l.key for l in local_locs if l.location_type == "ATLAS"}
    missing_seed_local = EXPECTED_SEED_ATLAS_KEYS - local_atlas_keys
    if missing_seed_local:
        raise PreflightError(
            f"Local sanity: missing Atlas seed keys: "
            f"{sorted(missing_seed_local)}"
        )

    # Sanity: all 3 community seed keys exist locally (as COMMUNITY type).
    local_community_keys = {l.key for l in local_locs if l.location_type == "COMMUNITY"}
    missing_com_local = EXPECTED_SEED_COMMUNITY_KEYS - local_community_keys
    if missing_com_local:
        raise PreflightError(
            f"Local sanity: missing Community seed keys: "
            f"{sorted(missing_com_local)}"
        )

    # Sanity: local Atlas count is exactly 20 (19 active + crystal-hollow).
    if len(local_atlas_keys) != 20:
        raise PreflightError(
            f"Local sanity: expected 20 ATLAS keys, got {len(local_atlas_keys)}."
        )

    # Build UPDATE / CREATE partitions using the injected snapshot.
    prod_locs_by_key = prod_state.locations_by_key

    for l in local_locs:
        if l.key == EXCLUDED_ATLAS_KEY:
            continue  # crystal-hollow — deliberately excluded.

        final_key, final_name = _atlas_key_and_name(l)

        if l.location_type == "ATLAS":
            if l.key in EXPECTED_SEED_ATLAS_KEYS:
                # UPDATE existing seed row (prod ID stable).
                prod_row = prod_locs_by_key.get(l.key)
                if prod_row is None:
                    raise PreflightError(
                        f"Prod is missing expected seed Atlas key {l.key!r}. "
                        "Prod's migrations may not be at head, or a seed "
                        "row was manually deleted."
                    )
                plan.locations_update.append({
                    "source": l, "prod_row": prod_row,
                    "expected": _location_expected(l),
                })
            else:
                # CREATE (admin-authored or renamed).
                plan.locations_create.append({
                    "source": l, "expected": _location_expected(l),
                })
        elif l.location_type == "CORNERSTONE":
            plan.locations_create.append({
                "source": l, "expected": _location_expected(l),
            })
        elif l.location_type == "COMMUNITY":
            if l.key not in EXPECTED_SEED_COMMUNITY_KEYS:
                raise PreflightError(
                    f"Unexpected COMMUNITY key {l.key!r} in local — "
                    "manifest only expects the three seeded rows."
                )
            prod_row = prod_locs_by_key.get(l.key)
            if prod_row is None:
                raise PreflightError(
                    f"Prod is missing expected seed Community key {l.key!r}."
                )
            plan.locations_update.append({
                "source": l, "prod_row": prod_row,
                "expected": _location_expected(l),
            })
        else:
            raise PreflightError(
                f"Local Location {l.key!r} has unknown location_type "
                f"{l.location_type!r} — refusing (manifest supports only "
                "ATLAS, CORNERSTONE, COMMUNITY)."
            )

    # Prod collision refusal for CREATE targets.
    expected_create_keys = (
        TARGET_ATLAS_CREATE_KEYS | TARGET_CORNERSTONE_CREATE_KEYS
    )
    for k in expected_create_keys:
        if k in prod_locs_by_key:
            raise PreflightError(
                f"Prod already has a Location with key {k!r}. Refusing to "
                "duplicate — this indicates a prior partial run or manual "
                "admin work. Manual reconciliation required."
            )

    # ----- Places -----------------------------------------------------------
    local_places = local.query(Place).all()
    local_place_slugs = {p.slug for p in local_places}
    if not {"melbourne", "mornington-penninsula"}.issubset(local_place_slugs):
        raise PreflightError(
            f"Local sanity: expected Places 'melbourne' and "
            f"'mornington-penninsula'; got {sorted(local_place_slugs)}."
        )
    prod_place_slugs = prod_state.place_slugs
    for expected_slug in TARGET_PLACE_CREATE_SLUGS:
        if expected_slug in prod_place_slugs:
            raise PreflightError(
                f"Prod already has a Place with slug {expected_slug!r}. "
                "Refusing to duplicate."
            )
    # ONLY carry the two we care about — anything else in local is
    # out of scope. Defensive against future local test rows.
    for p in local_places:
        if p.slug in ("melbourne", "mornington-penninsula"):
            plan.places_create.append({
                "source": p, "expected": _place_expected(p),
            })

    # ----- World Guide ------------------------------------------------------
    local_wgdocs = local.query(WorldGuideDocument).all()
    if len(local_wgdocs) != 9:
        raise PreflightError(
            f"Local sanity: expected 9 WorldGuideDocument rows; "
            f"got {len(local_wgdocs)}."
        )

    # Draft-only invariant on the source side.
    for d in local_wgdocs:
        if d.current_version_id is not None:
            raise PreflightError(
                f"Local WorldGuideDocument {d.slug!r} has "
                "current_version_id set — draft-only invariant violated "
                "in the source. Refusing to proceed."
            )

    prod_wgdoc_slugs = prod_state.wgdoc_slugs
    for d in local_wgdocs:
        if d.slug in prod_wgdoc_slugs:
            raise PreflightError(
                f"Prod already has a WorldGuideDocument with slug "
                f"{d.slug!r}. Refusing to duplicate."
            )
        plan.wgdocs_create.append({
            "source": d,
            "expected": _wgdoc_expected(d, ctx.prod_lindsey_id),
        })

    # Versions — each must be draft, none published.
    local_wgvers = local.query(WorldGuideVersion).all()
    if len(local_wgvers) != len(local_wgdocs):
        # Not strictly required to be 1:1 but the audit found 1 per doc;
        # any drift is a signal to re-review before migrating.
        raise PreflightError(
            f"Local sanity: expected {len(local_wgdocs)} WorldGuideVersion "
            f"rows (1 per document); got {len(local_wgvers)}."
        )
    for v in local_wgvers:
        if v.published_at is not None or v.published_by_user_id is not None:
            raise PreflightError(
                f"Local WorldGuideVersion {v.id!r} has publication fields "
                "set — draft-only invariant violated in the source."
            )
        if v.status != "draft":
            raise PreflightError(
                f"Local WorldGuideVersion {v.id!r} has status "
                f"{v.status!r} — expected 'draft'."
            )
    # Preserve local source order; we'll link via document_id later.
    for v in local_wgvers:
        # Version's expected `document_id` is resolved at write time
        # once the doc UUID is known — recorded as None here.
        plan.wgvers_create.append({
            "source": v,
            "expected_partial": {},  # filled in during execute
        })

    # Final total assertion — must match the locked manifest.
    if plan.total_writes() != EXPECTED_TOTAL_WRITES:
        raise PreflightError(
            f"Plan totals {plan.total_writes()} writes; manifest expects "
            f"exactly {EXPECTED_TOTAL_WRITES}. Refusing — enumeration "
            "produced a plan of the wrong shape."
        )
    if plan.total_updates() != EXPECTED_UPDATES or plan.total_creates() != EXPECTED_CREATES:
        raise PreflightError(
            f"Plan U/C split {plan.total_updates()}/{plan.total_creates()} "
            f"— manifest expects {EXPECTED_UPDATES}/{EXPECTED_CREATES}."
        )
    return plan


# ---------------------------------------------------------------------------
# Summary + confirmation
# ---------------------------------------------------------------------------


def _rule(c: str = "=", w: int = 78) -> str:
    return c * w


def print_summary(plan: MigrationPlan, ctx: MigrationContext) -> None:
    mode = "COMMIT" if ctx.commit else "DRY RUN — no writes will occur"
    print(_rule())
    print(f"Mother World / shared-content migration — {mode}")
    print(_rule())
    print(f"  Target owner: {PROD_OWNER_EMAIL} (prod id={ctx.prod_lindsey_id})")
    print(f"  Total writes: {plan.total_writes()} "
          f"({plan.total_updates()} UPDATE + {plan.total_creates()} CREATE)")
    print(f"  Manifest expects {EXPECTED_TOTAL_WRITES} "
          f"({EXPECTED_UPDATES} + {EXPECTED_CREATES}) — parity: "
          f"{'✓' if plan.total_writes() == EXPECTED_TOTAL_WRITES else '✗'}")
    print()
    print("Locations — UPDATE ({}):".format(len(plan.locations_update)))
    for entry in plan.locations_update:
        exp = entry["expected"]
        prod_row = entry["prod_row"]
        print(f"  ~ key={exp['key']!r:35}  prod_id={prod_row.id}   type={exp['location_type']}")
    print("Locations — CREATE ({}):".format(len(plan.locations_create)))
    for entry in plan.locations_create:
        exp = entry["expected"]
        rename = (" (renamed from " +
                  entry["source"].key + ")") if entry["source"].key != exp["key"] else ""
        print(f"  + key={exp['key']!r:35}   type={exp['location_type']}{rename}")
    print()
    print("Places — CREATE ({}):".format(len(plan.places_create)))
    for entry in plan.places_create:
        exp = entry["expected"]
        rename = (" (renamed from " + entry["source"].slug + ")"
                  if entry["source"].slug != exp["slug"] else "")
        print(f"  + slug={exp['slug']!r:35}   name={exp['name']!r}{rename}")
    print()
    print("WorldGuideDocument — CREATE ({}):".format(len(plan.wgdocs_create)))
    for entry in plan.wgdocs_create:
        exp = entry["expected"]
        print(f"  + slug={exp['slug']!r:40} audience={exp['audience']} "
              f"category={exp['category']}")
    print()
    print("WorldGuideVersion — CREATE ({}, all draft, all published_at NULL):".format(
        len(plan.wgvers_create)))
    for entry in plan.wgvers_create:
        v = entry["source"]
        print(f"  + doc_id={v.document_id}   v{v.version_number}   status={v.status}")
    print()
    print("R2 objects to touch: 0 (media excluded from this migration)")
    print()


def confirm_interactive() -> None:
    print("Type 'y' to commit to prod, anything else to abort: ", end="", flush=True)
    if sys.stdin.readline().strip().lower() != "y":
        raise SystemExit("Aborted by operator.")


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


@dataclass
class IdMaps:
    wgdoc: dict[str, str] = field(default_factory=dict)   # local_id → prod_id


def execute(plan: MigrationPlan, ctx: MigrationContext) -> IdMaps:
    """Perform every write inside a single prod-side transaction.
    Caller wraps in try/except with rollback."""
    id_maps = IdMaps()
    prod = ctx.prod_session

    # 1. Location UPDATEs — mutate the existing prod row.
    for entry in plan.locations_update:
        exp = entry["expected"]
        prod_row = entry["prod_row"]
        for f, v in exp.items():
            setattr(prod_row, f, v)
    log.info("Location — %d rows UPDATED", len(plan.locations_update))

    # 2. Location CREATEs — fresh UUIDs.
    for entry in plan.locations_create:
        exp = entry["expected"]
        source = entry["source"]
        row = Location(
            id=str(uuid4()),
            created_at=source.created_at,
            **exp,
        )
        prod.add(row)
    prod.flush()
    log.info("Location — %d rows CREATED", len(plan.locations_create))

    # 3. Place CREATEs.
    for entry in plan.places_create:
        exp = entry["expected"]
        source = entry["source"]
        row = Place(
            id=str(uuid4()),
            created_at=source.created_at,
            **exp,
        )
        prod.add(row)
    prod.flush()
    log.info("Place — %d rows CREATED", len(plan.places_create))

    # 4. WorldGuideDocument CREATEs — capture id map.
    for entry in plan.wgdocs_create:
        exp = entry["expected"]
        source = entry["source"]
        prod_id = str(uuid4())
        id_maps.wgdoc[source.id] = prod_id
        row = WorldGuideDocument(
            id=prod_id,
            created_at=source.created_at,
            **exp,
        )
        prod.add(row)
    prod.flush()
    log.info("WorldGuideDocument — %d rows CREATED", len(plan.wgdocs_create))

    # 5. WorldGuideVersion CREATEs — remap document_id.
    for entry in plan.wgvers_create:
        source = entry["source"]
        prod_doc_id = id_maps.wgdoc.get(source.document_id)
        if not prod_doc_id:
            raise RuntimeError(
                f"WorldGuideVersion {source.id!r} references local "
                f"document_id {source.document_id!r} which is not in "
                "the doc id_map — enumeration is inconsistent."
            )
        expected = _wgver_expected(source, prod_doc_id, ctx.prod_lindsey_id)
        entry["expected"] = expected  # record for verification
        row = WorldGuideVersion(
            id=str(uuid4()),
            created_at=source.created_at,
            **expected,
        )
        prod.add(row)
    prod.flush()
    log.info("WorldGuideVersion — %d rows CREATED", len(plan.wgvers_create))

    prod.commit()
    return id_maps


# ---------------------------------------------------------------------------
# Deterministic content verification
# ---------------------------------------------------------------------------


def _compare_fields(
    *,
    prod_row: Any,
    expected: dict[str, Any],
    label: str,
    key_desc: str,
) -> list[str]:
    errors: list[str] = []
    for f, want in expected.items():
        got = getattr(prod_row, f)
        if got != want:
            errors.append(
                f"{label} {key_desc}: field {f!r} "
                f"expected {want!r} got {got!r}"
            )
    return errors


def verify(plan: MigrationPlan, ctx: MigrationContext) -> list[str]:
    """Re-read prod, compare every migrated row's carried fields to
    the expected snapshot. Returns list of error strings; empty means
    verification passed."""
    errors: list[str] = []
    prod = ctx.prod_session

    # Locations
    for entry in plan.locations_update + plan.locations_create:
        exp = entry["expected"]
        prod_row = prod.query(Location).filter(Location.key == exp["key"]).first()
        if prod_row is None:
            errors.append(f"Location key={exp['key']!r} NOT FOUND in prod after commit.")
            continue
        errors.extend(_compare_fields(
            prod_row=prod_row, expected=exp,
            label="Location", key_desc=f"key={exp['key']!r}",
        ))

    # Places
    for entry in plan.places_create:
        exp = entry["expected"]
        prod_row = prod.query(Place).filter(Place.slug == exp["slug"]).first()
        if prod_row is None:
            errors.append(f"Place slug={exp['slug']!r} NOT FOUND in prod after commit.")
            continue
        errors.extend(_compare_fields(
            prod_row=prod_row, expected=exp,
            label="Place", key_desc=f"slug={exp['slug']!r}",
        ))

    # WorldGuideDocuments
    for entry in plan.wgdocs_create:
        exp = entry["expected"]
        prod_row = prod.query(WorldGuideDocument).filter(
            WorldGuideDocument.slug == exp["slug"]).first()
        if prod_row is None:
            errors.append(f"WorldGuideDocument slug={exp['slug']!r} NOT FOUND after commit.")
            continue
        errors.extend(_compare_fields(
            prod_row=prod_row, expected=exp,
            label="WorldGuideDocument", key_desc=f"slug={exp['slug']!r}",
        ))

    # WorldGuideVersions — verify each version by walking source→doc slug→prod
    # doc, then finding the matching version_number under that doc.
    docs_by_local_id = {e["source"].id: e for e in plan.wgdocs_create}
    for entry in plan.wgvers_create:
        source_v = entry["source"]
        exp = entry.get("expected")
        if exp is None:
            errors.append(f"WorldGuideVersion {source_v.id!r}: expected snapshot not captured during execute.")
            continue
        doc_entry = docs_by_local_id.get(source_v.document_id)
        if not doc_entry:
            errors.append(f"WorldGuideVersion {source_v.id!r}: parent doc not in plan.")
            continue
        doc_slug = doc_entry["expected"]["slug"]
        prod_doc = prod.query(WorldGuideDocument).filter(
            WorldGuideDocument.slug == doc_slug).first()
        if prod_doc is None:
            errors.append(f"WorldGuideVersion for doc {doc_slug!r}: parent doc missing.")
            continue
        prod_row = prod.query(WorldGuideVersion).filter(
            WorldGuideVersion.document_id == prod_doc.id,
            WorldGuideVersion.version_number == source_v.version_number,
        ).first()
        if prod_row is None:
            errors.append(
                f"WorldGuideVersion doc={doc_slug!r} "
                f"v{source_v.version_number} NOT FOUND after commit."
            )
            continue
        errors.extend(_compare_fields(
            prod_row=prod_row, expected=exp,
            label="WorldGuideVersion",
            key_desc=f"doc={doc_slug!r} v{source_v.version_number}",
        ))

    # Draft-only global invariant assertions (belt-and-braces).
    n_pub_docs = prod.query(WorldGuideDocument).filter(
        WorldGuideDocument.current_version_id.isnot(None)).count()
    if n_pub_docs > 0:
        errors.append(
            f"Draft-only invariant broken: {n_pub_docs} WorldGuideDocument(s) "
            "have current_version_id set after commit."
        )
    n_pub_vers = prod.query(WorldGuideVersion).filter(
        (WorldGuideVersion.published_at.isnot(None))
        | (WorldGuideVersion.published_by_user_id.isnot(None))
        | (WorldGuideVersion.status != "draft")
    ).count()
    if n_pub_vers > 0:
        errors.append(
            f"Draft-only invariant broken: {n_pub_vers} WorldGuideVersion(s) "
            "have published_at / published_by_user_id / non-draft status "
            "after commit."
        )

    return errors


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Mother World / shared-content migration — local → prod.",
    )
    p.add_argument("--commit", action="store_true",
                   help="Actually write to prod. Default is dry-run.")
    p.add_argument("--yes-i-am-sure", action="store_true",
                   help="Skip interactive confirmation.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
    )
    args = parse_args(argv)

    try:
        ctx = _open_sessions(args)
    except PreflightError as e:
        print(f"PREFLIGHT: {e}", file=sys.stderr)
        return 2

    try:
        plan = enumerate_plan(ctx)
    except PreflightError as e:
        print(f"PREFLIGHT: {e}", file=sys.stderr)
        return 2

    print_summary(plan, ctx)

    if not ctx.commit:
        print("Dry-run complete. Pass --commit to actually migrate.")
        return 0

    if not ctx.yes_i_am_sure:
        confirm_interactive()

    try:
        execute(plan, ctx)
    except Exception as e:  # noqa: BLE001
        ctx.prod_session.rollback()
        print(f"\nWRITE FAILED — prod DB rolled back: {e}", file=sys.stderr)
        return 4

    errors = verify(plan, ctx)
    if errors:
        print(f"\nCONTENT VERIFICATION FAILED — {len(errors)} mismatch(es):",
              file=sys.stderr)
        for e in errors[:50]:
            print(f"  ✗ {e}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  ... and {len(errors) - 50} more", file=sys.stderr)
        print(
            "\nCommit already landed but content differs from expected.\n"
            "Investigate before proceeding with any Collective migration.",
            file=sys.stderr,
        )
        return 5

    print()
    print(_rule())
    print(f"MIGRATION COMPLETE — {EXPECTED_TOTAL_WRITES} rows written, "
          f"content verification passed on every field of every row.")
    print(_rule())
    return 0


if __name__ == "__main__":
    sys.exit(main())
