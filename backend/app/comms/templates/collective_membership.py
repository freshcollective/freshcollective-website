"""Templates for the paid Collective membership lifecycle.

Copy rules, inherited from the creator-billing templates and tightened
for a member paying a creator:

* **The member's agreed terms, never the catalogue.** Every amount and
  interval arrives already resolved from their own subscription row. A
  creator who re-priced yesterday has not re-priced them, and the copy
  must not imply otherwise.
* **Never claim an access state the billing does not provide.** Payment
  failed says access *continues*, because during grace it does.
  Cancellation scheduled loses nothing yet and says so with a date.
  Only "ended" says access has ended.
* **A scheduled cancellation and an ended membership are different
  facts** and read differently — conflating them is the specific
  mistake §15 of the Stage 5A.2 brief named.
* **Leaving is not cancelling.** Nothing here tells a member they have
  left a Collective; cancelling renewal keeps them until the period
  ends.
* **What they bought separately is safe.** A membership ending does not
  touch a purchased Pathway, ticket, Series pass or Offering, and the
  ended message says so rather than leaving them to wonder.
* **No Stripe vocabulary** — no invoices, retries, dunning or
  subscription ids.
* **No persuasion.** These are receipts and notices. Announcements
  about pricing are the creator's to send, and nothing here nudges
  anybody to subscribe.
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

_PURCHASED   = "collective.membership.purchased"
_RENEWED     = "collective.membership.renewed"
_FAILED      = "collective.membership.payment_failed"
_SCHEDULED   = "collective.membership.cancellation_scheduled"
_ENDED       = "collective.membership.ended"
_REACTIVATED = "collective.membership.reactivated"

#: These are account and receipt messages, not preference-gated mail.
_SHOW_PREFS = False


def _greeting(first_name: str | None) -> str:
    name = (first_name or "").strip()
    return f"Hi {name}," if name else "Hi,"


def _collective(ctx: dict) -> str:
    return (ctx.get("collective_name") or "").strip() or "this collective"


def _fmt_date(iso: str | None) -> str:
    """'5 September 2026', or empty when absent. Never raises."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return ""
    return dt.strftime("%-d %B %Y")


def _terms(ctx: dict) -> str:
    """"A$29 per month", or "A$290 once" — the member's own agreement.

    Falls back to naming no figure at all rather than guessing one. A
    receipt with a wrong number is worse than a receipt with none.
    """
    amount = (ctx.get("amount_label") or "").strip()
    if not amount:
        return ""
    if ctx.get("one_time"):
        return f"{amount} once"
    interval = (ctx.get("interval_label") or "").strip()
    return f"{amount} {interval}".strip() if interval else amount


def _manage(ctx: dict) -> str:
    return ctx.get("membership_url") or ""


def _payload(
    db: Session, *, subject: str, greeting: str, opening: str,
    paragraphs: list[str], action: tuple[str, str] | None,
    signoff: str, notification_type: str,
) -> RenderedPayload:
    body_text = "\n\n".join(
        [greeting, *[p for p in paragraphs if p]]
        + ([f"{action[0]}:\n{action[1]}"] if action and action[1] else [])
        + ([signoff] if signoff else [])
    )
    body_html = render_email_shell(
        db=db,
        preheader=opening,
        heading=subject,
        greeting=greeting,
        body_paragraphs=[p for p in paragraphs if p],
        action=action if action and action[1] else None,
        signoff=signoff,
        show_preferences_link=_SHOW_PREFS,
    )
    return RenderedPayload(
        to="", subject=subject, body_html=body_html, body_text=body_text,
        metadata={"notification_type": notification_type},
    )


# ---------------------------------------------------------------------------
# Purchased
# ---------------------------------------------------------------------------


