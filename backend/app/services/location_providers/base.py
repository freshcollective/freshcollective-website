"""
Provider-agnostic contract for the location autocomplete picker.

A LocationSuggestion is what a picker row looks like on the Place &
Feel form — enough for a Creator to disambiguate ("Melbourne,
Victoria, Australia" vs "Melbourne, Florida, United States") and
enough to create a Place when the Creator selects one.

The `provider_place_id` is load-bearing: it is the deduplication
key. See
``docs/foundations/discovery-connection-belonging-location-model.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LocationSuggestion:
    """One row in an autocomplete result set.

    The value the picker returns to the browser and, on selection,
    the value the browser posts back to ``/api/places/resolve``.
    """

    #: The provider's canonical id for this place — the dedup key.
    provider_place_id: str
    #: Human-readable name (e.g. "Melbourne").
    name: str
    #: Region / state / province (e.g. "Victoria"). May be empty for
    #: places without a meaningful region.
    region: str
    #: Country name (e.g. "Australia").
    country: str
    #: ISO 3166-1 alpha-2 country code (e.g. "AU").
    country_code: str
    #: Latitude / longitude in decimal degrees.
    latitude: float
    longitude: float
    #: IANA timezone if the provider supplies one; None otherwise.
    #: Nominatim does not return a timezone directly.
    timezone: str | None

    @property
    def display(self) -> str:
        """The label shown in the picker row.

        Example: "Melbourne, Victoria, Australia".
        Blank region is omitted cleanly.
        """
        parts = [self.name]
        if self.region and self.region != self.name:
            parts.append(self.region)
        parts.append(self.country)
        return ", ".join(parts)


class LocationProvider(Protocol):
    """The behaviour every autocomplete provider must implement.

    Only two operations are needed:
      * ``search`` — the picker query, returns a small ranked list.
      * ``fetch`` — resolves a ``provider_place_id`` back to a
        canonical suggestion. Used by the resolve endpoint to
        rebuild a suggestion payload from just the id, so the
        client cannot lie about a Place's coordinates or name.
    """

    async def search(self, query: str, limit: int = 6) -> list[LocationSuggestion]:
        ...

    async def fetch(self, provider_place_id: str) -> LocationSuggestion | None:
        ...
