"""P1 — regression coverage for the canonical comms email shell.

Every ``email_transactional`` template in the comms pipeline renders
through :func:`app.comms.templates.base.render_email_shell`. These
tests pin three things:

1. **Structure** — each email is a full branded document, not a bare
   ``<p>`` fragment.
2. **Escaping** — user-generated strings (collective names, gathering
   titles, post titles, member names, experience names) cannot inject
   markup, and are not double-escaped.
3. **Greeting policy** — the two signup emails greet with a fixed
   phrase and never derive one from ``users.name``.

Nothing here touches the database, the routing pipeline or Resend;
templates are rendered directly. Preference / suppression behaviour is
covered by ``test_comms_preferences.py`` and
``test_comms_suppressions.py`` and is deliberately untouched by P1.
"""

from __future__ import annotations

import re

import pytest

import app.comms.templates  # noqa: F401 — registers every template
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.base import render_email_shell
from app.comms.templates.registry import get_template_for


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A string that is inert as text but becomes markup if unescaped.
XSS = '<img src=x onerror="alert(1)">'


def _recipient(**ctx) -> ResolvedRecipient:
    return ResolvedRecipient(
        user_id="u_1",
        role_in_event="recipient",
        human_reason="Because a test said so.",
        template_context=ctx,
    )


def _render(event_type: str, **ctx):
    template = get_template_for(event_type, CHANNEL_EMAIL_TRANSACTIONAL)
    assert template is not None, f"no email template for {event_type!r}"
    return template.render(None, None, _recipient(**ctx))


def _body_paragraphs(html: str) -> list[str]:
    """The shell's body paragraphs, in order. The greeting is the first
    entry when a template supplies one."""
    return [
        p.strip()
        for p in re.findall(
            r'<p style="margin:0;font-size:15\.5px[^"]*">\s*(.*?)\s*</p>',
            html,
            re.S,
        )
    ]


def _cta(html: str) -> tuple[str, str] | None:
    """(label, url) of the primary call to action, if present.

    Matches the pill button specifically (``border-radius:999px``) so
    the footer's preferences anchor is never mistaken for a CTA.
    """
    m = re.search(
        r'<a href="([^"]+)"\s+style="[^"]*border-radius:999px[^"]*">'
        r'\s*(.*?)\s*</a>',
        html,
        re.S,
    )
    return (m.group(2).strip(), m.group(1)) if m else None


def _assert_branded_shell(html: str) -> None:
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "Fresh Collective" in html          # brand mark + footer
    assert "#F5F0E8" in html                   # ivory page background
    assert "#38A09E" in html                   # teal accent
    assert "<h1" in html                       # heading slot
    assert "</html>" in html.rstrip()
    # The eyebrow treatment is deliberately not carried across from the
    # legacy renderer.
    assert "text-transform:uppercase" not in html


