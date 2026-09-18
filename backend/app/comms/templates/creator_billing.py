"""Templates for the creator monthly-subscription lifecycle.

Copy rules, inherited from the member commerce templates and tightened
for the creator relationship:

* Never expose the internal plan shorthand. The label arrives already
  translated (see ``app/services/creator_plan_labels.py``); templates
  render it verbatim.
* Never claim an access state the billing system does not provide.
  Payment-failed says access *continues* during grace, because it does
  — the grace reconciler is what eventually changes that.
* A scheduled cancellation and an ended subscription are different
  facts and read differently. The first loses nothing yet.
* Ending a creator subscription stops NEW commercial sales. It does not
  delete or refund anything members already bought, and the copy says
  so explicitly.
* No Stripe vocabulary — no invoices, retries, dunning or subscription
  ids.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.base import render_email_shell
from app.comms.templates.registry import template_for


_EVENT_PAYMENT_FAILED         = "creator.subscription.payment_failed"
_EVENT_RECOVERED              = "creator.subscription.recovered"
_EVENT_CANCELLATION_SCHEDULED = "creator.subscription.cancellation_scheduled"
_EVENT_CANCELLED              = "creator.subscription.cancelled"


# These events resolve to CATEGORY_ACCOUNT, which is locked for
# email_transactional — a creator cannot switch off messages about
# their own billing, so no preferences link is offered.
_SHOW_PREFS = False


def _greeting(first_name: str | None) -> str:
    name = (first_name or "").strip()
    return f"Hi {name}," if name else "Hi,"


def _plan(ctx: dict) -> str:
    return (ctx.get("plan_label") or "").strip() or "Creator"


def _fmt_date(iso: str | None) -> str:
    """'5 September 2026', or empty when absent/malformed. Never raises."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return ""
    return dt.strftime("%-d %B %Y")


# ---------------------------------------------------------------------------
# Payment failed — grace window open, plan still active
# ---------------------------------------------------------------------------


@template_for(_EVENT_PAYMENT_FAILED, CHANNEL_EMAIL_TRANSACTIONAL)
class CreatorSubscriptionPaymentFailedEmailTemplate:
    key = "creator.subscription.payment_failed.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        greeting = _greeting(ctx.get("first_name"))
        plan = _plan(ctx)
        billing_url = ctx.get("billing_url") or ""
        deadline = _fmt_date(ctx.get("grace_expires_at"))

        subject = "There’s a problem with your Creator plan payment"

        opening = (
            f"We couldn’t process the latest payment for your Fresh "
            f"Collective {plan} plan."
        )
        # Deliberately states that access CONTINUES. The grace window is
        # open; nothing has been suspended at this point.
        reassurance = (
            f"Your {plan} plan is still active, and your Collectives and "
            "members are unaffected. We’ll keep trying the payment."
        )
        window = (
            f"If the payment hasn’t succeeded by {deadline}, your plan will "
            "move to unpaid and you won’t be able to start new paid offers "
            "until it’s resolved."
            if deadline
            else
            "If the payment can’t be recovered within the 7-day grace "
            "period, your plan will move to unpaid and you won’t be able to "
            "start new paid offers until it’s resolved."
        )

        body_text = (
            f"{greeting}\n\n{opening}\n\n{reassurance}\n\n{window}\n\n"
            f"Update your payment method:\n{billing_url}\n\n"
            "If your card details haven’t changed, no action is needed — "
            "we’ll keep trying."
        )
        body_html = render_email_shell(
            preheader=opening,
            heading=subject,
            greeting=greeting,
            body_paragraphs=[opening, reassurance, window],
            action=("Update payment method", billing_url),
            signoff=(
                "If your card details haven’t changed, no action is needed "
                "— we’ll keep trying."
            ),
            show_preferences_link=_SHOW_PREFS,
        )
        return RenderedPayload(
            to="", subject=subject, body_html=body_html, body_text=body_text,
            metadata={"notification_type": "creator_subscription_payment_failed"},
        )


@template_for(_EVENT_PAYMENT_FAILED, CHANNEL_IN_APP)
class CreatorSubscriptionPaymentFailedInAppTemplate:
    key = "creator.subscription.payment_failed.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        deadline = _fmt_date(ctx.get("grace_expires_at"))
        body = (
            f"Your plan is still active. Update your payment method by "
            f"{deadline} to keep it that way."
            if deadline
            else "Your plan is still active. Update your payment method to "
                 "keep it that way."
        )
        return RenderedPayload(
            to="", subject="Payment problem — Creator plan", body_text=body,
            metadata={
                "notification_type": "creator_subscription_payment_failed",
                "url": ctx.get("billing_url"),
            },
        )


# ---------------------------------------------------------------------------
# Recovered — billing is healthy again
# ---------------------------------------------------------------------------


@template_for(_EVENT_RECOVERED, CHANNEL_EMAIL_TRANSACTIONAL)
class CreatorSubscriptionRecoveredEmailTemplate:
    key = "creator.subscription.recovered.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        greeting = _greeting(ctx.get("first_name"))
        plan = _plan(ctx)
        billing_url = ctx.get("billing_url") or ""
        renews = _fmt_date(ctx.get("current_period_end"))

        subject = "Your Creator plan payment went through"

        opening = (
            f"The payment for your Fresh Collective {plan} plan has gone "
            "through. Nothing further is needed."
        )
        state = (
            f"Your {plan} plan is active and continues as normal"
            + (f", with the next payment due {renews}." if renews else ".")
        )

        body_text = (
            f"{greeting}\n\n{opening}\n\n{state}\n\n"
            f"View billing:\n{billing_url}"
        )
        body_html = render_email_shell(
            preheader=opening,
            heading=subject,
            greeting=greeting,
            body_paragraphs=[opening, state],
            action=("View billing", billing_url),
            show_preferences_link=_SHOW_PREFS,
        )
        return RenderedPayload(
            to="", subject=subject, body_html=body_html, body_text=body_text,
            metadata={"notification_type": "creator_subscription_recovered"},
        )