@template_for(_PURCHASED, CHANNEL_EMAIL_TRANSACTIONAL)
class MembershipPurchasedEmail:
    key = f"{_PURCHASED}.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent,
        recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        name = _collective(ctx)
        terms = _terms(ctx)
        subject = f"You've joined {name}"
        opening = f"Your membership of {name} is active."
        if ctx.get("one_time"):
            money = (
                f"You paid {terms} to join. There's nothing further to pay "
                "and no renewal — your membership continues."
                if terms else
                "There's nothing further to pay and no renewal."
            )
        else:
            renews = _fmt_date(ctx.get("next_renewal_at"))
            money = (
                f"Your membership costs {terms} and continues until you "
                "cancel it."
                if terms else
                "Your membership continues until you cancel it."
            )
            if renews:
                money += f" Your next payment is on {renews}."
        return _payload(
            db, subject=subject, greeting=_greeting(ctx.get("first_name")),
            opening=opening, paragraphs=[opening, money],
            action=("Go to the collective", ctx.get("collective_url") or ""),
            signoff="You can manage your membership any time in Fresh "
                    "Collective.",
            notification_type="collective_membership_purchased",
        )


@template_for(_PURCHASED, CHANNEL_IN_APP)
class MembershipPurchasedInApp:
    key = f"{_PURCHASED}.in_app"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        return RenderedPayload(
            to="", subject=f"You've joined {_collective(ctx)}",
            body_html="", body_text="Your membership is active.",
            metadata={"notification_type": "collective_membership_purchased"},
        )


# ---------------------------------------------------------------------------
# Renewed
# ---------------------------------------------------------------------------


@template_for(_RENEWED, CHANNEL_EMAIL_TRANSACTIONAL)
class MembershipRenewedEmail:
    key = f"{_RENEWED}.email_transactional"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        name = _collective(ctx)
        terms = _terms(ctx)
        period = (ctx.get("period_label") or "").strip()
        subject = f"Your {name} membership payment"
        opening = (
            f"We've received your membership payment for {name}."
            if not terms else
            f"We've received your {terms.split()[0]} membership payment "
            f"for {name}."
        )
        detail = f"This covers {period}." if period else ""
        renews = _fmt_date(ctx.get("next_renewal_at"))
        next_up = f"Your next payment is on {renews}." if renews else ""
        return _payload(
            db, subject=subject, greeting=_greeting(ctx.get("first_name")),
            opening=opening, paragraphs=[opening, detail, next_up],
            action=("Go to the collective", ctx.get("collective_url") or ""),
            signoff="", notification_type="collective_membership_renewed",
        )


@template_for(_RENEWED, CHANNEL_IN_APP)
class MembershipRenewedInApp:
    key = f"{_RENEWED}.in_app"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        return RenderedPayload(
            to="", subject=f"{_collective(ctx)} membership payment received",
            body_html="", body_text="Your membership payment was received.",
            metadata={"notification_type": "collective_membership_renewed"},
        )


# ---------------------------------------------------------------------------
# Payment failed
# ---------------------------------------------------------------------------


@template_for(_FAILED, CHANNEL_EMAIL_TRANSACTIONAL)
class MembershipPaymentFailedEmail:
    key = f"{_FAILED}.email_transactional"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        name = _collective(ctx)
        deadline = _fmt_date(ctx.get("grace_expires_at"))
        subject = f"There's a problem with your {name} membership payment"
        opening = (
            f"We couldn't process your latest membership payment for {name}."
        )
        # States plainly that access CONTINUES. Nothing is paused yet.
        reassurance = (
            "Your membership is still active and nothing has changed yet. "
            "We'll keep trying the payment."
        )
        window = (
            f"If it hasn't succeeded by {deadline}, your membership will "
            "pause and you'll lose access to members-only experiences "
            "until it's resolved."
            if deadline else
            "If it can't be recovered, your membership will pause and "
            "you'll lose access to members-only experiences until it's "
            "resolved."
        )
        return _payload(
            db, subject=subject, greeting=_greeting(ctx.get("first_name")),
            opening=opening, paragraphs=[opening, reassurance, window],
            action=("Update your payment details", _manage(ctx)),
            signoff="If your card details haven't changed, no action is "
                    "needed — we'll keep trying.",
            notification_type="collective_membership_payment_failed",
        )


@template_for(_FAILED, CHANNEL_IN_APP)
class MembershipPaymentFailedInApp:
    key = f"{_FAILED}.in_app"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        return RenderedPayload(
            to="", subject=f"Payment problem — {_collective(ctx)}",
            body_html="",
            body_text="Update your payment details to keep your membership.",
            metadata={
                "notification_type": "collective_membership_payment_failed",
            },
        )


