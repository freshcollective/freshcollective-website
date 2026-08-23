"""Templates for account category events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.registry import template_for


_EVENT_PASSWORD_RESET_REQUESTED = "account.password_reset_requested"
_EVENT_WELCOME_AFTER_SIGNUP     = "account.welcome_after_signup"
_EVENT_CREATOR_PLAN_ACTIVATED   = "creator.plan_activated"


@template_for(_EVENT_PASSWORD_RESET_REQUESTED, CHANNEL_EMAIL_TRANSACTIONAL)
class PasswordResetRequestedEmailTemplate:
    key = "account.password_reset_requested.email_transactional"
    version = "v1"

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
        body_html = (
            "<p>You asked to reset your password.</p>"
            f'<p><a href="{reset_url}">Open this link to choose a new one</a>.</p>'
            "<p>If you didn't request this, you can safely ignore this message.</p>"
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
# Welcome after signup
# ---------------------------------------------------------------------------


def _greeting(first_name: str | None) -> str:
    name = (first_name or "").strip()
    return f"Hi {name}," if name else "Hi,"


@template_for(_EVENT_WELCOME_AFTER_SIGNUP, CHANNEL_EMAIL_TRANSACTIONAL)
class WelcomeAfterSignupEmailTemplate:
    key = "account.welcome_after_signup.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        greeting = _greeting(ctx.get("first_name"))
        next_url = ctx.get("next_url") or ""

        subject = "Welcome to Fresh Collective"
        body_text = (
            f"{greeting}\n\n"
            "Welcome to Fresh Collective. Your account is ready.\n\n"
            "Fresh Collective is a calm, structured place to gather, learn, "
            "and stay connected. Take your time — there's no rush.\n\n"
            f"When you're ready, sign in here:\n{next_url}\n\n"
            "We're glad you're here."
        )
        body_html = (
            f"<p>{greeting}</p>"
            "<p>Welcome to Fresh Collective. Your account is ready.</p>"
            "<p>Fresh Collective is a calm, structured place to gather, "
            "learn, and stay connected. Take your time — there's no rush.</p>"
            f'<p>When you\'re ready, <a href="{next_url}">sign in here</a>.</p>'
            "<p>We're glad you're here.</p>"
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
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        greeting = _greeting(ctx.get("first_name"))
        plan_name = (ctx.get("plan_name") or "").strip() or "Creator"
        next_url = ctx.get("next_url") or ""
        is_fresh_creator = bool(ctx.get("is_fresh_creator"))

        # Subject unchanged across both variants — same event, same
        # transactional promise ("your plan is active").
        subject = "Your Fresh Collective Creator plan is active"

        # Body + CTA branch on onboarding state. Fresh Creators get
        # oriented toward setting up their first Collective (which is
        # what /creator-onboarding leads into); already-onboarded
        # Creators are pointed straight at Creator Studio.
        if is_fresh_creator:
            supporting_line = (
                "Let’s set up your first Collective — the shape it takes, "
                "where it lives in the world, and who you want to gather. "
                "Fresh Collective walks you through it, one gentle step at a "
                "time."
            )
            cta_label = "Set up your Collective"
        else:
            supporting_line = (
                "Your Creator Studio is ready. From here you can publish "
                "pathways, plan Gatherings, and invite the people you want "
                "to gather."
            )
            cta_label = "Open Creator Studio"

        body_text = (
            f"{greeting}\n\n"
            f"Your Fresh Collective {plan_name} plan is now active.\n\n"
            f"{supporting_line}\n\n"
            f"{cta_label}:\n{next_url}\n\n"
            "Take your time — Fresh Collective is built for depth, not speed."
        )
        body_html = (
            f"<p>{greeting}</p>"
            f"<p>Your Fresh Collective <strong>{plan_name}</strong> plan is "
            "now active.</p>"
            f"<p>{supporting_line}</p>"
            f'<p><a href="{next_url}">{cta_label}</a>.</p>'
            "<p>Take your time — Fresh Collective is built for depth, "
            "not speed.</p>"
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
        plan_name = (ctx.get("plan_name") or "").strip() or "Creator"
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
