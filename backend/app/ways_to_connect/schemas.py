"""Response shapes for the Ways to Connect read API.

People first. A member asked "who do I belong alongside?", and the
answer is a person — the shared Gatherings and Pathways are the
reason that person is here, not the subject of the page.

What keeps this from being a directory is not the shape but the
constraints around it: at most three people, chosen by the server,
each one anchored to evidence ``RecognitionService`` derived and
re-derives on every read. No search. No pagination. No show-more. No
way to ask for a person who was not offered. Members are not
browsable; a few are introduced, with reasons.

Nothing here scores, ranks or grades. There is no "strength", no
"match", no count of things in common presented as a quality. The
evidence is listed plainly and the member decides what it means.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CollectiveRef(BaseModel):
    """Where a shared experience lives.

    Present on every person because it is also a privacy statement:
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


class SharedGatheringRef(BaseModel):
    """A Gathering two people share.

    ``basis`` separates a shared intention from a shared memory:
    ``upcoming`` means both hold a confirmed booking for something
    that has not happened; ``attended`` means the roster was finalised
    and both were marked present. The frontend needs the difference to
    choose a tense.
    """

    kind: Literal["gathering"] = "gathering"
    id: str
    title: str
    starts_at: datetime
    basis: Literal["upcoming", "attended"]
    collective_id: str


class SharedPathwayRef(BaseModel):
    """A Pathway two people are both walking.

    ``crossing_at`` is the earlier of their two latest completed
    steps — the point past which the pair's shared progress cannot be
    said to have continued. Ordering only; it never gates eligibility.
    """

    kind: Literal["pathway"] = "pathway"
    id: str
    slug: str
    title: str
    collective_id: str
    crossing_at: datetime | None = None


class PersonRef(BaseModel):
    """Someone the viewer genuinely shares something with.

    ``display_name`` and ``avatar_url`` are both nullable and both
    being null is an ordinary state rather than a broken one. A member
    who has set no name and has no public CreatorProfile takes part in
    Recognition exactly like anyone else; the surface is not a reason
    to make them fill in a profile. Null means "no name to show", not
    "name withheld" — and never a placeholder, because "Member" reads
    as three strangers all called Member the moment there are three of
    them. There is no fallback to the local part of an email address.

    Deliberately absent: email, bio, join date, location, other
    Collectives, any count, any score. If the viewer could not already
    learn it through the shared context, it is not here.
    """

    id: str
    display_name: str | None = None
    avatar_url: str | None = None
    #: Collectives this pair shares. Context and privacy boundary,
    #: never on its own a reason to be here.
    collectives: list[CollectiveRef]
    #: Why this person is shown. Always at least one entry — a person
    #: with nothing shared is not recognisable and never appears.
    shared: list[SharedGatheringRef | SharedPathwayRef]


class WaysToConnectResponse(BaseModel):
    """Everything the viewer currently shares with anyone.

    ``people`` is every recognisable person, ordered so that the first
    ``featured_count`` entries are the ones the destination shows
    today. The tail is not a second page — nothing in the product
    offers it to a member — it is there because the in-context lines
    on Gathering and Pathway pages need the whole set to say "Sarah
    and 2 other people", and one payload serving both keeps a single
    derivation behind both surfaces.

    ``featured_count`` is 0 to 3 and may be smaller than the number of
    people: unnamed members are never featured, and a viewer with two
    eligible people sees two. Nobody is invented to reach three.
    """

    people: list[PersonRef]
    featured_count: int = 0
    #: The safety bound was reached. Not a cursor and not a total —
    #: there is nothing to page to.
    truncated: bool = False
