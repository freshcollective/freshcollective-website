"""Pathway.direct_purchase_enabled — is the direct price an active offer?

Revision ID: 183
Revises: 182
Create Date: 2026-11-07

Stage 2B needs to tell two states apart that the schema currently
conflates:

  * a Pathway whose own price is on sale, and
  * a Pathway that *has* a price nobody may pay.

Today the difference is read off ``pricing_mode``: ``legacy`` sells
``price_cents``, ``payment_options`` refuses it at the till. That works
only while the two are mutually exclusive, which is exactly the
assumption Stage 2B removes — a Pathway may legitimately be sold both
individually and through a Payment Option at the same time.

Inferring the direct offer from the leftover columns is not an option.
When a published Option grants a Pathway, ``_sync_pathway_pricing_mode``
moves ``pricing_mode`` and deliberately leaves ``access_type`` and
``price_cents`` alone — production's Test Pathway still carries
``access_type='one_time'`` and ``price_cents=500`` beside a published
$2 Option. So "has a one_time access type and a positive price" is true
of every Pathway that was ever sold directly, including those whose
direct price the creator stopped intending to charge. Treating that as
an active offer would put dormant prices back on sale the moment the
Stage 2B flag was enabled, which is the one thing §13 forbids.

So the fact is stored rather than guessed. The backfill is written to
preserve current behaviour exactly: a Pathway selling directly today
gets ``true``, and every other row — including every Pathway whose
direct price is currently dormant behind ``payment_options`` — gets
``false``.

Rollback: dropping the column returns every consumer to
``pricing_mode``, which this migration does not touch. No price,
transaction or entitlement is read or written here.
"""
from alembic import op
import sqlalchemy as sa


revision = "183"
down_revision = "182"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``server_default='false'`` so existing rows land dormant and any
    # row written by code that predates this column is dormant too —
    # the safe direction. The backfill below then switches on only the
    # rows that are genuinely selling today.
    op.add_column(
        "pathways",
        sa.Column(
            "direct_purchase_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Behaviour-preserving backfill.
    #
    # These are precisely the Pathways the option-less checkout door
    # sells right now: ``POST /api/checkout/pathway`` refuses
    # ``pricing_mode='payment_options'``, refuses any access_type but
    # ``one_time``, and refuses a null or non-positive price. Mirroring
    # those three conditions means no Pathway changes what it does on
    # the day this ships.
    #
    # ``status`` is deliberately NOT part of the backfill. A draft or
    # archived Pathway is refused by the status guard at the door, and
    # that guard still runs; writing ``false`` here instead would mean a
    # creator publishing a previously-drafted priced Pathway found its
    # price silently off sale.
    op.execute(
        """
        UPDATE pathways
           SET direct_purchase_enabled = true
         WHERE pricing_mode = 'legacy'
           AND access_type = 'one_time'
           AND price_cents IS NOT NULL
           AND price_cents > 0
        """
    )


def downgrade() -> None:
    op.drop_column("pathways", "direct_purchase_enabled")
