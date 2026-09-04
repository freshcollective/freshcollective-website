"""SEC-009 — email verification.

Revision ID: 121
Revises: 120
Create Date: 2026-09-04

Adds:

  * ``users.email_verified_at TIMESTAMP NULL`` — the moment the
    account proved control of its email. NULL = unverified. Every
    existing row is backfilled to ``COALESCE(created_at, NOW())`` so
    the small pre-external-testing production user set is
    grandfathered as verified. Every NEW signup lands here with
    ``NULL`` and completes a verification flow to flip it.

  * ``email_verifications`` table — dedicated per-user verification
    token store. Kept separate from ``password_resets`` because the
    two token types have materially different semantics (password
    reset is a credential rotation that expires in 1h; email
    verification is a one-time email-ownership proof that expires
    in 24h). Sharing the table would force branch-heavy consume
    paths and a shared cooldown that isn't semantically shared.

Token model:

  * 64-char raw token (``secrets.token_hex(32)``) — same entropy
    profile as ``password_resets.token_hash``.
  * SHA-256 hashed at rest (``token_hash UNIQUE``); raw only ever
    leaves the server in the verification email URL.
  * 24-hour ``expires_at``.
  * Single-use ``used_at`` marker.
  * ``invalidated_at`` marker set when a resend supersedes a prior
    outstanding token (invalidate-and-replace, mirroring the
    ``PasswordReset`` invalidation pattern).

Deployment notes:

  * Additive column + additive table + bounded backfill UPDATE. Safe
    for the automatic ``fc-api`` ``preDeployCommand: alembic upgrade
    head`` path.

  * Grandfather backfill runs in a single UPDATE. At the current
    production scale (a handful of hand-known accounts) this
    completes in milliseconds and does not require any operator
    action.

  * Downgrade is defined and drops the column + table cleanly.
    Because the column is nullable and there is no FK from other
    tables into it, downgrade is safe post-deployment if a rollback
    is ever required (see the security-post-mortem procedure in
    ``docs/`` for the full sequence).

Related decisions locked in this migration:

  * Successful password-reset consumption (SEC-006) also flips
    ``email_verified_at`` — implemented in
    ``app.auth.service.consume_password_reset_token``, not here.
    This migration only creates the field; the auto-verify semantics
    live in the service layer.

  * Invitation acceptance, Stripe checkout, and any commerce event
    do NOT auto-verify. Those are policy decisions enforced at the
    endpoint/dependency layer, not the schema.
"""

from alembic import op
import sqlalchemy as sa


revision = "121"
down_revision = "120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- users.email_verified_at ----
    op.add_column(
        "users",
        sa.Column(
            "email_verified_at",
            sa.DateTime(timezone=False),
            nullable=True,
        ),
    )
    # Grandfather existing accounts. Every row created before SEC-009
    # is presumed to have a real, controlled email — the pre-external-
    # testing production set is hand-known, and forcing existing
    # accounts (including the operator) to re-verify would add friction
    # without safety benefit. See the SEC-009 investigation for the
    # option comparison that led to this choice.
    op.execute(
        "UPDATE users SET email_verified_at = COALESCE(created_at, NOW()) "
        "WHERE email_verified_at IS NULL"
    )

    # ---- email_verifications table ----
    op.create_table(
        "email_verifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_email_verifications_user_created",
        "email_verifications",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_verifications_user_created",
        table_name="email_verifications",
    )
    op.drop_table("email_verifications")
    op.drop_column("users", "email_verified_at")
