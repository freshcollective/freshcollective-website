"""Payment Options can grant an Offering.

Revision ID: 162
Revises: 161
Create Date: 2026-10-21

Offerings Phase C/D. One column on ``payment_option_grants``, one
widened CHECK, two indexes. This is the migration migration 160
deferred:

    ``payment_option_grants`` has no ``offering_id`` column and no
    ``offering`` grant kind yet — both are deferred to Phase D by
    approval, because adding them means altering a live commerce
    CHECK constraint.

That is now done, and this file is the whole of it.

Why an Offering becomes a grant rather than its own checkout
------------------------------------------------------------

A paid Offering is a one-time purchase of a thing inside a Collective,
which is precisely what ``PaymentOption`` + ``PaymentOptionGrant``
already models for Pathways and Gathering Series. Routing Offerings
through the same pair means they inherit — unchanged and untested-by-
us — the Stripe Connect routing, the platform fee arithmetic, the
discount-code reservation ladder, the mandatory fulfilment snapshot,
the duplicate-webhook idempotency and the refund bookkeeping.

The alternative was a second checkout path beside the first. On the
most financially consequential code in the platform, a parallel
implementation is the more expensive choice however small it starts.

The one altered constraint, and why it is safe
----------------------------------------------

``payment_option_grants_target_matches_kind`` is dropped and recreated
with a fourth branch. It is a live commerce constraint, so:

  * The change is a **widening**. Every row that satisfied the old
    predicate satisfies the new one — the three existing branches are
    reproduced verbatim and a fourth is added. No existing row can be
    invalidated, so the recreate cannot fail on live data.
  * Postgres validates the new constraint against the table as it is
    added. If any row did somehow fail it, this migration aborts and
    the transaction rolls back, leaving the old constraint in place.
    The failure mode is "deploy stops", never "constraint quietly
    missing".
  * ``offering_id`` is added nullable with no default, so the column
    add rewrites nothing.

The two constraints NOT touched, deliberately
---------------------------------------------

``payment_option_grants_credits_only_for_series`` reads
``(grant_kind = 'event_series') OR (sessions_per_week IS NULL AND
total_sessions IS NULL)``. An ``offering`` grant therefore must carry
no session credits, which is correct — an Offering is a file, not a
booking allowance — and needs no change to say so.

``payment_option_grants_windows_not_on_gathering`` reads
``(grant_kind IN ('event_series', 'pathway')) OR (valid_from_override
IS NULL AND valid_until_override IS NULL)``. An ``offering`` grant
therefore must carry no window, which is the single most important
property of Offering ownership: **you keep it**. Access does not
expire, is not tied to a term, and survives leaving the Collective,
the Offering being retired and the creator changing plans. Expressing
that as "the window columns cannot be populated" puts the rule in the
database rather than in a comment.

Its *name* now reads a little oddly — it forbids windows on two kinds,
not just gatherings. Renaming a live constraint to improve its prose
is churn on a commerce table for no behavioural gain, so the name
stays and this paragraph is the explanation.

Existing data
-------------

Production holds zero ``offerings`` rows, so no grant can reference one
and no backfill is possible or needed. ``offering_id`` starts NULL
everywhere, which every branch of the widened CHECK permits for the
three pre-existing kinds.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "162"
down_revision = "161"
branch_labels = None
depends_on = None


#: The pre-existing predicate, reproduced exactly so the downgrade
#: restores what was there rather than something equivalent-looking.
_TARGET_MATCHES_KIND_V1 = (
    "(grant_kind = 'pathway'      AND pathway_id IS NOT NULL "
    "  AND series_id IS NULL AND event_id IS NULL)"
    " OR (grant_kind = 'event_series' AND series_id IS NOT NULL "
    "  AND pathway_id IS NULL AND event_id IS NULL)"
    " OR (grant_kind = 'gathering'    AND event_id IS NOT NULL "
    "  AND pathway_id IS NULL AND series_id IS NULL)"
)

#: The same three branches, each extended with ``offering_id IS NULL``,
#: plus a fourth for the new kind. Written out rather than composed from
#: the old string so the whole invariant is readable in one place.
_TARGET_MATCHES_KIND_V2 = (
    "(grant_kind = 'pathway'      AND pathway_id IS NOT NULL "
    "  AND series_id IS NULL AND event_id IS NULL AND offering_id IS NULL)"
    " OR (grant_kind = 'event_series' AND series_id IS NOT NULL "
    "  AND pathway_id IS NULL AND event_id IS NULL AND offering_id IS NULL)"
    " OR (grant_kind = 'gathering'    AND event_id IS NOT NULL "
    "  AND pathway_id IS NULL AND series_id IS NULL AND offering_id IS NULL)"
    " OR (grant_kind = 'offering'     AND offering_id IS NOT NULL "
    "  AND pathway_id IS NULL AND series_id IS NULL AND event_id IS NULL)"
)


def upgrade() -> None:
    op.add_column(
        "payment_option_grants",
        sa.Column("offering_id", sa.String(), nullable=True),
    )
    # RESTRICT, matching the three sibling targets: an Offering that a
    # Payment Option still grants cannot be hard-deleted out from under
    # it. Offerings are never hard-deleted once anyone owns one, so this
    # is a backstop rather than a workflow.
    op.create_foreign_key(
        "fk_payment_option_grants_offering",
        "payment_option_grants",
        "offerings",
        ["offering_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "payment_option_grants_target_matches_kind",
        "payment_option_grants",
        type_="check",
    )
    op.create_check_constraint(
        "payment_option_grants_target_matches_kind",
        "payment_option_grants",
        _TARGET_MATCHES_KIND_V2,
    )

    # One Option must not grant the same Offering twice. Partial because
    # the column is nullable — same shape as the three sibling indexes.
    op.create_index(
        "uq_payment_option_grants_option_offering",
        "payment_option_grants",
        ["payment_option_id", "offering_id"],
        unique=True,
        postgresql_where=sa.text("offering_id IS NOT NULL"),
    )
    # Reverse lookup: "which Option sells this Offering?" — asked on
    # every paid Offering page render and every price change.
    op.create_index(
        "ix_payment_option_grants_offering",
        "payment_option_grants",
        ["offering_id"],
        postgresql_where=sa.text("offering_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Offering grants must go before the column can. A downgrade with
    # live Offering commerce would otherwise fail on the FK, which is
    # the right outcome but an opaque one — so delete the rows this
    # migration made possible, and only those.
    op.execute(
        "DELETE FROM payment_option_grants WHERE grant_kind = 'offering'"
    )

    op.drop_index(
        "ix_payment_option_grants_offering", "payment_option_grants",
    )
    op.drop_index(
        "uq_payment_option_grants_option_offering", "payment_option_grants",
    )

    op.drop_constraint(
        "payment_option_grants_target_matches_kind",
        "payment_option_grants",
        type_="check",
    )
    op.create_check_constraint(
        "payment_option_grants_target_matches_kind",
        "payment_option_grants",
        _TARGET_MATCHES_KIND_V1,
    )

    op.drop_constraint(
        "fk_payment_option_grants_offering",
        "payment_option_grants",
        type_="foreignkey",
    )
    op.drop_column("payment_option_grants", "offering_id")
