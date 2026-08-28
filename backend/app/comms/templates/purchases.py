"""Templates for member money/access lifecycle events (R3).

Copy rules — strictly member-facing:
  * Never expose Stripe internals (invoice ids, PaymentIntent,
    SubscriptionSchedule, retry terminology, internal PurchasePlan
    state names).
  * Use "payment plan" / "single payment" / "payment" / "access".
  * Completion wording does NOT promise perpetual access — access
    continues according to whatever the purchased experience grants.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.registry import template_for


_EVENT_PURCHASE_COMPLETED       = "purchase.completed"
_EVENT_INSTALMENT_FAILED        = "payment.instalment_failed"
_EVENT_ACCESS_SUSPENDED         = "access.suspended"
_EVENT_PAYMENT_RECOVERED        = "payment.recovered"
_EVENT_PLAN_COMPLETED           = "purchase.plan_completed"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _greeting(first_name: str | None) -> str:
    name = (first_name or "").strip()
    return f"Hi {name}," if name else "Hi,"


def _fmt_amount(cents: int | None, currency: str | None) -> str:
    """Member-facing money string. Falls back to a bare integer when
    we lack currency data — never invents a symbol."""
    if cents is None:
        return ""
    dollars = cents / 100
    cur = (currency or "").upper() or ""
    # Two-decimal formatting matches Stripe conventions for the
    # currencies FC supports today (AUD/USD/NZD/GBP/EUR/CAD, all
    # two-decimal). Zero-decimal currencies (JPY) would need a
    # dedicated branch — none are in production catalogue.
    return f"{cur} {dollars:,.2f}".strip()


def _fmt_date(iso: str | None) -> str:
    """A soft date for member copy — '5 September 2026', or empty when
    the input is malformed. Never raises."""
    if not iso:
        return ""
    try:
        from datetime import datetime
        # Accept either full ISO with offset or a naive isoformat.
        s = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except Exception:
        return ""
    return dt.strftime("%-d %B %Y")


def _progress_line(paid: int | None, expected: int | None) -> str:
    """'Payment 1 of 6' — omitted when we don't have both numbers."""
    if not isinstance(paid, int) or not isinstance(expected, int):
        return ""
    if expected <= 0:
        return ""
    return f"Payment {paid} of {expected}"


# ---------------------------------------------------------------------------
# purchase.completed — single payment OR FIP first-instalment
# ---------------------------------------------------------------------------


@template_for(_EVENT_PURCHASE_COMPLETED, CHANNEL_EMAIL_TRANSACTIONAL)
class PurchaseCompletedEmailTemplate:
    key = "purchase.completed.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx          = recipient.template_context
        greeting     = _greeting(ctx.get("first_name"))
        experience   = (ctx.get("experience_name") or "").strip() or "your purchase"
        member_url   = ctx.get("member_url") or ""
        payment_mode = (ctx.get("payment_mode") or "single").strip()
        amount_line  = _fmt_amount(ctx.get("amount_cents"), ctx.get("currency"))

        is_plan = payment_mode == "plan"
        progress = _progress_line(
            ctx.get("installments_paid"), ctx.get("installments_expected"),
        )

        if is_plan:
            subject = f"Your payment plan for {experience} has begun"
            first_line = (
                f"Your payment plan for {experience} has started. "
                f"We’ve received your first payment"
                + (f" ({amount_line})." if amount_line else ".")
            )
            middle_line = (
                f"{progress}. Your access is now active."
                if progress else "Your access is now active."
            )
        else:
            subject = f"Your purchase of {experience} is confirmed"
            first_line = (
                f"Thanks for your purchase of {experience}"
                + (f" ({amount_line})." if amount_line else ".")
            )
            middle_line = "Your access is now active."

        cta_label = f"Open {experience}" if experience != "your purchase" else "Open your purchase"

        body_text = (
            f"{greeting}\n\n"
            f"{first_line}\n\n"
            f"{middle_line}\n\n"
            f"{cta_label}:\n{member_url}\n\n"
            "Take your time — Fresh Collective is built for depth, not speed."
        )
        body_html = (
            f"<p>{greeting}</p>"
            f"<p>{first_line}</p>"
            f"<p>{middle_line}</p>"
            f'<p><a href="{member_url}">{cta_label}</a>.</p>'
            "<p>Take your time — Fresh Collective is built for depth, "
            "not speed.</p>"
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "purchase_completed"},
        )


@template_for(_EVENT_PURCHASE_COMPLETED, CHANNEL_IN_APP)
class PurchaseCompletedInAppTemplate:
    key = "purchase.completed.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx        = recipient.template_context
        experience = (ctx.get("experience_name") or "").strip() or "your purchase"
        member_url = ctx.get("member_url") or ""
        is_plan    = (ctx.get("payment_mode") or "single") == "plan"
        subject    = (
            f"Payment plan for {experience} started"
            if is_plan else f"{experience} — purchase confirmed"
        )
        body_text  = (
            "Your first payment has been received and your access is active."
            if is_plan else "Your access is now active."
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_text=body_text,
            metadata={
                "notification_type": "purchase_completed",
                "url": member_url,
            },
        )


