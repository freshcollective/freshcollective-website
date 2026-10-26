"""The Pathway ↔ PaymentOption relationship, and who owns it.

Sibling of :mod:`app.services.offering_commerce`, and split out of
``pathway_deletion`` for the same reason that module exists: one place
decides which Payment Options exist only to serve a Pathway and which
belong to something else. Two very different questions need that
answer, and both used to guess:

* **May this Pathway be deleted?** A Pathway's own never-sold draft
  Option is part of what gets deleted; an Option held by the Collective
  or by a Gathering Series is a promise to that Option's buyers and
  refuses the delete. Getting this backwards is Sentry FC-API-D — the
  Pathway could not be deleted because of its own Payment Option, and
  the Collective could not then be deleted because of the same Option.
* **May this Option still be sold?** Archiving a Pathway has to stop
  new purchases of it, and the honest place to enforce that is the
  checkout door, not a mutation of the creator's rows. See
  :func:`unsellable_reason`.

How a Pathway's own Option is recognised
----------------------------------------
``PaymentOption`` carries three different ways of pointing at a
Pathway, and they do not mean the same thing:

``attaches_to_kind`` / ``attaches_to_id``
    Where the Option is authored and displayed. ``'pathway'`` means it
    came from the Pathway's own payment-options surface
    (``creator.routes.create_payment_option``). The two other authoring
    surfaces use ``'event_series'`` and ``'space'``, and both set
    ``pathway_id=None`` explicitly. **This is the ownership test.**

``pathway_id``
    The pre-polymorphic column, kept in step by that same surface. It
    is ``ondelete=CASCADE``, so an Option carrying it while attached
    elsewhere would be deleted outright as a side effect — which is
    why a mismatch refuses rather than being guessed at.

``grants_pathway_id`` and ``payment_option_grants``
    What the Option *grants*, which may be a different Pathway
    entirely, or several. ``payment_option_grants.pathway_id`` is
    ``ondelete=RESTRICT`` — the constraint FC-API-D tripped over.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover — typing only
    from sqlalchemy.orm import Session

    from app.models.payment_option import PaymentOption
    from app.models.platform import Pathway

logger = logging.getLogger(__name__)

#: ``PaymentOption.attaches_to_kind`` for an option authored on a
#: Pathway's own payment-options surface. See the module docstring.
PATHWAY_ATTACH_KIND = "pathway"


def owned_option_ids(db: "Session", pathway: "Pathway") -> list[str]:
    """Payment Options that exist only to sell this Pathway.

    Matched on the polymorphic attachment rather than the legacy
    ``pathway_id`` column, because the two can disagree and only the
    attachment says who authored the option. An option carrying this
    Pathway's ``pathway_id`` while attached elsewhere is handled as a
    blocker below, not as one of ours — ``payment_options.pathway_id``
    is ``CASCADE``, so mistaking it for ours would delete somebody
    else's option as a side effect.
    """
    from app.models.payment_option import PaymentOption

    return [
        row[0]
        for row in db.query(PaymentOption.id)
        .filter(
            PaymentOption.attaches_to_kind == PATHWAY_ATTACH_KIND,
            PaymentOption.attaches_to_id == pathway.id,
        )
        .all()
    ]


def _option_usage_reference(db: "Session", option_ids: list[str]) -> str | None:
    """Why one of this Pathway's own options cannot be removed with it.

    Removing a Payment Option is far from free: ``discount_codes``
    scoped to it and its ``discount_reservations``,
    ``payment_option_grants``, ``payment_option_schedules`` and
    ``pathway_unlock_requirements`` all ``CASCADE``, while
    ``payment_transactions``, ``access_passes``, ``manual_members``,
    ``purchase_intents`` and ``space_invitations`` are ``SET NULL`` and
    ``purchase_plans`` is ``RESTRICT``.

    So "unused" is checked explicitly rather than inferred from the
    Pathway's own emptiness. A draft option a creator priced and never
    published has none of these rows and goes quietly; anything that
    has been through checkout, carries a discount code, or is named by
    an invitation stays, and the Pathway is refused.
    """
    if not option_ids:
        return None

    from app.models.discount_code import DiscountCode, DiscountReservation
    from app.models.payment_option import PaymentOption, PaymentOptionStatus
    from app.models.payment import PaymentTransaction
    from app.models.access_pass import AccessPass
    from app.models.platform import ManualMember, SpaceInvitation
    from app.models.purchase_intent import PurchaseIntent
    from app.models.purchase_plan import PurchasePlan

    published = (
        db.query(PaymentOption.id)
        .filter(
            PaymentOption.id.in_(option_ids),
            PaymentOption.status == PaymentOptionStatus.published,
        )
        .first()
    )
    if published:
        return (
            "This pathway is on sale through a published Payment Option. "
            "Archive that option first if you no longer want to offer it."
        )

    # Each of these is a record somebody else's row points at. Ordered
    # money-first so the sentence a creator reads names the most
    # consequential reason rather than the first one queried.
    usages: tuple[tuple[Callable[[], object], str], ...] = (
        (
            lambda: db.query(PaymentTransaction.id).filter(
                PaymentTransaction.payment_option_id.in_(option_ids),
            ).first(),
            "payments have been taken through this pathway's Payment Option",
        ),
        (
            lambda: db.query(PurchasePlan.id).filter(
                PurchasePlan.payment_option_id.in_(option_ids),
            ).first(),
            "an instalment plan was set up on this pathway's Payment Option",
        ),
        (
            lambda: db.query(AccessPass.id).filter(
                AccessPass.payment_option_id.in_(option_ids),
            ).first(),
            "a pass was issued from this pathway's Payment Option",
        ),
        (
            lambda: db.query(PurchaseIntent.id).filter(
                PurchaseIntent.payment_option_id.in_(option_ids),
            ).first(),
            "a checkout was started on this pathway's Payment Option",
        ),
        (
            lambda: db.query(DiscountCode.id).filter(
                DiscountCode.scope_kind == "payment_option",
                DiscountCode.scope_id.in_(option_ids),
            ).first(),
            "a discount code is scoped to this pathway's Payment Option",
        ),
        (
            lambda: db.query(DiscountReservation.id).filter(
                DiscountReservation.payment_option_id.in_(option_ids),
            ).first(),
            "a discount is reserved against this pathway's Payment Option",
        ),
        (
            lambda: db.query(ManualMember.id).filter(
                ManualMember.payment_option_id.in_(option_ids),
            ).first(),
            "a manually added member is recorded against this pathway's "
            "Payment Option",
        ),
        (
            lambda: db.query(SpaceInvitation.id).filter(
                SpaceInvitation.payment_option_id.in_(option_ids),
            ).first(),
            "an invitation names this pathway's Payment Option",
        ),
    )
    for probe, reason in usages:
        if probe() is not None:
            return (
                f"This pathway cannot be permanently deleted because {reason}. "
                "Those records must not be discarded."
            )
    return None


def blocking_reference(
    db: "Session", pathway: "Pathway",
) -> str | None:
    """Why another product's commerce rows forbid deleting this Pathway.

    The direct analogue of
    ``offering_commerce.blocking_commerce_reference``, and it draws the
    same line. A Payment Option the
    creator authored **on this Pathway** is not a blocker — it is part
    of what gets deleted. An option that belongs to the Collective or to
    a Gathering Series and happens to *include* this Pathway is, because
    deleting the Pathway would silently remove something a buyer of that
    option is owed.

    ``payment_option_grants.pathway_id`` is the ``ondelete=RESTRICT``
    that produced FC-API-D's 500. This is what turns it into a sentence.
    """
    from app.models.payment_option import PaymentOption
    from app.models.payment_option_grant import PaymentOptionGrant
    from app.models.platform import PathwayUnlockRequirement

    own = owned_option_ids(db, pathway)

    # The RESTRICT, named. A grant row whose option is not one of ours
    # means some other Payment Option includes this Pathway.
    foreign_grant = db.query(PaymentOptionGrant.id).filter(
        PaymentOptionGrant.pathway_id == pathway.id,
        *(
            (~PaymentOptionGrant.payment_option_id.in_(own),)
            if own else ()
        ),
    ).first()
    if foreign_grant:
        return (
            "Another Payment Option includes this pathway in what it "
            "grants. Remove this pathway from that option first."
        )

    # ``grants_pathway_id`` is the pre-grants way of saying the same
    # thing, and it is ``SET NULL`` — so without this check deleting the
    # Pathway would quietly turn a paid option into one that grants
    # nothing, and the next buyer would be charged for no access.
    foreign_grants_column = db.query(PaymentOption.id).filter(
        PaymentOption.grants_pathway_id == pathway.id,
        *((~PaymentOption.id.in_(own),) if own else ()),
    ).first()
    if foreign_grants_column:
        return (
            "Another Payment Option grants access to this pathway. "
            "Point that option somewhere else first."
        )

    # An option carrying our ``pathway_id`` but attached elsewhere. The
    # column is ``CASCADE``, so deleting the Pathway would delete that
    # option outright. Not expected — every other authoring surface sets
    # ``pathway_id=None`` explicitly — which is exactly why it refuses
    # rather than guessing.
    cross_attached = db.query(PaymentOption.id).filter(
        PaymentOption.pathway_id == pathway.id,
        PaymentOption.attaches_to_kind != PATHWAY_ATTACH_KIND,
    ).first()
    if cross_attached:
        return (
            "A Payment Option belonging to another part of this "
            "Collective is scoped to this pathway. Detach it first."
        )

    # ``included_with_offer`` wiring: which Options unlock this Pathway.
    # Rows naming one of our own options go with it (CASCADE); a row
    # naming somebody else's option is that option's promise to its
    # buyers.
    foreign_unlock = db.query(PathwayUnlockRequirement.id).filter(
        PathwayUnlockRequirement.pathway_id == pathway.id,
        *(
            (~PathwayUnlockRequirement.payment_option_id.in_(own),)
            if own else ()
        ),
    ).first()
    if foreign_unlock:
        return (
            "A Payment Option is configured to unlock this pathway. "
            "Remove that link first."
        )

    return _option_usage_reference(db, own)


def delete_owned_commerce_rows(db: "Session", pathway: "Pathway") -> int:
    """Remove the Payment Options this Pathway owns. Returns the count.

    Only ever called once :func:`blocking_reference` has returned
    ``None``, so by then every option attached to this Pathway is a
    draft or archived one it provisioned for itself, nothing has been
    through checkout on it, and no other option grants this Pathway.

    Deleting the option is enough and is also the only order that works:
    ``payment_option_grants``, ``payment_option_schedules`` and
    ``pathway_unlock_requirements`` all ``CASCADE`` from
    ``payment_options.id``, so the grant holding the RESTRICT on
    ``pathways.id`` goes with its option rather than needing its own
    delete.
    """
    from app.models.payment_option import PaymentOption

    options = (
        db.query(PaymentOption)
        .filter(
            PaymentOption.attaches_to_kind == PATHWAY_ATTACH_KIND,
            PaymentOption.attaches_to_id == pathway.id,
        )
        .all()
    )
    for option in options:
        db.delete(option)
    if options:
        # Flushed here so the CASCADE clears the grants before the
        # caller deletes the Pathway row they point at.
        db.flush()
        logger.info(
            "pathway_commerce: removed %d option(s) for pathway=%s",
            len(options), pathway.id,
        )
    return len(options)


# ---------------------------------------------------------------------------
# May this Option still be sold?
# ---------------------------------------------------------------------------


def granted_pathway_ids(db: "Session", option: "PaymentOption") -> set[str]:
    """Every Pathway this Option would hand over on purchase.

    All three pointers are read, because fulfilment reads all three:
    ``services.purchase_fulfilment`` resolves grant rows when the
    Option is grant-ready and falls back to the legacy
    ``attaches_to_*`` / ``grants_pathway_id`` pair when it is not. A
    guard that consulted only one of them would be bypassable by the
    other.
    """
    from app.models.payment_option_grant import (
        GRANT_KIND_PATHWAY,
        PaymentOptionGrant,
    )

    ids: set[str] = set()
    if option.attaches_to_kind == PATHWAY_ATTACH_KIND and option.attaches_to_id:
        ids.add(option.attaches_to_id)
    if option.grants_pathway_id:
        ids.add(option.grants_pathway_id)
    if option.pathway_id:
        ids.add(option.pathway_id)
    ids.update(
        row[0]
        for row in db.query(PaymentOptionGrant.pathway_id)
        .filter(
            PaymentOptionGrant.payment_option_id == option.id,
            PaymentOptionGrant.grant_kind == GRANT_KIND_PATHWAY,
            PaymentOptionGrant.pathway_id.isnot(None),
        )
        .all()
    )
    return ids


def grants_anything_but_pathways(db: "Session", option: "PaymentOption") -> bool:
    """Whether this Option also hands over a Series, Gathering or
    Offering — i.e. whether refusing it would cost the buyer something
    other than the Pathway in question."""
    from app.models.payment_option_grant import (
        GRANT_KIND_PATHWAY,
        PaymentOptionGrant,
    )

    other = (
        db.query(PaymentOptionGrant.id)
        .filter(
            PaymentOptionGrant.payment_option_id == option.id,
            PaymentOptionGrant.grant_kind != GRANT_KIND_PATHWAY,
        )
        .first()
    )
    if other is not None:
        return True
    # Legacy attachment: a Series-attached Option sells the Series even
    # when its only grant row is a bundled Pathway.
    return option.attaches_to_kind not in (PATHWAY_ATTACH_KIND, "space")


def unsellable_reason(db: "Session", option: "PaymentOption") -> str | None:
    """Why this Option may no longer be sold, or ``None``.

    Archiving a Pathway has to stop new purchases of it. There were two
    ways to do that and only one of them is reversible:

    **Archive the Pathway's Payment Options too.** This is what
    Offerings do — ``retire_offering`` calls ``offering_commerce.sync``,
    which archives the Option so "checkout refuses it". It works there
    because an Offering's Option is *auto-provisioned* and invisible:
    the creator never made it and cannot see it, so moving it is not
    acting on their behalf.

    A Pathway's Options are the opposite. They are authored by hand on
    the Pathway Settings page, which lists them with their own Publish
    and Archive buttons, and the platform's standing rule about them is
    explicit — ``delete_gathering_series`` refuses rather than archive,
    because "they belong to the Series and archiving them is a Creator
    choice, not an automatic side effect". Auto-archiving would also be
    a one-way door: restoring the Pathway would not un-archive the
    Options, so a creator undoing an archive would silently find their
    prices gone.

    **So the status is read at the door instead.** Nothing the creator
    authored is mutated, archiving and restoring are symmetrical, and
    the refusal is one sentence rather than a cascade.

    What is refused, and what deliberately is not
    ---------------------------------------------
    Only an Option whose *whole purpose* is archived Pathways:
    everything it grants is a Pathway, and every one of those is
    archived. A bundle that also includes a live Pathway, a Gathering
    Series or an Offering keeps selling — refusing it would take away
    access to things that are still on offer, which is the opposite of
    the instruction.

    The consequence of that line, stated rather than hidden: a creator
    who archives one Pathway out of a five-Pathway bundle is still
    selling that bundle, and a new buyer still receives an entitlement
    for the archived Pathway — which, under the archive access rule,
    still opens it. That is a deliberate creator arrangement rather
    than a leak (the Pathway is not discoverable, and the bundle says
    what it contains), and the Pathway Settings page already lists
    every Option that references the Pathway so the creator can see
    which ones to revisit.

    ``draft`` and ``coming_soon`` Pathways are **not** refused here.
    The legacy ``/api/checkout/pathway`` door refuses any non-active
    status, but the unified door never has, and a pre-sale of a
    coming-soon Pathway is a plausible deliberate arrangement rather
    than an obvious mistake. Narrowing this to ``archived`` keeps the
    change to what archiving means.
    """
    from app.models.platform import Pathway, PathwayStatus

    pathway_ids = granted_pathway_ids(db, option)
    if not pathway_ids:
        return None
    if grants_anything_but_pathways(db, option):
        return None

    rows = (
        db.query(Pathway.status)
        .filter(Pathway.id.in_(pathway_ids))
        .all()
    )
    if not rows:
        return None
    statuses = {str(getattr(r[0], "value", r[0])) for r in rows}
    if statuses != {PathwayStatus.archived.value}:
        return None
    return (
        "This pathway has been archived and is no longer available to "
        "buy. Members who already have access keep it."
    )


def check_sellable_or_raise(db: "Session", option: "PaymentOption") -> None:
    """HTTP form of :func:`unsellable_reason`, for the checkout doors.

    409 rather than 400: the request is well formed and was valid when
    the member was shown the price. What changed is the world — the
    same reasoning, and the same status code, as the discount-code
    revalidation a few lines further down the unified checkout.
    """
    from fastapi import HTTPException

    reason = unsellable_reason(db, option)
    if reason:
        raise HTTPException(status_code=409, detail=reason)


__all__ = [
    "PATHWAY_ATTACH_KIND",
    "blocking_reference",
    "check_sellable_or_raise",
    "delete_owned_commerce_rows",
    "granted_pathway_ids",
    "grants_anything_but_pathways",
    "owned_option_ids",
    "unsellable_reason",
]
