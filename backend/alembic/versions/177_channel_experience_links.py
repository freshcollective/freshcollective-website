"""Many experiences per Channel, and membership that outlives them.

Revision ID: 177
Revises: 176
Create Date: 2026-11-02

Two changes, both additive, because everything already created must
survive: no channel, post, poll, membership or setting is deleted,
recreated, or archived here.

1. ``channel_experience_links``
   ------------------------------
   ``conversation_channels`` carries three singular columns —
   ``pathway_id``, ``gathering_id``, ``series_id`` — so a channel could
   name at most one experience of each kind. A creator running monthly
   women's circles needs one ongoing channel linked to November's,
   December's and January's Gatherings, which that shape cannot
   express.

   Three nullable FKs with a CHECK that exactly one is set, rather than
   a polymorphic ``(type, id)`` pair: the pair cannot be constrained by
   the database, and ``conversation_channels.gathering_id`` is already
   an unconstrained String — one orphan-prone column is enough.

   ``ON DELETE CASCADE`` on each FK drops the *link* when an experience
   is deleted. It never touches the channel or its members, which is
   the §5 rule: unlinking an experience does not remove anybody.

   The three existing columns are **left in place and still written**.
   They are backfilled into this table below, and nothing is dropped —
   so a rollback is a plain table drop with no data recovery needed,
   and any code path still reading them keeps working.

2. ``channel_memberships`` gains a lifecycle
   -----------------------------------------
   Membership rows exist today only for ``private`` channels; access to
   pathway/gathering/series channels is recomputed live on every check.
   That makes two things impossible: membership cannot outlive the
   experience access that created it, and a creator cannot remove
   somebody (there is no row to remove).

   ``status`` + ``removed_reason`` give the three states the feature
   needs, and the two removal reasons are not interchangeable:

     * ``active`` + source ``experience``  — joined automatically
     * ``active`` + source ``manual``      — the creator added them
     * ``removed`` + reason ``creator``    — deliberate; a later
       purchase must NOT silently re-admit them
     * ``removed`` + reason ``access_revoked`` — their access was taken
       away (refund, removal for cause); a genuine new purchase MAY
       re-admit them

   Existing rows default to ``active`` with a NULL reason, which is
   what every current row means.

Safety against production
-------------------------
Every column is added nullable or with a server default, so rows
written by code that predates this migration remain valid. The
backfill reads only the three columns it replaces and writes only new
rows, so running it twice is harmless — the unique constraint makes
the insert idempotent via ON CONFLICT DO NOTHING.

The backfill deliberately does **not** materialise memberships. Who
currently qualifies for a pathway or series channel is decided by
``compute_pathway_access`` / ``compute_series_access``, which encode
status rules, access types and caretaker privilege. Reimplementing
them in SQL here would risk silently over- or under-granting access to
real members. That work belongs to
``scripts/backfill_channel_memberships.py``, which calls the real
functions. Until it runs, nobody loses access: the permission service
still admits anyone who qualifies today.
"""
from alembic import op
import sqlalchemy as sa

revision = "177"
down_revision = "176"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_experience_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "channel_id", sa.String(),
            sa.ForeignKey("conversation_channels.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "pathway_id", sa.String(),
            sa.ForeignKey("pathways.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column(
            "event_id", sa.String(),
            sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column(
            "series_id", sa.String(),
            sa.ForeignKey("event_series.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column(
            "created_by", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=False),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "(CASE WHEN pathway_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN event_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN series_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_channel_experience_links_exactly_one",
        ),
    )
    # One link per (channel, experience), per kind. Partial uniques
    # rather than one composite: only one column is ever non-NULL, and
    # NULLs do not collide in a composite unique index.
    for col in ("pathway_id", "event_id", "series_id"):
        op.create_index(
            f"uq_channel_experience_links_{col}",
            "channel_experience_links", ["channel_id", col],
            unique=True, postgresql_where=sa.text(f"{col} IS NOT NULL"),
        )

    # Backfill: every experience a channel already names becomes a link.
    # ``gathering_id`` has no FK on its source column, so a channel may
    # name an event that no longer exists; the EXISTS guard keeps the
    # insert from violating this table's FK.
    op.execute("""
        INSERT INTO channel_experience_links
               (id, channel_id, pathway_id, created_by, created_at)
        SELECT 'cel_pw_' || c.id, c.id, c.pathway_id, c.created_by, NOW()
        FROM conversation_channels c
        WHERE c.pathway_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM pathways p WHERE p.id = c.pathway_id)
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO channel_experience_links
               (id, channel_id, event_id, created_by, created_at)
        SELECT 'cel_ev_' || c.id, c.id, c.gathering_id, c.created_by, NOW()
        FROM conversation_channels c
        WHERE c.gathering_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM events e WHERE e.id = c.gathering_id)
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO channel_experience_links
               (id, channel_id, series_id, created_by, created_at)
        SELECT 'cel_se_' || c.id, c.id, c.series_id, c.created_by, NOW()
        FROM conversation_channels c
        WHERE c.series_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM event_series s WHERE s.id = c.series_id)
        ON CONFLICT DO NOTHING
    """)

    op.add_column(
        "channel_memberships",
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="active",
        ),
    )
    op.add_column(
        "channel_memberships",
        sa.Column("removed_reason", sa.String(16), nullable=True),
    )
    op.add_column(
        "channel_memberships",
        sa.Column(
            "removed_at", sa.DateTime(timezone=False), nullable=True,
        ),
    )
    op.add_column(
        "channel_memberships",
        sa.Column(
            "removed_by", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_channel_memberships_status",
        "channel_memberships",
        "status IN ('active', 'removed')",
    )
    op.create_check_constraint(
        "ck_channel_memberships_removed_reason",
        "channel_memberships",
        "(status = 'active' AND removed_reason IS NULL)"
        " OR (status = 'removed'"
        "     AND removed_reason IN ('creator', 'access_revoked'))",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_channel_memberships_removed_reason", "channel_memberships",
        type_="check",
    )
    op.drop_constraint(
        "ck_channel_memberships_status", "channel_memberships", type_="check",
    )
    for col in ("removed_by", "removed_at", "removed_reason", "status"):
        op.drop_column("channel_memberships", col)
    for col in ("pathway_id", "event_id", "series_id"):
        op.drop_index(
            f"uq_channel_experience_links_{col}",
            table_name="channel_experience_links",
        )
    op.drop_table("channel_experience_links")
