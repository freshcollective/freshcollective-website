"""Whether a Pathway may be permanently deleted, and why not.

The bug this exists to fix
--------------------------
``delete_pathway`` was three lines — resolve the Collective, resolve the
Pathway, ``db.delete``. Twenty foreign keys point at ``pathways`` and
exactly one of them carries ``ondelete=RESTRICT``
(``payment_option_grants.pathway_id``). So the database was the only
thing guarding the endpoint, and it guarded it by accident:

* A Pathway that happened to have a grant row produced an
  ``IntegrityError`` and an unhandled **HTTP 500** (Sentry FC-API-D).
  The creator saw "something went wrong" and could not clean up a test
  Collective, because the Pathway's own Payment Option then blocked the
  Collective delete too.
* A Pathway with **no** grant row deleted successfully — and took the
  members with it. ``pathway_entitlements`` is ``CASCADE``, so the
  record that somebody paid for access was destroyed;
  ``payment_transactions.pathway_id`` and ``.entitlement_id`` are
  ``SET NULL``, so the money survived with nothing left to say what it
  bought.

The second case is the serious one, and it is why this module exists.
The 500 was the lesser problem.

What a Pathway delete actually destroys
---------------------------------------
Directly and transitively, through ``CASCADE``:

    pathway_entitlements        purchased or granted access
    enrollments                 a member's relationship to the journey
    pathway_steps
      → step_progress           completions AND ``reflection_text``
      → step_comments           member-authored comments
      → pathway_step_blocks
          → (answers)           members' private written answers
    manual_member_pathway_access
    access_grant_records
    pathway_sections, pathway_about_blocks,
    pathway_unlock_requirements, space_resource_pathways,
    payment_options (via the legacy ``pathway_id`` column)

and, severed rather than deleted, through ``SET NULL``:

    payment_transactions.pathway_id   the purchase loses its subject
    access_passes.*_pathway_id
    purchase_intents.pathway_id
    activities.pathway_id
    conversation_channels.pathway_id
    events.booking_required_pathway_id
    space_resources.pathway_id
    payment_options.grants_pathway_id

Members' private reflections and exercise answers are in that list. So
the question this module answers is not "will the database let us?" but
"is there anything here that must outlive a creator tidying a list?".

Where the parts live
--------------------
Split the way Offerings are split, because the same two questions came
up: ``_offering_routes.delete_offering`` keeps the status and
member-record refusals and asks
``services.offering_commerce.blocking_commerce_reference`` about the
Payment Options. So:

* **this module** — publication history, member records, the Gathering
  booking gate, the Pathway's own conversation Channel, and the order
  the refusals are asked in;
* :mod:`app.services.pathway_commerce` — everything about the Pathway
  ↔ PaymentOption relationship, which also has to answer "may this
  Option still be sold?" once a Pathway is archived. One module owns
  that relationship rather than two deciding separately what a
  Pathway's "own" Option is.

The pattern, not a new one
--------------------------
Offerings (``_offering_routes.delete_offering`` +
``services.offering_commerce``) and Gathering Series
(``_gathering_series_routes.delete_gathering_series``) already solved
this, and the platform rule they encode is: **a draft that was never
publicly used is deleted; anything published or historical is kept.**
Pathways are the one experience that never got the pass — the
``PaymentOptionGrant`` model docstring even says so, promising
"application-layer preflight on the experience-delete endpoints" in a
later commit. This is that commit.

Two parts of the Offerings reasoning are carried over verbatim, because
getting either wrong is what makes a lifecycle rule unusable:

1. **A Pathway's own commerce rows are not blockers.** They exist only
   to serve this Pathway and no other product can reach them, so they
   are part of what gets deleted. Treating them as blockers is what
   made every paid Offering draft undeletable, with a message telling
   the creator to archive an option they never created and cannot see.
   This is also precisely the dead end reported in FC-API-D.
2. **A reference held by something else is a 409, never a 500.** The
   RESTRICT is a correct refusal; it just cannot explain itself.

"Published, ever" without a ``published_at`` column
---------------------------------------------------
Offerings and Gathering Series both stamp ``published_at`` on first
publish and never clear it, so they can ask "was this ever public?"
where ``status`` only answers "is it public now?". ``pathways`` has no
such column and one is deliberately not being added, so the question is
asked of records that already exist — and of two of them, not one:

* ``communication_events`` carries the ``pathway.published``
  announcement keyed ``"{pathway_id}:{space_id}"``. The module that
  writes it (``services.pathway_announcement``) states outright that
  "the event row *is* the record of having announced", and it is never
  cleared — returning a Pathway to draft and publishing again finds the
  key present and stays silent.
* ``activities`` carries the deduped ``pathway_published`` row, written
  under the same ``is_member_visible`` predicate.

Both are checked because **either can be missing from a Pathway that
really was published**: each writer wraps its emit in a ``try/except``
that logs and continues, on the explicit grounds that losing a
notification is a smaller harm than failing a creator's publish. One
signal is unreliable; the union of two independently-written ones is
the conservative reading, and it costs two indexed lookups on a path
that runs at most once per Pathway.

The gap that remains, stated rather than hidden: a Pathway that went
``draft → coming_soon → draft`` was listed publicly but never announced
and never recorded, so neither signal fires. It is deletable. Nobody
could ever open it — ``coming_soon`` raises 403 for members — and the
dependency checks below still refuse if a single record exists, so what
is lost is a listing nobody could act on.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from app.services import pathway_commerce

if TYPE_CHECKING:  # pragma: no cover — typing only
    from sqlalchemy.orm import Session

    from app.models.platform import Pathway

logger = logging.getLogger(__name__)

#: The one status a Pathway may be deleted from. Mirrors
#: ``delete_offering`` (draft only) and ``delete_gathering_series``
#: (``status != 'draft'`` refuses). ``active`` and ``coming_soon`` are
#: public states; ``archived`` is a historical one.
DELETABLE_STATUS = "draft"


def _status_of(pathway: "Pathway") -> str:
    status = getattr(pathway, "status", None)
    return str(getattr(status, "value", status))


# ---------------------------------------------------------------------------
# Publication history
# ---------------------------------------------------------------------------


def was_ever_published(db: "Session", pathway: "Pathway") -> bool:
    """Whether this Pathway has ever been available to members.

    Stands in for the ``published_at`` column Offerings and Series have.
    See the module docstring for why two signals are read instead of
    one, and for the one transition neither of them covers.
    """
    from app.comms.models import CommunicationEvent
    from app.models.activity import Activity, ActivityType
    from app.services.pathway_announcement import (
        ANNOUNCEMENT_EVENT,
        announcement_dedupe_key,
    )

    if pathway.space_id:
        announced = (
            db.query(CommunicationEvent.id)
            .filter(
                CommunicationEvent.event_type == ANNOUNCEMENT_EVENT,
                CommunicationEvent.dedupe_key == announcement_dedupe_key(
                    pathway.id, pathway.space_id,
                ),
            )
            .first()
        )
        if announced:
            return True

    recorded = (
        db.query(Activity.id)
        .filter(
            Activity.pathway_id == pathway.id,
            Activity.event_type == ActivityType.pathway_published.value,
        )
        .first()
    )
    return recorded is not None


# ---------------------------------------------------------------------------
# Member records
# ---------------------------------------------------------------------------


def _blocking_member_reference(
    db: "Session", pathway: "Pathway",
) -> str | None:
    """Why somebody's access, purchase or work forbids deleting this.

    Every one of these is destroyed or orphaned by the delete — see the
    table in the module docstring — so each is asked about separately
    and in its own words. ``pathway_entitlements`` is checked **in any
    state**, exactly as ``delete_offering`` checks
    ``OfferingEntitlement``: an expired or revoked entitlement is still
    the record that somebody once had access, and a refunded purchase
    still happened.

    One row in the destruction list is deliberately **not** asked about
    here: the table holding members' private written answers to
    exercise blocks. It sits behind a privacy boundary that a test
    enforces by grep — nothing outside its own member endpoints may
    name the model or its table at all, "so there is no surface to
    audit rather than one that merely happens to omit the field". That
    is also why this paragraph describes it rather than naming it.
    Counting the rows here would weaken the boundary for no gain,
    because the gates that run *before* this function already exclude
    every path by which a member could have written one: a response can
    only be saved through a step the member can open, and
    ``_check_pathway_access`` refuses ``draft``, ``coming_soon`` and
    ``archived`` to everyone but caretakers. A deletable Pathway is a
    draft with no publication history, so the only answers it can hold
    are the creator's own, written while building it.

    The residual case, stated rather than hidden: a Pathway that was
    live, collected answers, was returned to draft, and whose *both*
    publication signals failed to be written — each writer swallows its
    own failure by design. Such a Pathway would almost certainly also
    carry ``step_progress`` or an entitlement, which are checked, but
    "almost certainly" is the honest word.
    """
    from app.models.access_grant_record import AccessGrantRecord
    from app.models.access_pass import AccessPass
    from app.models.payment import PaymentTransaction
    from app.models.platform import (
        Enrollment,
        ManualMemberPathwayAccess,
        PathwayEntitlement,
        PathwayStep,
        StepComment,
        StepProgress,
    )
    from app.models.purchase_intent import PurchaseIntent

    step_ids = [
        row[0]
        for row in db.query(PathwayStep.id)
        .filter(PathwayStep.pathway_id == pathway.id)
        .all()
    ]

    checks: tuple[tuple[Callable[[], object], str], ...] = (
        (
            lambda: db.query(PathwayEntitlement.id).filter(
                PathwayEntitlement.pathway_id == pathway.id,
            ).first(),
            "members hold access to it",
        ),
        (
            lambda: db.query(PaymentTransaction.id).filter(
                PaymentTransaction.pathway_id == pathway.id,
            ).first(),
            "payments are recorded against it",
        ),
        (
            lambda: db.query(PurchaseIntent.id).filter(
                PurchaseIntent.pathway_id == pathway.id,
            ).first(),
            "a checkout was started for it",
        ),
        (
            lambda: db.query(AccessPass.id).filter(
                (AccessPass.grants_pathway_id == pathway.id)
                | (AccessPass.eligible_pathway_id == pathway.id),
            ).first(),
            "passes are scoped to it",
        ),
        (
            lambda: db.query(AccessGrantRecord.id).filter(
                AccessGrantRecord.target_pathway_id == pathway.id,
            ).first(),
            "access to it has been granted and recorded",
        ),
        (
            lambda: db.query(ManualMemberPathwayAccess.id).filter(
                ManualMemberPathwayAccess.pathway_id == pathway.id,
            ).first(),
            "a manually added member has been given access to it",
        ),
        (
            lambda: db.query(Enrollment.id).filter(
                Enrollment.pathway_id == pathway.id,
            ).first(),
            "members have enrolled in it",
        ),
        (
            lambda: (
                db.query(StepProgress.id).filter(
                    StepProgress.step_id.in_(step_ids),
                ).first() if step_ids else None
            ),
            "members have recorded progress and reflections in it",
        ),
        (
            lambda: (
                db.query(StepComment.id).filter(
                    StepComment.step_id.in_(step_ids),
                ).first() if step_ids else None
            ),
            "members have left comments on its steps",
        ),
    )
    for probe, reason in checks:
        if probe() is not None:
            return (
                f"This pathway cannot be permanently deleted because "
                f"{reason}. Those records are kept."
            )
    return None


def _blocking_gathering_gate_reference(
    db: "Session", pathway: "Pathway",
) -> str | None:
    """A Gathering that uses this Pathway as its booking requirement.

    ``events.booking_required_pathway_id`` is ``SET NULL``, and
    ``gathering_booking_rules`` reads::

        is_pathway_gated = access == "included_with_pathway" \
            and bool(required_pathway_id)

    so nulling the column does not break the gate, it **removes** it:
    the Gathering silently becomes bookable by any member rather than
    only by those holding a pass for this Pathway. A quiet widening of
    access is worse than a refusal, so this refuses.

    Checked regardless of ``booking_access_type``, because the pairing
    is what matters and a creator can switch the type back at any time.
    """
    from app.models.platform import Event

    gated = (
        db.query(Event.id)
        .filter(Event.booking_required_pathway_id == pathway.id)
        .first()
    )
    if gated:
        return (
            "A gathering uses this pathway to decide who may book it. "
            "Point that gathering's booking requirement somewhere else "
            "first."
        )
    return None


def _blocking_conversation_reference(
    db: "Session", pathway: "Pathway",
) -> str | None:
    """A pathway Channel carrying member posts.

    ``conversation_channels.pathway_id`` is ``SET NULL`` and
    ``can_view_channel`` reads ``channel.pathway_id is not None``, so a
    deleted Pathway leaves its Channel standing and reachable by nobody
    — the conversation is not leaked, it is entombed.

    An **empty** Channel is not a blocker, for the same reason the
    Pathway's own draft Payment Option is not: ``create_pathway``
    provisions it on request at birth, nobody else can reach it, and
    refusing on it would make every Pathway created with a Channel
    permanently undeletable. It is removed with the Pathway instead.
    """
    from app.models.platform import ConversationChannel, CommunityPost

    channel_ids = [
        row[0]
        for row in db.query(ConversationChannel.id)
        .filter(ConversationChannel.pathway_id == pathway.id)
        .all()
    ]
    if not channel_ids:
        return None
    posted = (
        db.query(CommunityPost.id)
        .filter(CommunityPost.channel_id.in_(channel_ids))
        .first()
    )
    if posted:
        return (
            "This pathway's conversation channel has posts in it. "
            "Those stay, so the pathway cannot be permanently deleted."
        )
    return None


def delete_owned_conversation_channels(
    db: "Session", pathway: "Pathway",
) -> int:
    """Remove the Pathway's own empty Channel(s). Returns the count.

    Called only after :func:`blocking_reference` has confirmed no posts
    exist, so ``community_posts.channel_id`` — which is ``RESTRICT`` —
    has nothing to refuse. Leaving the Channel behind would be worse
    than deleting it: ``SET NULL`` would strand an empty, permanently
    invisible row in the Collective's channel list.
    """
    from app.models.platform import ConversationChannel

    channels = (
        db.query(ConversationChannel)
        .filter(ConversationChannel.pathway_id == pathway.id)
        .all()
    )
    for channel in channels:
        db.delete(channel)
    if channels:
        db.flush()
        logger.info(
            "pathway_deletion: removed %d empty channel(s) for pathway=%s",
            len(channels), pathway.id,
        )
    return len(channels)


# ---------------------------------------------------------------------------
# The question the endpoint asks
# ---------------------------------------------------------------------------


def blocking_reference(db: "Session", pathway: "Pathway") -> str | None:
    """The sentence explaining why this Pathway may not be deleted, or
    ``None`` when it may.

    Ordered so that the reason a creator reads is the most meaningful
    one available, not the cheapest one to query: what state the Pathway
    is in, then whether members were ever let near it, then what they
    did, then what the commerce layer promises, then what else in the
    Collective is wired to it, then the conversation.
    """
    status = _status_of(pathway)
    if status != DELETABLE_STATUS:
        if status == "archived":
            return (
                "This pathway is archived, so it is kept rather than "
                "erased. If you are certain you want it gone, set its "
                "status back to Draft first — every check below still "
                "applies, so anything members hold will still stop it."
            )
        return (
            "Only a draft pathway can be permanently deleted. Set this "
            "one back to Draft first — that already takes it out of "
            "members' view."
        )

    if was_ever_published(db, pathway):
        return (
            "This pathway has been live to members before, so it is kept "
            "rather than erased. It is a draft now, which already means "
            "members cannot see it."
        )

    member = _blocking_member_reference(db, pathway)
    if member:
        return member

    commerce = pathway_commerce.blocking_reference(db, pathway)
    if commerce:
        return commerce

    gate = _blocking_gathering_gate_reference(db, pathway)
    if gate:
        return gate

    return _blocking_conversation_reference(db, pathway)


__all__ = [
    "DELETABLE_STATUS",
    "blocking_reference",
    "delete_owned_conversation_channels",
    "was_ever_published",
]
