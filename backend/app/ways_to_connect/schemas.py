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
    #: IANA zone the Collective schedules in. A Gathering's
    #: ``starts_at`` is stored without one, so a client rendering a
    #: day or a time needs this to be right rather than
    #: approximately right.
    timezone: str


class PersonRef(BaseModel):
    """Another member, inside a context both people share.

    The minimum a surface needs to render someone: something to key
    on, something to call them, and a picture if one is already
    visible to this viewer.

    ``display_name`` and ``avatar_url`` are both nullable, and both
    being null is an ordinary state rather than a broken one. A member
    who has set no name and has no public CreatorProfile takes part in
    Ways to Connect exactly like anyone else; the surface is not a
    reason to make them fill in a profile.

    Null means "no name to show", not "name withheld" and not "call
    them something generic". The frontend decides how to represent an
    unnamed person, which it can do far better than a server that
    would have to invent the same placeholder for everybody. There is
    no fallback to the local part of an email address — that leaks
    half of somebody's address to anyone sharing a Collective with
    them. (``app.members.routes._display_name`` still does this on the
    member directory; separate surface, separate fix.)

    Deliberately absent: email, bio, join date, location, other
    Collectives, any count, any score. If the viewer could not
    already learn it through the shared context, it is not here.
    """

    id: str
    display_name: str | None = None
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
