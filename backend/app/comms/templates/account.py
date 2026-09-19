"""Templates for account category events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.base import render_email_shell
from app.comms.templates.editable import resolver_for
from app.comms.templates.registry import template_for
from app.services.creator_plan_labels import creator_facing_plan_label


_EVENT_PASSWORD_RESET_REQUESTED     = "account.password_reset_requested"
_EVENT_WELCOME_AFTER_SIGNUP         = "account.welcome_after_signup"
_EVENT_EMAIL_VERIFICATION_REQUESTED = "account.email_verification_requested"
_EVENT_CREATOR_PLAN_ACTIVATED       = "creator.plan_activated"


# Every event in this module resolves to CATEGORY_ACCOUNT, which is
# locked for email_transactional (``communication_channel_defaults``).
# A member cannot switch these off, so the footer does not offer them a
# preferences link they cannot act on.
_SHOW_PREFS = False


# ---------------------------------------------------------------------------
# Greetings
# ---------------------------------------------------------------------------

# P1 product decision — the two emails a brand-new account receives
# (verify, then welcome) greet everyone identically and do NOT derive a
# name from ``users.name``. That field is unvalidated free text used as
# a legal/display name, and whatever a person typed at signup was being
# echoed back as the way Fresh Collective addresses them. Fixing the
# name architecture is deliberately out of scope for this phase; not
# greeting a stranger by an unverified string is the safe default in
# the meantime.
FRIEND_GREETING = "Hey friend,"


def _greeting(first_name: str | None) -> str:
    """Name-derived greeting, retained for emails sent to accounts whose
    identity is already established (see ``FRIEND_GREETING`` above for
    why the two signup emails no longer use this)."""
    name = (first_name or "").strip()
    return f"Hi {name}," if name else "Hi,"


@template_for(_EVENT_PASSWORD_RESET_REQUESTED, CHANNEL_EMAIL_TRANSACTIONAL)
class PasswordResetRequestedEmailTemplate:
    key = "account.password_reset_requested.email_transactional"
    version = "v2"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        reset_url = recipient.template_context.get("reset_url") or ""
        subject = "Reset your Fresh Collective password"
        body_text = (
            "You asked to reset your password.\n\n"
            f"Open this link to choose a new one:\n{reset_url}\n\n"
            "If you didn't request this, you can safely ignore this message."
        )
        body_html = render_email_shell(
            preheader="You asked to reset your password.",
            heading="Reset your password",
            body_paragraphs=[
                "You asked to reset your password.",
                "If you didn't request this, you can safely ignore this "
                "message.",
            ],
            action=("Choose a new password", reset_url),
            show_preferences_link=_SHOW_PREFS,
        )
        return RenderedPayload(
            to="",  # decision pipeline fills recipient_address on the intent
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "password_reset_requested"},
        )


@template_for(_EVENT_PASSWORD_RESET_REQUESTED, CHANNEL_IN_APP)
class PasswordResetRequestedInAppTemplate:
    key = "account.password_reset_requested.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        return RenderedPayload(
            to="",
            subject="Password reset requested",
            body_text="A password reset link was sent to your email.",
            metadata={"notification_type": "password_reset_requested"},
        )


# ---------------------------------------------------------------------------
# Email verification requested (SEC-009) — the ONE email a new
# unverified account receives at signup. Warm but verification-first.
# The existing WelcomeAfterSignup templates below fire AFTER
# successful verification, so a new account gets exactly two account
# emails across its lifetime: verify → welcome.
# ---------------------------------------------------------------------------


@template_for(_EVENT_EMAIL_VERIFICATION_REQUESTED, CHANNEL_EMAIL_TRANSACTIONAL)
class EmailVerificationRequestedEmailTemplate:
    key = "account.email_verification_requested.email_transactional"
    version = "v2"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        verify_url = ctx.get("verify_url") or ""
        r = resolver_for(db, self.key, ctx)

        greeting = r.text("greeting")
        subject = r.text("subject")
        welcome = r.text("body.welcome")
        why = r.text("body.why")
        cta = r.text("cta_label")
        signoff = r.text("signoff")
        # Locked: the expiry sentence states how the link actually
        # behaves, so it is not an editable slot.
        expiry = (
            "This link is good for 24 hours. If it expires you can request "
            "a fresh one from your dashboard."
        )

        body_text = (
            f"{greeting}\n\n"
            f"{welcome}\n\n"
            f"{why}\n\n"
            f"{cta}:\n{verify_url}\n\n"
            f"{expiry}\n\n"
            f"{signoff}"
        )
        body_html = render_email_shell(
            # Deliberately a tighter line than the body — this is the
            # inbox preview, not the first paragraph. Not a slot in
            # this phase.
            preheader=(
                "Confirm your email address so we know we can reach you "
                "when it matters."
            ),
            heading=r.text("heading"),
            greeting=greeting,
            body_paragraphs=[welcome, why, expiry],
            action=(cta, verify_url),
            signoff=signoff,
            show_preferences_link=_SHOW_PREFS,
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "email_verification_requested"},
        )


@template_for(_EVENT_EMAIL_VERIFICATION_REQUESTED, CHANNEL_IN_APP)
class EmailVerificationRequestedInAppTemplate:
    key = "account.email_verification_requested.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        return RenderedPayload(
            to="",
            subject="Please verify your email",
            body_text=(
                "We sent a verification link to your email. "
                "Verify to start joining Collectives and Gatherings."
            ),
            metadata={"notification_type": "email_verification_requested"},
        )


# ---------------------------------------------------------------------------
# Welcome after signup
# ---------------------------------------------------------------------------


@template_for(_EVENT_WELCOME_AFTER_SIGNUP, CHANNEL_EMAIL_TRANSACTIONAL)
class WelcomeAfterSignupEmailTemplate:
    key = "account.welcome_after_signup.email_transactional"
    version = "v2"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        next_url = ctx.get("next_url") or ""
        r = resolver_for(db, self.key, ctx)

        greeting = r.text("greeting")
        subject = r.text("subject")
        opening = r.text("body.opening")
        reassurance = r.text("body.reassurance")
        cta = r.text("cta_label")
        signoff = r.text("signoff")

        body_text = (
            f"{greeting}\n\n"
            f"{opening}\n\n"
            f"{reassurance}\n\n"
            f"When you're ready, {cta.lower()} here:\n{next_url}\n\n"
            f"{signoff}"
        )
        body_html = render_email_shell(
            preheader="Your account is ready.",
            heading=r.text("heading"),
            greeting=greeting,
            body_paragraphs=[opening, reassurance],
            action=(cta, next_url),
            signoff=signoff,
            show_preferences_link=_SHOW_PREFS,
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "welcome_after_signup"},
        )


@template_for(_EVENT_WELCOME_AFTER_SIGNUP, CHANNEL_IN_APP)
class WelcomeAfterSignupInAppTemplate:
    key = "account.welcome_after_signup.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        next_url = ctx.get("next_url") or ""
        return RenderedPayload(
            to="",
            subject="Welcome to Fresh Collective",
            body_text=(
                "Your account is ready. Take your time — there's no rush."
            ),
            metadata={
                "notification_type": "welcome_after_signup",
                "url": next_url,
            },
        )


# ---------------------------------------------------------------------------
# Creator plan activated
# ---------------------------------------------------------------------------


@template_for(_EVENT_CREATOR_PLAN_ACTIVATED, CHANNEL_EMAIL_TRANSACTIONAL)
class CreatorPlanActivatedEmailTemplate:
    key = "creator.plan_activated.email_transactional"
    version = "v2"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        greeting = _greeting(ctx.get("first_name"))
        # ``plan_name`` arrives as the internal ``CreatorPlan.name``,
        # which for the ``pro`` tier is the internal shorthand "Pro".
        # Translate to the creator-facing label before it reaches copy.
        plan_name = creator_facing_plan_label(
            slug=ctx.get("plan_slug"), name=ctx.get("plan_name"),
        )
        next_url = ctx.get("next_url") or ""
        is_fresh_creator = bool(ctx.get("is_fresh_creator"))

        # The creator-facing plan label is resolved above and handed to
        # the resolver, so an override using {{plan_label}} can never
        # surface the internal name.
        r = resolver_for(db, self.key, {**ctx, "plan_name": plan_name})
        signoff = r.text("signoff")

        # Subject unchanged across both variants — same event, same
        # transactional promise ("your plan is active").
        subject = r.text("subject")

        # Body + CTA branch on onboarding state. Fresh Creators get
        # oriented toward setting up their first Collective (which is
        # what /creator-onboarding leads into); already-onboarded
        # Creators are pointed straight at Creator Studio.
        if is_fresh_creator:
            supporting_line = r.text("body.fresh_creator")
            cta_label = r.text("cta_label.fresh_creator")
        else:
            supporting_line = r.text("body.returning_creator")
            cta_label = r.text("cta_label.returning_creator")

        activation_line = r.text("body.activation")

        body_text = (
            f"{greeting}\n\n"
            f"{activation_line}\n\n"
            f"{supporting_line}\n\n"
            f"{cta_label}:\n{next_url}\n\n"
            f"{signoff}"
        )
        body_html = render_email_shell(
            preheader=activation_line,
            heading=r.text("heading"),
            greeting=greeting,
            body_paragraphs=[activation_line, supporting_line],
            action=(cta_label, next_url),
            signoff=r.text("signoff"),
            show_preferences_link=_SHOW_PREFS,
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "creator_plan_activated"},
        )


@template_for(_EVENT_CREATOR_PLAN_ACTIVATED, CHANNEL_IN_APP)
class CreatorPlanActivatedInAppTemplate:
    key = "creator.plan_activated.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        plan_name = creator_facing_plan_label(
            slug=ctx.get("plan_slug"), name=ctx.get("plan_name"),
        )
        next_url = ctx.get("next_url") or ""
        is_fresh_creator = bool(ctx.get("is_fresh_creator"))
        body_text = (
            "Set up your first Collective when you’re ready."
            if is_fresh_creator
            else "Your Creator Studio is ready."
        )
        return RenderedPayload(
            to="",
            subject=f"Your {plan_name} plan is active",
            body_text=body_text,
            metadata={
                "notification_type": "creator_plan_activated",
                "url": next_url,
            },
        )
