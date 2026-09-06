#!/usr/bin/env python
"""Read-only local-vs-prod audit for platform-authored / reference-catalogue
tables.

Goal: surface every discrepancy between local dev and production for the
tables Fresh Collective authors through Mother World / Admin Portal —
Locations, Places, Atmosphere/Colour/Element/Landscape catalogues,
Platform Artwork, World Guide, Creator/Subscription plans, Comms
topics/categories/defaults. Compares by stable natural key (never by
UUID) and classifies every row as IDENTICAL / DIFFERENT / LOCAL_ONLY /
PROD_ONLY.

Safety (structurally enforced):
  * SELECT-only. No INSERT/UPDATE/DELETE/DDL anywhere in the source.
    A regression test in tests/test_audit_local_vs_prod.py greps the
    source and asserts the absence of every write verb.
  * Refuses to run if DATABASE_URL and PROD_DATABASE_URL resolve to
    the same host+database. Same guard shape as the EMBODY importer.
  * Two separate SQLAlchemy engines, no cross-DB session mixing.
  * No R2 client, no boto3 import, no filesystem writes outside
    stdout.
  * Passwords/credentials never printed — only sanitised host+dbname.

Usage:
    cd backend
    .venv/bin/python scripts/audit_local_vs_prod.py

Optional:
    --json               Print full report as JSON (in addition to text).
    --sections=LIST      Only run named sections (default: all).
                         Comma-separated from: tables, fk, motherworld,
                         media, summary.
    --show-diffs=N       For DIFFERENT rows, show up to N field diffs
                         per row (default 8).

Required env vars:
    DATABASE_URL          local dev DB (already in backend/.env)
    PROD_DATABASE_URL     prod DB (exported from Render → fc-db
                          External Connection String; NEVER in .env)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Same bootstrap pattern as the other backend scripts.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except ImportError:
    pass

import app.main  # noqa: F401,E402  — prime SQLAlchemy registry

from sqlalchemy import create_engine, inspect as sa_inspect, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.comms.models import (  # noqa: E402
    CommunicationCategory,
    CommunicationChannelDefault,
    CommunicationTopic,
)
from app.models.creator_billing import CreatorPlan  # noqa: E402
from app.models.place import Place, SpacePlace  # noqa: E402
from app.models.platform import (  # noqa: E402
    AtmosphereOption,
    ColourStory,
    ElementOption,
    LandscapeOption,
    Location,
    PlatformArtwork,
    Space,
)
from app.models.sales import SubscriptionPlan, SubscriptionPrice  # noqa: E402
from app.models.world_guide import WorldGuideDocument, WorldGuideVersion  # noqa: E402


# ---------------------------------------------------------------------------
# Preflight / safety
# ---------------------------------------------------------------------------


class PreflightError(RuntimeError):
    pass


def _sanitised_url(url: str) -> str:
    p = urlparse(url)
    host = p.hostname or "?"
    port = f":{p.port}" if p.port else ""
    return f"{p.scheme}://{p.username or '?'}@{host}{port}{p.path}"


def _same_db(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.hostname, pa.port, pa.path) == (pb.hostname, pb.port, pb.path)


def _open_sessions() -> tuple[Session, Session, str, str]:
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
            "host+database. Refusing — audit is meaningless."
        )

    local_engine = create_engine(local_url, future=True)
    prod_engine = create_engine(prod_url, future=True)
    LocalSession = sessionmaker(bind=local_engine, future=True)
    ProdSession = sessionmaker(bind=prod_engine, future=True)
    local = LocalSession()
    prod = ProdSession()
    local.execute(select(1)).scalar_one()
    prod.execute(select(1)).scalar_one()
    return local, prod, _sanitised_url(local_url), _sanitised_url(prod_url)


# ---------------------------------------------------------------------------
# Diff engine
# ---------------------------------------------------------------------------


@dataclass
class FieldDiff:
    field: str
    local: Any
    prod: Any


@dataclass
class RowDiff:
    key: str
    fields: list[FieldDiff]

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "fields": [
                {"field": f.field, "local": _shorten(f.local), "prod": _shorten(f.prod)}
                for f in self.fields
            ],
        }


@dataclass
class TableAudit:
    label: str  # human-readable table label
    tablename: str  # DB tablename
    key_kind: str  # description of the natural key used
    total_local: int
    total_prod: int
    identical: int
    different: list[RowDiff] = field(default_factory=list)
    local_only: list[dict] = field(default_factory=list)
    prod_only: list[dict] = field(default_factory=list)
    # Rows whose data is IDENTICAL except for URL fields — surfaces
    # separately as "requires media migration".
    media_url_differs: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary_line(self) -> str:
        return (
            f"{self.label:38}  local={self.total_local:>4}  prod={self.total_prod:>4}  "
            f"identical={self.identical:>4}  diff={len(self.different):>3}  "
            f"local_only={len(self.local_only):>3}  prod_only={len(self.prod_only):>3}"
        )


def _shorten(v: Any, limit: int = 120) -> Any:
    if v is None or isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    if len(s) <= limit:
        return s
    return s[:limit] + "..."


def _normalise_jsonish(v: Any) -> Any:
    """Sort JSON lists so element order doesn't produce false diffs."""
    if isinstance(v, list):
        # sort by str repr; won't mutate original list because we rebuild
        try:
            return sorted(v, key=str)
        except Exception:  # noqa: BLE001
            return v
    return v


