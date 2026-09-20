"""How people get into a Collective, and which Options are the door.

Revision ID: 136
Revises: 135
Create Date: 2026-09-20

Two additive columns, both defaulting to today's behaviour.

``spaces.join_policy`` — ``'open'`` (anyone signed in may join, free,
which is what every Collective does today and what most should keep
doing) or ``'purchase_required'`` (the free-join door is closed;
membership arrives with a purchase). The default means this migration
changes nothing for any existing Collective until a creator says
otherwise.

``payment_options.is_joining_option`` — whether this Option is offered
as a way *in* on a purchase-required Collective's About page. Defaults
to ``false`` deliberately: a Collective that flips to
``purchase_required`` should present the doors its creator chose, not
every Option that happens to exist. Nominating an Option does not
change what it grants — fulfilment already creates membership for every
purchase; this flag only decides what a visitor is shown.

Both are plain columns rather than a JSON blob because both are queried
(``WHERE is_joining_option``) and both have a small closed vocabulary.
That is the opposite call from ``spaces.home_config`` in migration 135,
and for the opposite reason: that one is a document nobody filters on.
"""

from alembic import op
import sqlalchemy as sa

revision = "136"
down_revision = "135"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "spaces",
        sa.Column(
            "join_policy",
            sa.String(length=20),
            nullable=False,
            server_default="open",
        ),
    )
    op.add_column(
        "payment_options",
        sa.Column(
            "is_joining_option",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Reverse lookup: "which Options are the doors into this
    # Collective?" runs on every About page view of a
    # purchase-required Collective. Partial so it stays small — the
    # overwhelming majority of Options are not joining doors.
    op.create_index(
        "ix_payment_options_joining",
        "payment_options",
        ["space_id"],
        unique=False,
        postgresql_where=sa.text("is_joining_option"),
    )


def downgrade() -> None:
    op.drop_index("ix_payment_options_joining", table_name="payment_options")
    op.drop_column("payment_options", "is_joining_option")
    op.drop_column("spaces", "join_policy")
