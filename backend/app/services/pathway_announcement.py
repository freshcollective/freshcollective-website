"""When a Pathway first becomes available to members — and only then.

The bug this exists to fix
--------------------------
A member of World Builders received an email about a Pathway that was
still a draft. The cause was not the "new pathway" notification at all:
that one has never fired. ``notification_service.trigger_new_pathway``
has no callers, the ``new_pathway_email`` template has no callers, and
the ``pathway.published`` comms event — registry entry, resolver and
templates all written — is emitted by nothing.

What *was* live is the step announcement. ``POST
/spaces/{slug}/pathways/{slug}/steps`` queues
``trigger_new_step``, which notifies every active member of the
Collective and emails them a link to the new step, with **no check on
the Pathway's status**. So authoring a draft announced each section as
it was written, to everybody, linking to content they could not open.

Two separate problems, and this module is about the second one as much
as the first: there was no notification at the moment that actually
matters, and there was a notification at moments that do not.

What "available" means
----------------------
Taken from the rule members are already subject to, not invented here.
``spaces/routes.py`` shows ordinary members pathways with status in
``("active", "coming_soon")``; draft and archived are caretaker-only.

Announcing is narrower than listing. ``coming_soon`` appears in the
list but is not open, and "a new pathway is available" is not true of
it — so the announcement waits for ``active``. A pathway that goes
draft → coming_soon → active announces once, on the last step.

The Collective has to be available too. A pathway inside a draft,
archived or closed Collective is not reachable by its members, so it is
not announced.

Idempotency
-----------
The comms layer already provides a durable mechanism, so there is no
new column and no boolean. ``communication_events`` carries a partial
unique index on ``(event_type, dedupe_key)`` — see migration 097 — and
the key here is::

    pathway.published  +  "{pathway_id}:{space_id}"

The event row *is* the record of having announced. That gives every
case the brief asks for without any schema change:

  * republishing after a return to draft finds the key present and
    does nothing;
  * editing a published pathway never reaches this code;
  * and the key is per pathway **and** per Collective, so if pathways
    ever become attachable to more than one Collective, the second
    Collective gets its own first-availability announcement while the
    first is not told twice. Today ``pathways.space_id`` is a single
    non-null column, so one pathway belongs to exactly one Collective
    and the space half of the key is constant — but keying on the pair
    costs nothing and means the idempotency does not have to be
    redesigned later.

Checked with a ``SELECT`` rather than by inspecting what ``emit``
returns. ``emit`` returns ``None`` both for a dedupe collision and for
a transient integrity failure, which are not the same thing, and this
decision should not rest on telling them apart.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.models.platform import Pathway, PathwayStatus, Space, SpaceStatus

logger = logging.getLogger(__name__)

#: The registered comms event for first availability. Already defined in
#: ``app/comms/registry.py`` with a resolver and templates; nothing was
#: emitting it.
ANNOUNCEMENT_EVENT = "pathway.published"


def announcement_dedupe_key(pathway_id: str, space_id: str) -> str:
    """The durable "this audience has been told" key."""
    return f"{pathway_id}:{space_id}"


def is_member_visible(db: Session, pathway: Pathway) -> bool:
    """Can ordinary members of the Collective reach this Pathway now?

    Deliberately stricter than the member *list* filter, which also
    includes ``coming_soon``: this answers "is it available", and a
    coming-soon pathway is announced when it opens rather than when it
    is listed.
    """
    status = getattr(pathway.status, "value", pathway.status)
    if status != PathwayStatus.active.value:
        return False
    if not pathway.space_id:
        return False

    space = db.get(Space, pathway.space_id)
    if space is None:
        return False
    space_status = getattr(space.status, "value", space.status)
    if space_status != SpaceStatus.active.value:
        return False

    # Community Care can close or pause a Collective independently of
    # its own status. Imported lazily — this module is reached from
    # route handlers and the import graph there is already heavy.
    try:
        from app.community_care.shared import is_space_closed

        if is_space_closed(space):
            return False
    except Exception:  # pragma: no cover - defensive
        logger.exception(
            "pathway_announcement: could not evaluate collective closure "
            "for space %s; treating as not announceable", pathway.space_id,
        )
        return False

    return True


def already_announced(db: Session, pathway: Pathway) -> bool:
    """Has this audience already been told about this Pathway?"""
    if not pathway.space_id:
        return False
    key = announcement_dedupe_key(pathway.id, pathway.space_id)
    return db.scalar(
        select(CommunicationEvent.id).where(
            CommunicationEvent.event_type == ANNOUNCEMENT_EVENT,
            CommunicationEvent.dedupe_key == key,
        ).limit(1)
    ) is not None


def should_announce(db: Session, pathway: Pathway) -> bool:
    """The transition, expressed as a question about the present.

    "Not member-visible → member-visible" needs no before-state stored
    anywhere: it is "visible now" and "never announced". That is what
    makes returning to draft and publishing again a no-op rather than a
    second announcement.
    """
    return is_member_visible(db, pathway) and not already_announced(db, pathway)


def announce_if_newly_available(
    db: Session,
    pathway: Pathway,
    *,
    actor_user_id: str,
) -> "CommunicationEvent | None":
    """Record first availability. Returns the event, or None if it did
    not announce.

    Emits inside the caller's transaction, so a rollback in the route
    takes the announcement with it — there is no announcement without
    the publication that caused it. Sends nothing itself: the caller
    commits and then schedules routing, the same shape
    ``community.post.published`` uses, which keeps the decision
    separable from the delivery and testable without a mail server.
    """
    if not should_announce(db, pathway):
        return None

    space = db.get(Space, pathway.space_id)
    from app.comms import Source, emit as comms_emit

    # The announcement must never fail the publication.
    #
    # A creator pressing Publish is doing something they are entitled to
    # do; losing a notification is a smaller harm than a 500 that leaves
    # them unsure whether it worked. ``emit`` opens a SAVEPOINT for the
    # dedupe insert, and a savepoint can fail for reasons that have
    # nothing to do with this pathway — so it is caught, logged loudly,
    # and the publish proceeds.
    #
    # Safe to swallow because idempotency does not depend on it:
    # ``already_announced`` above is the authoritative guard and the
    # unique index is the race guard. The cost of a lost emit is one
    # un-sent announcement, and the next publish of a *different*
    # pathway is unaffected.
    try:
        return comms_emit(
            db,
            event_type=ANNOUNCEMENT_EVENT,
            # The creator is the sender, as with every other creator-
            # authored announcement; ``source_id`` is their user id, not
            # the Collective's.
            source_type=Source.CREATOR,
            source_id=actor_user_id,
            actor_user_id=actor_user_id,
            subject_type="pathway",
            subject_id=pathway.id,
            context={
                "space_id": pathway.space_id,
                "collective_name": space.name if space else None,
            },
            payload={
                "pathway_id": pathway.id,
                "pathway_slug": pathway.slug,
                "pathway_title": pathway.title,
                "pathway_type": getattr(
                    pathway.pathway_type, "value", pathway.pathway_type,
                ),
            },
            dedupe_key=announcement_dedupe_key(pathway.id, pathway.space_id),
        )
    except Exception:
        logger.exception(
            "pathway_announcement: could not record first availability for "
            "pathway %s in space %s; the pathway is published either way",
            pathway.id, pathway.space_id,
        )
        return None