def _row_to_dict(row: Any, columns: list[str]) -> dict:
    return {c: getattr(row, c) for c in columns}


# ---------------------------------------------------------------------------
# Per-table auditors
# ---------------------------------------------------------------------------


# Fields whose difference should be surfaced as "requires media
# migration" rather than "config drift".
_MEDIA_URL_FIELDS: set[str] = {
    "hero_artwork_url",
    "thumbnail_artwork_url",
    "image_url",
    "thumbnail_url",
}
# Every table's ``created_at`` / ``updated_at`` is expected to differ.
_TIMESTAMP_FIELDS: set[str] = {"created_at", "updated_at"}


def _audit_by_natural_key(
    *,
    label: str,
    tablename: str,
    model: Any,
    natural_key: str,
    local: Session,
    prod: Session,
    identity_fields: list[str],
    compare_fields: list[str] | None = None,
    key_kind: str = "single-column key",
    key_extractor=None,
) -> TableAudit:
    """Generic single-column-natural-key auditor.

    ``key_extractor`` is a callable ``row → key`` used for the composite
    key auditors; when None, we just use ``getattr(row, natural_key)``.
    """
    columns = [c.name for c in sa_inspect(model).columns]
    all_local = local.query(model).all()
    all_prod = prod.query(model).all()

    if key_extractor is None:
        def key_extractor(r):
            return getattr(r, natural_key)

    by_key_local = {key_extractor(r): r for r in all_local}
    by_key_prod = {key_extractor(r): r for r in all_prod}

    audit = TableAudit(
        label=label,
        tablename=tablename,
        key_kind=key_kind,
        total_local=len(all_local),
        total_prod=len(all_prod),
        identical=0,
    )

    local_keys = set(by_key_local)
    prod_keys = set(by_key_prod)

    for k in sorted(local_keys - prod_keys, key=str):
        row = by_key_local[k]
        audit.local_only.append({
            "key": k,
            **{f: _shorten(getattr(row, f, None)) for f in identity_fields},
        })

    for k in sorted(prod_keys - local_keys, key=str):
        row = by_key_prod[k]
        audit.prod_only.append({
            "key": k,
            **{f: _shorten(getattr(row, f, None)) for f in identity_fields},
        })

    fields_to_check = compare_fields or [
        c for c in columns
        if c != natural_key
        and c not in _TIMESTAMP_FIELDS
        and c != "id"
    ]

    for k in sorted(local_keys & prod_keys, key=str):
        lrow = by_key_local[k]
        prow = by_key_prod[k]
        diffs: list[FieldDiff] = []
        media_diffs: list[FieldDiff] = []
        for f in fields_to_check:
            lv = _normalise_jsonish(getattr(lrow, f, None))
            pv = _normalise_jsonish(getattr(prow, f, None))
            if lv != pv:
                fd = FieldDiff(field=f, local=lv, prod=pv)
                if f in _MEDIA_URL_FIELDS:
                    media_diffs.append(fd)
                else:
                    diffs.append(fd)
        if not diffs and not media_diffs:
            audit.identical += 1
        else:
            if diffs:
                audit.different.append(RowDiff(key=str(k), fields=diffs))
            if media_diffs:
                audit.media_url_differs.append({
                    "key": str(k),
                    "urls": [
                        {"field": d.field, "local": d.local, "prod": d.prod}
                        for d in media_diffs
                    ],
                })

    return audit


def audit_locations(local: Session, prod: Session) -> TableAudit:
    return _audit_by_natural_key(
        label="Location (Mother World)",
        tablename="locations",
        model=Location,
        natural_key="key",
        local=local, prod=prod,
        identity_fields=["name", "location_type", "status"],
        compare_fields=[
            "name", "description", "atlas_entry", "status", "location_type",
            "hero_artwork_url", "thumbnail_artwork_url", "biome",
            "archipelago", "preferred_atmospheres",
            "preferred_colour_stories", "preferred_themes", "position",
        ],
    )