# ---------------------------------------------------------------------------
# payment.instalment_failed — grace opens atomically with the failure
# ---------------------------------------------------------------------------


@template_for(_EVENT_INSTALMENT_FAILED, CHANNEL_EMAIL_TRANSACTIONAL)
class PaymentInstalmentFailedEmailTemplate:
    key = "payment.instalment_failed.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx        = recipient.template_context
        greeting   = _greeting(ctx.get("first_name"))
        experience = (ctx.get("experience_name") or "").strip() or "your payment plan"
        repair_url = ctx.get("repair_url") or ""
        grace_line = _fmt_date(ctx.get("grace_expires_at"))
        amount     = _fmt_amount(ctx.get("amount_cents"), ctx.get("currency"))

        subject = "There’s a problem with your payment"

        opening = (
            f"A payment on your payment plan for {experience} could not be "
            "processed."
        )
        if amount:
            opening += f" (The scheduled amount was {amount}.)"

        reassurance = (
            "Your access is still active for now. We’ll try the payment "
            "again automatically."
        )
        deadline = (
            f"If the payment can’t be recovered by {grace_line}, your access "
            "will be paused until it succeeds."
            if grace_line
            else "If the payment can’t be recovered soon, your access will be "
                 "paused until it succeeds."
        )

        body_text = (
            f"{greeting}\n\n"
            f"{opening}\n\n"
            f"{reassurance}\n\n"
            f"{deadline}\n\n"
            f"Fix payment:\n{repair_url}\n\n"
            "If nothing needs to change on your card, no action is required "
            "— we’ll keep trying."
        )
        body_html = (
            f"<p>{greeting}</p>"
            f"<p>{opening}</p>"
            f"<p>{reassurance}</p>"
            f"<p>{deadline}</p>"
            f'<p><a href="{repair_url}">Fix payment</a>.</p>'
            "<p>If nothing needs to change on your card, no action is "
            "required — we’ll keep trying.</p>"
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "payment_instalment_failed"},
        )


@template_for(_EVENT_INSTALMENT_FAILED, CHANNEL_IN_APP)
class PaymentInstalmentFailedInAppTemplate:
    key = "payment.instalment_failed.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx        = recipient.template_context
        experience = (ctx.get("experience_name") or "").strip() or "your payment plan"
        repair_url = ctx.get("repair_url") or ""
        grace_line = _fmt_date(ctx.get("grace_expires_at"))
        body = (
            "A payment couldn’t be processed. Your access remains active"
            + (f" until {grace_line}." if grace_line else ".")
        )
        return RenderedPayload(
            to="",
            subject=f"Payment problem — {experience}",
            body_text=body,
            metadata={
                "notification_type": "payment_instalment_failed",
                "url": repair_url,
            },
        )


# ---------------------------------------------------------------------------
# access.suspended — grace elapsed without recovery
# ---------------------------------------------------------------------------


@template_for(_EVENT_ACCESS_SUSPENDED, CHANNEL_EMAIL_TRANSACTIONAL)
class AccessSuspendedEmailTemplate:
    key = "access.suspended.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx        = recipient.template_context
        greeting   = _greeting(ctx.get("first_name"))
        experience = (ctx.get("experience_name") or "").strip() or "your payment plan"
        repair_url = ctx.get("repair_url") or ""

        subject = f"Your access to {experience} is paused"

        opening = (
            f"We couldn’t recover the overdue payment on your payment plan "
            f"for {experience}, so your access has been paused."
        )
        promise = (
            "Nothing else is required from Fresh Collective — as soon as the "
            "payment succeeds, your access will be restored."
        )
        how = (
            "You can update the payment on file and we’ll try again straight "
            "away."
        )

        body_text = (
            f"{greeting}\n\n"
            f"{opening}\n\n"
            f"{how}\n\n"
            f"Fix payment:\n{repair_url}\n\n"
            f"{promise}"
        )
        body_html = (
            f"<p>{greeting}</p>"
            f"<p>{opening}</p>"
            f"<p>{how}</p>"
            f'<p><a href="{repair_url}">Fix payment</a>.</p>'
            f"<p>{promise}</p>"
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "access_suspended"},
        )


@template_for(_EVENT_ACCESS_SUSPENDED, CHANNEL_IN_APP)
class AccessSuspendedInAppTemplate:
    key = "access.suspended.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx        = recipient.template_context
        experience = (ctx.get("experience_name") or "").strip() or "your payment plan"
        repair_url = ctx.get("repair_url") or ""
        return RenderedPayload(
            to="",
            subject=f"Access paused — {experience}",
            body_text=(
                "Your access is paused until the overdue payment succeeds."
            ),
            metadata={
                "notification_type": "access_suspended",
                "url": repair_url,
            },
        )


