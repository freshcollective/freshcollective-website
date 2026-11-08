"""Stage 4 — let a discount reservation describe a direct purchase.

Before this, a reservation could only name a Payment Option purchase:
``payment_option_id`` and ``payment_option_schedule_id`` were both NOT
NULL, and migration 140 relied on that — "All four are NOT NULL, so the
partial unique index cannot be evaded by a null". That property is what
makes a retry find its own hold instead of being told the code is full.

A direct Pathway purchase, a standalone Gathering ticket and a direct
Offering have no Payment Option at all, so they cannot be described by
those columns, and a Collective-wide code cannot hold a slot for them.

The shape added here keeps the old guarantee and adds a second one
beside it:

``target_kind``
    Which door the purchase came through. NOT NULL with a server default
    of ``payment_option``, so every existing row reads as exactly what
    it is and no backfill is needed.

``target_id``
    The Pathway or Gathering being bought directly. NULL for a Payment
    Option purchase.

The two Payment Option columns become nullable, and a CHECK makes the
two shapes exclusive: a Payment Option reservation names an option and a
schedule and no target; a direct reservation names a target and neither
of those. So "not evadable by a null" still holds — each shape's
identity columns are mandatory *for that shape*, enforced by the CHECK
rather than by NOT NULL.

Two partial unique indexes rather than one, for the same reason. The
existing index is narrowed to Payment Option rows (it would otherwise
stop constraining anything, because Postgres treats NULLs in a unique
index as distinct), and a sibling covers direct rows.

Additive and reversible. No existing row changes value, no established
purchase is touched, and with ``universal_discount_codes_enabled`` off
nothing ever writes a direct-shaped row.

Revision ID: 186
Revises: 185
"""

from alembic import op
import sqlalchemy as sa

revision = "186"
down_revision = "185"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discount_reservations",
        sa.Column(
            "target_kind", sa.String(length=20), nullable=False,
            server_default="payment_option",
        ),
    )
    op.add_column(
        "discount_reservations",
        sa.Column("target_id", sa.String(), nullable=True),
    )

    op.alter_column(
        "discount_reservations", "payment_option_id",
        existing_type=sa.String(), nullable=True,
    )
    op.alter_column(
        "discount_reservations", "payment_option_schedule_id",
        existing_type=sa.String(), nullable=True,
    )

    op.create_check_constraint(
        "ck_discount_reservations_target_kind",
        "discount_reservations",
        "target_kind IN ('payment_option', 'pathway', 'gathering')",
    )
    # The two shapes, exclusively. This is what replaces the NOT NULLs:
    # a reservation must fully describe exactly one kind of purchase.
    op.create_check_constraint(
        "ck_discount_reservations_target_shape",
        "discount_reservations",
        "(target_kind = 'payment_option'"
        "  AND payment_option_id IS NOT NULL"
        "  AND payment_option_schedule_id IS NOT NULL"
        "  AND target_id IS NULL)"
        " OR (target_kind IN ('pathway', 'gathering')"
        "  AND target_id IS NOT NULL"
        "  AND payment_option_id IS NULL"
        "  AND payment_option_schedule_id IS NULL)",
    )

    # Narrow the existing identity index to the shape it describes. With
    # the columns now nullable it would otherwise admit any number of
    # direct rows, because NULLs compare as distinct in a unique index.
    op.drop_index(
        "uq_discount_reservations_held_attempt",
        table_name="discount_reservations",
    )
    op.create_index(
        "uq_discount_reservations_held_attempt",
        "discount_reservations",
        ["discount_code_id", "user_id", "payment_option_id",
         "payment_option_schedule_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'held' AND payment_option_id IS NOT NULL"
        ),
    )
    # The same exclusivity for a direct purchase attempt: one live hold
    # per (code, member, kind, experience).
    op.create_index(
        "uq_discount_reservations_held_direct_attempt",
        "discount_reservations",
        ["discount_code_id", "user_id", "target_kind", "target_id"],
        unique=True,
        postgresql_where=sa.text("status = 'held' AND target_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_discount_reservations_held_direct_attempt",
        table_name="discount_reservations",
    )
    op.drop_index(
        "uq_discount_reservations_held_attempt",
        table_name="discount_reservations",
    )
    op.create_index(
        "uq_discount_reservations_held_attempt",
        "discount_reservations",
        ["discount_code_id", "user_id", "payment_option_id",
         "payment_option_schedule_id"],
        unique=True, postgresql_where=sa.text("status = 'held'"),
    )
    op.drop_constraint(
        "ck_discount_reservations_target_shape",
        "discount_reservations", type_="check",
    )
    op.drop_constraint(
        "ck_discount_reservations_target_kind",
        "discount_reservations", type_="check",
    )
    # Direct-shaped rows cannot satisfy the restored NOT NULLs, and the
    # columns that describe them are about to be dropped, so there is no
    # representation to keep them in. They only exist at all if the
    # Stage 4 flag was on.
    #
    # Nothing permanent is lost. A reservation is a transient hold; the
    # record of a direct purchase that actually completed is its
    # ``DiscountRedemption`` row, which this migration does not touch. A
    # live hold being dropped frees a slot that, post-downgrade, no
    # direct checkout can spend anyway.
    op.execute("DELETE FROM discount_reservations WHERE target_id IS NOT NULL")
    op.alter_column(
        "discount_reservations", "payment_option_schedule_id",
        existing_type=sa.String(), nullable=False,
    )
    op.alter_column(
        "discount_reservations", "payment_option_id",
        existing_type=sa.String(), nullable=False,
    )
    op.drop_column("discount_reservations", "target_id")
    op.drop_column("discount_reservations", "target_kind")