def audit_places(local: Session, prod: Session) -> TableAudit:
    return _audit_by_natural_key(
        label="Place (physical)",
        tablename="places",
        model=Place,
        natural_key="slug",
        local=local, prod=prod,
        identity_fields=["name", "country_code", "status"],
        compare_fields=[
            "name", "country_code", "region", "blurb", "admin_note",
            "hero_artwork_url", "artwork_alt_text", "artwork_focal_x",
            "artwork_focal_y", "latitude", "longitude", "timezone",
            "provider_place_id", "status",
        ],
    )


def audit_atmospheres(local: Session, prod: Session) -> TableAudit:
    return _audit_by_natural_key(
        label="AtmosphereOption", tablename="atmosphere_options",
        model=AtmosphereOption, natural_key="key",
        local=local, prod=prod,
        identity_fields=["name", "position", "is_active"],
    )


def audit_colour_stories(local: Session, prod: Session) -> TableAudit:
    return _audit_by_natural_key(
        label="ColourStory", tablename="colour_stories",
        model=ColourStory, natural_key="key",
        local=local, prod=prod,
        identity_fields=["name", "position", "is_active"],
    )


def audit_elements(local: Session, prod: Session) -> TableAudit:
    return _audit_by_natural_key(
        label="ElementOption", tablename="element_options",
        model=ElementOption, natural_key="key",
        local=local, prod=prod,
        identity_fields=["name", "glyph_key", "position", "is_active"],
    )


def audit_landscapes(local: Session, prod: Session) -> TableAudit:
    return _audit_by_natural_key(
        label="LandscapeOption", tablename="landscape_options",
        model=LandscapeOption, natural_key="key",
        local=local, prod=prod,
        identity_fields=["name", "motif_key", "position", "is_active"],
    )


def audit_platform_artwork(local: Session, prod: Session) -> TableAudit:
    return _audit_by_natural_key(
        label="PlatformArtwork", tablename="platform_artwork",
        model=PlatformArtwork, natural_key="key",
        local=local, prod=prod,
        identity_fields=["image_url", "thumbnail_url"],
    )


def audit_world_guide_documents(local: Session, prod: Session) -> TableAudit:
    """Includes ALL documents (not just published). Version breakdown
    happens in ``audit_world_guide_versions``."""
    return _audit_by_natural_key(
        label="WorldGuideDocument", tablename="world_guide_documents",
        model=WorldGuideDocument, natural_key="slug",
        local=local, prod=prod,
        identity_fields=["title", "category", "audience", "archived_at"],
        compare_fields=[
            "title", "category", "audience", "summary",
            "reading_time_minutes", "archived_at",
        ],
    )


def audit_world_guide_versions(local: Session, prod: Session) -> TableAudit:
    """Compare by composite (document.slug, version_number). Reports
    status so we can distinguish published missing/stale from local-
    only drafts and archived rows. Per your instruction: do NOT
    restrict to published — draft local-only content is exactly what
    this audit needs to reveal."""

    def _versions_by_composite(session: Session) -> dict[tuple[str, str], WorldGuideVersion]:
        result: dict[tuple[str, str], WorldGuideVersion] = {}
        # Build a doc_id → slug map per session first.
        docs = {d.id: d.slug for d in session.query(WorldGuideDocument).all()}
        for v in session.query(WorldGuideVersion).all():
            slug = docs.get(v.document_id)
            if slug is None:
                continue  # orphan; separate concern
            result[(slug, v.version_number)] = v
        return result

    local_by = _versions_by_composite(local)
    prod_by = _versions_by_composite(prod)

    audit = TableAudit(
        label="WorldGuideVersion",
        tablename="world_guide_versions",
        key_kind="composite: (document.slug, version_number)",
        total_local=len(local_by),
        total_prod=len(prod_by),
        identical=0,
    )
    audit.notes.append(
        "Includes ALL versions regardless of status (published, draft, "
        "archived). Draft local-only rows are surfaced deliberately."
    )

    id_fields = ["status", "effective_date", "published_at"]
    compare_fields = [
        "status", "effective_date", "why_this_exists", "what_this_covers",
        "main_content", "whats_changed", "published_at",
    ]

    local_keys = set(local_by)
    prod_keys = set(prod_by)

    for k in sorted(local_keys - prod_keys):
        v = local_by[k]
        audit.local_only.append({
            "key": f"{k[0]} v{k[1]}",
            **{f: _shorten(getattr(v, f, None)) for f in id_fields},
        })
    for k in sorted(prod_keys - local_keys):
        v = prod_by[k]
        audit.prod_only.append({
            "key": f"{k[0]} v{k[1]}",
            **{f: _shorten(getattr(v, f, None)) for f in id_fields},
        })

    for k in sorted(local_keys & prod_keys):
        lv = local_by[k]
        pv = prod_by[k]
        diffs = [
            FieldDiff(field=f, local=_shorten(getattr(lv, f, None)),
                      prod=_shorten(getattr(pv, f, None)))
            for f in compare_fields
            if getattr(lv, f, None) != getattr(pv, f, None)
        ]
        if diffs:
            audit.different.append(RowDiff(key=f"{k[0]} v{k[1]}", fields=diffs))
        else:
            audit.identical += 1
    return audit


