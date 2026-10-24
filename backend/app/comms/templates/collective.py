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
_EVENT_WELCOME = "collective.membership.welcome"


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
    # The same verb the email uses, so the in-app notification and the
    # email do not describe one event two different ways. Falls back to
    # "joined" for an event emitted before the verb existed on the
    # payload, which is exactly what those events used to say.
    verb = (ctx.get("purchase_verb") or "joined").strip() or "joined"
    suffix = ctx.get("purchase_suffix") or ""
    headline = f"{buyer} {verb} {what}{suffix}"

    amount = (ctx.get("amount_display") or "").strip()
    if ctx.get("is_free"):
        # Said plainly. A creator reading "their access is open" with no
        # amount beside it would be left to work out whether a payment
        # failed to record; nothing was owed, and the line says so.
        detail = "It was free, so no payment was taken. Their access is open."
    elif ctx.get("payment_mode") == "plan":
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
        # ``detail`` stays in code: it states the amount and the access
        # granted, which is fact rather than voice, and the declaration
        # deliberately offers no slot for it.
        _, detail = _purchase_lines(ctx)
        collective = (ctx.get("collective_name") or "").strip() or "your Collective"
        cta_url = ctx.get("cta_url") or ""

        # THROUGH THE DECLARED SLOTS, deliberately.
        #
        # This template declared four editable slots but used to build
        # its copy from ``_purchase_lines`` instead, so an admin editing
        # it in World Management changed the preview and nothing else.
        # It was the only declared-editable template in the codebase
        # that bypassed its own slots; ``test_editable_templates_are_
        # wired`` now makes that impossible to reintroduce.
        r = resolver_for(db, self.key, {
            **ctx,
            "collective_name": collective,
            "purchase_name": (ctx.get("experience_name") or "").strip(),
            "purchase_verb": (ctx.get("purchase_verb") or "joined"),
            # Empty for every paid purchase, which is why adding it to
            # the slot defaults changed no paid wording.
            "purchase_suffix": (ctx.get("purchase_suffix") or ""),
        })
        subject = r.text("subject")
        headline = r.text("heading")
        opening = r.text("body.opening")
        cta_label = r.text("cta_label")

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
            action=(cta_label, cta_url),
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


# ---------------------------------------------------------------------------
# collective.membership.welcome — the Collective's own greeting
# ---------------------------------------------------------------------------


@template_for(_EVENT_WELCOME, CHANNEL_EMAIL_TRANSACTIONAL)
class CollectiveMembershipWelcomeEmailTemplate:
    """The welcome a Collective sends the first time someone joins it.

    Every line of voice is a declared slot, so this renders entirely
    through ``resolver_for`` — platform default underneath, the
    Collective's own customisation on top. The **destination is not a
    slot**: ``collective_url`` is generated by the platform from the
    Collective's slug and passed to the shell as the CTA, so a creator
    can rename the button but can never aim it somewhere else.

    Scoped by ``space_id`` from the payload. That single argument is
    what makes one Collective's copy invisible to another, and it is
    why the preview a creator sees is rendered through this same path
    rather than a preview-only one.
    """

    key = "collective.membership.welcome.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        collective = (ctx.get("collective_name") or "").strip() or "your Collective"
        first_name = (ctx.get("member_first_name") or "").strip()
        collective_url = ctx.get("collective_url") or ""

        space_id = ctx.get("space_id") or None
        r = resolver_for(db, self.key, {
            **ctx,
            "collective_name": collective,
            "member_first_name": first_name or "there",
        }, space_id=space_id)

        # The Collective's own artwork, resolved HERE rather than
        # carried on the event. Two reasons: a creator who changes
        # their Location in Place & Feel changes the next welcome too,
        # and the Creator Studio preview renders through this very
        # line — so the preview cannot show artwork a real send would
        # not. ``None`` when the Collective has chosen no Location,
        # and the shell then simply omits the image.
        banner_url = None
        if db is not None and space_id:
            from app.brand.resolver import collective_artwork_for_email
            banner_url = collective_artwork_for_email(db, space_id)

        subject = r.text("subject")
        heading = r.text("heading")
        message = r.text("body.message")
        cta_label = r.text("cta_label")
        signature = r.text("signature")

        # The message is authored as prose and may run to several
        # paragraphs; blank lines separate them, exactly as the creator
        # typed them into the editor.
        paragraphs = [
            seg.strip() for seg in message.split("\n\n") if seg.strip()
        ] or [message]

        body_text = (
            f"{heading}\n\n{message}\n\n"
            f"{cta_label}: {collective_url}\n\n{signature}\n"
        )
        body_html = render_email_shell(
            db=db,
            preheader=heading,
            heading=heading,
            body_paragraphs=paragraphs,
            # Alt text names the Collective, because most clients
            # block remote images by default — for a large share of
            # recipients this text IS the artwork, and "Moonlit
            # Circle" tells them where they have arrived where
            # "banner image" would not.
            banner=(banner_url, collective) if banner_url else None,
            # The Collective's artwork is the hero here, so the Fresh
            # Collective mark moves to the footer — present as the
            # platform holding the connection, not as the sender being
            # introduced. With no artwork the card simply opens on the
            # welcome heading rather than on a 200px platform logo.
            brand_placement="footer",
            action=(cta_label, collective_url) if collective_url else None,
            signoff=signature,
            # The creator wrote this one, so it is set as part of the
            # message rather than as a platform footnote. Every other
            # template keeps the muted default.
            signoff_style="body",
            # A welcome is preference-controlled rather than
            # transactional, so the preferences link belongs here: a
            # member who would rather not hear from Collectives must be
            # able to say so from the first message they receive.
            show_preferences_link=True,
        )
        return RenderedPayload(
            to="", subject=subject, body_html=body_html, body_text=body_text,
            metadata={"notification_type": "collective_membership_welcome"},
        )
