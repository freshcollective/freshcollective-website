"""Add 'test' to the reporting classification vocabulary

Revision ID: 173
Revises: 172
Create Date: 2026-10-30

Migration 171 introduced ``reporting_class`` on ``spaces`` and ``users``
with three values: production, internal_operations and demonstration.
Classifying the real inventory showed a fourth is needed — a Collective
or account that exists to exercise the platform, including through live
Stripe keys.

Mapping a fixture onto one of the existing three would have cost the
distinction the column exists for. ``internal_operations`` is Fresh
Collective running itself, which the World Builders governance
Collective genuinely is; ``demonstration`` is a Collective shown to
people, which Moonlit Circle genuinely is. Folding test fixtures into
either makes both unreadable.

Reporting only. This widens a CHECK constraint and changes nothing else:
no permission, no payment behaviour, no financial record, and no
existing row's value. A reporting class says how to *read* money — a
test account's live charge stays in every total, because the money
moved.

Reversible without loss as long as no row has been set to 'test'. The
downgrade refuses rather than silently rewriting data, because choosing
a replacement classification is an operator's judgement and not a
migration's.
"""

from alembic import op
import sqlalchemy as sa

revision = "173"
down_revision = "172"
branch_labels = None
depends_on = None

_TABLES = ("spaces", "users")
_OLD = "('production', 'internal_operations', 'demonstration')"
_NEW = "('production', 'internal_operations', 'demonstration', 'test')"


def upgrade() -> None:
    for table in _TABLES:
        op.drop_constraint(f"ck_{table}_reporting_class", table, type_="check")
        op.create_check_constraint(
            f"ck_{table}_reporting_class",
            table,
            f"reporting_class IS NULL OR reporting_class IN {_NEW}",
        )


def downgrade() -> None:
    conn = op.get_bind()
    for table in _TABLES:
        stuck = conn.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE reporting_class = 'test'")
        ).scalar()
        if stuck:
            raise RuntimeError(
                f"{stuck} row(s) in {table!r} are classified 'test'. "
                "Narrowing the constraint would require reclassifying them, "
                "which is a judgement about what those rows are and not "
                "something this migration should decide. Reclassify them "
                "first, then downgrade."
            )

    for table in _TABLES:
        op.drop_constraint(f"ck_{table}_reporting_class", table, type_="check")
        op.create_check_constraint(
            f"ck_{table}_reporting_class",
            table,
            f"reporting_class IS NULL OR reporting_class IN {_OLD}",
        )
