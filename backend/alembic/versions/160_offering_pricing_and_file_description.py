"""Offerings carry pricing intent, and files carry a description.

Revision ID: 160
Revises: 159
Create Date: 2026-10-18

Offerings Phase B4. Two columns on ``offerings``, one on
``offering_files``, and two CHECK constraints. Additive: nothing
altered, nothing dropped, no data moved, ``offer_pages`` untouched.

Pricing *intent*, not a Payment Option
--------------------------------------

The creator picks Free or One-time purchase and, for the latter, a
price. That choice is stored here rather than being turned into a
``PaymentOption`` with an Offering grant, and the reason is sequencing:
``payment_option_grants`` has no ``offering_id`` column and no
``offering`` grant kind yet — both are deferred to Phase D by approval,
because adding them means altering a live commerce CHECK constraint.

Creating a Payment Option now would therefore mean writing a commerce
row that nothing can fulfil, in production, months before checkout
exists. Storing the intent keeps the creator's decision durable and
leaves provisioning to the phase that can actually honour it.

``pricing_kind`` is a string with a CHECK rather than a PostgreSQL
enum, matching ``offerings.status`` and ``payment_option_grants
.grant_kind``: a future kind (a payment plan, a pay-what-you-feel
option) widens a CHECK instead of migrating an enum.

The constraint that keeps the two columns honest
------------------------------------------------

``ck_offerings_pricing_shape`` ties them together so the pair cannot
contradict itself:

  * ``free``     → ``price_cents`` must be NULL or 0.
  * ``one_time`` → ``price_cents`` must be a positive integer.
  * NULL kind    → ``price_cents`` must be NULL (a draft that has not
                   reached the Pricing tab yet).

Without it, a free Offering could carry a price nobody charges, or a
paid one could carry none — and the publication check would be the only
thing standing between that and a member seeing it. Two guards are
better than one when the failure is a wrong price.

File descriptions
-----------------

``offering_files.description`` is optional and capped at 300
characters: a sentence explaining one resource ("A 15-minute guided
audio practice"), not a second body of rich text. Length-limited in
the column rather than only in a schema so the ceiling holds whatever
writes the row.

Existing data
-------------

Production holds zero ``offerings`` and zero ``offering_files`` rows —
both tables arrived empty and no creator endpoint exists yet — so every
default here backfills nothing. The nullable ``pricing_kind`` is also
the correct state for a draft that has not been priced, so even with
rows it would have been right.

Compatibility
-------------

The old application version does not know these columns exist and never
reads them. Either deploy order is safe. ``downgrade`` drops the
constraints and the three columns.
"""

from alembic import op
import sqlalchemy as sa


revision = "160"
down_revision = "159"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── offerings: pricing intent ─────────────────────────────────────
    op.add_column(
        "offerings",
        sa.Column("pricing_kind", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "offerings",
        sa.Column("price_cents", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_offerings_pricing_kind",
        "offerings",
        "pricing_kind IS NULL OR pricing_kind IN ('free', 'one_time')",
    )
    # The pair cannot contradict itself. See the module docstring.
    op.create_check_constraint(
        "ck_offerings_pricing_shape",
        "offerings",
        "(pricing_kind IS NULL AND price_cents IS NULL)"
        " OR (pricing_kind = 'free' AND (price_cents IS NULL OR price_cents = 0))"
        " OR (pricing_kind = 'one_time' AND price_cents IS NOT NULL"
        "     AND price_cents > 0)",
    )

    # ── offering_files: optional per-file description ──────────────────
    op.add_column(
        "offering_files",
        sa.Column("description", sa.String(length=300), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("offering_files", "description")
    op.drop_constraint(
        "ck_offerings_pricing_shape", "offerings", type_="check",
    )
    op.drop_constraint(
        "ck_offerings_pricing_kind", "offerings", type_="check",
    )
    op.drop_column("offerings", "price_cents")
    op.drop_column("offerings", "pricing_kind")
