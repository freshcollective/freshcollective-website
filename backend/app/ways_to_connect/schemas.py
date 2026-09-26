"""Response shapes for the Ways to Connect read API.

Indexed by shared experience, never by person. That is the product
invariant, and it is expressed structurally here rather than left to
discipline in the route: the top level is a list of *contexts*, and
people exist only inside one. There is no shape in this module that
can carry a person who is not attached to something the viewer and
that person were genuinely both in.

Nothing here ranks, scores, counts or explains. The frontend is given
facts — this Gathering, that Pathway, these people, this Collective —
and does the phrasing. A "why you're seeing this" sentence composed
on the server would be the beginning of a recommendation engine
justifying itself; there is nothing to justify, because the shared
thing *is* the reason.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CollectiveRef(BaseModel):
    """Where a shared experience lives.

    Present on every context because it is also a privacy statement:
    it tells the viewer which Collective this person can already see
    them in.
    """

    id: str
    slug: str
    name: str


class PersonRef(BaseModel):
    """Another member, inside a context both people share.

    The minimum a surface needs to render someone: something to key
    on, something to call them, and a picture if one is already
    visible to this viewer.

    ``avatar_url`` is null for most members and that is the ordinary
    case, not a degraded one — an avatar exists only where someone
    has a public CreatorProfile. A name and an initial is a complete
    rendering.

    Deliberately absent: email, bio, join date, location, other
    Collectives, any count, any score. If the viewer could not
    already learn it through the shared context, it is not here.
    """

    id: str
    display_name: str
    avatar_url: str | None = None


class GatheringContext(BaseModel):
    """A Gathering the viewer and these people share.

    ``basis`` distinguishes a shared intention from a shared memory:
    ``upcoming`` means everyone here holds a confirmed booking for
    something that has not happened; ``attended`` means the creator
    finalised the roster and everyone here was marked present. The
    frontend needs the difference to choose a tense.
    """

    kind: Literal["gathering"] = "gathering"
    id: str
    title: str
    starts_at: datetime
    basis: Literal["upcoming", "attended"]
    collective: CollectiveRef
    people: list[PersonRef]


class PathwayContext(BaseModel):
    """A Pathway the viewer and these people are all walking."""

    kind: Literal["pathway"] = "pathway"
    id: str
    slug: str
    title: str
    collective: CollectiveRef
    people: list[PersonRef]


class WaysToConnectResponse(BaseModel):
    """Everything the viewer currently shares with anyone.

    Finite by construction: no cursor, no page token, no total. A
    caller reaches the end. ``truncated`` says whether the safety
    bound was reached rather than offering a way to page past it —
    there is no second page, because browsing members is not
    something this surface does.
    """

    contexts: list[GatheringContext | PathwayContext]
    truncated: bool = False