def audit_creator_plans(local: Session, prod: Session) -> TableAudit:
    return _audit_by_natural_key(
        label="CreatorPlan (subscription tier)",
        tablename="creator_plans",
        model=CreatorPlan, natural_key="slug",
        local=local, prod=prod,
        identity_fields=["name", "monthly_price_cents", "is_active"],
        compare_fields=[
            "name", "description", "monthly_price_cents", "currency",
            "transaction_fee_basis_points", "collective_limit",
            "pathway_limit", "media_storage_limit_mb",
            "creator_admin_seat_limit", "is_active",
        ],
    )


def audit_subscription_plans(local: Session, prod: Session) -> TableAudit:
    """Sales-CRM plan catalogue. Distinct from CreatorPlan (which is
    Fresh Collective's own creator subscription tiers). Both are live
    per source-trace at time of audit build:
    ``app/sales/service.py`` writes/reads SubscriptionPlan;
    ``app/purchases/checkout.py`` reads CreatorPlan. Include both."""
    audit = _audit_by_natural_key(
        label="SubscriptionPlan (sales CRM)",
        tablename="subscription_plans",
        model=SubscriptionPlan, natural_key="name",
        local=local, prod=prod,
        identity_fields=["is_active"],
        compare_fields=["description", "is_active"],
        key_kind="⚠ 'name' (not unique-constrained — duplicate-name detection below)",
    )
    # Flag duplicates.
    from collections import Counter
    local_names = Counter(p.name for p in local.query(SubscriptionPlan).all())
    prod_names = Counter(p.name for p in prod.query(SubscriptionPlan).all())
    dupes_local = [n for n, c in local_names.items() if c > 1]
    dupes_prod = [n for n, c in prod_names.items() if c > 1]
    if dupes_local:
        audit.notes.append(f"Local has duplicate names: {dupes_local}")
    if dupes_prod:
        audit.notes.append(f"Prod has duplicate names: {dupes_prod}")
    return audit


def audit_subscription_prices(local: Session, prod: Session) -> TableAudit:
    """Composite key: (plan.name, currency, billing_interval,
    effective_from date). Datetime→date to avoid ms-precision noise."""

    def _prices_by_composite(session: Session) -> dict[tuple[str, str, str, Any], SubscriptionPrice]:
        result: dict[tuple[str, str, str, Any], SubscriptionPrice] = {}
        plans = {p.id: p.name for p in session.query(SubscriptionPlan).all()}
        for p in session.query(SubscriptionPrice).all():
            plan_name = plans.get(p.plan_id, "?")
            eff = p.effective_from.date() if p.effective_from else None
            result[(plan_name, p.currency, p.billing_interval, eff)] = p
        return result

    local_by = _prices_by_composite(local)
    prod_by = _prices_by_composite(prod)

    audit = TableAudit(
        label="SubscriptionPrice",
        tablename="subscription_prices",
        key_kind="composite: (plan.name, currency, billing_interval, effective_from.date)",
        total_local=len(local_by),
        total_prod=len(prod_by),
        identical=0,
    )
    id_fields = ["amount_cents", "is_active", "effective_to"]
    compare_fields = ["amount_cents", "is_active", "effective_to"]

    local_keys = set(local_by)
    prod_keys = set(prod_by)
    for k in sorted(local_keys - prod_keys, key=str):
        v = local_by[k]
        audit.local_only.append({
            "key": " / ".join(str(x) for x in k),
            **{f: _shorten(getattr(v, f, None)) for f in id_fields},
        })
    for k in sorted(prod_keys - local_keys, key=str):
        v = prod_by[k]
        audit.prod_only.append({
            "key": " / ".join(str(x) for x in k),
            **{f: _shorten(getattr(v, f, None)) for f in id_fields},
        })
    for k in sorted(local_keys & prod_keys, key=str):
        lv, pv = local_by[k], prod_by[k]
        diffs = [
            FieldDiff(field=f, local=_shorten(getattr(lv, f, None)),
                      prod=_shorten(getattr(pv, f, None)))
            for f in compare_fields
            if getattr(lv, f, None) != getattr(pv, f, None)
        ]
        if diffs:
            audit.different.append(RowDiff(key=" / ".join(str(x) for x in k), fields=diffs))
        else:
            audit.identical += 1
    return audit


