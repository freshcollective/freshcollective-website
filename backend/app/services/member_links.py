"""Member-facing links to the things a member bought.

``core.public_url`` joins an origin to a path and deliberately holds no
opinion about what a path means. This module holds that opinion for the
experiences a purchase can point at, so the comms layer builds one URL
per experience rather than one per email.

Why it exists
-------------

Two emit services both needed a Gathering Series link and built it with
their own f-string. ``gathering_booking_emit._series_url`` took the
``EventSeries`` row and was correct; ``purchase_lifecycle_emit``
resolved the Series from a ``PaymentOption.attaches_to_kind`` and
matched on ``"series"`` — a value nothing writes. The platform writes
``"event_series"``, so every Series purchase email, and every
payment-recovery email for a Series instalment plan, linked to
``/dashboard`` instead.

``core.public_url``'s own source guard did not catch it: that guard
stops a link builder reading the *origin* setting directly, and both
callers used ``public_app_url`` correctly. Nothing watched the *path*.
So the path is built here now, once.

The attachment vocabulary
-------------------------

``PaymentOption.attaches_to_kind`` is a free ``String(30)`` with no enum
or CHECK constraint, and four writers populate it:

    pathway        creator.routes
    event_series   creator._gathering_series_routes
    offering       services.offering_commerce
    space          creator._space_payment_options_routes (grants-first
                   sentinel — the option grants many things, so there is
                   no single destination and ``/dashboard`` is the
                   honest answer)

The two sets below name every value, which is what lets a test fail
when a fifth writer appears with a spelling this module has never heard
of. That is the guard the original defect lacked.
"""

from __future__ import annotations

from typing import Any

from app.core.public_url import public_app_url

#: Attachment kinds that resolve to a specific member-facing page.
#: ``series`` is accepted alongside ``event_series`` for compatibility:
#: ``event_series`` is what exists, and honouring both costs nothing
#: while making the fix immune to a future writer picking the other
#: spelling.
ATTACH_KINDS_WITH_MEMBER_URL: frozenset[str] = frozenset({
    "pathway",
    "event_series",
    "series",
    "offering",
})

#: Attachment kinds that deliberately have no specific destination and
#: fall back to ``/dashboard``. Listed rather than left implicit so the
#: fallback is a decision on the record, not an accident.
ATTACH_KINDS_WITHOUT_MEMBER_URL: frozenset[str] = frozenset({
    "space",
})

#: Every value the platform writes. A kind outside this set reaching the
#: comms layer means a writer was added without telling it.
KNOWN_ATTACH_KINDS: frozenset[str] = (
    ATTACH_KINDS_WITH_MEMBER_URL | ATTACH_KINDS_WITHOUT_MEMBER_URL
)

#: The spellings that mean "a Gathering Series".
SERIES_ATTACH_KINDS: frozenset[str] = frozenset({"event_series", "series"})


def dashboard_url() -> str:
    """Where a member goes when no specific destination is honest."""
    return public_app_url("/dashboard")


def series_member_url(space: Any, series: Any) -> str:
    """The member-facing Gathering Series page, or ``""``.

    Takes the rows rather than ids so a caller that has already loaded
    them does not load them again, and so a missing slug is answerable
    without a query. Empty string when either row cannot supply a slug
    — the caller decides whether that means a fallback or no link at
    all, because those differ: an email body wants a fallback, an
    optional CTA wants omitting.
    """
    if space is None or series is None:
        return ""
    space_slug = getattr(space, "slug", None)
    series_slug = getattr(series, "slug", None)
    if not space_slug or not series_slug:
        return ""
    return public_app_url(
        f"/spaces/{space_slug}/gathering-series/{series_slug}"
    )


def pathway_member_url(space: Any, pathway: Any) -> str:
    """The member-facing Pathway page, or ``""``."""
    if space is None or pathway is None:
        return ""
    space_slug = getattr(space, "slug", None)
    pathway_slug = getattr(pathway, "slug", None)
    if not space_slug or not pathway_slug:
        return ""
    return public_app_url(f"/spaces/{space_slug}/pathways/{pathway_slug}")


def offering_member_url(space: Any, offering: Any) -> str:
    """The member-facing Offering page, or ``""``."""
    if space is None or offering is None:
        return ""
    space_slug = getattr(space, "slug", None)
    offering_slug = getattr(offering, "slug", None)
    if not space_slug or not offering_slug:
        return ""
    return public_app_url(f"/spaces/{space_slug}/offerings/{offering_slug}")


__all__ = [
    "ATTACH_KINDS_WITHOUT_MEMBER_URL",
    "ATTACH_KINDS_WITH_MEMBER_URL",
    "KNOWN_ATTACH_KINDS",
    "SERIES_ATTACH_KINDS",
    "dashboard_url",
    "offering_member_url",
    "pathway_member_url",
    "series_member_url",
]
