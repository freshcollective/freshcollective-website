"""Card-change tracking, and room for a membership paid once.

Two nullable columns and one widened CHECK on
``collective_memberships``. Nothing is backfilled and no behaviour
changes on apply.

Why they are needed
-------------------
A member changes the card on one membership through a Stripe
``mode='setup'`` Checkout Session. Stage 5A.3b applied the result when
the member came *back* from Stripe — which is secure, because the
Session is re-read from the provider and checked both ways, but
incomplete: a member who completes Stripe's form and then closes the
tab never returns, so the card they just entered is never attached.
They would reasonably believe it had been.

Stage 5A.3c adds the webhook that closes that gap, which means two
paths can now complete the same setup. These columns are how they
converge rather than race:

``payment_method_setup_session_id``
    The Session already applied. Whichever path arrives second
    recognises its own Session as done and changes nothing, so a
    duplicate webhook, a refreshed return page, or both at once all
    settle on one outcome.

``payment_method_updated_at``
    When it landed. Read by nothing that decides anything — it exists
    so an operator looking at a disputed charge can see whether the
    card moved before or after the invoice that is being argued about.

The deliberate rule, stated here because it is a product decision and
not an implementation detail: **the last setup a member completes
wins.** If they open two card changes and finish the older one last,
the older one is what sticks — because from where they are sitting it
is simply the one they just completed. The alternative, ranking by
when each Session was *created*, would silently discard the card they
had most recently typed in.
"""

from alembic import op
import sqlalchemy as sa

revision = "190"
down_revision = "189"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_collective_memberships_interval",
        "collective_memberships",
        type_="check",
    )
    op.create_check_constraint(
        "ck_collective_memberships_interval",
        "collective_memberships",
        "interval IN ('month','year','one_time')",
    )
    op.add_column(
        "collective_memberships",
        sa.Column(
            "payment_method_setup_session_id", sa.String(200), nullable=True,
        ),
    )
    op.add_column(
        "collective_memberships",
        sa.Column(
            "payment_method_updated_at",
            sa.DateTime(timezone=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("collective_memberships", "payment_method_updated_at")
    op.drop_column("collective_memberships", "payment_method_setup_session_id")
    # Restores 189's narrower constraint rather than leaving the table
    # unconstrained. If a ``one_time`` agreement exists this fails, and
    # loudly is the right way for it to fail: downgrading past one-time
    # membership while somebody holds one is a decision about their
    # membership, not about the schema, and it should not happen by
    # running a command.
    op.drop_constraint(
        "ck_collective_memberships_interval",
        "collective_memberships",
        type_="check",
    )
    op.create_check_constraint(
        "ck_collective_memberships_interval",
        "collective_memberships",
        "interval IN ('month','year')",
    )
