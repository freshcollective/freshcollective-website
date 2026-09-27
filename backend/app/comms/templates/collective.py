"""Templates for collective-membership events.

R2A coverage: ``collective.invitation.sent`` — the email a
prospective member receives when a creator sends them an invitation
to a Collective. Content mirrors the tone of the legacy
``services/email_templates.py::invitation_email`` template so the
switch is invisible to the recipient.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.base import render_email_shell
from app.comms.templates.editable import resolver_for
from app.comms.templates.registry import template_for


_EVENT = "collective.invitation.sent"


@template_for(_EVENT, CHANNEL_EMAIL_TRANSACTIONAL)
class InvitationSentEmailTemplate:
    key = "collective.invitation.sent.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        inviter_name    = ctx.get("inviter_name") or "A creator"
        collective_name = ctx.get("collective_name") or "a Collective"
        accept_url      = ctx.get("accept_url") or ""

        r = resolver_for(db, self.key, {
            **ctx,
            "inviter_name": inviter_name,
            "collective_name": collective_name,
        })
        subject = r.text("subject")
        opening = r.text("body.opening")
        instruction = r.text("body.instruction")
        cta = r.text("cta_label")

        body_text = (
            f"{opening}\n\n"
            # The plain-text part introduces the bare URL, so the
            # instruction ends in a colon there rather than a full stop.
            f"{instruction.rstrip('.')}:\n"
            f"{accept_url}"
        )

        # No preferences link: the invitee usually has no account yet, so
        # there are no preferences for them to manage.
        body_html = render_email_shell(
            db=db,
            preheader=opening,
            heading=r.text("heading"),
            body_paragraphs=[opening, instruction],
            action=(cta, accept_url),
            show_preferences_link=False,
        )

        return RenderedPayload(
            to="",  # decision pipeline fills recipient_address on the intent
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "collective_invitation_sent"},
        )


# ---------------------------------------------------------------------------
# Someone bought access to a Collective you run
# ---------------------------------------------------------------------------

_EVENT_PURCHASE_RECEIVED = "collective.purchase.received"


def _purchase_lines(ctx: dict) -> tuple[str, str]:
    """(headline, detail) — the two facts a Creator wants first.

    Names the buyer and what they bought, and nothing about payment
    mechanics. A payment plan says its first payment has landed, because
    that is the moment access is actually granted; saying "paid in full"
    there would be untrue.
    """
    buyer = (ctx.get("buyer_name") or "").strip() or "Someone"
    experience = (ctx.get("experience_name") or "").strip()
    collective = (ctx.get("collective_name") or "").strip() or "your Collective"

    what = f"“{experience}”" if experience else f"access to {collective}"
    headline = f"{buyer} joined {what}"

    amount = (ctx.get("amount_display") or "").strip()
    if ctx.get("payment_mode") == "plan":
        detail = (
            f"Their first payment{f' of {amount}' if amount else ''} has gone "
            "through and their access is open."
        )
    else:
        detail = (
            f"They paid {amount} and their access is open."
            if amount else "Their access is open."
        )

    count = ctx.get("session_count")
    if isinstance(count, int) and count > 1:
        detail += f" That covers {count} Gatherings."
    return headline, detail


@template_for(_EVENT_PURCHASE_RECEIVED, CHANNEL_EMAIL_TRANSACTIONAL)
class CollectivePurchaseReceivedEmailTemplate:
    key = "collective.purchase.received.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        headline, detail = _purchase_lines(ctx)
        collective = (ctx.get("collective_name") or "").strip() or "your Collective"
        cta_url = ctx.get("cta_url") or ""

        subject = f"{headline} — {collective}"
        opening = f"{headline} in {collective}."

        body_text = (
            f"Hi,\n\n{opening}\n\n{detail}\n\n"
            f"See them in Creator Studio:\n{cta_url}\n"
        )
        body_html = render_email_shell(
            db=db,
            preheader=opening,
            heading=headline,
            greeting="Hi,",
            body_paragraphs=[opening, detail],
            action=("Open Creator Studio", cta_url),
            # CATEGORY_PURCHASES is locked for email_transactional, so a
            # preferences link would offer a control that does not exist.
            # Same reasoning as the creator-billing emails.
            show_preferences_link=False,
        )
        return RenderedPayload(
            to="", subject=subject, body_html=body_html, body_text=body_text,
            metadata={"notification_type": "collective_purchase_received"},
        )


@template_for(_EVENT_PURCHASE_RECEIVED, CHANNEL_IN_APP)
class CollectivePurchaseReceivedInAppTemplate:
    key = "collective.purchase.received.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        headline, detail = _purchase_lines(ctx)
        return RenderedPayload(
            to="", subject=headline, body_text=detail,
            metadata={
                "notification_type": "collective_purchase_received",
                "url": ctx.get("cta_url"),
            },
        )