# Every comms email template, with a context rich enough to render.
# ``expect_cta`` is False for templates whose resolver supplies no URL.
ALL_EMAIL_TEMPLATES = [
    pytest.param(
        "account.email_verification_requested",
        {"first_name": "Ada", "verify_url": "https://fc.test/verify?t=1"},
        True, id="email_verification_requested",
    ),
    pytest.param(
        "account.welcome_after_signup",
        {"first_name": "Ada", "next_url": "https://fc.test/dashboard"},
        True, id="welcome_after_signup",
    ),
    pytest.param(
        "account.password_reset_requested",
        {"reset_url": "https://fc.test/reset?t=1"},
        True, id="password_reset_requested",
    ),
    pytest.param(
        "creator.plan_activated",
        {"first_name": "Grace", "plan_name": "Creator Portfolio",
         "next_url": "https://fc.test/studio", "is_fresh_creator": False},
        True, id="creator_plan_activated",
    ),
    pytest.param(
        "purchase.completed",
        {"first_name": "Ada", "experience_name": "Life in Alignment",
         "member_url": "https://fc.test/p/1", "payment_mode": "single",
         "amount_cents": 2000, "currency": "AUD"},
        True, id="purchase_completed",
    ),
    pytest.param(
        "payment.instalment_failed",
        {"first_name": "Ada", "experience_name": "Life in Alignment",
         "repair_url": "https://fc.test/fix", "amount_cents": 2000,
         "currency": "AUD", "grace_expires_at": "2026-10-01T00:00:00Z"},
        True, id="payment_instalment_failed",
    ),
    pytest.param(
        "access.suspended",
        {"first_name": "Ada", "experience_name": "Life in Alignment",
         "repair_url": "https://fc.test/fix"},
        True, id="access_suspended",
    ),
    pytest.param(
        "payment.recovered",
        {"first_name": "Ada", "experience_name": "Life in Alignment",
         "member_url": "https://fc.test/p/1", "was_suspended": True,
         "installments_paid": 2, "installments_expected": 3},
        True, id="payment_recovered",
    ),
    pytest.param(
        "purchase.plan_completed",
        {"first_name": "Ada", "experience_name": "Life in Alignment",
         "member_url": "https://fc.test/p/1", "total_paid_cents": 6000,
         "currency": "AUD", "installments_expected": 3},
        True, id="purchase_plan_completed",
    ),
    pytest.param(
        "gathering.booking.confirmed",
        {"gathering_title": "Morning Sit", "gathering_starts_at": "9am Friday",
         "collective_name": "Still Water", "gathering_id": "g1"},
        False, id="booking_confirmed",
    ),
    pytest.param(
        "collective.invitation.sent",
        {"inviter_name": "Sarah", "collective_name": "Still Water",
         "accept_url": "https://fc.test/invites/abc"},
        True, id="invitation_sent",
    ),
    pytest.param(
        "community.post.published",
        {"collective_name": "Still Water", "excerpt": "A quiet thought."},
        False, id="post_published",
    ),
    pytest.param(
        "community.comment.created",
        {"commenter_name": "Sarah", "post_title": "On stillness",
         "view_url": "https://fc.test/posts/1"},
        True, id="comment_created",
    ),
    pytest.param(
        "pathway.published",
        {"collective_name": "Still Water", "pathway_title": "Beginning"},
        False, id="pathway_published",
    ),
    pytest.param(
        "dm.message.sent",
        {"sender_name": "Sarah", "excerpt": "Hello there."},
        False, id="dm_sent",
    ),
]


# ---------------------------------------------------------------------------
# The shell itself
# ---------------------------------------------------------------------------


class TestShell:
    def test_renders_full_branded_document(self):
        html = render_email_shell(
            preheader="Preview line",
            heading="A heading",
            body_paragraphs=["A quiet paragraph."],
        )
        _assert_branded_shell(html)
        assert "Preview line" in html
        assert "A heading" in html
        assert "A quiet paragraph." in html

    def test_escapes_every_string_argument(self):
        html = render_email_shell(
            preheader=XSS,
            heading=XSS,
            greeting=XSS,
            body_paragraphs=[XSS],
            action=(XSS, "https://fc.test/x"),
            signoff=XSS,
        )
        # The angle brackets are gone, so no tag is ever formed. The
        # quoted attribute text survives as inert body text, which is
        # correct — quotes carry no meaning in element content.
        # The shell header carries exactly one real image — the
        # approved brand logo — so "no <img anywhere" is no longer
        # the right shape. What must hold is that the injected tag
        # never formed and that no second image appeared.
        assert "<img src=x" not in html
        assert html.count("<img") == 1
        assert 'alt="Fresh Collective"' in html
        # Escaped once, not twice.
        assert "&lt;img src=x" in html
        assert "&amp;lt;" not in html

    def test_drops_empty_paragraphs(self):
        html = render_email_shell(
            preheader="p", heading="h",
            body_paragraphs=["One", "", "   ", "Two"],
        )
        assert _body_paragraphs(html) == ["One", "Two"]

    def test_action_renders_button_and_copyable_link(self):
        html = render_email_shell(
            preheader="p", heading="h", body_paragraphs=["b"],
            action=("Do the thing", "https://fc.test/go?a=1&b=2"),
        )
        label, url = _cta(html)
        assert label == "Do the thing"
        # Ampersand escaped in the href, destination otherwise intact.
        assert url == "https://fc.test/go?a=1&amp;b=2"
        assert "or copy this link:" in html

    def test_no_action_renders_no_button(self):
        html = render_email_shell(
            preheader="p", heading="h", body_paragraphs=["b"],
        )
        assert "or copy this link:" not in html

    def test_preferences_link_is_conditional(self):
        shown = render_email_shell(
            preheader="p", heading="h", body_paragraphs=["b"],
            show_preferences_link=True,
        )
        hidden = render_email_shell(
            preheader="p", heading="h", body_paragraphs=["b"],
            show_preferences_link=False,
        )
        assert "Manage your Stay Connected preferences" in shown
        assert "/settings/stay-connected" in shown
        assert "Manage your Stay Connected preferences" not in hidden
        # The sender-identifying footer survives either way.
        assert "Fresh Collective" in hidden

    def test_no_eyebrow_parameter(self):
        with pytest.raises(TypeError):
            render_email_shell(
                preheader="p", heading="h", body_paragraphs=["b"],
                eyebrow="ACCOUNT",
            )


