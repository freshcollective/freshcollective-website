"""
Backfill connection_style and Geographic Location for existing
Fresh-Collective-owned Collectives.

Ships as part of Stage 1 (complete Place & Feel). Idempotent —
safe to rerun in any environment. It does not touch Collectives it
does not know about, so a Collective added after this script was
last modified is simply left alone.

Usage (from repo root):

    cd backend
    .venv/bin/python3 scripts/backfill_fc_places.py

For each entry in ``COLLECTIVES``:

  * sets ``Space.connection_style`` if it differs from the target;
  * for in-person / hybrid Collectives, resolves the target
    Geographic Location through the configured provider (creating
    the Place row if not already present, deduplicating by
    provider_place_id), then ensures a single ``SpacePlace`` row
    linking the Collective to that Place;
  * for online-only Collectives, ensures no ``SpacePlace`` row
    exists (a Collective that used to be in-person and became
    online gets cleaned up).

The provider abstraction lives in
``app/services/location_providers``. This script uses whatever
provider ``settings.location_provider`` names — Nominatim in the
default configuration. Runs the provider synchronously via
``asyncio.run`` so the script has no async plumbing.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path
from typing import TypedDict

# Ensure the app package is importable regardless of invocation cwd.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

# Register every mapper so relationship strings resolve when this
# script runs standalone (the FastAPI app does this by transitive
# imports).
import app.models.user          # noqa: F401
import app.models.community_care  # noqa: F401

from app.core.database import SessionLocal
from app.models.place import Place, SpacePlace
from app.models.platform import Space
from app.services.location_providers import get_location_provider
from app.services.location_providers.base import LocationSuggestion


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_fc_places")


class Backfill(TypedDict, total=False):
    """One entry per Fresh-Collective-owned Collective."""

    slug: str
    connection_style: str                # 'online' | 'in_person' | 'both'
    #: Free-text query used to resolve the Geographic Location.
    #: Omit for online-only Collectives.
    location_query: str
    #: Optional exact-match filter — only pick a provider result
    #: whose region and country match. Guards against ambiguous
    #: names ("Melbourne" AU vs "Melbourne" US).
    match_region: str
    match_country: str


# ---------------------------------------------------------------------------
# The mapping — authored by hand, per Stage 1 backfill decision.
#
#   EMBODY               → In person → Hobart, Tasmania
#   The Grove            → Online
#   World Builders       → Online
#
# Collective Homes (Sanctuary Springs / Atlas Isles) are the Atlas
# system's concern and are already set on these Collectives — the
# Discovery pillar's Geographic Location is a separate axis and is
# what this script populates. See
# docs/foundations/discovery-connection-belonging-location-model.md.
# ---------------------------------------------------------------------------

COLLECTIVES: list[Backfill] = [
    {
        "slug": "embody",
        "connection_style": "in_person",
        "location_query": "Hobart, Tasmania, Australia",
        "match_region": "Tasmania",
        "match_country": "Australia",
    },
    {
        "slug": "the-natural-leader-hub",  # The Grove
        "connection_style": "online",
    },
    {
        "slug": "world-builders",
        "connection_style": "online",
    },
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _pick_suggestion(
    results: list[LocationSuggestion],
    match_region: str,
    match_country: str,
) -> LocationSuggestion | None:
    """From an autocomplete result list, pick the first row whose
    region + country match the operator's intent. Avoids
    ambiguous-name collisions (e.g. Melbourne AU vs Melbourne US)."""
    r_lower = match_region.strip().lower()
    c_lower = match_country.strip().lower()
    for row in results:
        if row.country.lower() == c_lower and row.region.lower() == r_lower:
            return row
    return None


async def _resolve_place(db: Session, entry: Backfill) -> Place:
    """Idempotent resolve — reuse a Place row if the provider id
    already matches; otherwise create."""
    provider = get_location_provider()
    query = entry["location_query"]
    results = await provider.search(query, limit=6)
    if not results:
        raise RuntimeError(
            f"Provider returned no results for query {query!r}. "
            f"Check network access and provider configuration."
        )
    pick = _pick_suggestion(results, entry["match_region"], entry["match_country"])
    if pick is None:
        raise RuntimeError(
            f"No result matched region={entry['match_region']!r} "
            f"country={entry['match_country']!r} for query {query!r}. "
            f"Got: {[r.display for r in results]}"
        )

    existing = db.execute(
        select(Place).where(Place.provider_place_id == pick.provider_place_id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    place = Place(
        id=f"place_{uuid.uuid4().hex[:12]}",
        slug=_slugify(pick.name, pick.country_code, db),
        name=pick.name,
        country_code=pick.country_code or "??",
        region=pick.region or None,
        latitude=pick.latitude,
        longitude=pick.longitude,
        timezone=pick.timezone,
        provider_place_id=pick.provider_place_id,
    )
    db.add(place)
    db.flush()
    return place


def _slugify(name: str, country_code: str, db: Session) -> str:
    base = "".join(c.lower() if c.isalnum() else "-" for c in name.strip())
    while "--" in base:
        base = base.replace("--", "-")
    base = base.strip("-") or country_code.lower()
    if not db.execute(select(Place).where(Place.slug == base)).scalar_one_or_none():
        return base
    n = 2
    while True:
        candidate = f"{base}-{n}"
        if not db.execute(select(Place).where(Place.slug == candidate)).scalar_one_or_none():
            return candidate
        n += 1


def _apply(db: Session, space: Space, entry: Backfill) -> tuple[str, str]:
    """Apply the backfill for one Collective. Returns (action, detail)."""
    style_before = space.connection_style
    target_style = entry["connection_style"]

    style_changed = style_before != target_style
    if style_changed:
        space.connection_style = target_style

    if target_style == "online":
        deleted = db.query(SpacePlace).filter(SpacePlace.space_id == space.id).delete()
        db.flush()
        if style_changed or deleted:
            return ("updated", f"→ online (removed {deleted} link(s))")
        return ("unchanged", "already online, no link")

    # in_person / both — resolve place, ensure single link.
    place = asyncio.run(_resolve_place(db, entry))

    existing_link = (
        db.query(SpacePlace)
        .filter(SpacePlace.space_id == space.id)
        .first()
    )

    if existing_link is None:
        db.add(SpacePlace(space_id=space.id, place_id=place.id))
        db.flush()
        return ("updated", f"→ {target_style} at {place.name}, {place.region} (linked)")

    if existing_link.place_id != place.id:
        db.query(SpacePlace).filter(SpacePlace.space_id == space.id).delete()
        db.add(SpacePlace(space_id=space.id, place_id=place.id))
        db.flush()
        return ("updated", f"→ {target_style} at {place.name}, {place.region} (replaced)")

    if style_changed:
        return ("updated", f"connection_style → {target_style} (link unchanged)")
    return ("unchanged", f"{target_style} at {place.name}, {place.region}")


def main() -> None:
    db = SessionLocal()
    try:
        summary = {"updated": 0, "unchanged": 0, "skipped": 0}
        for entry in COLLECTIVES:
            slug = entry["slug"]
            space = db.execute(select(Space).where(Space.slug == slug)).scalar_one_or_none()
            if space is None:
                summary["skipped"] += 1
                logger.info("  skipped    %s  (not in this database)", slug)
                continue
            action, detail = _apply(db, space, entry)
            summary[action] += 1
            logger.info("  %-9s  %s  %s", action, slug, detail)
        db.commit()
        logger.info(
            "\nDone. updated=%d unchanged=%d skipped=%d",
            summary["updated"], summary["unchanged"], summary["skipped"],
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
