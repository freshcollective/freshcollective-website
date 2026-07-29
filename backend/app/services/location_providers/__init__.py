"""
Location autocomplete providers.

Everything Fresh Collective needs from the outside world for the
Place & Feel picker sits behind ``LocationProvider``. Today the
concrete implementation is ``NominatimProvider`` (OpenStreetMap);
swapping to Google Places, Mapbox or OpenCage in future is a
change to this module alone — the routes, models and Creator UI
do not know which provider is in use.

Provider selection is a config concern
(``settings.location_provider``); the factory lives here to keep
the boundary explicit.
"""

from app.core.config import settings

from .base import LocationProvider, LocationSuggestion
from .nominatim import NominatimProvider


def get_location_provider() -> LocationProvider:
    """Return the configured provider.

    Kept as a plain function rather than a cached singleton so tests
    can monkeypatch ``settings.location_provider`` and get a fresh
    instance without shared state.
    """
    name = (settings.location_provider or "nominatim").lower()
    if name == "nominatim":
        return NominatimProvider()
    raise RuntimeError(
        f"Unknown location provider {name!r}. "
        f"Supported: 'nominatim'."
    )


__all__ = [
    "LocationProvider",
    "LocationSuggestion",
    "NominatimProvider",
    "get_location_provider",
]
