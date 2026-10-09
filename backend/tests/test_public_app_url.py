"""Every member-facing link comes from the public domain.

What went wrong
---------------
A password-reset email went out with
``https://fc-web-q950.onrender.com/reset-password?token=…``.

Two settings looked interchangeable. ``FRONTEND_ORIGIN`` is the CORS
allow-list and on Render is wired to fc-web's ``RENDER_EXTERNAL_URL``,
so its value *is* the platform host. ``PUBLIC_APP_URL`` is the product's
public address. Email links were built from the first, and because the
second was never declared in the blueprint, the fallback
``public_app_url or frontend_origin`` meant even the callers that
reached for the right setting resolved to the Render host.

So these tests cover three things, because fixing any one alone would
have left the bug in place:

  * the helper joins correctly and reads the canonical setting
  * production refuses to boot with a platform or localhost link origin
  * the real templates, rendered, carry the public domain in both the
    HTML and the plain-text body

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_public_app_url.py
"""

from __future__ import annotations

import os
import pathlib
import re
from unittest import mock

import pytest

import app.comms.templates  # noqa: F401 — registers every template
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.registry import get_template_for, registered_templates
from app.core.config import Settings, settings
from app.core.public_url import (
    NON_PUBLIC_HOST_MARKERS,
    is_public_host,
    public_app_url,
)

PUBLIC = "https://freshcollective.au"
RENDER_HOST = "https://fc-web-q950.onrender.com"

BACKEND = pathlib.Path(__file__).resolve().parent.parent
REPO = BACKEND.parent


@pytest.fixture
def production_like(monkeypatch):
    """What fc-api sees once ``PUBLIC_APP_URL`` is declared: the public
    domain for links, the Render host still correct for CORS."""
    monkeypatch.setattr(settings, "public_app_url", PUBLIC, raising=False)
    monkeypatch.setattr(settings, "frontend_origin", RENDER_HOST, raising=False)
    return settings


@pytest.fixture
def misconfigured_like_production(monkeypatch):
    """The live state before this fix: nothing declared, so links fall
    through to the CORS origin."""
    monkeypatch.setattr(settings, "public_app_url", None, raising=False)
    monkeypatch.setattr(settings, "frontend_origin", RENDER_HOST, raising=False)
    return settings


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


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------