@template_for(_EVENT_RECOVERED, CHANNEL_IN_APP)
class CreatorSubscriptionRecoveredInAppTemplate:
    key = "creator.subscription.recovered.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        return RenderedPayload(
            to="", subject="Payment received — Creator plan",
            body_text="Your plan is active and continues as normal.",
            metadata={
                "notification_type": "creator_subscription_recovered",
                "url": ctx.get("billing_url"),
            },
        )


# ---------------------------------------------------------------------------
# Cancellation scheduled — still active until period end
# ---------------------------------------------------------------------------


@template_for(_EVENT_CANCELLATION_SCHEDULED, CHANNEL_EMAIL_TRANSACTIONAL)
class CreatorSubscriptionCancellationScheduledEmailTemplate:
    key = "creator.subscription.cancellation_scheduled.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        greeting = _greeting(ctx.get("first_name"))
        plan = _plan(ctx)
        billing_url = ctx.get("billing_url") or ""
        ends = _fmt_date(ctx.get("current_period_end"))

        subject = "Your Creator plan is scheduled to end"

        opening = (
            f"Your Fresh Collective {plan} plan is set to end"
            + (f" on {ends}." if ends else " at the end of the current billing period.")
        )
        # Nothing is lost yet — say so plainly.
        until_then = (
            "Until then everything stays exactly as it is: your plan is "
            "active, your Collectives are open, and your members keep their "
            "access."
        )
        # Reactivation is supported today by clearing the scheduled
        # cancellation from the billing page before the end date.
        reactivate = (
            "If you change your mind, you can restart your plan from your "
            "billing page any time before then."
        )

        body_text = (
            f"{greeting}\n\n{opening}\n\n{until_then}\n\n{reactivate}\n\n"
            f"Manage billing:\n{billing_url}"
        )
        body_html = render_email_shell(
            preheader=opening,
            heading=subject,
            greeting=greeting,
            body_paragraphs=[opening, until_then, reactivate],
            action=("Manage billing", billing_url),
            show_preferences_link=_SHOW_PREFS,
        )
        return RenderedPayload(
            to="", subject=subject, body_html=body_html, body_text=body_text,
            metadata={
                "notification_type": "creator_subscription_cancellation_scheduled",
            },
        )


@template_for(_EVENT_CANCELLATION_SCHEDULED, CHANNEL_IN_APP)
class CreatorSubscriptionCancellationScheduledInAppTemplate:
    key = "creator.subscription.cancellation_scheduled.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        ends = _fmt_date(ctx.get("current_period_end"))
        return RenderedPayload(
            to="",
            subject="Creator plan scheduled to end",
            body_text=(
                f"Your plan stays active until {ends}."
                if ends else
                "Your plan stays active until the end of the current period."
            ),
            metadata={
                "notification_type": "creator_subscription_cancellation_scheduled",
                "url": ctx.get("billing_url"),
            },
        )


# ---------------------------------------------------------------------------
# Cancelled — the paid subscription has ended
# ---------------------------------------------------------------------------


@template_for(_EVENT_CANCELLED, CHANNEL_EMAIL_TRANSACTIONAL)
class CreatorSubscriptionCancelledEmailTemplate:
    key = "creator.subscription.cancelled.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        greeting = _greeting(ctx.get("first_name"))
        plan = _plan(ctx)
        billing_url = ctx.get("billing_url") or ""

        subject = "Your Creator plan has ended"

        opening = (
            f"Your paid Fresh Collective {plan} plan has now ended."
        )
        what_changes = (
            "You can’t start new paid offers or take new payments while the "
            "plan is inactive."
        )
        # The single most important reassurance, and the one most easily
        # got wrong: nothing already bought is touched.
        what_does_not = (
            "What members have already bought is unaffected — existing "
            "purchases, payment plans and access all continue exactly as "
            "before. Nothing has been cancelled or refunded."
        )

        body_text = (
            f"{greeting}\n\n{opening}\n\n{what_changes}\n\n{what_does_not}\n\n"
            f"Restart your plan:\n{billing_url}\n\n"
            "Thank you for building with Fresh Collective."
        )
        body_html = render_email_shell(
            preheader=opening,
            heading=subject,
            greeting=greeting,
            body_paragraphs=[opening, what_changes, what_does_not],
            action=("Restart your plan", billing_url),
            signoff="Thank you for building with Fresh Collective.",
            show_preferences_link=_SHOW_PREFS,
        )
        return RenderedPayload(
            to="", subject=subject, body_html=body_html, body_text=body_text,
            metadata={"notification_type": "creator_subscription_cancelled"},
        )


@template_for(_EVENT_CANCELLED, CHANNEL_IN_APP)
class CreatorSubscriptionCancelledInAppTemplate:
    key = "creator.subscription.cancelled.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        return RenderedPayload(
            to="",
            subject="Creator plan ended",
            body_text=(
                "New paid offers are paused. Everything members already "
                "bought continues as before."
            ),
            metadata={
                "notification_type": "creator_subscription_cancelled",
                "url": ctx.get("billing_url"),
            },
        )
