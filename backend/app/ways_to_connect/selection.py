"""Who has crossed paths with the viewer often enough to introduce.

Two questions, in order. First, is there enough between these two
people to be worth a card at all? Second, of everyone who passes,
which few appear today?

Neither question is answered with a score. The first is a count of
distinct shared things plus one requirement about their kind; the
second is a fixed list of categories. Nothing here is weighted,
nothing is summed into a rating, and nothing a member sees exposes
either.


Eligibility — two signals, at least one of them realised
--------------------------------------------------------

One shared Gathering is a coincidence. Two people who were in the
same room once have not established anything a platform should
comment on, and a card built on it reads as arbitrary — which is
exactly how it read on review.

So a person needs **two shared signals**. Each of these counts once,
per thing:

  * a past Gathering both were marked attended at   (realised)
  * an active Pathway both have genuinely started    (realised)
  * an upcoming Gathering both are confirmed for     (supporting)

And at least one of them must be **realised**. Two bookings for two
future Gatherings are two signals, and they are still only a plan:
nothing has happened between those people yet. Upcoming Gatherings
say *when* an existing overlap is about to continue, which is worth
knowing and is never the overlap itself.

Collective membership is not on that list and never will be. It is
the privacy boundary that makes any of this permissible, not evidence
of anything: two hundred people share a Collective and know nothing
about each other.


Categories — what happened, in order
------------------------------------

Every eligible pair falls into exactly one of five, strongest first:

  1. two or more past attended Gatherings
  2. a past attended Gathering and an active Pathway
  3. a past attended Gathering and an upcoming one
  4. two or more active Pathways
  5. an active Pathway and an upcoming Gathering

The list is deliberately a list and not a formula. It says repeated
attendance beats one attendance plus a plan, and that a walked path
beats a planned room, without ever saying by how much — because "how
much" is a score, and a score would eventually be tuned, then
surfaced, then argued with.

Recency orders people *within* a category, never across one. No
amount of imminence moves a pair up the list.


Rotation
--------

When more people qualify than there are slots, those in the same
category take turns by the day. Rotating across categories would
quietly undo the ordering, so it happens inside each one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.services.recognition_service import Recognition, SharedGatheringBasis

#: The whole point of the destination. Three is a glance.
MAX_PEOPLE = 3

#: One shared thing is a coincidence. Two is a pattern worth naming.
MIN_SIGNALS = 2

# The five categories, strongest first. Named rather than scored:
# there is no arithmetic that turns one into another, and no number
# here that could be surfaced, tuned or argued with.
CAT_REPEATED_ATTENDANCE = 1   # 2+ attended
CAT_ATTENDED_AND_PATHWAY = 2  # 1 attended + a Pathway
CAT_ATTENDED_AND_UPCOMING = 3 # 1 attended + a plan
CAT_REPEATED_PATHWAYS = 4     # 2+ Pathways
CAT_PATHWAY_AND_UPCOMING = 5  # 1 Pathway + a plan

#: In order, so selection can walk them.
CATEGORIES = (
    CAT_REPEATED_ATTENDANCE,
    CAT_ATTENDED_AND_PATHWAY,
    CAT_ATTENDED_AND_UPCOMING,
    CAT_REPEATED_PATHWAYS,
    CAT_PATHWAY_AND_UPCOMING,
)


def _naive_utc(value: datetime) -> datetime:
    """``Event.starts_at`` is stored naive; ``StepProgress.completed_at``
    may arrive tz-aware. Compare them on one clock rather than letting
    a TypeError decide the running order."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class Evidence:
    """Everything selection knows about one pair, sorted into kinds.

    Deliberately three separate lists rather than one weighted total.
    The shape of this object is the argument: you can read what two
    people share, and you cannot read how much it is worth.
    """

    recognition: Recognition
    #: Gatherings both were marked attended at, most recent first.
    attended: tuple[datetime, ...]
    #: Pathway crossing dates, most recent first.
    pathways: tuple[datetime | None, ...]
    #: Upcoming Gatherings both are confirmed for, soonest first.
    upcoming: tuple[datetime, ...]

    @property
    def user_id(self) -> str:
        return self.recognition.other_user_id

    @property
    def signal_count(self) -> int:
        """Distinct shared things. Not a score — a count of rows."""
        return len(self.attended) + len(self.pathways) + len(self.upcoming)

    @property
    def realised_count(self) -> int:
        """Shared things that have actually happened, or are underway.

        An upcoming Gathering is excluded on purpose: two people
        confirmed for the same room next week have shared nothing yet.
        """
        return len(self.attended) + len(self.pathways)

    @property
    def is_eligible(self) -> bool:
        """Two signals, at least one of them realised."""
        return self.signal_count >= MIN_SIGNALS and self.realised_count >= 1

    @property
    def category(self) -> int | None:
        """Which of the five, or None when this pair is not eligible.

        Exhaustive and mutually exclusive over eligible pairs, which is
        worth checking by eye: with two or more attended it is 1; with
        exactly one attended it is 2 or 3 depending on whether a
        Pathway is present; with none attended a Pathway must be, so it
        is 4 or 5. Anything left over has only plans and is not
        eligible at all.
        """
        if not self.is_eligible:
            return None
        if len(self.attended) >= 2:
            return CAT_REPEATED_ATTENDANCE
        if len(self.attended) == 1:
            return (
                CAT_ATTENDED_AND_PATHWAY
                if self.pathways
                else CAT_ATTENDED_AND_UPCOMING
            )
        return (
            CAT_REPEATED_PATHWAYS
            if len(self.pathways) >= 2
            else CAT_PATHWAY_AND_UPCOMING
        )