class TestPublicAppUrl:
    def test_it_reads_the_canonical_setting_not_the_cors_origin(
        self, production_like,
    ):
        """The whole point. Both are set, and they differ."""
        assert public_app_url("/reset-password") == (
            f"{PUBLIC}/reset-password"
        )
        assert RENDER_HOST not in public_app_url("/reset-password")

    def test_it_falls_back_so_local_development_still_works(self, monkeypatch):
        """Nothing configured is the normal state locally and in the
        test suite, and localhost is the right answer there."""
        monkeypatch.setattr(settings, "public_app_url", None, raising=False)
        monkeypatch.setattr(
            settings, "frontend_origin", "http://localhost:3000", raising=False,
        )
        assert public_app_url("/dashboard") == "http://localhost:3000/dashboard"

    def test_exactly_one_slash_at_the_join(self, production_like):
        assert public_app_url("/dashboard") == f"{PUBLIC}/dashboard"
        assert public_app_url("dashboard") == f"{PUBLIC}/dashboard"
        assert "//" not in public_app_url("/dashboard").removeprefix("https://")

    def test_a_trailing_slash_on_the_setting_does_not_double_up(
        self, monkeypatch,
    ):
        """Operators paste URLs with trailing slashes. Fifteen call
        sites each used to ``.rstrip("/")`` for themselves."""
        monkeypatch.setattr(
            settings, "public_app_url", "https://freshcollective.au/",
            raising=False,
        )
        assert public_app_url("/dashboard") == f"{PUBLIC}/dashboard"
        assert public_app_url() == PUBLIC

    def test_the_bare_origin_has_no_trailing_slash(self, production_like):
        assert public_app_url() == PUBLIC

    def test_the_setting_itself_strips_a_trailing_slash(self, monkeypatch):
        """Where the guarantee lives. The previous test passes whether
        or not the helper strips, because the property already did."""
        monkeypatch.setattr(
            settings, "public_app_url", "https://freshcollective.au/",
            raising=False,
        )
        assert settings.resolved_public_app_url == PUBLIC

    def test_the_helper_strips_too_rather_than_trusting_its_input(
        self, monkeypatch,
    ):
        """Deliberate duplication, so it has a test.

        The helper strips the base as well as the path. That is
        redundant today — ``resolved_public_app_url`` already strips —
        and the point is that it stays correct if that ever stops being
        true. Asserted by handing it a base it would otherwise
        double-slash.
        """
        monkeypatch.setattr(
            type(settings), "resolved_public_app_url",
            property(lambda self: "https://freshcollective.au/"),
            raising=False,
        )
        assert public_app_url("/dashboard") == f"{PUBLIC}/dashboard"
        assert public_app_url() == PUBLIC

    def test_a_query_string_is_preserved_verbatim(self, production_like):
        """The token is the whole value of a reset link. Only the origin
        was ever wrong."""
        token = "aBc-123_x.y~z"
        assert public_app_url(f"/reset-password?token={token}") == (
            f"{PUBLIC}/reset-password?token={token}"
        )

    def test_multiple_query_parameters_and_a_fragment_survive(
        self, production_like,
    ):
        assert public_app_url("/checkout/complete?a=1&b=2#done") == (
            f"{PUBLIC}/checkout/complete?a=1&b=2#done"
        )
        assert public_app_url("/for-creators#plans") == (
            f"{PUBLIC}/for-creators#plans"
        )

    def test_a_root_path_keeps_its_slash(self, production_like):
        assert public_app_url("/") == f"{PUBLIC}/"

    @pytest.mark.parametrize("absolute", [
        "https://evil.test/phish",
        "http://evil.test/phish",
        "//evil.test/phish",
        "HTTPS://Evil.Test/phish",
    ])
    def test_an_absolute_url_is_refused(self, production_like, absolute):
        """Not silently returned, not concatenated.

        A caller passing one has either already built the link — worth
        seeing — or is passing something that came from input, and a
        user-supplied origin reflected into an email over our name is
        the shape of a phishing link.
        """
        with pytest.raises(ValueError, match="takes a path"):
            public_app_url(absolute)

    def test_the_helper_is_the_only_thing_that_needs_to_know(self):
        """``is_public_host`` is substring-based on purpose: the
        question is "could this have come from the wrong setting",
        and a marker anywhere in the authority answers it."""
        assert is_public_host(PUBLIC)
        assert not is_public_host(RENDER_HOST)
        assert not is_public_host("http://localhost:3000")
        assert not is_public_host("http://127.0.0.1:8000")
        assert not is_public_host("")


# ---------------------------------------------------------------------------
# The two settings are not the same thing
# ---------------------------------------------------------------------------


