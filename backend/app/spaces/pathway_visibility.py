"""Which Pathways a viewer may see listed — one answer, three callers.

The Pathways tab has always had this right: a non-caretaker sees
Pathways whose ``status`` is ``active`` or ``coming_soon``, and nobody
else sees draft or archived ones. Two other surfaces counted them their
own way and disagreed with it:

* the public Explore card counted ``status != 'archived'``, so a
  Collective with one draft Pathway advertised "1 pathway";
* ``SpaceResponse`` serialises the ``Space.pathways`` ORM relationship
  wholesale, which is unfiltered — so the Collective's own page counted
  drafts AND archived, and the draft rows travelled in the payload to
  anonymous callers.

So the rule lives here now and all three read it from one place.

Status, not access
------------------

This filters on **status only**, and that is deliberate rather than an
omission. Access — ``free`` / ``included`` / ``one_time`` /
``subscription`` — does not decide whether a Pathway is *listed*; it
decides whether it is *unlocked*. ``list_pathways`` computes
``has_access`` per row and returns it as a field, so a paid or
members-only published Pathway appears in the list and renders locked,
with a route to buy it.

That matters for the counts: making them hide paid Pathways would make
them disagree with the tab in the opposite direction, and would hide a
Collective's paid offering from the very visitors it is meant to
attract. "Discoverable" here means listed, which is what the tab shows
and therefore what a count should agree with.

Unpublishing and access changes
-------------------------------

Both follow from reading status at query time rather than storing a
count. A Pathway moved back to ``draft`` leaves every public count on
the next request; one promoted to ``active`` enters them. An access
change moves nothing, because access was never part of the predicate —
it only changes whether the listed Pathway is locked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — typing only
    from sqlalchemy.orm import Session

    from app.models.platform import Pathway, Space
    from app.models.user import User

#: The statuses a Pathway must hold to be listed to a non-caretaker.
#:
#: ``coming_soon`` is included because it is a published state a creator
#: chooses deliberately — "ready and waiting for release" — and the
#: Pathways tab has always shown it. ``draft`` and ``archived`` are
#: caretaker-only.
LISTED_STATUSES: tuple[str, ...] = ("active", "coming_soon")


def viewer_sees_all_pathways(
    user: "User | None", space: "Space", db: "Session",
) -> bool:
    """Whether this viewer sees draft and archived Pathways too.

    Delegates to ``is_caretaker`` — admin, the Collective's owner, or an
    active creator/moderator membership — so Creator Studio keeps its
    view of drafts and anonymous callers never gain one. Named for what
    it decides rather than for who the viewer is, because the callers
    care about the former.
    """
    from app.services import channel_permissions as channel_perms

    return channel_perms.is_caretaker(user, space, db)


def listed_pathway_filter(include_unpublished: bool):
    """A SQLAlchemy criterion for a Pathway query, or ``None``.

    ``None`` when the viewer sees everything, so a caller can write::

        q = db.query(Pathway).filter(Pathway.space_id == space.id)
        crit = listed_pathway_filter(sees_all)
        if crit is not None:
            q = q.filter(crit)

    Returning ``None`` rather than a true-criterion keeps the emitted
    SQL identical to what these queries produced before this module
    existed.
    """
    if include_unpublished:
        return None
    from app.models.platform import Pathway

    return Pathway.status.in_(LISTED_STATUSES)


def is_listed(pathway: "Pathway") -> bool:
    """Whether one already-loaded Pathway is listed to a non-caretaker.

    For the places holding ORM rows rather than building a query — the
    ``Space.pathways`` relationship in particular, which is serialised
    whole and cannot be filtered in SQL without changing the
    relationship for every other reader of it.
    """
    status = getattr(pathway, "status", None)
    # ``status`` is an enum column; compare on its value so a plain
    # string and an enum member both work.
    raw = getattr(status, "value", status)
    return raw in LISTED_STATUSES


__all__ = [
    "LISTED_STATUSES",
    "is_listed",
    "listed_pathway_filter",
    "viewer_sees_all_pathways",
]