def read_evidence(recognition: Recognition, now: datetime) -> Evidence:
    """Sort one Recognition's shared things into the three kinds."""
    attended: list[datetime] = []
    upcoming: list[datetime] = []

    for gathering in recognition.gatherings:
        starts = _naive_utc(gathering.starts_at)
        if gathering.basis is SharedGatheringBasis.UPCOMING and starts > now:
            upcoming.append(starts)
        elif gathering.basis is SharedGatheringBasis.ATTENDED:
            attended.append(starts)

    pathways = [
        _naive_utc(p.crossing_at) if p.crossing_at else None
        for p in recognition.pathways
    ]

    return Evidence(
        recognition=recognition,
        attended=tuple(sorted(attended, reverse=True)),
        pathways=tuple(
            sorted(pathways, key=lambda d: (d is None, -(d.timestamp() if d else 0)))
        ),
        upcoming=tuple(sorted(upcoming)),
    )


def day_index(now: datetime) -> int:
    """Whole days since the epoch, in UTC.

    The rotation's only moving part. It changes once a day, at the same
    moment for everyone, and is reproducible from a timestamp — so a
    member asking "why these three?" gets an answer that does not
    depend on anything hidden.
    """
    return int(_naive_utc(now).timestamp() // 86_400)


def _within_category_key(e: Evidence):
    """Order people who fall in the same category.

    Recency of the *realised* evidence — the thing that actually
    happened is the thing worth being recent. An imminent Gathering
    breaks ties between otherwise-comparable people, and the user id
    breaks the rest so the order is total and a given day always
    renders identically.
    """
    if e.attended:
        primary = -e.attended[0].timestamp()
    else:
        first = e.pathways[0]
        primary = -first.timestamp() if first else float("inf")

    soonest = e.upcoming[0].timestamp() if e.upcoming else float("inf")
    return (primary, soonest, e.user_id)


def is_eligible_pair(
    recognitions: list[Recognition],
    other_user_id: str,
    *,
    now: datetime,
) -> bool:
    """Would this person be eligible to be introduced to the viewer?

    The authorisation half of the same rule ``select_people`` uses for
    display, expressed through the same two primitives —
    ``read_evidence`` and ``Evidence.is_eligible`` — so the two cannot
    drift. If the threshold ever changes, it changes here too because
    there is only one threshold.

    Deliberately **not** limited. ``select_people`` takes the few people
    the page introduces today; a person who is eligible but fell outside
    that day's rotation is still someone the viewer may greet. The
    display limit is a presentation choice and must not become an
    authorisation rule.

    Returns False for a stranger: a user id the viewer shares nothing
    with is absent from ``recognitions`` entirely, which is also what
    makes probing arbitrary ids uninformative.
    """
    for recognition in recognitions:
        if recognition.other_user_id == other_user_id:
            return read_evidence(recognition, now).is_eligible
    return False


def select_people(
    recognitions: list[Recognition],
    *,
    now: datetime,
    limit: int = MAX_PEOPLE,
) -> list[Recognition]:
    """The few people the destination introduces today.

    Only people with two shared signals, one of them realised, are
    considered — and the threshold never drops to fill a slot. A viewer
    with one eligible person is shown one person. An empty page is a
    truer answer than a card nobody can justify.

    Callers filter to people they can name before calling — a card
    introduces somebody, and we do not introduce a person we cannot
    name. This function trusts the list it is given.
    """
    if not recognitions or limit <= 0:
        return []

    eligible = [
        e for e in (read_evidence(r, now) for r in recognitions) if e.is_eligible
    ]
    if not eligible:
        return []

    chosen: list[Evidence] = []

    # Category by category, strongest first. Within one everyone is
    # comparable, so when a category holds more people than slots left
    # they take turns by the day. The rotation never reaches across a
    # category boundary, which is what stops one attendance plus a plan
    # displacing somebody the viewer has been in the room with twice.
    for category in CATEGORIES:
        if len(chosen) >= limit:
            break
        band = sorted(
            (e for e in eligible if e.category == category),
            key=_within_category_key,
        )
        if not band:
            continue

        room = limit - len(chosen)
        if len(band) <= room:
            chosen.extend(band)
            continue

        start = day_index(now) % len(band)
        picked = [band[(start + i) % len(band)] for i in range(room)]
        # Present the day's pick in the category's own order rather
        # than in the order the rotation happened to reach them.
        picked.sort(key=_within_category_key)
        chosen.extend(picked)

    return [e.recognition for e in chosen]