# ---------------------------------------------------------------------------
# payment.recovered — either during grace or after suspension
# ---------------------------------------------------------------------------


@template_for(_EVENT_PAYMENT_RECOVERED, CHANNEL_EMAIL_TRANSACTIONAL)
class PaymentRecoveredEmailTemplate:
    key = "payment.recovered.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx           = recipient.template_context
        greeting      = _greeting(ctx.get("first_name"))
        experience    = (ctx.get("experience_name") or "").strip() or "your payment plan"
        member_url    = ctx.get("member_url") or ""
        was_suspended = bool(ctx.get("was_suspended"))
        progress      = _progress_line(
            ctx.get("installments_paid"), ctx.get("installments_expected"),
        )

        if was_suspended:
            subject = "Payment fixed — access restored"
            opening = (
                f"The overdue payment on your payment plan for {experience} "
                "has been recovered, and your access is active again."
            )
        else:
            subject = "Payment fixed — nothing more to do"
            opening = (
                f"The overdue payment on your payment plan for {experience} "
                "has been recovered. Your access remains active."
            )
        progress_line = (
            f"{progress}. The plan continues as scheduled." if progress
            else "The plan continues as scheduled."
        )

        body_text = (
            f"{greeting}\n\n"
            f"{opening}\n\n"
            f"{progress_line}\n\n"
            f"Open {experience}:\n{member_url}"
        )
        body_html = (
            f"<p>{greeting}</p>"
            f"<p>{opening}</p>"
            f"<p>{progress_line}</p>"
            f'<p><a href="{member_url}">Open {experience}</a>.</p>'
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "payment_recovered"},
        )


@template_for(_EVENT_PAYMENT_RECOVERED, CHANNEL_IN_APP)
class PaymentRecoveredInAppTemplate:
    key = "payment.recovered.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx           = recipient.template_context
        experience    = (ctx.get("experience_name") or "").strip() or "your payment plan"
        member_url    = ctx.get("member_url") or ""
        was_suspended = bool(ctx.get("was_suspended"))
        body = (
            "Payment recovered — access is active again."
            if was_suspended
            else "Payment recovered — nothing more to do."
        )
        return RenderedPayload(
            to="",
            subject=f"Payment fixed — {experience}",
            body_text=body,
            metadata={
                "notification_type": "payment_recovered",
                "url": member_url,
            },
        )


# ---------------------------------------------------------------------------
# purchase.plan_completed — final scheduled instalment succeeded
# ---------------------------------------------------------------------------


@template_for(_EVENT_PLAN_COMPLETED, CHANNEL_EMAIL_TRANSACTIONAL)
class PurchasePlanCompletedEmailTemplate:
    key = "purchase.plan_completed.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx        = recipient.template_context
        greeting   = _greeting(ctx.get("first_name"))
        experience = (ctx.get("experience_name") or "").strip() or "your payment plan"
        member_url = ctx.get("member_url") or ""
        total      = _fmt_amount(ctx.get("total_paid_cents"), ctx.get("currency"))
        expected   = ctx.get("installments_expected")

        subject = f"Your payment plan for {experience} is complete"

        opening = (
            f"You’ve made your final payment on the payment plan for "
            f"{experience}."
        )
        summary_line = ""
        if isinstance(expected, int) and expected > 0:
            summary_line = (
                f"All {expected} payments received"
                + (f" — {total} in total." if total else ".")
            )
        elif total:
            summary_line = f"{total} received in total."

        closing = (
            "No further scheduled payments will be taken. Your access "
            "continues according to what the purchase includes."
        )

        body_text = (
            f"{greeting}\n\n"
            f"{opening}\n\n"
            + (f"{summary_line}\n\n" if summary_line else "")
            + f"{closing}\n\n"
            f"Open {experience}:\n{member_url}\n\n"
            "Thank you for being part of Fresh Collective."
        )
        body_html = (
            f"<p>{greeting}</p>"
            f"<p>{opening}</p>"
            + (f"<p>{summary_line}</p>" if summary_line else "")
            + f"<p>{closing}</p>"
            f'<p><a href="{member_url}">Open {experience}</a>.</p>'
            "<p>Thank you for being part of Fresh Collective.</p>"
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "purchase_plan_completed"},
        )


@template_for(_EVENT_PLAN_COMPLETED, CHANNEL_IN_APP)
class PurchasePlanCompletedInAppTemplate:
    key = "purchase.plan_completed.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx        = recipient.template_context
        experience = (ctx.get("experience_name") or "").strip() or "your payment plan"
        member_url = ctx.get("member_url") or ""
        return RenderedPayload(
            to="",
            subject=f"Payment plan complete — {experience}",
            body_text=(
                "You’ve made your final payment. No further payments will "
                "be taken."
            ),
            metadata={
                "notification_type": "purchase_plan_completed",
                "url": member_url,
            },
        )
