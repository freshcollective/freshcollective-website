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

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.base import render_email_shell
from app.comms.templates.registry import template_for

_PURCHASED   = "collective.membership.purchased"
_RENEWAL_RESUMED = "collective.membership.renewal_resumed"
_PM_UPDATED = "collective.membership.payment_method_updated"
_DEPARTED = "collective.membership.voluntary_departure"
_DEPARTURE_BILLING_STOPPED = (
    "collective.membership.departure_billing_stopped"
)
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


def _fmt_date(iso: str | None, tz_name: str | None = None) -> str:
    """'5 September 2026', or empty when absent. Never raises.

    Rendered in ``tz_name`` when one is given. Stored instants are
    UTC-naive, so a period ending late in the UTC day is already
    tomorrow where the member is — formatting the raw instant would
    show them a date a day early, which on a cancellation notice is
    the difference between keeping access and believing it has gone.

    There is no per-member timezone on this platform. The Collective's
    is the reference ``membership_pricing.transition_instant`` already
    treats as authoritative for membership dates, so it is the one
    used here too. Without a name, behaviour is unchanged.
    """
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return ""
    if tz_name:
        from app.services.discount_pricing import collective_timezone

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        dt = dt.astimezone(collective_timezone(tz_name))
    return dt.strftime("%-d %B %Y")