def audit_communication_topics(local: Session, prod: Session) -> TableAudit:
    return _audit_by_natural_key(
        label="CommunicationTopic", tablename="communication_topics",
        model=CommunicationTopic, natural_key="key",
        local=local, prod=prod,
        identity_fields=["label"],
    )


def audit_communication_categories(local: Session, prod: Session) -> TableAudit:
    return _audit_by_natural_key(
        label="CommunicationCategory", tablename="communication_categories",
        model=CommunicationCategory, natural_key="key",
        local=local, prod=prod,
        identity_fields=["label", "sort_order", "is_critical"],
        compare_fields=["label", "description", "sort_order", "is_critical"],
    )


def audit_communication_channel_defaults(local: Session, prod: Session) -> TableAudit:
    def _by_composite(session: Session) -> dict[tuple[str, str], CommunicationChannelDefault]:
        return {
            (r.category_key, r.channel): r
            for r in session.query(CommunicationChannelDefault).all()
        }

    local_by = _by_composite(local)
    prod_by = _by_composite(prod)

    audit = TableAudit(
        label="CommunicationChannelDefault",
        tablename="communication_channel_defaults",
        key_kind="composite: (category_key, channel)",
        total_local=len(local_by), total_prod=len(prod_by),
        identical=0,
    )
    id_fields = ["default_enabled", "is_locked"]
    compare_fields = ["default_enabled", "is_locked", "notes"]
    local_keys, prod_keys = set(local_by), set(prod_by)
    for k in sorted(local_keys - prod_keys):
        v = local_by[k]
        audit.local_only.append({
            "key": f"{k[0]} / {k[1]}",
            **{f: _shorten(getattr(v, f, None)) for f in id_fields},
        })
    for k in sorted(prod_keys - local_keys):
        v = prod_by[k]
        audit.prod_only.append({
            "key": f"{k[0]} / {k[1]}",
            **{f: _shorten(getattr(v, f, None)) for f in id_fields},
        })
    for k in sorted(local_keys & prod_keys):
        lv, pv = local_by[k], prod_by[k]
        diffs = [
            FieldDiff(field=f, local=_shorten(getattr(lv, f, None)),
                      prod=_shorten(getattr(pv, f, None)))
            for f in compare_fields
            if getattr(lv, f, None) != getattr(pv, f, None)
        ]
        if diffs:
            audit.different.append(RowDiff(key=f"{k[0]} / {k[1]}", fields=diffs))
        else:
            audit.identical += 1
    return audit


# Registered auditors — order matters for the summary output.
_AUDITORS = [
    ("Mother World: Locations", audit_locations),
    ("Physical Places", audit_places),
    ("Atmospheres", audit_atmospheres),
    ("Colour Stories", audit_colour_stories),
    ("Elements", audit_elements),
    ("Landscapes", audit_landscapes),
    ("Platform Artwork", audit_platform_artwork),
    ("World Guide Documents", audit_world_guide_documents),
    ("World Guide Versions", audit_world_guide_versions),
    ("Creator Plans (subscription tiers)", audit_creator_plans),
    ("Subscription Plans (sales CRM)", audit_subscription_plans),
    ("Subscription Prices", audit_subscription_prices),
    ("Communication Topics", audit_communication_topics),
    ("Communication Categories", audit_communication_categories),
    ("Communication Channel Defaults", audit_communication_channel_defaults),
]


# ---------------------------------------------------------------------------
# Cross-table FK reachability
# ---------------------------------------------------------------------------


@dataclass
class ReachabilityIssue:
    space_slug: str
    field: str
    local_target_key: str | None
    reason: str


