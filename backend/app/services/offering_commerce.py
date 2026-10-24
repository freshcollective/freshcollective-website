"""The commerce rows behind a paid Offering, and nothing else.

A creator picking "One-time purchase · $24" on the Pricing tab is
stating an intent. This module turns that intent into the rows the
platform's checkout already knows how to charge:

    Offering (pricing_kind='one_time', price_cents=2400)
        │
        ├─ PaymentOption      attaches_to_kind='offering'
        │     │               payment_type='one_time'
        │     │
        │     ├─ PaymentOptionSchedule   schedule_type='pay_in_full'
        │     │                          total_amount_cents=2400
        │     │
        │     └─ PaymentOptionGrant      grant_kind='offering'
        │                                offering_id=<the Offering>

Why go through Payment Options at all
-------------------------------------

Because the alternative is a second checkout. ``POST /api/checkout``
already resolves the option, revalidates the discount code, reserves
the code's slot, resolves the creator's fee basis points, picks the
Connect payout model, snapshots the fulfilment intent *before*
contacting Stripe, creates the Session, writes the ledger row, and
hands the webhook everything it needs to be idempotent under
re-delivery. Every one of those is load-bearing and none of it is
Offering-specific.

So the Offering is the product and the Payment Option is the price
tag. The creator never sees or manages the tag — they manage the
Offering — which is why these rows are **derived** rather than
authored, and why ``sync`` below is written to converge rather than to
assume what it will find.

The Offering stays the source of truth
--------------------------------------

``offerings.pricing_kind`` / ``price_cents`` remain authoritative.
These rows are a projection of them. That direction matters in two
places:

  * A creator editing a price edits the Offering; this module then
    moves the schedule to match. Nothing reads the price back off the
    schedule to display it.
  * If the projection is ever missing or stale, the fix is to re-run
    ``sync`` — never to hand-edit a Payment Option. The Offering
    cannot be wrong about its own price.

Free Offerings get no rows at all
---------------------------------

A free acquisition does not go through checkout (see
``services.offering_acquisition``), so provisioning an option for it
would create commerce rows that nothing charges, a zero-value ledger
entry for every download, and a second place for "is this free?" to be
answered. ``sync`` archives any option it finds on an Offering that
has become free.

Hidden from the Payment Options panel
-------------------------------------

``creator._space_payment_options_routes`` filters these out. A creator
opening Commerce → Payment Options must not find a row they did not
create, cannot meaningfully edit, and could archive — which would stop
their Offering selling with no indication why. The Offering's own
Pricing tab is the one place its price is managed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import true as sa_true
from sqlalchemy.orm import Session

from app.models.offering import Offering, OfferingPricingKind, OfferingStatus
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import (
    GRANT_KIND_OFFERING,
    PaymentOptionGrant,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Space
from app.services.purchase_fulfilment import OFFERING_ATTACHES_KIND

logger = logging.getLogger(__name__)

#: What the member sees on the Stripe page as the schedule name. The
#: Offering's own title becomes the Stripe line item (see
#: ``checkout.routes.create_offering_checkout_session``), so this stays
#: generic rather than duplicating the title into a second place that
#: would then go stale when the creator renames the Offering.
SCHEDULE_NAME = "One-time purchase"


@dataclass(frozen=True)
class CommerceRows:
    """What ``sync`` converged on."""

    payment_option: PaymentOption | None
    payment_schedule: PaymentOptionSchedule | None
    #: True when this call created, re-published or re-priced something.
    changed: bool = False

    @property
    def sellable(self) -> bool:
        """Whether a paid checkout could resolve these rows right now."""
        if self.payment_option is None or self.payment_schedule is None:
            return False
        status = (
            self.payment_option.status.value
            if hasattr(self.payment_option.status, "value")
            else str(self.payment_option.status)
        )
        return (
            status == PaymentOptionStatus.published.value
            and self.payment_schedule.status == "published"
        )


def find_option(db: Session, offering: Offering) -> PaymentOption | None:
    """The Payment Option selling this Offering, if one exists.

    Found through the grant rather than through ``attaches_to_id``,
    because the grant is what fulfilment reads. Looking it up any other
    way could return an option that would not actually grant the
    Offering on purchase.
    """
    row = (
        db.query(PaymentOption)
        .join(
            PaymentOptionGrant,
            PaymentOptionGrant.payment_option_id == PaymentOption.id,
        )
        .filter(
            PaymentOptionGrant.grant_kind == GRANT_KIND_OFFERING,
            PaymentOptionGrant.offering_id == offering.id,
        )
        .order_by(PaymentOption.created_at)
        .first()
    )
    return row


def pay_in_full_schedule(
    db: Session, option: PaymentOption,
) -> PaymentOptionSchedule | None:
    return (
        db.query(PaymentOptionSchedule)
        .filter(
            PaymentOptionSchedule.payment_option_id == option.id,
            PaymentOptionSchedule.schedule_type == "pay_in_full",
        )
        .order_by(PaymentOptionSchedule.created_at)
        .first()
    )


def sync(
    db: Session, *, offering: Offering, space: Space,
    now: datetime | None = None,
) -> CommerceRows:
    """Make the commerce rows match the Offering. Idempotent.

    Writes into the caller's session without committing — the caller
    owns the transaction, so provisioning lands with the publish (or
    the price change) or not at all.

    The four cases, all reachable by ordinary creator editing:

    ``paid + published``
        Ensure an option, a pay-in-full schedule and a grant exist,
        are published, and carry the current price.

    ``paid + draft``
        Ensure the rows exist but leave them **draft**. A draft
        Offering must not be purchasable even by someone who guessed
        the option id, and ``resolve_option_and_schedule`` refuses a
        non-published option with a 400. Provisioning early rather than
        at publish means publish is a status flip rather than a
        multi-row insert, which is one less thing to go wrong at the
        moment a creator is watching.

    ``paid + retired``
        Archive. Retirement stops new sales and changes nothing about
        existing ownership — the entitlement rows are not touched here
        and download authorisation never consults Offering status.

    ``free`` (any status)
        Archive anything that exists. A price tag on a free thing is
        the kind of contradiction that eventually charges somebody.

    Archiving rather than deleting, always: an option that has taken a
    payment is referenced by ``payment_transactions.payment_option_id``,
    and deleting it would detach a member's receipt from what they
    bought.
    """
    now = now or datetime.utcnow()
    option = find_option(db, offering)
    is_paid = offering.pricing_kind == OfferingPricingKind.one_time.value
    status = offering.status

    # ── Not sellable: free, or retired ────────────────────────────────
    if not is_paid or status == OfferingStatus.retired.value:
        if option is None:
            return CommerceRows(None, None)
        changed = _archive(db, option, now=now)
        if changed:
            logger.info(
                "offering_commerce: archived option=%s offering=%s reason=%s",
                option.id, offering.id,
                "retired" if status == OfferingStatus.retired.value else "free",
            )
        return CommerceRows(option, pay_in_full_schedule(db, option), changed)

    # ── Sellable: paid, draft or published ────────────────────────────
    price = int(offering.price_cents or 0)
    if price <= 0:
        # ``ck_offerings_pricing_shape`` makes this unreachable through
        # the API, and a positive price is what the schedule must carry.
        # Refusing beats provisioning a zero-price paid option, which
        # would send a buyer to the free path and hand over the files.
        raise ValueError(
            f"Offering {offering.id!r} is one_time but has no positive "
            f"price ({offering.price_cents!r}); refusing to provision."
        )

    target_status = (
        PaymentOptionStatus.published.value
        if status == OfferingStatus.published.value
        else PaymentOptionStatus.draft.value
    )
    changed = False

    if option is None:
        option = PaymentOption(
            id=str(uuid4()),
            space_id=space.id,
            attaches_to_kind=OFFERING_ATTACHES_KIND,
            attaches_to_id=offering.id,
            # The member-facing name on the Stripe page and in the
            # creator's Payments received list. The Offering's title at
            # the moment of provisioning; kept in step by ``sync``.
            name=_option_name(offering),
            payment_type=PaymentOptionType.one_time,
            status=target_status,
            currency=_currency(space),
            override_total_cents=price,
            # Never a joining door. ``list_joining_doors`` filters on
            # this, so leaving it false is what keeps an Offering out of
            # the Collective's About page "ways in" list.
            is_joining_option=False,
            position=0,
            created_at=now,
            updated_at=now,
        )
        db.add(option)
        db.flush()
        db.add(PaymentOptionGrant(
            id=str(uuid4()),
            payment_option_id=option.id,
            grant_kind=GRANT_KIND_OFFERING,
            offering_id=offering.id,
            position=0,
            created_at=now,
            updated_at=now,
        ))
        db.flush()
        changed = True
        logger.info(
            "offering_commerce: provisioned option=%s offering=%s price=%s %s",
            option.id, offering.id, price, target_status,
        )

    # Converge the option. Each field is compared before assignment so
    # a no-op sync does not dirty the row and flush a pointless UPDATE —
    # ``sync`` runs on every publish and every price edit.
    if _status_of(option) != target_status:
        option.status = target_status
        option.updated_at = now
        changed = True
    if option.override_total_cents != price:
        option.override_total_cents = price
        option.updated_at = now
        changed = True
    wanted_name = _option_name(offering)
    if option.name != wanted_name:
        option.name = wanted_name
        option.updated_at = now
        changed = True
    if option.attaches_to_id != offering.id:
        # Defensive: a grant pointing here while ``attaches_to_id``
        # points elsewhere would make the two disagree about what is
        # being sold.
        option.attaches_to_id = offering.id
        option.updated_at = now
        changed = True

    # Converge the schedule.
    schedule = pay_in_full_schedule(db, option)
    if schedule is None:
        schedule = PaymentOptionSchedule(
            id=str(uuid4()),
            payment_option_id=option.id,
            name=SCHEDULE_NAME,
            schedule_type="pay_in_full",
            status=target_status,
            total_amount_cents=price,
            currency=_currency(space),
            position=0,
            created_at=now,
            updated_at=now,
        )
        db.add(schedule)
        db.flush()
        changed = True
    else:
        if schedule.total_amount_cents != price:
            schedule.total_amount_cents = price
            schedule.updated_at = now
            changed = True
        if schedule.status != target_status:
            schedule.status = target_status
            schedule.updated_at = now
            changed = True

    # A grant can be missing on a row provisioned before this module
    # existed, or if one was deleted by hand. Without it the fulfilment
    # dispatcher refuses the purchase outright — correct, but better
    # repaired here than surfaced to a buyer.
    grant_exists = (
        db.query(PaymentOptionGrant.id)
        .filter(
            PaymentOptionGrant.payment_option_id == option.id,
            PaymentOptionGrant.grant_kind == GRANT_KIND_OFFERING,
            PaymentOptionGrant.offering_id == offering.id,
        )
        .first()
    ) is not None
    if not grant_exists:
        db.add(PaymentOptionGrant(
            id=str(uuid4()),
            payment_option_id=option.id,
            grant_kind=GRANT_KIND_OFFERING,
            offering_id=offering.id,
            position=0,
            created_at=now,
            updated_at=now,
        ))
        db.flush()
        changed = True
        logger.warning(
            "offering_commerce: repaired missing offering grant on "
            "option=%s offering=%s", option.id, offering.id,
        )

    return CommerceRows(option, schedule, changed)


def _option_name(offering: Offering) -> str:
    # Capped to the column width. Truncated rather than refused: a long
    # title must not be able to stop an Offering being sold.
    return (offering.title or "Offering")[:200]


def _currency(space: Space) -> str:
    return (getattr(space, "currency", None) or "AUD").upper()


def _status_of(option: PaymentOption) -> str:
    return (
        option.status.value
        if hasattr(option.status, "value") else str(option.status)
    )


def _archive(db: Session, option: PaymentOption, *, now: datetime) -> bool:
    """Archive the option and its schedules. Returns True if anything
    moved, so a repeat call is a silent no-op."""
    changed = False
    if _status_of(option) != PaymentOptionStatus.archived.value:
        option.status = PaymentOptionStatus.archived.value
        option.updated_at = now
        changed = True
    for sched in (
        db.query(PaymentOptionSchedule)
        .filter(PaymentOptionSchedule.payment_option_id == option.id)
        .all()
    ):
        if sched.status != "archived":
            sched.status = "archived"
            sched.updated_at = now
            changed = True
    return changed


__all__ = [
    "CommerceRows",
    "OFFERING_ATTACHES_KIND",
    "SCHEDULE_NAME",
    "find_option",
    "pay_in_full_schedule",
    "sync",
]


def blocking_commerce_reference(db: Session, offering: Offering) -> str | None:
    """Why another product's commerce rows forbid deleting this
    Offering, or ``None``.

    Lives here because this module owns the Offering ↔ PaymentOption
    relationship, and ``_offering_routes`` is deliberately kept clear
    of payment imports — a boundary two tests enforce by name.

    What counts as a blocker, and what does not
    -------------------------------------------

    A **paid draft already has commerce rows**. ``sync`` provisions the
    option, its grant and its schedule as soon as a price is set, in
    ``draft`` status, so that publishing is a status flip rather than a
    creation. Those rows exist only to serve this Offering and nobody
    else can reach them, so they are **not** blockers — they are part
    of what gets deleted. Treating them as blockers made every paid
    draft undeletable, with a message telling the creator to archive an
    option they never created and cannot see.

    Two things genuinely do block:

    * **A published option.** It is sellable right now. This cannot
      happen for a deletable Offering — a published option means a
      published Offering, which ``published_at`` already refuses — so
      it is defence in depth against a future path that publishes an
      option without publishing its Offering.

    * **A grant held by some OTHER option.** ``grant_kind='offering'``
      lets any option grant any Offering, so a bundle could include
      this one. Deleting it would break that bundle, and
      ``payment_option_grants.offering_id`` is ``ondelete=RESTRICT``,
      so the database would refuse the delete as a 500 that explains
      nothing. This turns it into a sentence a creator can act on.
    """
    own_option_ids = [
        row[0] for row in (
            db.query(PaymentOption.id)
            .filter(
                PaymentOption.attaches_to_kind == OFFERING_ATTACHES_KIND,
                PaymentOption.attaches_to_id == offering.id,
            )
            .all()
        )
    ]

    published = (
        db.query(PaymentOption.id)
        .filter(
            PaymentOption.attaches_to_kind == OFFERING_ATTACHES_KIND,
            PaymentOption.attaches_to_id == offering.id,
            PaymentOption.status == PaymentOptionStatus.published,
        )
        .first()
    )
    if published:
        return (
            "This Offering is on sale through a published Payment "
            "Option. Retire it instead."
        )

    foreign_grant = db.query(PaymentOptionGrant.id).filter(
        PaymentOptionGrant.offering_id == offering.id,
        ~PaymentOptionGrant.payment_option_id.in_(own_option_ids)
        if own_option_ids else sa_true(),
    ).first()
    if foreign_grant:
        return (
            "Another Payment Option includes this Offering. Remove it "
            "from that option first."
        )
    return None


def delete_commerce_rows(db: Session, offering: Offering) -> int:
    """Remove the commerce rows this Offering owns. Returns the count.

    Only ever called after :func:`blocking_commerce_reference` has
    returned ``None``, so by then the only options attached to this
    Offering are draft or archived ones it provisioned for itself, and
    no other option grants it.

    Deleting the option is enough: ``payment_option_grants`` and
    ``payment_option_schedules`` both carry ``ondelete=CASCADE`` from
    ``payment_options.id``, so the grant that holds the RESTRICT on
    ``offerings.id`` goes with its option rather than needing its own
    delete — which is also the order that satisfies the RESTRICT.
    """
    options = (
        db.query(PaymentOption)
        .filter(
            PaymentOption.attaches_to_kind == OFFERING_ATTACHES_KIND,
            PaymentOption.attaches_to_id == offering.id,
        )
        .all()
    )
    for option in options:
        db.delete(option)
    if options:
        # Flushed here so the CASCADE clears the grants before the
        # caller deletes the Offering row they point at.
        db.flush()
        logger.info(
            "offering_commerce: removed %d option(s) for offering=%s",
            len(options), offering.id,
        )
    return len(options)
