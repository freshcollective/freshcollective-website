"""Which Payment Options sell a Pathway.

One answer, because there were three and they disagreed.

Grants-first authoring
----------------------
A Payment Option used to belong to exactly one Pathway through
``PaymentOption.pathway_id``. Since the grants model (migration 108) an
Option sells whatever its ``PaymentOptionGrant`` rows say it sells —
possibly several Pathways, possibly a Series as well — and an Option
authored through the Payment Options editor leaves ``pathway_id`` NULL
because there is no single Pathway to put there.

Every member-facing read still asked the old question. A Pathway whose
only Option was linked by a grant therefore showed no options and no
price, and checkout refused the Option as "not available for this
pathway" even when the member managed to name it. The Option existed,
was published, had a published schedule, and was invisible.

Both links count. ``pathway_id`` is still populated on rows authored
through the legacy Pathway editor, and those Pathways must keep
selling, so this module answers "grant **or** legacy column" everywhere
rather than migrating one into the other.

What this module does not decide
--------------------------------
Nothing about price, schedules, or whether a given schedule is
checkoutable — ``_schedule_is_member_checkoutable`` still owns that.
This answers association only.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption
from app.models.payment_option_grant import PaymentOptionGrant

#: ``PaymentOptionGrant.grant_kind`` for a Pathway grant.
GRANT_KIND_PATHWAY = "pathway"


def pathway_option_pairs():
    """A selectable of ``(pathway_id, payment_option_id)``.

    For joining across many Pathways at once — the "from" price on the
    Collective list, for instance. Unions the grant rows with the legacy
    column so a Pathway linked either way appears exactly once per
    Option.
    """
    granted = select(
        PaymentOptionGrant.pathway_id.label("pathway_id"),
        PaymentOptionGrant.payment_option_id.label("payment_option_id"),
    ).where(
        PaymentOptionGrant.grant_kind == GRANT_KIND_PATHWAY,
        PaymentOptionGrant.pathway_id.isnot(None),
    )
    legacy = select(
        PaymentOption.pathway_id.label("pathway_id"),
        PaymentOption.id.label("payment_option_id"),
    ).where(PaymentOption.pathway_id.isnot(None))
    return granted.union(legacy).subquery()


def published_options_for_pathway(
    db: Session, pathway_id: str,
) -> list[PaymentOption]:
    """Published Options that sell this Pathway, in display order.

    Status is filtered here rather than by the caller because every
    member-facing caller wants the same thing, and a surface that
    accidentally showed a draft Option would be advertising a price
    nobody can pay.
    """
    granted_ids = select(PaymentOptionGrant.payment_option_id).where(
        PaymentOptionGrant.grant_kind == GRANT_KIND_PATHWAY,
        PaymentOptionGrant.pathway_id == pathway_id,
    )
    return (
        db.query(PaymentOption)
        .filter(
            PaymentOption.status == "published",
            or_(
                PaymentOption.pathway_id == pathway_id,
                PaymentOption.id.in_(granted_ids),
            ),
        )
        .order_by(PaymentOption.position)
        .all()
    )


def option_sells_pathway(
    db: Session, *, option: PaymentOption, pathway_id: str,
) -> bool:
    """Whether this Option may be bought for this Pathway.

    The authorisation half of the same question: it stops a member
    naming an Option that belongs to a different Collective's Pathway.
    Says nothing about the Option's status — callers that care check it,
    and the shared resolver already refuses an unpublished one.
    """
    if option is None:
        return False
    if option.pathway_id == pathway_id:
        return True
    return db.query(
        select(PaymentOptionGrant.id)
        .where(
            PaymentOptionGrant.payment_option_id == option.id,
            PaymentOptionGrant.grant_kind == GRANT_KIND_PATHWAY,
            PaymentOptionGrant.pathway_id == pathway_id,
        )
        .exists()
    ).scalar()