def audit_fk_reachability(local: Session, prod: Session) -> list[ReachabilityIssue]:
    """For every Space that references reference-catalogue rows by
    FK/key, check whether the target row exists in prod.

    Specifically:
      * Space.location_id → Location; verify the local Location's
        ``key`` exists in prod.
      * SpacePlace.place_id → Place; verify the local Place's
        ``slug`` exists in prod.
      * Space.colour_story_key / atmosphere_keys — check whether
        those keys exist in prod's colour_stories / atmosphere_options.
    """
    issues: list[ReachabilityIssue] = []

    # Preload prod key sets once.
    prod_location_keys = {l.key for l in prod.query(Location).all()}
    prod_place_slugs = {p.slug for p in prod.query(Place).all()}
    prod_atmosphere_keys = {a.key for a in prod.query(AtmosphereOption).all()}
    prod_colour_keys = {c.key for c in prod.query(ColourStory).all()}
    prod_element_keys = {e.key for e in prod.query(ElementOption).all()}
    prod_landscape_keys = {l.key for l in prod.query(LandscapeOption).all()}

    for space in local.query(Space).all():
        # Skip system spaces (World Builders is auto-managed by FC
        # itself and its FKs shouldn't necessarily match prod).
        if space.auto_grant_role is not None:
            continue

        if space.location_id:
            loc = local.query(Location).filter(
                Location.id == space.location_id
            ).first()
            if loc is None:
                issues.append(ReachabilityIssue(
                    space_slug=space.slug, field="location_id",
                    local_target_key=None,
                    reason=f"Local Location id {space.location_id!r} not found in local DB",
                ))
            elif loc.key not in prod_location_keys:
                issues.append(ReachabilityIssue(
                    space_slug=space.slug, field="location_id",
                    local_target_key=loc.key,
                    reason=f"Location key {loc.key!r} not present in prod",
                ))

        # SpacePlace bridge rows
        for sp in local.query(SpacePlace).filter(SpacePlace.space_id == space.id).all():
            place = local.query(Place).filter(Place.id == sp.place_id).first()
            if place is None:
                issues.append(ReachabilityIssue(
                    space_slug=space.slug, field="SpacePlace.place_id",
                    local_target_key=None,
                    reason=f"Local Place id {sp.place_id!r} not found in local DB",
                ))
            elif place.slug not in prod_place_slugs:
                issues.append(ReachabilityIssue(
                    space_slug=space.slug, field="SpacePlace.place_id",
                    local_target_key=place.slug,
                    reason=f"Place slug {place.slug!r} not present in prod",
                ))

        # String-key fields — resolve at render time, so missing prod
        # entries wouldn't cause a write failure, but the frontend
        # would fall back to defaults. Report as informational.
        if getattr(space, "colour_story_key", None):
            if space.colour_story_key not in prod_colour_keys:
                issues.append(ReachabilityIssue(
                    space_slug=space.slug, field="colour_story_key",
                    local_target_key=space.colour_story_key,
                    reason=f"colour_story key {space.colour_story_key!r} not present in prod (render fallback would apply)",
                ))
        if getattr(space, "landscape_key", None):
            if space.landscape_key not in prod_landscape_keys:
                issues.append(ReachabilityIssue(
                    space_slug=space.slug, field="landscape_key",
                    local_target_key=space.landscape_key,
                    reason=f"landscape key {space.landscape_key!r} not present in prod",
                ))
        for atm in (getattr(space, "atmosphere_keys", None) or []):
            if atm not in prod_atmosphere_keys:
                issues.append(ReachabilityIssue(
                    space_slug=space.slug, field="atmosphere_keys",
                    local_target_key=atm,
                    reason=f"atmosphere key {atm!r} not present in prod",
                ))
        for el in (getattr(space, "element_keys", None) or []):
            if el not in prod_element_keys:
                issues.append(ReachabilityIssue(
                    space_slug=space.slug, field="element_keys",
                    local_target_key=el,
                    reason=f"element key {el!r} not present in prod",
                ))

    return issues


# ---------------------------------------------------------------------------
# Mother World completeness
# ---------------------------------------------------------------------------


@dataclass
class MotherWorldReport:
    cornerstones_local: int
    cornerstones_prod: int
    atlas_local: int
    atlas_prod: int
    community_local: int
    community_prod: int
    places_local: int
    places_prod: int
    cornerstones_missing_from_prod: list[str]  # keys
    atlas_missing_from_prod: list[str]
    community_missing_from_prod: list[str]
    places_missing_from_prod: list[str]  # slugs
    # sanity-check callouts against expected counts (3 / 19 / 3)
    sanity_notes: list[str] = field(default_factory=list)


