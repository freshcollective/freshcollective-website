"""SQLAlchemy model for finite Payment Plans.

A ``PurchasePlan`` represents ONE member agreement to buy a Payment
Option via a specific finite-instalments schedule — e.g. Awaken as
$20/week × 10.

It is the parent record for the N ``PaymentTransaction`` rows that
will accumulate under it (one per successful invoice payment). It
carries the lifecycle state of the *agreement* — separate from the
per-transaction ``status`` on each ``PaymentTransaction``, which
records only whether a single monetary event cleared.

Explicitly finite: the terminal state ``completed`` fires when
``installments_paid == installments_expected``. This is not the model
for indefinite subscriptions.

FIP1 scope
----------
Foundation only. Nothing writes to this table yet — the
``recurring_installments`` guard in
``services/checkout_orchestration.py:241`` still returns 503. The
model and its schema exist so FIP2 (Stripe setup checkout +
SubscriptionSchedule creation) has a stable identity to attach
Customer / SubscriptionSchedule / Subscription / payment method IDs
to, and so ``PaymentTransaction``, ``AccessPass``, and
``PathwayEntitlement`` can already carry the ``purchase_plan_id``
foreign key that later reconciliation will need.

Pay-in-full purchases are unaffected — they do not create a
``PurchasePlan`` row; the existing single-``PaymentTransaction``
model continues to represent them 1:1.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PurchasePlanStatus(str, enum.Enum):
    """The lifecycle of the *agreement* (not of any single payment).

    ``pending_setup``
        Row created; payment method not yet on file. The member
        started Stripe Checkout in ``mode='setup'`` but has not
        completed it, or the ``SubscriptionSchedule`` has not been
        created yet. No access has been granted. Terminal only if
        setup is abandoned — then the row transitions to ``failed``.

    ``active``
        First invoice paid successfully. Stripe is billing the
        remaining instalments on schedule. Access is live.

    ``payment_problem``
        The most recent invoice failed. Stripe's Smart Retries are
        in progress (default: up to 4 weeks). Access remains live
        during the grace window (product decision: 7-day member-
        facing grace; see ``docs/finite-payment-plans-lifecycle.md``).
        A successful retry transitions back to ``active``; exhausted
        retries transition to ``failed``.

    ``completed``
        Every scheduled instalment cleared. Stripe emitted
        ``customer.subscription.deleted`` with a normal end. Access
        continues indefinitely (or until its own ``valid_until``
        expires — not a plan lifecycle concern).

    ``cancelled``
        Admin / creator cancelled the plan mid-flight (no member
        self-cancel in v1). Access decision handled separately.

    ``failed``
        Setup abandoned, OR Smart Retries exhausted with no
        recovery. Terminal. Access decision handled by the
        cancellation/revocation flow that will land in a later
        phase.

    See ``docs/finite-payment-plans-lifecycle.md`` for the state
    transition diagram + webhook triggers.
    """

    pending_setup = "pending_setup"
    active = "active"
    payment_problem = "payment_problem"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class PurchasePlan(Base):
    """One member's agreement to a finite Payment Option plan.

    Provider identifiers (all Stripe-namespaced, all nullable until
    FIP2 wires the setup + SubscriptionSchedule creation):

    * ``provider_customer_id`` — ``cus_...``. One per member per
      Stripe account; may be reused across plans if the member
      already had one.
    * ``provider_setup_session_id`` — ``cs_...``. The Checkout
      Session created in ``mode='setup'`` to collect the payment
      method. Populated when the Session is created; the completion
      webhook uses it to look this row up.
    * ``provider_payment_method_id`` — ``pm_...``. The payment
      method attached to the Customer via the setup Session.
    * ``provider_subscription_schedule_id`` — ``sub_sched_...``.
      The SubscriptionSchedule with a single phase of length
      ``installments_expected`` and ``end_behavior='cancel'``.
      The finite end is enforced by Stripe, not by us.
    * ``provider_subscription_id`` — ``sub_...``. The underlying
      Subscription created by the SubscriptionSchedule.

    Fee snapshot
    ------------
    ``platform_fee_basis_points`` is captured at plan creation and
    applied per instalment. This preserves the fee-rate promised
    at purchase time even if the platform fee changes mid-plan.

    Grants linkage
    --------------
    ``AccessPass.purchase_plan_id`` and
    ``PathwayEntitlement.purchase_plan_id`` (both nullable, added by
    migration 116) point back to this row for plan-derived access.
    Legacy pay-in-full access continues to point to
    ``payment_transaction_id`` only — that path is untouched.
    """

    __tablename__ = "purchase_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # Parties + option identity
    member_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    payment_option_id: Mapped[str] = mapped_column(
        String, ForeignKey("payment_options.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    payment_option_schedule_id: Mapped[str] = mapped_column(
        String, ForeignKey("payment_option_schedules.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    space_id: Mapped[str] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    creator_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Lifecycle
    status: Mapped[PurchasePlanStatus] = mapped_column(
        SAEnum(
            PurchasePlanStatus,
            name="purchase_plan_status_enum",
            create_type=True,
        ),
        nullable=False,
        default=PurchasePlanStatus.pending_setup,
        server_default="pending_setup",
    )

    # Money — snapshotted at creation from the underlying schedule so
    # a schedule edit doesn't retro-alter an in-flight plan.
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AUD", server_default="AUD",
    )
    installment_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    installments_expected: Mapped[int] = mapped_column(Integer, nullable=False)
    installments_paid: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    total_expected_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # Fee snapshot — applied to each per-invoice PaymentTransaction.
    platform_fee_basis_points: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    creator_plan_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("creator_plans.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Cadence — snapshot from the underlying schedule for reconciliation.
    stripe_interval: Mapped[str] = mapped_column(String(20), nullable=False)
    stripe_interval_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Provider identifiers. All nullable — populated as the setup +
    # SubscriptionSchedule flow reaches each stage. See class docstring.
    provider_customer_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_setup_session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_payment_method_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_subscription_schedule_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Sandbox vs. live — parallels ``PaymentTransaction.stripe_mode``.
    stripe_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="test", server_default="test",
    )

    # Timing
    next_billing_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    cancelled_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        # Reconciliation joins: a webhook carrying
        # ``customer.subscription.updated`` finds the plan by
        # ``provider_subscription_id`` in O(1).
        Index(
            "ix_purchase_plans_provider_subscription_id",
            "provider_subscription_id",
        ),
        Index(
            "ix_purchase_plans_provider_subscription_schedule_id",
            "provider_subscription_schedule_id",
        ),
        Index(
            "ix_purchase_plans_provider_setup_session_id",
            "provider_setup_session_id",
        ),
        # Duplicate-plan detection in FIP2 will lean on this.
        Index("ix_purchase_plans_member_option_status",
              "member_user_id", "payment_option_id", "status"),
        # A given Stripe SubscriptionSchedule / Subscription can only
        # anchor one plan. Unique-partial (WHERE NOT NULL) is emitted
        # by the migration so historical NULLs don't collide.
        UniqueConstraint(
            "provider_subscription_schedule_id",
            name="uq_purchase_plans_provider_subscription_schedule_id",
        ),
        UniqueConstraint(
            "provider_subscription_id",
            name="uq_purchase_plans_provider_subscription_id",
        ),
    )
