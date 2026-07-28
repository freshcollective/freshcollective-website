"""
Seed initial real-world Places.

Places are editorial, not derived — each row here is a decision the
operator has made that Fresh Collective has actual current activity in
that Place (a Collective based there, a Gathering hosted there, a
member community forming there). This script is intentionally
conservative: aspirational cities do not belong here.

Usage (from repo root):

    cd backend
    .venv/bin/python3 scripts/seed_initial_places.py

Idempotent: rerunning updates the ``name``/``region``/``country_code``/
``blurb`` fields on existing slugs (so an editorial copy tweak lands
by rerunning), inserts anything new, and never deletes.

Not run from any migration. Ship a Place by adding an entry to
``PLACES`` and running this script by hand in the target environment.

Current state (2026-07-26): platform data holds no Collective or
Gathering with populated real-world venue information — only Atlas
Locations (the mythic worldview layer) are attached to Collectives,
and Events use ``venue_name`` / ``venue_address`` free-text which is
empty on every current row. Rather than seed aspirational cities, the
list starts empty. Add entries here the moment a Collective or
Gathering has a real Place attached.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import TypedDict

# Ensure the app package is importable regardless of invocation cwd.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.place import Place


class PlaceSeed(TypedDict, total=False):
    slug: str
    name: str
    country_code: str
    region: str | None
    blurb: str | None


PLACES: list[PlaceSeed] = [
    # No entries yet — see module docstring. When Fresh Collective
    # opens a Collective or hosts a Gathering in a specific city, add
    # it here and rerun this script in each environment.
    #
    # Example (do not uncomment without a real Collective or Gathering
    # attached to it):
    #
    # {
    #     "slug": "byron-bay",
    #     "name": "Byron Bay",
    #     "country_code": "AU",
    #     "region": "Northern Rivers",
    #     "blurb": None,
    # },
]


def _upsert(db, seed: PlaceSeed) -> tuple[Place, str]:
    """Insert or update by slug. Returns (row, 'created' | 'updated' | 'unchanged')."""
    existing = db.execute(
        select(Place).where(Place.slug == seed["slug"])
    ).scalar_one_or_none()

    if existing is None:
        row = Place(
            id=f"place_{uuid.uuid4().hex[:12]}",
            slug=seed["slug"],
            name=seed["name"],
            country_code=seed["country_code"],
            region=seed.get("region"),
            blurb=seed.get("blurb"),
        )
        db.add(row)
        return row, "created"

    changed = False
    for field in ("name", "country_code", "region", "blurb"):
        if field in seed and getattr(existing, field) != seed[field]:
            setattr(existing, field, seed[field])
            changed = True
    return existing, "updated" if changed else "unchanged"


def main() -> None:
    if not PLACES:
        print("PLACES is empty — nothing to seed. See scripts/seed_initial_places.py.")
        return

    db = SessionLocal()
    try:
        summary: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0}
        for seed in PLACES:
            _row, action = _upsert(db, seed)
            summary[action] += 1
            print(f"  {action:10s}  {seed['slug']}  ({seed['name']})")
        db.commit()
        print()
        print(
            f"Done. created={summary['created']} "
            f"updated={summary['updated']} unchanged={summary['unchanged']}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