def audit_mother_world(local: Session, prod: Session) -> MotherWorldReport:
    def _by_type(session: Session, t: str) -> dict[str, Location]:
        return {
            l.key: l for l in session.query(Location)
            .filter(Location.location_type == t).all()
        }
    local_c = _by_type(local, "CORNERSTONE")
    prod_c = _by_type(prod, "CORNERSTONE")
    local_a = _by_type(local, "ATLAS")
    prod_a = _by_type(prod, "ATLAS")
    local_com = _by_type(local, "COMMUNITY")
    prod_com = _by_type(prod, "COMMUNITY")

    local_places = {p.slug for p in local.query(Place).all()}
    prod_places = {p.slug for p in prod.query(Place).all()}

    report = MotherWorldReport(
        cornerstones_local=len(local_c),
        cornerstones_prod=len(prod_c),
        atlas_local=len(local_a),
        atlas_prod=len(prod_a),
        community_local=len(local_com),
        community_prod=len(prod_com),
        places_local=len(local_places),
        places_prod=len(prod_places),
        cornerstones_missing_from_prod=sorted(set(local_c) - set(prod_c)),
        atlas_missing_from_prod=sorted(set(local_a) - set(prod_a)),
        community_missing_from_prod=sorted(set(local_com) - set(prod_com)),
        places_missing_from_prod=sorted(local_places - prod_places),
    )

    # Sanity checks — use the operator's expected counts as guidance,
    # not as truth. Report drift either way.
    for label, actual_local, expected in (
        ("Cornerstones", len(local_c), 3),
        ("Atlas islands", len(local_a), 19),
        ("Community islands", len(local_com), 3),
    ):
        if actual_local != expected:
            report.sanity_notes.append(
                f"Local {label} count is {actual_local}; operator expected {expected}."
            )

    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _rule(char: str = "=", width: int = 78) -> str:
    return char * width


