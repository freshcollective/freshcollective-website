from datetime import datetime
from enum import Enum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, Enum):
    """The three role tiers a user can hold.

    Mutually exclusive — the CHECK constraint on ``users.role`` enforces
    that exactly one is stored per row. New code should reference these
    constants rather than raw strings so the vocabulary stays
    grep-able and single-sourced. Existing string-literal callsites
    are left alone; they resolve to the same values.
    """
    user = "user"
    creator = "creator"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="user",
        server_default="user",
    )
    # SEC-008 / SEC-015 — server-side session revocation counter.
    # Embedded in every newly-issued JWT as the ``sv`` claim; a
    # mismatch between token and DB value forces re-authentication.
    # Bumped by password change, password reset, and explicit
    # logout-all (see ``app.auth.service.bump_session_version``).
    # NOT bumped by role change / suspension / cancellation —
    # those are enforced by live DB reads in ``get_current_user``.
    session_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    # SEC-009 — email verification. NULL = unverified. Grandfathered
    # to ``created_at`` on migration 121 for every pre-SEC-009 row.
    # Set on: successful ``POST /api/auth/verify-email`` AND on
    # successful password reset (possession of a reset link proves
    # email control). NOT set by invitation acceptance, Stripe
    # checkout, or any commerce event — those require an already-
    # verified user via ``get_verified_current_user``.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    # Creator onboarding (short, Creator-specific welcome shown once
    # after plan activation, before Build Your Collective). Independent
    # of ``onboarding_completed_at`` — the two flows serve different
    # audiences and are never gates for one another.
    creator_onboarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    interests: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ---- Community Care — suspension (protective, temporary) --------------
    # Set by Fresh Collective admins as a Protective Measure while a case
    # is under review. Enforcement lives at the auth layer (see the
    # feature-flag rollout in Stage 2D). Reversible.
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    suspended_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Community Care Stage 2C — points to the CC action that issued the
    # current suspension, so reversal can clear this row cleanly.
    suspended_by_action_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_care_actions.id", ondelete="SET NULL"),
        nullable=True,
    )
    creator_suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    creator_suspended_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    creator_suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Community Care — cancellation (resolution outcome, terminal) -----
    # Explicitly distinct from suspension. A cancellation is never
    # "reversed" by editing the case — if a re-review is warranted a
    # new case documents that decision.
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stage 2D — link back to the resolution action that cancelled the
    # account so the audit trail names the specific case + admin.
    cancelled_by_action_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_care_actions.id", ondelete="SET NULL"),
        nullable=True,
    )
    creator_cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    creator_cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator_cancelled_by_action_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_care_actions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ---- Discovery, Connection & Belonging — real-world home Place ---------
    # Opt-in and never auto-populated. Schema-only in Phase 0; profile UI
    # arrives in a later phase. SET NULL rather than CASCADE — a person is
    # not deleted when an editorial Place is retired.
    home_place_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("places.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        CheckConstraint("role IN ('user', 'creator', 'admin')", name="users_role_check"),
    )

    password_resets: Mapped[list["PasswordReset"]] = relationship(
        "PasswordReset", back_populates="user", cascade="all, delete-orphan"
    )
    email_verifications: Mapped[list["EmailVerification"]] = relationship(
        "EmailVerification", back_populates="user", cascade="all, delete-orphan"
    )


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship("User", back_populates="password_resets")


class EmailVerification(Base):
    """SEC-009 — per-user email verification token.

    Deliberately separate from ``PasswordReset``. See migration 121
    for the "why not one table" note.

    Lifecycle:
      * Created by ``create_email_verification_token`` on signup /
        resend; ``token_hash`` = SHA-256 of the raw 32-byte hex
        value. Raw token is only returned once and only ever leaves
        the server in the verification URL.
      * Consumed by ``consume_email_verification_token`` on
        ``POST /api/auth/verify-email``; sets ``used_at`` and
        flips ``users.email_verified_at`` in the same transaction.
      * Resend invalidates any prior outstanding row for the user
        by setting ``invalidated_at``, then issues a new one — the
        old link becomes dead immediately.
      * 24-hour ``expires_at``; single-use.
    """

    __tablename__ = "email_verifications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="email_verifications")