# ---------------------------------------------------------------------------
# Every migrated template
# ---------------------------------------------------------------------------


class TestAllTemplatesUseTheShell:
    @pytest.mark.parametrize("event_type,ctx,expect_cta", ALL_EMAIL_TEMPLATES)
    def test_renders_inside_branded_shell(self, event_type, ctx, expect_cta):
        payload = _render(event_type, **ctx)
        assert payload.body_html, f"{event_type} produced no HTML"
        _assert_branded_shell(payload.body_html)

    @pytest.mark.parametrize("event_type,ctx,expect_cta", ALL_EMAIL_TEMPLATES)
    def test_subject_and_plain_text_survive(self, event_type, ctx, expect_cta):
        payload = _render(event_type, **ctx)
        assert payload.subject.strip()
        assert payload.body_text and payload.body_text.strip()
        # The plain-text part is never wrapped in the HTML shell.
        assert "<!DOCTYPE" not in payload.body_text

    @pytest.mark.parametrize("event_type,ctx,expect_cta", ALL_EMAIL_TEMPLATES)
    def test_cta_url_is_intact_when_expected(self, event_type, ctx, expect_cta):
        payload = _render(event_type, **ctx)
        cta = _cta(payload.body_html)
        if not expect_cta:
            assert cta is None, f"{event_type} grew an unexpected CTA"
            return
        label, url = cta
        assert label, f"{event_type} CTA has no label"
        # The CTA points at exactly the URL the resolver supplied.
        supplied = [
            v for k, v in ctx.items()
            if k.endswith("_url") and isinstance(v, str)
        ]
        assert url in supplied, f"{event_type} CTA url {url!r} not in {supplied!r}"


# ---------------------------------------------------------------------------
# Escaping of user-generated content, end to end through the templates
# ---------------------------------------------------------------------------