def render_text(
    audits: list[TableAudit],
    fk_issues: list[ReachabilityIssue],
    mw: MotherWorldReport | None,
    show_diffs: int,
    header_local: str,
    header_prod: str,
) -> str:
    out: list[str] = []
    out.append(_rule("="))
    out.append("Fresh Collective — local vs prod reference-catalogue audit (READ-ONLY)")
    out.append(_rule("="))
    out.append(f"Local DB:  {header_local}")
    out.append(f"Prod DB:   {header_prod}")
    out.append("")

    # -- Per-table --
    out.append("Per-table summary")
    out.append(_rule("-"))
    for a in audits:
        out.append(a.summary_line())
        if a.notes:
            for n in a.notes:
                out.append(f"    note: {n}")
    out.append("")

    # -- Details per table --
    for a in audits:
        out.append(_rule("-"))
        out.append(f"{a.label}   [{a.tablename}]   key = {a.key_kind}")
        out.append(_rule("-"))

        if a.local_only:
            out.append(f"LOCAL_ONLY ({len(a.local_only)}):")
            for r in a.local_only[:50]:
                out.append(f"  + {r}")
            if len(a.local_only) > 50:
                out.append(f"  ... and {len(a.local_only) - 50} more")
            out.append("")

        if a.prod_only:
            out.append(f"PROD_ONLY ({len(a.prod_only)}):")
            for r in a.prod_only[:50]:
                out.append(f"  - {r}")
            if len(a.prod_only) > 50:
                out.append(f"  ... and {len(a.prod_only) - 50} more")
            out.append("")

        if a.different:
            out.append(f"DIFFERENT ({len(a.different)}):")
            for row in a.different[:25]:
                out.append(f"  ≠ key={row.key!r}")
                for f in row.fields[:show_diffs]:
                    out.append(f"      {f.field}:")
                    out.append(f"         local: {f.local}")
                    out.append(f"         prod:  {f.prod}")
                if len(row.fields) > show_diffs:
                    out.append(f"      ... and {len(row.fields) - show_diffs} more fields differ")
            if len(a.different) > 25:
                out.append(f"  ... and {len(a.different) - 25} more DIFFERENT rows")
            out.append("")

        if a.media_url_differs:
            out.append(f"REQUIRES MEDIA MIGRATION ({len(a.media_url_differs)} rows have differing URLs):")
            for m in a.media_url_differs[:20]:
                out.append(f"  ~ key={m['key']!r}")
                for u in m["urls"]:
                    out.append(f"      {u['field']}:")
                    out.append(f"         local: {u['local']}")
                    out.append(f"         prod:  {u['prod']}")
            if len(a.media_url_differs) > 20:
                out.append(f"  ... and {len(a.media_url_differs) - 20} more")
            out.append("")

    # -- Cross-table FK reachability --
    out.append(_rule("="))
    out.append("Cross-table FK reachability (per Collective)")
    out.append(_rule("="))
    if not fk_issues:
        out.append("  No issues — every reference-key on every Collective resolves in prod.")
    else:
        out.append(f"  {len(fk_issues)} issue(s):")
        by_space: dict[str, list[ReachabilityIssue]] = defaultdict(list)
        for i in fk_issues:
            by_space[i.space_slug].append(i)
        for slug, issues in sorted(by_space.items()):
            out.append(f"\n  Space {slug!r}:")
            for i in issues:
                out.append(f"    - {i.field}: {i.reason}")
    out.append("")

    # -- Mother World completeness --
    if mw is not None:
        out.append(_rule("="))
        out.append("Mother World completeness")
        out.append(_rule("="))
        out.append(f"  Cornerstones      local={mw.cornerstones_local:>3}  prod={mw.cornerstones_prod:>3}")
        if mw.cornerstones_missing_from_prod:
            out.append("    missing from prod: " + ", ".join(mw.cornerstones_missing_from_prod))
        out.append(f"  Atlas islands     local={mw.atlas_local:>3}  prod={mw.atlas_prod:>3}")
        if mw.atlas_missing_from_prod:
            out.append("    missing from prod: " + ", ".join(mw.atlas_missing_from_prod))
        out.append(f"  Community islands local={mw.community_local:>3}  prod={mw.community_prod:>3}")
        if mw.community_missing_from_prod:
            out.append("    missing from prod: " + ", ".join(mw.community_missing_from_prod))
        out.append(f"  Physical Places   local={mw.places_local:>3}  prod={mw.places_prod:>3}")
        if mw.places_missing_from_prod:
            out.append("    missing from prod: " + ", ".join(mw.places_missing_from_prod))
        for n in mw.sanity_notes:
            out.append(f"    sanity: {n}")
        out.append("")

    # -- Grouped final summary --
    out.append(_rule("="))
    out.append("Grouped summary")
    out.append(_rule("="))
    safe, missing_prod, diff_prod, prod_only_count, media_needs, no_key = 0, 0, 0, 0, 0, 0
    for a in audits:
        safe += a.identical
        missing_prod += len(a.local_only)
        diff_prod += len(a.different)
        prod_only_count += len(a.prod_only)
        media_needs += len(a.media_url_differs)
        if "no unique natural key" in a.key_kind.lower() or "not unique-constrained" in a.key_kind.lower():
            no_key += a.total_local + a.total_prod
    out.append(f"  Safe / in sync                            {safe}")
    out.append(f"  Missing from prod (author before migration) {missing_prod}")
    out.append(f"  Stale/different in prod                    {diff_prod}")
    out.append(f"  Prod-only (probably fine, noted)           {prod_only_count}")
    out.append(f"  Requires media migration (URL differs)     {media_needs}")
    out.append(f"  Requires follow-up: no stable key          {no_key}")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read-only local-vs-prod audit for reference tables.",
    )
    p.add_argument("--json", action="store_true", help="Print full report as JSON in addition to text.")
    p.add_argument("--sections", default="tables,fk,motherworld,summary",
                   help="Comma-separated: tables,fk,motherworld,summary")
    p.add_argument("--show-diffs", type=int, default=8,
                   help="Max field diffs to show per DIFFERENT row.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        local, prod, header_local, header_prod = _open_sessions()
    except PreflightError as e:
        print(f"PREFLIGHT: {e}", file=sys.stderr)
        return 2

    sections = set(s.strip() for s in args.sections.split(","))
    audits: list[TableAudit] = []
    fk_issues: list[ReachabilityIssue] = []
    mw_report: MotherWorldReport | None = None

    if "tables" in sections:
        for _, auditor in _AUDITORS:
            audits.append(auditor(local, prod))
    if "fk" in sections:
        fk_issues = audit_fk_reachability(local, prod)
    if "motherworld" in sections:
        mw_report = audit_mother_world(local, prod)

    text = render_text(audits, fk_issues, mw_report, args.show_diffs, header_local, header_prod)
    print(text)

    if args.json:
        payload = {
            "local": header_local,
            "prod": header_prod,
            "audits": [
                {
                    "label": a.label, "tablename": a.tablename,
                    "key_kind": a.key_kind,
                    "total_local": a.total_local, "total_prod": a.total_prod,
                    "identical": a.identical,
                    "different": [d.as_dict() for d in a.different],
                    "local_only": a.local_only, "prod_only": a.prod_only,
                    "media_url_differs": a.media_url_differs,
                    "notes": a.notes,
                }
                for a in audits
            ],
            "fk_issues": [asdict(i) for i in fk_issues],
            "mother_world": asdict(mw_report) if mw_report else None,
        }
        print("\n=== JSON REPORT ===")
        print(json.dumps(payload, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