# ---------------------------------------------------------------------------
# Cancellation scheduled — nothing is lost yet
# ---------------------------------------------------------------------------


@template_for(_SCHEDULED, CHANNEL_EMAIL_TRANSACTIONAL)
class MembershipCancellationScheduledEmail:
    key = f"{_SCHEDULED}.email_transactional"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        name = _collective(ctx)
        until = _fmt_date(ctx.get("access_until"))
        subject = f"Your {name} membership won't renew"
        opening = "You won't be charged again."
        # The distinction §15 names: this is not an ending.
        keeps = (
            f"Your membership stays active until {until}, and you keep full "
            "access until then."
            if until else
            "Your membership stays active until the end of the period "
            "you've paid for, and you keep full access until then."
        )
        resume = (
            "Changed your mind? You can turn renewal back on any time "
            "before then."
        )
        return _payload(
            db, subject=subject, greeting=_greeting(ctx.get("first_name")),
            opening=opening, paragraphs=[opening, keeps, resume],
            action=("Manage your membership", _manage(ctx)),
            signoff="",
            notification_type=(
                "collective_membership_cancellation_scheduled"
            ),
        )


@template_for(_SCHEDULED, CHANNEL_IN_APP)
class MembershipCancellationScheduledInApp:
    key = f"{_SCHEDULED}.in_app"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        until = _fmt_date(ctx.get("access_until"))
        return RenderedPayload(
            to="", subject=f"{_collective(ctx)} membership won't renew",
            body_html="",
            body_text=(
                f"You keep access until {until}." if until
                else "You keep access until the end of your paid period."
            ),
            metadata={
                "notification_type":
                    "collective_membership_cancellation_scheduled",
            },
        )


# ---------------------------------------------------------------------------
# Ended
# ---------------------------------------------------------------------------


@template_for(_ENDED, CHANNEL_EMAIL_TRANSACTIONAL)
class MembershipEndedEmail:
    key = f"{_ENDED}.email_transactional"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        name = _collective(ctx)
        subject = f"Your {name} membership has ended"
        opening = (
            f"Your membership of {name} has ended and you no longer have "
            "access to members-only experiences."
        )
        # What they bought separately is theirs, and saying so saves a
        # support conversation.
        kept = (
            "Anything you bought separately — a pathway, a ticket, a "
            "series pass or a download — is unaffected and still yours."
        )
        back = "You're welcome back any time."
        return _payload(
            db, subject=subject, greeting=_greeting(ctx.get("first_name")),
            opening=opening, paragraphs=[opening, kept, back],
            action=("Rejoin", ctx.get("collective_url") or ""),
            signoff="", notification_type="collective_membership_ended",
        )


@template_for(_ENDED, CHANNEL_IN_APP)
class MembershipEndedInApp:
    key = f"{_ENDED}.in_app"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        return RenderedPayload(
            to="", subject=f"Your {_collective(ctx)} membership has ended",
            body_html="",
            body_text="Anything you bought separately is still yours.",
            metadata={"notification_type": "collective_membership_ended"},
        )


# ---------------------------------------------------------------------------
# Reactivated
# ---------------------------------------------------------------------------


@template_for(_REACTIVATED, CHANNEL_EMAIL_TRANSACTIONAL)
class MembershipReactivatedEmail:
    key = f"{_REACTIVATED}.email_transactional"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        name = _collective(ctx)
        subject = f"You're back in {name}"
        opening = (
            f"Your membership of {name} is active again and your access "
            "has resumed."
        )
        renews = _fmt_date(ctx.get("next_renewal_at"))
        next_up = f"Your next payment is on {renews}." if renews else ""
        return _payload(
            db, subject=subject, greeting=_greeting(ctx.get("first_name")),
            opening=opening, paragraphs=[opening, next_up],
            action=("Go to the collective", ctx.get("collective_url") or ""),
            signoff="",
            notification_type="collective_membership_reactivated",
        )


@template_for(_REACTIVATED, CHANNEL_IN_APP)
class MembershipReactivatedInApp:
    key = f"{_REACTIVATED}.in_app"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        return RenderedPayload(
            to="", subject=f"You're back in {_collective(ctx)}",
            body_html="", body_text="Your access has resumed.",
            metadata={
                "notification_type": "collective_membership_reactivated",
            },
        )
