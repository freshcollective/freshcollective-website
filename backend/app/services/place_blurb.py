"""
Editorial blurb drafting for Physical Locations.

A **draft** is produced here — it is never saved directly. The admin
reviews and edits before hitting Save (see
``app.admin.physical_locations.draft_location_blurb``). This module is
deliberately deterministic: it composes a sentence from real data
already on the Place and its linked active Collectives, and never
invents Collectives, themes or gatherings that are not present.

An LLM-backed drafter can slot in later behind the same
``draft_blurb`` signature; the template output is a safe floor that
works offline, requires no API keys, and produces the same tone the
Fresh Collective voice would.

Guidelines encoded here:

  * name / region / country provide place identity;
  * up to three linked-Collective themes shape the "what's here"
    clause;
  * no marketing language ("bustling", "vibrant", "must-see"), no
    fabricated activity, no fabricated gatherings;
  * two short sentences at most.

See docs/foundations/discovery-connection-belonging-location-model.md.
"""

from __future__ import annotations


# ISO 3166-1 alpha-2 → country name. Kept intentionally small — the
# only countries that appear in the seed today. Extend when a new
# Physical Location country is added; the draft still renders (with
# the raw code) if a country is missing.
_COUNTRY_NAMES: dict[str, str] = {
    "AU": "Australia",
    "NZ": "New Zealand",
    "GB": "the United Kingdom",
    "US": "the United States",
    "CA": "Canada",
    "IE": "Ireland",
}


def draft_blurb(
    *,
    name: str,
    region: str | None,
    country_code: str,
    themes: list[str],
    active_collective_count: int,
) -> str:
    """Return a two-sentence editorial draft for a Physical Location.

    Args mirror the fields available on ``app.models.place.Place``
    plus the two aggregates the admin router already computes.
    """
    return f"{_first_sentence(name, themes)} {_second_sentence(region, country_code, active_collective_count)}".strip()


def _join_themes(themes: list[str]) -> str:
    """Human list of themes ("wellbeing, movement and leadership").

    Lowercased so the sentence reads naturally regardless of how the
    theme is stored in Space.themes (many are Title Case).
    """
    lower = [t.strip().lower() for t in themes if t and t.strip()]
    picked = lower[:3]
    if not picked:
        return ""
    if len(picked) == 1:
        return picked[0]
    if len(picked) == 2:
        return f"{picked[0]} and {picked[1]}"
    return f"{picked[0]}, {picked[1]} and {picked[2]}"


def _first_sentence(name: str, themes: list[str]) -> str:
    joined = _join_themes(themes)
    if joined:
        return (
            f"{name} is a place where Fresh Collective communities are "
            f"gathering across {joined}."
        )
    # No linked themes — keep the sentence honest. Never claim
    # activity that isn't there.
    return f"{name} is a Fresh Collective discovery location."


def _second_sentence(region: str | None, country_code: str, active_count: int) -> str:
    country = _COUNTRY_NAMES.get(country_code.upper(), country_code.upper())
    # Where the Place sits in the world — region if present,
    # otherwise fall back to just the country.
    where = f"in {region}, {country}" if region else f"in {country}"

    if active_count == 0:
        return (
            f"Nothing is happening here yet — {where}, this is a discovery "
            "location awaiting its first Collective."
        )
    if active_count == 1:
        return (
            f"Explore the Collective taking shape here, {where}."
        )
    return (
        f"Explore the Collectives and gatherings taking shape across "
        f"the area, {where}."
    )