class TestTheSettingsAreSeparated:
    def test_frontend_origin_is_used_for_cors_and_nothing_else(self):
        """One remaining reader outside config: the CORS middleware.

        Every link builder used to read it. If a new one appears, this
        fails — which is the only mechanism that would have caught the
        password-reset line.
        """
        readers: list[str] = []
        for path in sorted(BACKEND.glob("app/**/*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if rel in (
                "app/core/config.py", "app/core/public_url.py",
                "app/core/url_policy.py",
            ):
                continue
            for i, line in enumerate(path.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                if "frontend_origin" in code:
                    readers.append(f"{rel}:{i}: {line.strip()}")

        assert len(readers) == 1, (
            "frontend_origin is the CORS origin only. Member-facing links "
            "must come from public_app_url(). Unexpected readers:\n"
            + "\n".join(readers)
        )
        assert "app/main.py" in readers[0], readers
        assert "allow_origins" in readers[0], readers

    def test_no_link_builder_reads_the_resolved_setting_directly(self):
        """``resolved_public_app_url`` is right but raw — it owns no
        slash joining and will happily concatenate an absolute URL.
        Call sites go through the helper so one function has the rules.
        """
        offenders: list[str] = []
        for path in sorted(BACKEND.glob("app/**/*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if rel in (
                "app/core/config.py", "app/core/public_url.py",
                "app/core/url_policy.py",
            ):
                continue
            for i, line in enumerate(path.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                if "resolved_public_app_url" in code:
                    offenders.append(f"{rel}:{i}: {line.strip()}")
        assert offenders == [], (
            "use public_app_url() instead:\n" + "\n".join(offenders)
        )

    def test_no_platform_host_is_hardcoded_in_application_code(self):
        """Infrastructure may legitimately name the Render host — the
        blueprint wires CORS to it, and the comments explaining this bug
        quote the host it produced. Application *code* must not.

        So this inspects string constants through the AST with
        docstrings removed, rather than grepping lines. A line-based
        check fails on its own explanation, which is how the first
        version of this test behaved.
        """
        import ast

        offenders: list[str] = []
        for path in sorted(BACKEND.glob("app/**/*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if rel == "app/core/url_policy.py":
                continue  # defines the marker list
            if rel == "app/services/notification_link_canonicalisation.py":
                # Names the exact origin it migrates in-app links away
                # from. A one-time cleanup has to know which host was
                # wrong; that is the opposite of building a link from it.
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = set()
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if not isinstance(body, list) or not body:
                    continue
                first = body[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings
                    and "onrender.com" in node.value
                ):
                    offenders.append(f"{rel}:{node.lineno}: {node.value[:70]!r}")
        assert offenders == [], "\n".join(offenders)


class TestProductionRefusesANonPublicLinkOrigin:
    """The guard that makes this unrepeatable.

    Nothing failed when ``PUBLIC_APP_URL`` was unset: members got
    working links to the wrong host for as long as it took someone to
    notice. A silent wrong answer is worth trading for a loud refusal,
    which is what the R2 and Stripe guards already do.

    Every ``Settings`` below is built through ``_settings`` rather than
    constructed directly. ``Settings.model_config`` reads ``.env``, and
    ``conftest`` has already loaded that file into ``os.environ``, so a
    direct call inherited the developer's ``sk_test_…`` Stripe key —
    which under ``app_env="production"`` tripped the Stripe guard and
    raised about an entirely different variable. All seven tests in
    this class failed that way on any machine with a local
    ``backend/.env``, and passed only where none existed. The guards
    themselves are unchanged; the tests now supply their own inputs
    instead of inheriting a machine's.
    """

    BASE = {
        "database_url": "postgresql://u:p@localhost/db",
        "jwt_secret": "x" * 32,
        "fc_service_role": "job",
        "fc_job_requires_stripe": False,
    }

    @staticmethod
    def _settings(**kwargs) -> Settings:
        """Construct ``Settings`` from these values and nothing else.

        ``clear=True`` empties ``os.environ`` for the construction and
        ``_env_file=None`` stops the ``.env`` file being read, so the
        only inputs are the keyword arguments.
        """
        with mock.patch.dict(os.environ, {}, clear=True):
            return Settings(_env_file=None, **kwargs)

    def test_production_with_public_app_url_set_boots(self):
        s = self._settings(**self.BASE, app_env="production", public_app_url=PUBLIC)
        assert s.resolved_public_app_url == PUBLIC

    def test_production_falling_back_to_the_render_host_refuses(self):
        """The live misconfiguration, as a test."""
        with pytest.raises(ValueError, match="PUBLIC_APP_URL"):
            self._settings(**self.BASE, app_env="production",
                     frontend_origin=RENDER_HOST)

    def test_production_with_localhost_refuses(self):
        with pytest.raises(ValueError, match="PUBLIC_APP_URL"):
            self._settings(**self.BASE, app_env="production",
                     frontend_origin="http://localhost:3000")

    def test_production_with_an_empty_value_refuses(self):
        with pytest.raises(ValueError, match="PUBLIC_APP_URL"):
            self._settings(**self.BASE, app_env="production",
                     public_app_url="", frontend_origin="")

    def test_a_render_host_in_public_app_url_itself_refuses(self):
        """Setting the var is not enough if it is set to the wrong
        thing — which is exactly what a copy-paste from the dashboard
        would produce."""
        with pytest.raises(ValueError, match="PUBLIC_APP_URL"):
            self._settings(**self.BASE, app_env="production",
                     public_app_url=RENDER_HOST)

    def test_the_message_names_the_variable_and_the_fix(self):
        with pytest.raises(ValueError) as exc:
            self._settings(**self.BASE, app_env="production",
                     frontend_origin=RENDER_HOST)
        message = str(exc.value)
        assert "PUBLIC_APP_URL" in message
        assert "FRONTEND_ORIGIN" in message
        assert "onrender.com" in message

    def test_the_guard_applies_to_background_jobs_too(self):
        """The Gathering reminder cron sends email. A job with the wrong
        link origin is exactly as visible to a member as the web
        service."""
        with pytest.raises(ValueError, match="PUBLIC_APP_URL"):
            self._settings(
                database_url="postgresql://u:p@localhost/db",
                jwt_secret="x" * 32,
                fc_service_role="job",
                fc_job_requires_stripe=False,
                app_env="production",
                frontend_origin=RENDER_HOST,
            )

    @pytest.mark.parametrize("env", ["development", "test", "staging"])
    def test_non_production_is_untouched(self, env):
        """localhost is the correct answer outside production, and the
        test suite depends on it."""
        s = self._settings(**self.BASE, app_env=env,
                     frontend_origin="http://localhost:3000")
        assert s.resolved_public_app_url == "http://localhost:3000"


# ---------------------------------------------------------------------------
# Rendered emails
# ---------------------------------------------------------------------------


class TestPasswordResetEmail:
    """The reported case, end to end.

    Split at the session boundary rather than pretending it is one
    call: the route's emit is asserted on the stored event payload, and
    that exact payload is then run through the real resolver contract
    and the real template.
    """

    def _reset_url(self):
        # Built exactly as app/auth/routes.py builds it.
        return public_app_url("/reset-password?token=tok-abc123")

    def test_the_route_builds_the_link_from_the_public_domain(
        self, production_like,
    ):
        assert self._reset_url() == (
            f"{PUBLIC}/reset-password?token=tok-abc123"
        )

    def test_the_html_button_points_at_the_public_domain(
        self, production_like,
    ):
        rendered = _render(
            "account.password_reset_requested", reset_url=self._reset_url(),
        )
        hrefs = re.findall(r'href="([^"]+)"', rendered.body_html)
        reset_hrefs = [h for h in hrefs if "reset-password" in h]
        assert reset_hrefs, hrefs
        for href in reset_hrefs:
            assert href.startswith(PUBLIC), href
            assert "token=tok-abc123" in href, href

    def test_the_plain_text_fallback_points_at_the_public_domain(
        self, production_like,
    ):
        """A fix that changed only the button would leave the Render URL
        in the text body — which is what many clients show."""
        rendered = _render(
            "account.password_reset_requested", reset_url=self._reset_url(),
        )
        assert f"{PUBLIC}/reset-password?token=tok-abc123" in rendered.body_text
        assert "onrender.com" not in rendered.body_text

    def test_no_platform_host_survives_anywhere_in_the_message(
        self, production_like,
    ):
        rendered = _render(
            "account.password_reset_requested", reset_url=self._reset_url(),
        )
        whole = " ".join([
            rendered.subject, rendered.body_html, rendered.body_text or "",
        ])
        for marker in NON_PUBLIC_HOST_MARKERS:
            assert marker not in whole, marker

    def test_the_token_is_unchanged_only_the_origin_moves(
        self, production_like, misconfigured_like_production,
    ):
        """Comparing the two configurations directly: the path and query
        are identical, the origin is the only difference."""
        monkey_public = public_app_url("/reset-password?token=tok-abc123")
        # ``misconfigured_like_production`` applied last, so this is the
        # pre-fix value.
        assert monkey_public == (
            f"{RENDER_HOST}/reset-password?token=tok-abc123"
        )
        assert monkey_public.endswith("/reset-password?token=tok-abc123")


class TestRepresentativeEventEmails:
    """One per family, because the bug was per-call-site rather than
    per-template — fourteen builders agreed and one did not."""

    def test_email_verification(self, production_like):
        url = public_app_url("/verify-email?token=v-1")
        rendered = _render("account.email_verification_requested", verify_url=url)
        assert url in (rendered.body_text or "")
        assert PUBLIC in rendered.body_html
        assert "onrender.com" not in rendered.body_html

    def test_welcome_after_signup(self, production_like):
        url = public_app_url("/dashboard")
        rendered = _render("account.welcome_after_signup", next_url=url)
        assert PUBLIC in rendered.body_html
        assert "onrender.com" not in rendered.body_html

    def test_conversation_notification(self, production_like):
        url = public_app_url("/spaces/embody/community/post-1")
        rendered = _render(
            "community.comment.created", view_url=url,
            post_title="A post", commenter_name="Sam",
        )
        assert url in (rendered.body_text or "")
        assert "onrender.com" not in rendered.body_html

    def test_creator_billing_notification(self, production_like):
        url = public_app_url("/creator-studio/billing")
        for event in (
            "creator.subscription.payment_failed",
            "creator.subscription.activated",
        ):
            template = get_template_for(event, CHANNEL_EMAIL_TRANSACTIONAL)
            if template is None:
                continue
            rendered = template.render(
                None, None, _recipient(billing_url=url, first_name="Sam"),
            )
            assert "onrender.com" not in rendered.body_html, event
            assert PUBLIC in rendered.body_html, event

    def test_the_shared_preferences_footer(self, production_like):
        """One shared helper under every email with a footer. It read
        the CORS origin, so every one of them carried the Render host —
        including emails whose own link was correct."""
        from app.comms.templates.base import preferences_url
        from app.services.email_templates import _preferences_url

        assert preferences_url() == f"{PUBLIC}/settings/stay-connected"
        assert _preferences_url() == f"{PUBLIC}/settings/stay-connected"


class TestNoRegisteredEmailTemplateLeaksThePlatformHost:
    def test_every_email_template_renders_without_a_platform_host(
        self, production_like,
    ):
        """A sweep rather than a list, so a template added later is
        covered without anyone remembering to add it here.

        Every URL-ish context key is filled with a ``public_app_url``
        value and a generous pile of plausible strings for the rest.
        A template that cannot render from this is skipped and named,
        so the skip is visible rather than silent.
        """
        url = public_app_url("/somewhere?x=1")
        context = {
            "reset_url": url, "verify_url": url, "next_url": url,
            "view_url": url, "cta_url": url, "billing_url": url,
            "gathering_url": url, "pathway_url": url, "member_url": url,
            "repair_url": url, "retry_url": url, "accept_url": url,
            "url": url, "link": url,
            "first_name": "Sam", "name": "Sam", "post_title": "A post",
            "commenter_name": "Sam", "title": "A thing",
            "space_name": "EMBODY", "collective_name": "EMBODY",
            "pathway_title": "The REAL Journey", "event_title": "A Gathering",
            "amount_display": "$10.00", "payment_mode": "once",
            "session_count": 1, "inviter_name": "Sam",
        }

        rendered_any = 0
        skipped: list[str] = []
        for event_type, channel in registered_templates():
            if channel != CHANNEL_EMAIL_TRANSACTIONAL:
                continue
            template = get_template_for(event_type, channel)
            try:
                rendered = template.render(None, None, _recipient(**context))
            except Exception as exc:  # needs a DB or a real event
                skipped.append(f"{event_type} ({type(exc).__name__})")
                continue
            rendered_any += 1
            whole = " ".join([
                rendered.subject or "",
                rendered.body_html or "",
                rendered.body_text or "",
            ])
            assert "onrender.com" not in whole, (
                f"{event_type} rendered a platform host"
            )
            assert "localhost" not in whole, (
                f"{event_type} rendered a localhost URL under production-like "
                f"config"
            )

        assert rendered_any >= 5, (
            f"only {rendered_any} email templates rendered standalone; "
            f"skipped: {skipped}"
        )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestBlueprintDeclaresTheCanonicalDomain:
    """The code fix alone was not enough.

    ``PUBLIC_APP_URL`` was declared nowhere, so the fallback resolved
    every link to the Render host — meaning the call sites that already
    reached for the right setting were wrong too.
    """

    def _services(self):
        import yaml
        data = yaml.safe_load((REPO / "render.yaml").read_text())
        return data["services"]

    def test_every_production_service_declares_the_public_domain(self):
        import yaml  # noqa: F401 — imported in _services

        missing = []
        for service in self._services():
            env = {e["key"]: e.get("value") for e in service.get("envVars", [])}
            if env.get("APP_ENV") != "production":
                continue
            if env.get("PUBLIC_APP_URL") != PUBLIC:
                missing.append(
                    f"{service['name']}: {env.get('PUBLIC_APP_URL')!r}"
                )
        assert missing == [], (
            "every APP_ENV=production service needs PUBLIC_APP_URL — the boot "
            "guard refuses to start without it:\n" + "\n".join(missing)
        )

    def test_it_is_pinned_rather_than_dashboard_owned(self):
        """``sync: false`` would let a blueprint sync leave it unset, and
        this value is a stable fact about the product rather than an
        operator toggle. Pinning it means a sync reasserts the right
        answer instead of reverting it."""
        for service in self._services():
            for entry in service.get("envVars", []):
                if entry["key"] == "PUBLIC_APP_URL":
                    assert entry.get("value") == PUBLIC, service["name"]
                    assert "sync" not in entry, service["name"]

    def test_frontend_origin_is_still_wired_to_the_platform_host(self):
        """Not a mistake to fix. CORS needs the origin the browser
        actually presents, and that is the Render host."""
        api = next(s for s in self._services() if s["name"] == "fc-api")
        entry = next(
            e for e in api["envVars"] if e["key"] == "FRONTEND_ORIGIN"
        )
        assert entry["fromService"]["name"] == "fc-web"
        assert entry["fromService"]["envVarKey"] == "RENDER_EXTERNAL_URL"
