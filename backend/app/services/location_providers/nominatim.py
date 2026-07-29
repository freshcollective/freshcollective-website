"""
Nominatim (OpenStreetMap) implementation of ``LocationProvider``.

Chosen for the first ship because:
  * free, permissive licence (ODbL) that permits storing derived
    data;
  * no API key or vendor lock-in;
  * good coverage for the cities Fresh Collective is likely to
    care about at MVP scale.

Downsides (documented so we can migrate cleanly if they bite):
  * strict rate limits (1 req/sec, per the Nominatim usage policy);
    Fresh Collective's usage during Creator settings edits is well
    below this, but a Mapbox/Google switch would be worth it if
    picker volume ever grows.
  * autocomplete is less polished than commercial providers.
  * requires a truthful ``User-Agent`` header and contact email —
    both come from settings so an operator can update them for
    their deployment.

See
``docs/foundations/discovery-connection-belonging-location-model.md``.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

from .base import LocationProvider, LocationSuggestion


logger = logging.getLogger(__name__)

NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org"
DEFAULT_TIMEOUT = 4.0  # seconds — the picker feels slow beyond this


class NominatimProvider(LocationProvider):
    """OpenStreetMap-backed provider. See module docstring."""

    def __init__(self, endpoint: str = NOMINATIM_ENDPOINT) -> None:
        self._endpoint = endpoint.rstrip("/")

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def search(self, query: str, limit: int = 6) -> list[LocationSuggestion]:
        query = query.strip()
        if not query:
            return []
        params = {
            "q": query,
            "format": "jsonv2",
            "addressdetails": "1",
            "limit": str(max(1, min(limit, 10))),
            # Only surface places / cities / towns / villages — no
            # roads, POIs, addresses. This matches the "single
            # searchable Primary Location" intent of the location
            # model.
            "featuretype": "settlement",
        }
        raw = await self._request("/search", params)
        return [self._suggestion_from_row(row) for row in raw if self._is_settlement(row)]

    async def fetch(self, provider_place_id: str) -> LocationSuggestion | None:
        osm_type, osm_id = self._parse_id(provider_place_id)
        if osm_type is None or osm_id is None:
            return None
        params = {
            "osm_ids": f"{osm_type[0].upper()}{osm_id}",  # e.g. "N12345"
            "format": "jsonv2",
            "addressdetails": "1",
        }
        raw = await self._request("/lookup", params)
        if not raw:
            return None
        return self._suggestion_from_row(raw[0])

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _request(self, path: str, params: dict[str, str]) -> list[dict]:
        headers = {
            # Nominatim policy requires a truthful UA including a way
            # to contact the operator. Fed from settings so
            # deployments identify themselves honestly.
            "User-Agent": self._user_agent(),
            "Accept": "application/json",
        }
        url = f"{self._endpoint}{path}"
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "nominatim %s failed: %s params=%s", path, exc, params
            )
            return []

    def _user_agent(self) -> str:
        contact = (
            settings.location_provider_contact
            or settings.platform_owner_email
            or "operator-not-configured@example.invalid"
        )
        return f"FreshCollective/1.0 ({contact})"

    @staticmethod
    def _is_settlement(row: dict) -> bool:
        """Filter — settlement-ish rows only.

        Nominatim's ``featuretype=settlement`` filter isn't strict on
        the response, so a second-pass sanity check on ``addresstype``
        keeps the picker focused on cities / towns / villages /
        suburbs and rejects the odd river or road that slips through.
        """
        addresstype = row.get("addresstype") or row.get("type") or ""
        return addresstype in {
            "city",
            "town",
            "village",
            "suburb",
            "municipality",
            "county",
            "state",
            "administrative",
            "hamlet",
            "locality",
            "island",
            "region",
        }

    @staticmethod
    def _suggestion_from_row(row: dict) -> LocationSuggestion:
        address = row.get("address") or {}
        # Nominatim shape varies wildly by feature type; walk a small
        # priority list to find the best name for each field.
        name = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("suburb")
            or address.get("municipality")
            or address.get("hamlet")
            or address.get("locality")
            or row.get("name")
            or row.get("display_name", "").split(",")[0].strip()
        )
        region = (
            address.get("state")
            or address.get("region")
            or address.get("county")
            or ""
        )
        country = address.get("country") or ""
        country_code = (address.get("country_code") or "").upper()
        return LocationSuggestion(
            provider_place_id=f"osm:{row.get('osm_type', 'unknown')}:{row.get('osm_id', '0')}",
            name=name or row.get("display_name", "Unknown").split(",")[0].strip(),
            region=region,
            country=country,
            country_code=country_code,
            latitude=float(row.get("lat", 0.0)),
            longitude=float(row.get("lon", 0.0)),
            # Nominatim does not return timezone. Left None; the
            # backfill script or a later enrichment can fill this in
            # if a real Place page ever needs it.
            timezone=None,
        )

    @staticmethod
    def _parse_id(provider_place_id: str) -> tuple[str | None, str | None]:
        """Extract (osm_type, osm_id) from our stored id format.

        Our format is ``osm:<type>:<id>`` e.g. ``osm:node:12345``.
        Anything else returns (None, None) so ``fetch`` degrades to a
        clean miss rather than raising.
        """
        parts = provider_place_id.split(":")
        if len(parts) != 3 or parts[0] != "osm":
            return (None, None)
        return (parts[1], parts[2])
