"""Where a Gathering Series belongs: Upcoming, Archives, or neither.

A Series has three stored statuses — ``draft``, ``published``,
``archived`` — and no ``completed``. A term that finished last month is
still ``published``; nothing moves it. So "has this finished" is a
question about dates, and "has a creator put it away" is a question
about status, and the two are different questions.

Read-time, deliberately
-----------------------
Nothing here writes. A Series whose last session has passed is
reported as completed without its stored status changing, because
opening a list is not a decision a creator made about their own
content: a term that finishes while the creator is on holiday should
not quietly become ``archived``, and a background sweep to make list
filters work would be a schema change masquerading as a bug fix.

The classification
------------------
    draft      status='draft'      — not yet published, whatever its dates
    archived   status='archived'   — put away explicitly, whatever its dates
    scheduled  published, starts in the future
    running    published, started, and not finished
    completed  published, finished

"Finished" means ``ends_at`` has passed. A Series with no ``ends_at``
is an ongoing circle — the editor's own copy calls it "Ongoing" — so
it never becomes completed on its own, and a creator who wants it out
of the way archives it. That is also what keeps a Series with missing
dates from disappearing: with nothing to compare, it stays in
Upcoming, where it can be found and fixed.
"""

from __future__ import annotations

from datetime import datetime

#: Every value :func:`classify_series` can return.
DRAFT = "draft"
SCHEDULED = "scheduled"
RUNNING = "running"
COMPLETED = "completed"
ARCHIVED = "archived"

LIFECYCLES = (DRAFT, SCHEDULED, RUNNING, COMPLETED, ARCHIVED)

#: What belongs on the main Gatherings page. Drafts are here because
#: there is no separate Drafts view — a creator finishes a draft from
#: the same place they create one, and moving them would be a
#: navigation change rather than this fix.
UPCOMING_LIFECYCLES = frozenset({DRAFT, SCHEDULED, RUNNING})

#: What belongs in Archives.
ARCHIVE_LIFECYCLES = frozenset({COMPLETED, ARCHIVED})

SCOPES = ("upcoming", "archive")


def classify_series(
    *,
    status: str | None,
    starts_at: datetime | None,
    ends_at: datetime | None,
    now: datetime,
) -> str:
    """Which lifecycle a Series is in. See the module docstring.

    ``status`` wins over dates in both directions: an archived Series
    with future sessions is archived, and a draft with past dates is
    still a draft. Only a *published* Series is classified by time.
    """
    stored = (status or "").strip().lower()
    if stored == ARCHIVED:
        return ARCHIVED
    if stored == DRAFT:
        return DRAFT

    # Published. An unknown stored status is treated as published
    # rather than hidden — a row with a value this module has not met
    # must still be reachable.
    if ends_at is not None and ends_at < now:
        return COMPLETED
    if starts_at is not None and starts_at > now:
        return SCHEDULED
    return RUNNING


def series_in_scope(lifecycle: str, scope: str) -> bool:
    """Whether a lifecycle belongs in ``scope``.

    An unrecognised scope includes everything, so a typo in a query
    string shows a creator too much rather than nothing.
    """
    if scope == "upcoming":
        return lifecycle in UPCOMING_LIFECYCLES
    if scope == "archive":
        return lifecycle in ARCHIVE_LIFECYCLES
    return True


def archive_sort_key(
    *, lifecycle: str, ends_at: datetime | None, starts_at: datetime | None,
    updated_at: datetime | None,
) -> tuple:
    """Most recently finished or put away first, and stable.

    An archived Series may have no end date at all, and one archived
    early has an end date in the future that says nothing about when
    the creator archived it — so ``updated_at`` is the fallback, which
    is the closest stored approximation of "when did this stop being
    current". Returned as a tuple with a final discriminator so two
    Series sharing a date keep a fixed order rather than swapping
    places between requests.
    """
    stamp = ends_at or starts_at or updated_at
    # ``datetime.min`` for a Series with no dates at all: it sorts
    # last rather than vanishing.
    return (stamp or datetime.min, (updated_at or datetime.min))


__all__ = [
    "ARCHIVED",
    "ARCHIVE_LIFECYCLES",
    "COMPLETED",
    "DRAFT",
    "LIFECYCLES",
    "RUNNING",
    "SCHEDULED",
    "SCOPES",
    "UPCOMING_LIFECYCLES",
    "archive_sort_key",
    "classify_series",
    "series_in_scope",
]
