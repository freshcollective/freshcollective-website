"""What a Gathering's location says in public.

Two ideas share the venue fields and must not be confused:

* **Public location** — roughly where this happens, so someone
  deciding whether to come can tell if it is near them.
  ``venue_locality``, a creator-controlled label added in migration
  114 precisely because deriving it from the address "wasn't robust
  enough as a privacy boundary".
* **Attendee detail** — ``venue_address``, ``access_instructions``,
  ``location_url``. Behind the booking gate, unchanged by this module.

``venue_name`` sits between them, and its current meaning is settled
rather than assumed: the Gathering detail endpoint documents it as
what "everyone else sees … as a rough locator", the Place projection
calls it "the coarse locality", and the Series projection returns it
to anonymous callers. It is a public field today and creators have
been told so by its behaviour.

It is also where creators put whatever they have — EMBODY's thirty
Term 4 Gatherings carry "Private residence, South Croydon, Vic" in it
with ``venue_locality`` empty, because the Gathering editor never
offered a locality field to put it in. So the order here is:
``venue_locality`` first when set, ``venue_name`` only as the
already-public fallback, and **never** the address. A Gathering with
neither says nothing about where it is, which is the right failure:
omitting a location is a smaller harm than publishing a street
address.

One helper rather than three so the Gathering page, the Series page
and Discover Places cannot drift into three different answers about
what is safe to show.
"""

from __future__ import annotations

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
    safe for an anonymous viewer.
    """
    return {
        "venue_locality": (getattr(event, "venue_locality", None) or "").strip() or None,
        "venue_name": public_venue_label(event),
    }
