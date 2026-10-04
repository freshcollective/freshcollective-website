"""Has a creator published paid content?

Extracted verbatim from ``app.creator.routes._derived_has_paid_content``
so more than one caller can ask the question through the same
primitive — the same reason ``record_grant_event`` was lifted out of
``admin.routes``. ``creator.routes`` re-exports it under its old private
name, so existing callers and tests are unchanged.

The second helper here, :func:`creator_has_commercial_content`, spans a
creator's whole estate rather than one Collective. The complimentary-
grant expiry reconciler uses it to refuse to downgrade a creator who is
actively selling: Community forbids paid offers, and the platform has no
read-side plan gate that would retire existing paid content, so expiring
such a grant would either strand live checkouts or leave paid offers
purchasable on a plan that prohibits them. Both are worse than leaving
the grant in place for an admin to resolve deliberately.
"""

from __future__ import annotations

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption, PaymentOptionStatus
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Event, Pathway, Space


def derived_has_paid_content(space_id: str, db: Session) -> bool:
    """Has this creator published paid content inside this Collective?

    A **configuration** question, deliberately not the same one
    ``spaces.pathway_pricing.min_paid_price_cents_for_space`` answers:

    * public pricing helper — *what can a visitor buy right now, and at
      what headline price?* Depends on member checkoutability and
      therefore on ``finite_plan_member_checkout_enabled``.
    * this helper — *has the creator published paid content?* A
      Collective whose instalment plans are not yet offered to members
      still contains paid content, and the creator has still configured
      it.

    The distinction is load-bearing, not academic. The Creator Studio
    settings panel describes this as "Contains paid content inside this
    collective … also detected automatically when you publish a paid
    pathway", and uses it to gate the "What's included?" and "Paid
    separately" fields. Deriving it from member checkoutability would
    make a creator's own configuration flicker in and out of existence
    behind a platform feature flag they cannot see, taking their copy
    fields with it.

    What counts:

    * ``pricing_mode='legacy'`` → an active, paid-access Pathway with
      ``price_cents > 0``. Unchanged.
    * ``pricing_mode='payment_options'`` → an active Pathway with at
      least one **published, genuinely paid** Payment Option. The
      Pathway's own ``price_cents`` is ignored: it is the legacy column
      and is stale by design after the mode switch — reading it was the
      bug this replaces, which both claimed paid content for a price
      the creator had stopped selling at and denied it for a Pathway
      priced wholly through its Options.

    "Genuinely paid" means a positive price somewhere in the Option's
    configuration: its own ``override_total_cents`` /
    ``calculated_total_cents``, **or** a published schedule with a
    positive total. The Option columns are authoring fields and are
    routinely NULL on real Options, so they are one of two alternatives
    here rather than the only source. Schedule *shape* is not
    considered — a plan counts whether or not checkout would currently
    accept it.

    Draft and archived Pathways and Options do not count: nothing has
    been published. Nor do ``payment_type='free'`` Options.
    """
    from sqlalchemy import or_, select

    from app.models.payment_option import (
        PaymentOption,
        PaymentOptionStatus,
        PaymentOptionType,
    )
    from app.models.payment_option_schedule import PaymentOptionSchedule
    from app.models.platform import Pathway  # local import to avoid circular
    from app.services import pathway_payment_options

    _paid_access = ("one_time", "subscription")

    legacy_paid = (
        db.query(Pathway.id)
        .filter(
            Pathway.space_id == space_id,
            Pathway.status == "active",
            Pathway.access_type.in_(_paid_access),
            Pathway.pricing_mode == "legacy",
            Pathway.price_cents.isnot(None),
            Pathway.price_cents > 0,
        )
        .first()
    )
    if legacy_paid is not None:
        return True

    # A positive total on any published schedule of this Option. The
    # price of a finite plan lives here and nowhere else.
    priced_schedule = (
        select(PaymentOptionSchedule.id)
        .where(
            PaymentOptionSchedule.payment_option_id == PaymentOption.id,
            PaymentOptionSchedule.status == "published",
            PaymentOptionSchedule.total_amount_cents.isnot(None),
            PaymentOptionSchedule.total_amount_cents > 0,
        )
        .exists()
    )
    option_own_price = func.coalesce(
        PaymentOption.override_total_cents,
        PaymentOption.calculated_total_cents,
    )

    # Joined through the grant/legacy union, not ``PaymentOption.pathway_id``:
    # a grants-first Option has no ``pathway_id``, and most real ones
    # are grants-first. Reading the column alone would miss them.
    _pairs = pathway_payment_options.pathway_option_pairs()
    options_paid = (
        db.query(Pathway.id)
        .join(_pairs, _pairs.c.pathway_id == Pathway.id)
        .join(PaymentOption, PaymentOption.id == _pairs.c.payment_option_id)
        .filter(
            Pathway.space_id == space_id,
            Pathway.status == "active",
            Pathway.pricing_mode == "payment_options",
            PaymentOption.status == PaymentOptionStatus.published,
            PaymentOption.payment_type != PaymentOptionType.free,
            or_(option_own_price > 0, priced_schedule),
        )
        .first()
    )
    return options_paid is not None


def space_has_paid_gathering(space_id: str, db: Session) -> bool:
    """Does this Collective have a non-draft Gathering sold by ticket?

    Standalone paid Gatherings price themselves on ``Event`` rather than
    through a Pathway's Payment Options, so they are invisible to
    :func:`derived_has_paid_content`. Migration 080's CHECK guarantees a
    published ``paid_separately`` Event carries ``ticket_price_cents >
    0``, so a positive price is a reliable signal of commercial intent.
    """
    return db.query(
        exists().where(
            Event.space_id == space_id,
            Event.ticket_price_cents.is_not(None),
            Event.ticket_price_cents > 0,
            Event.status != "draft",
        )
    ).scalar() or False


def creator_has_commercial_content(user_id: str, db: Session) -> bool:
    """Is this creator selling anything, anywhere they create or manage?

    Scoped to Collectives the creator *owns* (``Space.creator_id``) and
    which are not archived — an archived Collective sells nothing, and a
    Collective someone else owns is that owner's commercial decision,
    governed by their plan rather than this creator's.

    Deliberately a configuration question, not a checkoutability one:
    it must not change with ``finite_plan_member_checkout_enabled`` or
    ``creator_plan_guard_enabled``, because the point is to detect that
    a creator has *set up* commerce, whichever way the platform flags
    currently route it.
    """
    space_ids = [
        row[0]
        for row in db.query(Space.id)
        .filter(Space.creator_id == user_id, Space.status != "archived")
        .all()
    ]
    for space_id in space_ids:
        if derived_has_paid_content(space_id, db):
            return True
        if space_has_paid_gathering(space_id, db):
            return True
    return False
