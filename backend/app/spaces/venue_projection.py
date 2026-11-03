"""What a Gathering's location says in public.

Two ideas share the venue fields and must not be confused:

* **Public location** — roughly where this happens, so someone
  deciding whether to come can tell if it is near them.
  ``venue_locality``, a creator-controlled label added in migration
  114 precisely because deriving it from the address "wasn't robust
  enough as a privacy boundary".
* **Attendee detail** — ``venue_address``, ``access_instructions``,
  ``location_url``. Behind the booking gate, unchanged by this module.

``venue_name`` is public, and that meaning is settled rather than
assumed: the member events *list* has always returned it raw to
anonymous callers, the Place projection calls it "the coarse
locality", and the Series projection returns it too.

Two shapes of caller, two helpers
---------------------------------
Some surfaces have room for one string — a Place card, a Discover
listing. :func:`public_venue_label` is for those: locality first,
``venue_name`` as the already-public fallback, and **never** the
address. A Gathering with neither says nothing about where it is,
which is the right failure — omitting a location is a smaller harm
than publishing a street address.

Surfaces with room for two — the Gathering page, the Series schedule —
get :func:`public_venue_fields`, which returns both fields as they
are. That function used to overwrite ``venue_name`` with the label,
which collapsed "Arrabri Community House" and "42 Allambanan Drive,
Bayswater North" into one string printed twice, and meant a creator
who named their venue never saw that name in public. It protected
nothing: the same anonymous viewer can read the raw value from the
list endpoint one call away.

The legacy shape it was written for still works. EMBODY's thirty
Term 4 Gatherings carry "Private residence, South Croydon, Vic" in
``venue_name`` with ``venue_locality`` empty, because the editor never
offered a locality field to put it in; they keep saying exactly that,
through the name rather than through the label.

What is never public, here or anywhere: ``venue_address`` (the private
address), ``access_instructions`` and ``location_url``. Those are
gated on a confirmed booking by the endpoint, not by this module.
"""

from __future__ import annotations

import re
from typing import Any


def public_venue_label(event: Any) -> str | None:
    """The location string any viewer may see, or ``None``.

    Never consults ``venue_address`` or ``access_instructions``. Those
    are attendee detail and have their own gate.
    """
    locality = (getattr(event, "venue_locality", None) or "").strip()
    if locality:
        return locality

    # Fallback, not a second source of truth: ``venue_name`` is already
    # public on every surface that shows a Gathering. Dropping it here
    # would strip location context from every Collective that has been
    # using it as intended, to fix one that used it for something else.
    name = (getattr(event, "venue_name", None) or "").strip()
    return name or None


def public_venue_fields(event: Any) -> dict[str, str | None]:
    """The venue half of a public Gathering payload.

    Both keys are returned so a caller cannot forget one, and both are
    safe for an anonymous viewer: the name of the place, and the
    address the creator chose to publish.

    They are returned *separately*. Composing them into one line is a
    presentation decision — which goes first, whether one repeats the
    other — and it belongs to the surface doing the rendering, not
    here. ``frontend/src/lib/gatheringLocation.ts`` is where the
    Gathering page makes it.
    """
    return {
        "venue_locality": (getattr(event, "venue_locality", None) or "").strip() or None,
        "venue_name": (getattr(event, "venue_name", None) or "").strip() or None,
    }

def public_location_summary(event: Any) -> str:
    """The public location as one line, for a surface with no layout.

    Used by the ``.ics`` export, whose ``LOCATION`` field is a single
    string that any viewer of a public Gathering can read.

    Venue name and public address, joined, with a leading repeat of the
    name removed so "Arrabri Community House" beside "Arrabri Community
    House - 42 Allambanan Drive" does not print the venue twice.

    Mirrors ``composeGatheringLocation`` in
    ``frontend/src/lib/gatheringLocation.ts``, deliberately: the rule is
    small, and two short implementations with a shared case table beat
    an endpoint that exists only so the calendar can ask the frontend
    how to phrase a string. ``tests/test_venue_privacy.py`` runs the
    same cases as ``gatheringLocation.test.ts``; if one is changed, the
    other fails.

    Never consults ``venue_address``, ``access_instructions`` or
    ``location_url``.
    """
    name = (getattr(event, "venue_name", None) or "").strip()
    address = (getattr(event, "venue_locality", None) or "").strip()
    if not name:
        return address
    if not address:
        return name
    if _compare_key(address) == _compare_key(name):
        return name
    trimmed = _without_leading_name(address, name)
    return f"{name}, {trimmed}"


def _compare_key(value: str) -> str:
    """Case- and punctuation-insensitive, for comparison only."""
    return re.sub(r"\s+", " ", re.sub(r"[.,\u00b7|\u2013\u2014-]", " ", value.lower())).strip()


def _without_leading_name(address: str, name: str) -> str:
    """``address`` with a leading repeat of ``name`` removed.

    Narrow on purpose. The name must lead the address and be followed
    by a real separator — never whitespace alone, because "The Studio
    Annexe" is a different place and not a repeat. A partial overlap is
    not permission to delete somebody's address.
    """
    a, n = _compare_key(address), _compare_key(name)
    if not n or not a.startswith(n) or a == n:
        return address

    consumed = 0
    index = 0
    while index < len(address) and consumed < len(n):
        index += 1
        normalised = _compare_key(address[:index])
        if len(normalised) > consumed:
            consumed = len(normalised)
    rest = address[index:]
    match = re.match(r"^\s*[,\-\u2013\u2014\u00b7|]+\s*(.+)$", rest)
    if not match:
        return address
    return match.group(1).strip() or address