class TestUserContentIsEscaped:
    @pytest.mark.parametrize(
        "event_type,ctx,field",
        [
            ("gathering.booking.confirmed",
             {"gathering_title": XSS, "gathering_starts_at": "9am",
              "collective_name": "Still Water"}, "gathering_title"),
            ("gathering.booking.confirmed",
             {"gathering_title": "Morning Sit", "gathering_starts_at": "9am",
              "collective_name": XSS}, "collective_name"),
            ("community.post.published",
             {"collective_name": XSS, "excerpt": "x"}, "collective_name"),
            ("community.post.published",
             {"collective_name": "Still Water", "excerpt": XSS}, "excerpt"),
            ("community.comment.created",
             {"commenter_name": XSS, "post_title": "t",
              "view_url": "https://fc.test/1"}, "commenter_name"),
            ("community.comment.created",
             {"commenter_name": "Sarah", "post_title": XSS,
              "view_url": "https://fc.test/1"}, "post_title"),
            ("collective.invitation.sent",
             {"inviter_name": XSS, "collective_name": "Still Water",
              "accept_url": "https://fc.test/i"}, "inviter_name"),
            ("collective.invitation.sent",
             {"inviter_name": "Sarah", "collective_name": XSS,
              "accept_url": "https://fc.test/i"}, "collective_name"),
            ("purchase.completed",
             {"first_name": "Ada", "experience_name": XSS,
              "member_url": "https://fc.test/p", "payment_mode": "single"},
             "experience_name"),
            ("purchase.plan_completed",
             {"first_name": "Ada", "experience_name": XSS,
              "member_url": "https://fc.test/p"}, "experience_name"),
            ("creator.plan_activated",
             {"first_name": "Grace", "plan_name": XSS,
              "next_url": "https://fc.test/s"}, "plan_name"),
            ("pathway.published",
             {"collective_name": "Still Water", "pathway_title": XSS},
             "pathway_title"),
            ("dm.message.sent",
             {"sender_name": XSS, "excerpt": "hi"}, "sender_name"),
        ],
    )
    def test_injected_markup_never_reaches_the_html(
        self, event_type, ctx, field,
    ):
        html = _render(event_type, **ctx).body_html
        # One <img> in the document: the brand logo in the shell header.
        assert "<img src=x" not in html, f"{event_type}.{field} not escaped"
        assert html.count("<img") == 1, f"{event_type}.{field} added an image"
        assert "&lt;img src=x" in html, f"{event_type}.{field} lost its value"

    def test_ampersands_are_not_double_escaped(self):
        html = _render(
            "community.post.published",
            collective_name="Tea & Quiet", excerpt="x",
        ).body_html
        assert "Tea &amp; Quiet" in html
        assert "&amp;amp;" not in html


# ---------------------------------------------------------------------------
# Greeting policy for the two signup emails
# ---------------------------------------------------------------------------


SIGNUP_EMAILS = [
    ("account.email_verification_requested",
     {"verify_url": "https://fc.test/verify?t=1"}),
    ("account.welcome_after_signup",
     {"next_url": "https://fc.test/dashboard"}),
]


class TestSignupGreeting:
    @pytest.mark.parametrize("event_type,ctx", SIGNUP_EMAILS)
    def test_greets_with_hey_friend(self, event_type, ctx):
        payload = _render(event_type, **ctx)
        assert _body_paragraphs(payload.body_html)[0] == "Hey friend,"
        assert payload.body_text.startswith("Hey friend,")

    @pytest.mark.parametrize("event_type,ctx", SIGNUP_EMAILS)
    @pytest.mark.parametrize(
        "first_name", ["Creator", "Ada", "", None, "Creator Portfolio"],
    )
    def test_greeting_never_derives_from_the_stored_name(
        self, event_type, ctx, first_name,
    ):
        """The reported "Hi Creator" defect: whatever sits in
        ``users.name`` must not become the way we address someone."""
        payload = _render(event_type, first_name=first_name, **ctx)
        assert "Hey friend," in payload.body_html
        assert "Hi " not in _body_paragraphs(payload.body_html)[0]
        if first_name:
            assert f"Hi {first_name}," not in payload.body_html
            assert f"Hi {first_name}," not in payload.body_text

    @pytest.mark.parametrize("event_type,ctx", SIGNUP_EMAILS)
    def test_greeting_is_identical_across_both_signup_emails(
        self, event_type, ctx,
    ):
        payload = _render(event_type, first_name="Ada", **ctx)
        assert _body_paragraphs(payload.body_html)[0] == "Hey friend,"

    def test_other_emails_still_greet_by_name(self):
        """P1 changed the two signup emails only — established accounts
        keep their dynamic greeting."""
        html = _render(
            "creator.plan_activated",
            first_name="Grace", plan_name="Creator",
            next_url="https://fc.test/s",
        ).body_html
        assert "Hi Grace," in html
        assert "Hey friend," not in html

        html = _render(
            "purchase.completed",
            first_name="Ada", experience_name="Life in Alignment",
            member_url="https://fc.test/p", payment_mode="single",
        ).body_html
        assert "Hi Ada," in html


