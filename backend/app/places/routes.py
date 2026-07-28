"""
/api/places — the read surface for real-world Places.

Places are the geographic layer of the Discovery, Connection &
Belonging pillar (see
``docs/foundations/discovery-connection-belonging-v1.1.md``).
Editorial, curated by hand as Fresh Collective expands into a new
city.

Phase 0 ships one deliberately small endpoint: a list of currently
active Places, with no member data, no Recognition data, no
personalisation, no filtering, no search. Every one of those
extensions is a considered product decision that later phases can
land on top of a shape that already exists.

The whole surface is gated by ``settings.discovery_pillar_enabled``.
When the flag is off the endpoint returns 503 — matching the
convention set by Community Care — so a half-built surface can't be
discovered by accident.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.place import Place


router = APIRouter(prefix="/api/places", tags=["places"])


class PlaceSummary(BaseModel):
    """Public shape for a Place. Intentionally minimal — extend when a
    real UI need appears, not before."""

    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    country_code: str
    region: str | None


def _ensure_discovery_flag_on() -> None:
    """Refuse when the Discovery pillar is not yet enabled."""
    if not settings.discovery_pillar_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discovery is not yet enabled on this deployment.",
        )


@router.get("", response_model=list[PlaceSummary])
def list_places(db: Session = Depends(get_db)) -> list[PlaceSummary]:
    """List every active Place. Hidden Places are excluded.

    No pagination — Places are editorial and rare; the list is
    expected to stay small enough for a single response for a long
    time. When that changes, extend the shape.
    """
    _ensure_discovery_flag_on()

    rows = db.execute(
        select(Place)
        .where(Place.status == "active")
        .order_by(Place.name)
    ).scalars().all()
    return [PlaceSummary.model_validate(r) for r in rows]