def _fmt_datetime(iso: str | None, tz_name: str | None = None) -> str:
    """'21 December 2026 at 1:00 am', or empty when absent.

    For the moment access *stops*, where a bare calendar date is a
    small lie: a membership ending at 1:00 am on the 21st does not give
    anybody the 21st, and "until 21 December" says it does. Payment
    dates keep the plain date — they are day-level facts and a time on
    them is noise.

    No timezone abbreviation. "AEDT" means nothing to most readers and
    the date is already rendered where they are.
    """
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return ""
    if tz_name:
        from app.services.discount_pricing import collective_timezone

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        dt = dt.astimezone(collective_timezone(tz_name))
    hour = dt.strftime("%-I:%M %p").lower()
    return f"{dt.strftime('%-d %B %Y')} at {hour}"


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
    signoff: str, notification_type: str, heading: str | None = None,
) -> RenderedPayload:
    """``heading`` defaults to the subject, which is right for most of
    these. A cancellation says more in the inbox than it needs to on
    the page — the Collective is named in the subject line so it is
    identifiable at a glance, and the heading, read with that Collective
    already in mind, does not repeat it."""
    body_text = "\n\n".join(
        [greeting, *[p for p in paragraphs if p]]
        + ([f"{action[0]}:\n{action[1]}"] if action and action[1] else [])
        + ([signoff] if signoff else [])
    )
    body_html = render_email_shell(
        db=db,
        preheader=opening,
        heading=heading or subject,
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
            renews = _fmt_date(
                ctx.get("next_renewal_at"), ctx.get("collective_timezone"),
            )
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
            metadata={
                # Where this notification goes when tapped. The
                # provider reads ``metadata["url"]`` as the
                # click-through destination and treats it as optional —
                # which is why these six arrived unclickable. Both URLs
                # are already built by ``_base_payload`` through
                # ``public_app_url``, so nothing is assembled here.
                "notification_type": "collective_membership_purchased",
                "url": ctx.get("collective_url") or "",
            },
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
        renews = _fmt_date(
            ctx.get("next_renewal_at"), ctx.get("collective_timezone"),
        )
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
            metadata={
                "notification_type": "collective_membership_renewed",
                "url": ctx.get("membership_url") or "",
            },
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
        deadline = _fmt_datetime(
            ctx.get("grace_expires_at"), ctx.get("collective_timezone"),
        )
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
                "url": ctx.get("membership_url") or "",
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
        # Access stops at a moment, not on a day. "until 21 December"
        # promises somebody the whole of the 21st when a period ending
        # at 1:00 am gives them an hour of it.
        until = _fmt_datetime(
            ctx.get("access_until"), ctx.get("collective_timezone"),
        )
        # "won't renew" read as a renewal that had failed rather than
        # one the member had just stopped on purpose. Every line now
        # says who did this and that it worked.
        subject = f"Your {name} membership renewal has been cancelled"
        heading = "Your membership renewal has been cancelled"
        opening = (
            f"You've successfully cancelled your membership renewal for "
            f"{name}."
        )
        keeps = (
            f"You'll continue to have access until {until}, and no further "
            "payments will be taken."
            if until else
            "You'll continue to have access until the end of the period "
            "you've paid for, and no further payments will be taken."
        )
        # Said here as well as in the confirmation dialog, because an
        # email is what a member keeps and comes back to.
        after = (
            "After that date, you'll lose access to the Collective and its "
            "included Pathways and Gatherings. You'll still be able to "
            "access any Offerings you've purchased separately."
        )
        resume = (
            f"Changed your mind? You can resume your membership renewal any "
            f"time before {until} in your Fresh Collective account settings."
            if until else
            "Changed your mind? You can resume your membership renewal any "
            "time before then in your Fresh Collective account settings."
        )
        return _payload(
            db, subject=subject, heading=heading,
            greeting=_greeting(ctx.get("first_name")),
            opening=opening, paragraphs=[opening, keeps, after, resume],
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
        # Access stops at a moment, not on a day. "until 21 December"
        # promises somebody the whole of the 21st when a period ending
        # at 1:00 am gives them an hour of it.
        until = _fmt_datetime(
            ctx.get("access_until"), ctx.get("collective_timezone"),
        )
        # Same two facts as the email, in the length a notification has.
        return RenderedPayload(
            to="",
            subject=(
                f"You've successfully cancelled your renewal for "
                f"{_collective(ctx)}."
            ),
            body_html="",
            body_text=(
                f"You'll retain access until {until}." if until
                else "You'll retain access until the end of your paid period."
            ),
            metadata={
                "notification_type":
                    "collective_membership_cancellation_scheduled",
                "url": ctx.get("membership_url") or "",
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
            metadata={
                "notification_type": "collective_membership_ended",
                "url": ctx.get("membership_url") or "",
            },
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
        renews = _fmt_date(
            ctx.get("next_renewal_at"), ctx.get("collective_timezone"),
        )
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
                "url": ctx.get("collective_url") or "",
            },
        )


# ---------------------------------------------------------------------------
# Renewal resumed — they changed their mind, without ever losing access
# ---------------------------------------------------------------------------


@template_for(_RENEWAL_RESUMED, CHANNEL_EMAIL_TRANSACTIONAL)
class MembershipRenewalResumedEmail:
    key = f"{_RENEWAL_RESUMED}.email_transactional"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        name = _collective(ctx)
        tz = ctx.get("collective_timezone")
        when = _fmt_date(ctx.get("next_renewal_at"), tz)
        amount = (ctx.get("amount_label") or "").strip()
        subject = f"Your {name} membership renewal is back on"
        heading = "Your membership renewal is back on"
        opening = (
            f"You've successfully resumed your membership renewal for "
            f"{name}."
        )
        # A next payment the member can check against their own bank.
        # Both halves are optional because an agreement can be missing
        # either, and half a sentence is worse than a general one.
        if amount and when:
            continues = (
                f"Your membership will continue automatically, with your "
                f"next payment of {amount} scheduled for {when}."
            )
        elif when:
            continues = (
                f"Your membership will continue automatically, with your "
                f"next payment scheduled for {when}."
            )
        else:
            continues = "Your membership will continue automatically."
        nothing = "You don't need to do anything else."
        return _payload(
            db, subject=subject, heading=heading,
            greeting=_greeting(ctx.get("first_name")),
            opening=opening, paragraphs=[opening, continues, nothing],
            action=("Manage your membership", _manage(ctx)),
            signoff="",
            notification_type="collective_membership_renewal_resumed",
        )


@template_for(_RENEWAL_RESUMED, CHANNEL_IN_APP)
class MembershipRenewalResumedInApp:
    key = f"{_RENEWAL_RESUMED}.in_app"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        when = _fmt_date(
            ctx.get("next_renewal_at"), ctx.get("collective_timezone"),
        )
        return RenderedPayload(
            to="",
            subject=f"Your {_collective(ctx)} membership renewal is back on.",
            body_html="",
            body_text=(
                f"Your membership will continue, with your next payment "
                f"scheduled for {when}." if when
                else "Your membership will continue as before."
            ),
            metadata={
                "notification_type": "collective_membership_renewal_resumed",
                "url": ctx.get("membership_url") or "",
            },
        )


# ---------------------------------------------------------------------------
# Payment method updated — a security notice, not a receipt
# ---------------------------------------------------------------------------


@template_for(_PM_UPDATED, CHANNEL_EMAIL_TRANSACTIONAL)
class MembershipPaymentMethodUpdatedEmail:
    key = f"{_PM_UPDATED}.email_transactional"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        name = _collective(ctx)
        subject = "Your payment method has been updated"
        heading = "Payment method updated"
        opening = (
            f"The payment method for your membership with {name} has been "
            "successfully updated."
        )
        future = (
            "Your future membership payments will use your new payment "
            "method."
        )
        # Named explicitly because a card change is the moment somebody
        # wonders what *else* moved. Nothing did.
        unchanged = (
            "Your membership, payment amount and next renewal date remain "
            "unchanged."
        )
        review = (
            "You can review your membership details any time in your Fresh "
            "Collective account settings."
        )
        # No card number, brand or last four. The confirmation's job is
        # to tell somebody a change happened, and a card they do not
        # recognise is answered by the line below, not by more digits.
        query = (
            "Didn't make this change? Please contact Fresh Collective "
            "support at support@freshcollective.au."
        )
        return _payload(
            db, subject=subject, heading=heading,
            greeting=_greeting(ctx.get("first_name")),
            opening=opening,
            paragraphs=[opening, future, unchanged, review, query],
            action=("Manage your membership", _manage(ctx)),
            signoff="",
            notification_type="collective_membership_payment_method_updated",
        )


@template_for(_PM_UPDATED, CHANNEL_IN_APP)
class MembershipPaymentMethodUpdatedInApp:
    key = f"{_PM_UPDATED}.in_app"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        return RenderedPayload(
            to="",
            subject=f"Payment method updated for {_collective(ctx)}",
            body_html="",
            body_text=(
                "Your future membership payments will use your new payment "
                "method."
            ),
            metadata={
                "notification_type":
                    "collective_membership_payment_method_updated",
                "url": ctx.get("membership_url") or "",
            },
        )


# ---------------------------------------------------------------------------
# Voluntary departure — their decision, and what it did to the billing
# ---------------------------------------------------------------------------


def _departure_billing_line(ctx: dict) -> str:
    """What to promise about future payments, and nothing more.

    Cancelling at Stripe can fail while the departure succeeds, by
    design — a member must be able to leave when Stripe is
    unreachable. Telling them payments have stopped when we have not
    managed to stop them is the one sentence this message must not
    contain.
    """
    if ctx.get("billing_cancelled"):
        return (
            "Your membership subscription has been cancelled, so no "
            "further payments will be taken."
        )
    return (
        "We're still finalising the cancellation of your membership "
        "subscription with our payment provider. We'll confirm as soon "
        "as it's done, and you don't need to do anything."
    )


@template_for(_DEPARTED, CHANNEL_EMAIL_TRANSACTIONAL)
class MembershipVoluntaryDepartureEmail:
    key = f"{_DEPARTED}.email_transactional"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        name = _collective(ctx)
        subject = f"You've left {name}"
        heading = "You've left this collective"
        opening = f"You've left {name}, and your membership has ended."
        lost = (
            "Its Pathways, Gatherings and member-only spaces are no longer "
            "available to you."
        )
        kept = (
            "Anything you bought separately stays yours — Offerings in Your "
            "Collection, and any other purchases you made outright."
        )
        back = (
            f"You're welcome to rejoin {name} later, subject to its "
            "membership requirements."
        )
        return _payload(
            db, subject=subject, heading=heading,
            greeting=_greeting(ctx.get("first_name")),
            opening=opening,
            paragraphs=[opening, _departure_billing_line(ctx), lost, kept, back],
            action=("Manage your memberships", _manage(ctx)),
            signoff="",
            notification_type="collective_membership_voluntary_departure",
        )


@template_for(_DEPARTED, CHANNEL_IN_APP)
class MembershipVoluntaryDepartureInApp:
    key = f"{_DEPARTED}.in_app"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        return RenderedPayload(
            to="", subject=f"You've left {_collective(ctx)}",
            body_html="",
            body_text=(
                "Your membership has ended. "
                + ("Your subscription is cancelled and no further payments "
                   "will be taken."
                   if ctx.get("billing_cancelled") else
                   "We're still finalising the cancellation of your "
                   "subscription and will confirm when it's done.")
            ),
            metadata={
                "notification_type":
                    "collective_membership_voluntary_departure",
                "url": ctx.get("membership_url") or "",
            },
        )


@template_for(_DEPARTURE_BILLING_STOPPED, CHANNEL_EMAIL_TRANSACTIONAL)
class MembershipDepartureBillingStoppedEmail:
    key = f"{_DEPARTURE_BILLING_STOPPED}.email_transactional"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        name = _collective(ctx)
        subject = f"Your {name} membership payments have stopped"
        heading = "Your membership payments have stopped"
        # Deliberately refers back. The member was told this was being
        # finalised; this closes that sentence rather than arriving as
        # news about a membership they already know they left.
        opening = (
            f"The membership subscription for {name} has now been "
            "cancelled with our payment provider, so no further payments "
            "will be taken."
        )
        context_line = (
            "You left this collective earlier, and this confirms the part "
            "we were still finalising. Nothing else has changed."
        )
        return _payload(
            db, subject=subject, heading=heading,
            greeting=_greeting(ctx.get("first_name")),
            opening=opening, paragraphs=[opening, context_line],
            action=("Manage your memberships", _manage(ctx)),
            signoff="",
            notification_type=(
                "collective_membership_departure_billing_stopped"
            ),
        )


@template_for(_DEPARTURE_BILLING_STOPPED, CHANNEL_IN_APP)
class MembershipDepartureBillingStoppedInApp:
    key = f"{_DEPARTURE_BILLING_STOPPED}.in_app"
    version = "v1"

    def render(self, db, event, recipient) -> RenderedPayload:
        ctx = recipient.template_context
        return RenderedPayload(
            to="",
            subject=f"{_collective(ctx)} payments have stopped",
            body_html="",
            body_text=(
                "The subscription cancellation we were finalising is "
                "complete. No further payments will be taken."
            ),
            metadata={
                "notification_type":
                    "collective_membership_departure_billing_stopped",
                "url": ctx.get("membership_url") or "",
            },
        )