# ---------------------------------------------------------------------------
# Named spot-checks for the three emails called out in the brief
# ---------------------------------------------------------------------------


class TestKeyEmails:
    def test_confirm_email(self):
        p = _render(
            "account.email_verification_requested",
            first_name="Creator", verify_url="https://fc.test/verify?t=abc",
        )
        assert p.subject == "Welcome to Fresh Collective — confirm your email"
        assert "<h1" in p.body_html and "Confirm your email" in p.body_html
        assert _body_paragraphs(p.body_html)[0] == "Hey friend,"
        assert _cta(p.body_html) == (
            "Verify my email", "https://fc.test/verify?t=abc",
        )
        # A locked category offers no preferences link.
        assert "Manage your Stay Connected preferences" not in p.body_html
        # Expiry wording is a transactional fact and must survive.
        assert "24 hours" in p.body_html

    def test_welcome_email(self):
        p = _render(
            "account.welcome_after_signup",
            first_name="Creator", next_url="https://fc.test/dashboard",
        )
        assert p.subject == "Welcome to Fresh Collective"
        assert _body_paragraphs(p.body_html)[0] == "Hey friend,"
        assert _cta(p.body_html) == ("Sign in", "https://fc.test/dashboard")
        assert "Your account is ready." in p.body_html

    def test_password_reset_email(self):
        p = _render(
            "account.password_reset_requested",
            reset_url="https://fc.test/reset?t=abc",
        )
        assert p.subject == "Reset your Fresh Collective password"
        assert "Reset your password" in p.body_html
        assert _cta(p.body_html) == (
            "Choose a new password", "https://fc.test/reset?t=abc",
        )
        # Security instruction must survive the migration verbatim.
        assert (
            "If you didn't request this, you can safely ignore this message."
            in p.body_html
        )
        assert "Manage your Stay Connected preferences" not in p.body_html
        # No greeting — this email addresses nobody by name.
        assert "Hey friend," not in p.body_html
        assert "Hi " not in _body_paragraphs(p.body_html)[0]


# ---------------------------------------------------------------------------
# Preferences-link policy follows the locked-category split
# ---------------------------------------------------------------------------


class TestPreferencesLinkPolicy:
    @pytest.mark.parametrize("event_type,ctx", [
        ("account.welcome_after_signup", {"next_url": "https://fc.test/d"}),
        ("account.email_verification_requested", {"verify_url": "https://fc.test/v"}),
        ("account.password_reset_requested", {"reset_url": "https://fc.test/r"}),
        ("creator.plan_activated", {"next_url": "https://fc.test/s"}),
        ("purchase.completed", {"member_url": "https://fc.test/p",
                                "experience_name": "X"}),
        ("access.suspended", {"repair_url": "https://fc.test/f",
                              "experience_name": "X"}),
        ("collective.invitation.sent", {"accept_url": "https://fc.test/i",
                                        "inviter_name": "S",
                                        "collective_name": "C"}),
    ])
    def test_locked_categories_omit_the_link(self, event_type, ctx):
        html = _render(event_type, **ctx).body_html
        assert "Manage your Stay Connected preferences" not in html
        assert "Fresh Collective" in html  # footer identity retained

    @pytest.mark.parametrize("event_type,ctx", [
        ("gathering.booking.confirmed", {"gathering_title": "G",
                                         "collective_name": "C"}),
        ("community.post.published", {"collective_name": "C", "excerpt": "e"}),
        ("community.comment.created", {"commenter_name": "S",
                                       "post_title": "T",
                                       "view_url": "https://fc.test/1"}),
        ("pathway.published", {"collective_name": "C", "pathway_title": "P"}),
        ("dm.message.sent", {"sender_name": "S", "excerpt": "e"}),
    ])
    def test_unlocked_categories_offer_the_link(self, event_type, ctx):
        html = _render(event_type, **ctx).body_html
        assert "Manage your Stay Connected preferences" in html
        assert "/settings/stay-connected" in html
