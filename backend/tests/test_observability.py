"""Error reporting that cannot leak a credential.

Phase 1 adds Sentry to fc-api. The risk is not that it fails to
report — it is that it reports too much. Every secret this platform
handles passes through a path Sentry would capture by default: a raw
reset token in a request body, a session cookie in a header, a Stripe
webhook payload, a member's address in an exception message.

So most of this file is about what must *not* arrive, asserted against
real SDK machinery rather than against the scrubber in isolation: a
capturing ``Transport`` receives the actual envelope the SDK would have
put on the wire, after ``before_send`` and after every default
integration has had its turn.

The rest proves the useful half survives — exception type, stack,
route, component, release — because a scrubber that redacts everything
is as useless as one that redacts nothing.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_observability.py
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re

import pytest
import sentry_sdk
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

from app.core.observability import (
    DEFAULT_APP_ENV,
    REDACTED,
    SENSITIVE_QUERY_PARAMS,
    init_sentry,
    redact_text,
    redact_url,
    scrub_event,
)

BACKEND = pathlib.Path(__file__).resolve().parent.parent

FAKE_DSN = "https://fakekey@o0.ingest.sentry.io/0"
FAKE_EMAIL = "member@example.invalid"
FAKE_TOKEN = "FAKE_RESET_TOKEN_abc123"
FAKE_BEARER = "Bearer FAKE_JWT_xyz789"
FAKE_COOKIE = "fc_session=FAKE_SESSION_VALUE"
FAKE_SIG = "t=1,v1=FAKE_STRIPE_SIGNATURE"

#: Every fake credential used anywhere in this file. A captured event is
#: checked against the whole set rather than against the one secret the
#: test happened to be about — the failure mode worth catching is a
#: channel nobody thought of.
ALL_FAKE_SECRETS = (
    FAKE_EMAIL, FAKE_TOKEN, FAKE_BEARER, FAKE_COOKIE, FAKE_SIG,
    "FAKE_SESSION_VALUE", "FAKE_JWT_xyz789", "FAKE_STRIPE_SIGNATURE",
    "hunter2",
)


class CapturingTransport(Transport):
    """Collects envelopes instead of sending them.

    A ``Transport`` subclass rather than the function form, which the
    SDK deprecates. This sits at the very end of the pipeline, so what
    it records is what would genuinely have left the process.
    """

    def __init__(self) -> None:
        super().__init__({"dsn": FAKE_DSN})
        self.events: list[dict] = []

    def capture_envelope(self, envelope) -> None:  # noqa: ANN001
        for item in envelope.items:
            payload = item.payload
            data = getattr(payload, "json", None)
            if data is None:
                raw = getattr(payload, "get_bytes", None)
                if raw is None:
                    continue
                try:
                    data = json.loads(raw())
                except Exception:
                    continue
            if isinstance(data, dict) and (
                "exception" in data or "logentry" in data or "message" in data
            ):
                self.events.append(data)

    def flush(self, timeout, callback=None) -> None:  # noqa: ANN001
        return None

    def kill(self) -> None:
        return None


@pytest.fixture
def sentry(monkeypatch):
    """A real, initialised SDK whose events are captured locally.

    Restores whatever client was active afterwards so an initialised SDK
    cannot leak into another test.
    """
    previous = sentry_sdk.get_client()
    transport = CapturingTransport()

    monkeypatch.setenv("SENTRY_DSN", FAKE_DSN)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "5f0dadaf02f72f74bbfeb1b8019c4cf856bb7d14")

    def _start(**overrides):
        from app.core import observability

        real_init = sentry_sdk.init

        def init_with_transport(**kwargs):
            kwargs["transport"] = transport
            kwargs.update(overrides)
            return real_init(**kwargs)

        monkeypatch.setattr(observability.sentry_sdk if hasattr(
            observability, "sentry_sdk") else sentry_sdk, "init",
            init_with_transport, raising=False)
        monkeypatch.setattr(sentry_sdk, "init", init_with_transport)
        enabled = init_sentry("fc-api")
        assert enabled is True
        return transport

    yield _start

    sentry_sdk.get_global_scope().clear()
    sentry_sdk.get_isolation_scope().clear()
    sentry_sdk.Scope.get_global_scope().set_client(previous)


def _blob(event: dict) -> str:
    """The whole event as one searchable string."""
    return json.dumps(event, default=str)


def _assert_no_secrets(event: dict) -> None:
    blob = _blob(event)
    for secret in ALL_FAKE_SECRETS:
        assert secret not in blob, (
            f"{secret!r} survived into the event:\n{blob[:2000]}"
        )


# ---------------------------------------------------------------------------
# A. DSN absent
# ---------------------------------------------------------------------------


class TestWithoutADsn:
    """Every local run and the entire test suite. It must be as if
    Sentry were not installed."""

    def test_init_is_a_clean_no_op(self, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        assert init_sentry("fc-api") is False

    def test_an_empty_or_whitespace_dsn_is_also_a_no_op(self, monkeypatch):
        for value in ("", "   ", "\n"):
            monkeypatch.setenv("SENTRY_DSN", value)
            assert init_sentry("fc-api") is False

    def test_no_transport_is_constructed(self, monkeypatch):
        """The specific guarantee: nothing that could make a network
        call is created."""
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        init_sentry("fc-api")
        client = sentry_sdk.get_client()
        assert not client.is_active() or client.transport is None

    def test_the_app_still_boots(self, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        from app.main import app
        assert len(app.routes) > 100

    def test_capture_does_not_raise_with_no_client(self, monkeypatch):
        """Calling into the SDK with no DSN must be inert, not an
        error — otherwise a future ``capture_exception`` would crash
        local development."""
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        init_sentry("fc-api")
        assert sentry_sdk.capture_message("inert") is None


# ---------------------------------------------------------------------------
# B. Production-like init
# ---------------------------------------------------------------------------


class TestInitialisation:
    def test_environment_release_and_component(self, sentry):
        transport = sentry()
        try:
            raise RuntimeError("init shape")
        except RuntimeError:
            sentry_sdk.capture_exception()

        assert transport.events, "no event captured"
        event = transport.events[-1]
        assert event["environment"] == "production"
        assert event["release"] == (
            "5f0dadaf02f72f74bbfeb1b8019c4cf856bb7d14"
        )
        assert event["tags"]["component"] == "fc-api"

    def test_environment_tracks_app_env_rather_than_its_own_variable(
        self, sentry, monkeypatch,
    ):
        """Derived, so it cannot drift. ``SENTRY_ENVIRONMENT`` is
        deliberately not a variable we set."""
        monkeypatch.setenv("APP_ENV", "development")
        transport = sentry()
        sentry_sdk.capture_message("env check")
        assert transport.events[-1]["environment"] == "development"

    def test_we_never_fabricate_a_release(self, sentry, monkeypatch):
        """With ``RENDER_GIT_COMMIT`` absent we pass ``release=None``,
        which hands the question to the SDK's own discovery — it reads
        git, or finds nothing.

        That is the correct behaviour and worth stating, because the
        tempting alternative is a placeholder like ``"unknown"``, which
        looks like a version and groups every deploy together.
        """
        monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
        transport = sentry()
        sentry_sdk.capture_message("release check")
        release = transport.events[-1].get("release")
        assert release in (None, "") or re.fullmatch(r"[0-9a-f]{7,40}", release), (
            f"release {release!r} is neither absent nor a commit sha"
        )
        for placeholder in ("unknown", "latest", "dev", "none", "0.0.0"):
            assert release != placeholder

    def test_the_app_env_default_matches_settings(self):
        """The one duplicated value in a deliberately dependency-free
        module. If ``Settings.app_env``'s default ever changes, this
        fails rather than the two quietly disagreeing."""
        from app.core.config import Settings

        assert (
            Settings.model_fields["app_env"].default == DEFAULT_APP_ENV
        )

    def test_performance_features_are_off(self, sentry):
        sentry()
        options = sentry_sdk.get_client().options
        assert options["traces_sample_rate"] == 0
        assert options["profiles_sample_rate"] == 0
        assert options["send_default_pii"] is False
        assert options["max_request_body_size"] == "never"
        assert options["include_local_variables"] is False

    def test_the_component_tag_is_a_parameter_not_a_constant(
        self, sentry,
    ):
        """Phase 2 reuses this for seven crons. The tag has to follow
        the caller."""
        transport = sentry()
        sentry_sdk.get_global_scope().set_tag("component", "ignored")
        init_sentry("fc-connect-transfer-sweeper")
        sentry_sdk.capture_message("component check")
        assert transport.events[-1]["tags"]["component"] == (
            "fc-connect-transfer-sweeper"
        )


# ---------------------------------------------------------------------------
# C. Privacy
# ---------------------------------------------------------------------------


class TestNothingSensitiveSurvives:
    def test_a_fully_loaded_event_is_scrubbed(self):
        """Every channel at once, through the real ``before_send``."""
        event = {
            "request": {
                "url": f"https://freshcollective.au/reset-password?token={FAKE_TOKEN}&x=1",
                "query_string": f"token={FAKE_TOKEN}&page=2",
                "method": "POST",
                "data": {"token": FAKE_TOKEN, "password": "hunter2"},
                "cookies": {"fc_session": "FAKE_SESSION_VALUE"},
                "headers": {
                    "Authorization": FAKE_BEARER,
                    "Cookie": FAKE_COOKIE,
                    "Set-Cookie": FAKE_COOKIE,
                    "X-Internal-Token": "FAKE_INTERNAL",
                    "Stripe-Signature": FAKE_SIG,
                    "User-Agent": "Mozilla/5.0",
                    "Content-Type": "application/json",
                },
            },
            "extra": {
                "reset_url": f"https://freshcollective.au/reset?token={FAKE_TOKEN}",
                "verify_url": f"https://freshcollective.au/verify?token={FAKE_TOKEN}",
                "accept_url": "https://freshcollective.au/invites/FAKE_INVITE",
                "claim_token": FAKE_TOKEN,
                "stripe_payload": {"customer_email": FAKE_EMAIL},
                "harmless": "keep me",
            },
            "user": {"id": "u_123", "email": FAKE_EMAIL, "username": "Sam"},
            "exception": {"values": [{
                "type": "ValueError",
                "module": "app.auth.service",
                "value": f"bad token={FAKE_TOKEN} for {FAKE_EMAIL}",
                "stacktrace": {"frames": [
                    {"filename": "app/auth/service.py", "lineno": 402,
                     "function": "send_verification"},
                ]},
            }]},
            "breadcrumbs": {"values": [
                {"message": f"GET /reset?token={FAKE_TOKEN}", "category": "http"},
            ]},
            "tags": {"component": "fc-api", "session": "FAKE_SESSION_VALUE"},
        }
        out = scrub_event(event, None)
        assert out is not None
        _assert_no_secrets(out)

        # And the useful half is intact.
        assert out["exception"]["values"][0]["type"] == "ValueError"
        assert out["exception"]["values"][0]["module"] == "app.auth.service"
        assert out["exception"]["values"][0]["stacktrace"]["frames"][0][
            "function"] == "send_verification"
        assert out["extra"]["harmless"] == "keep me"
        assert out["tags"]["component"] == "fc-api"
        assert out["request"]["method"] == "POST"
        assert out["request"]["headers"]["User-Agent"] == "Mozilla/5.0"
        assert out["user"] == {"id": "u_123"}
        # The path survives; only the credential in the query goes.
        assert "/reset-password" in out["request"]["url"]
        assert "x=1" in out["request"]["url"]

    def test_the_request_body_is_removed_entirely(self):
        out = scrub_event({"request": {"data": {"anything": "at all"}}}, None)
        assert "data" not in out["request"]

    def test_cookies_are_removed_entirely(self):
        out = scrub_event(
            {"request": {"cookies": {"fc_session": "FAKE_SESSION_VALUE"}}}, None,
        )
        assert "cookies" not in out["request"]

    @pytest.mark.parametrize("header", [
        "Authorization", "authorization", "Cookie", "Set-Cookie",
        "X-Internal-Token", "Stripe-Signature", "stripe-signature",
    ])
    def test_sensitive_headers_are_redacted_case_insensitively(self, header):
        out = scrub_event(
            {"request": {"headers": {header: "SECRET-VALUE"}}}, None,
        )
        assert out["request"]["headers"][header] == REDACTED

    def test_a_benign_header_is_kept(self):
        """Redacting everything would make the events useless."""
        out = scrub_event(
            {"request": {"headers": {"User-Agent": "curl/8", "Referer": "/x"}}},
            None,
        )
        assert out["request"]["headers"]["User-Agent"] == "curl/8"
        assert out["request"]["headers"]["Referer"] == "/x"

    @pytest.mark.parametrize("param", SENSITIVE_QUERY_PARAMS)
    def test_every_declared_query_param_is_redacted(self, param):
        url = f"https://freshcollective.au/x?{param}=SECRET&keep=yes"
        out = redact_url(url)
        assert "SECRET" not in out
        assert "keep=yes" in out
        assert "/x" in out

    def test_a_url_without_a_query_is_untouched(self):
        url = "https://freshcollective.au/spaces/embody/community/p1"
        assert redact_url(url) == url

    def test_the_reset_link_shape_from_production(self):
        """The literal shape ``auth/routes.py`` builds."""
        out = redact_url(
            f"https://freshcollective.au/reset-password?token={FAKE_TOKEN}"
        )
        assert FAKE_TOKEN not in out
        assert out == f"https://freshcollective.au/reset-password?token={REDACTED}"

    def test_an_email_in_an_exception_message_is_redacted(self):
        assert FAKE_EMAIL not in redact_text(
            f"could not deliver to {FAKE_EMAIL}"
        )

    @pytest.mark.parametrize("text,keep", [
        ("Stripe charge ch_3Abc123XyZ failed", "ch_3Abc123XyZ"),
        ("transfer tr_1Nxyz rejected", "tr_1Nxyz"),
        ("space slug embody-circle not found", "embody-circle"),
        ("version 2.71.0 mismatch", "2.71.0"),
    ])
    def test_the_email_pattern_does_not_eat_useful_identifiers(
        self, text, keep,
    ):
        """The fragility risk. An over-greedy pattern would redact
        Stripe ids and slugs, which is most of what makes a message
        worth reading."""
        assert keep in redact_text(text)

    def test_an_inline_token_in_free_text_is_redacted(self):
        out = redact_text(f"open https://x.test/r?token={FAKE_TOKEN} to reset")
        assert FAKE_TOKEN not in out
        assert "https://x.test/r?token=" in out

    def test_the_scrubber_fails_closed(self, monkeypatch):
        """If the scrubber breaks, the event is dropped rather than
        sent unscrubbed. Documented, and asserted, because the opposite
        default would be invisible."""
        from app.core import observability

        def explode(*a, **k):
            raise RuntimeError("scrubber bug")

        monkeypatch.setattr(observability, "_scrub_request", explode)
        assert scrub_event({"request": {"headers": {}}}, None) is None

    def test_deep_nesting_terminates(self):
        deep: dict = {"token": "x"}
        for _ in range(40):
            deep = {"nest": deep}
        out = scrub_event({"extra": deep}, None)
        assert out is not None

    def test_a_minimal_event_is_handled(self):
        assert scrub_event({}, None) == {}
        assert scrub_event({"message": "hello"}, None)["message"] == "hello"


class TestPrivacyEndToEndThroughTheSdk:
    """The same guarantees, but after every default integration has
    run — which is where a surprise would come from."""

    def test_a_captured_exception_carries_no_secrets(self, sentry):
        transport = sentry()
        sentry_sdk.get_isolation_scope().set_extra("authorization", FAKE_BEARER)
        sentry_sdk.get_isolation_scope().set_user(
            {"id": "u_1", "email": FAKE_EMAIL},
        )
        try:
            raise ValueError(f"token={FAKE_TOKEN} for {FAKE_EMAIL}")
        except ValueError:
            sentry_sdk.capture_exception()

        event = transport.events[-1]
        _assert_no_secrets(event)
        assert event["exception"]["values"][0]["type"] == "ValueError"
        assert event["exception"]["values"][0]["stacktrace"]["frames"]

    def test_local_variables_are_not_attached(self, sentry):
        """``include_local_variables=False``. A frame in ``auth/`` holds
        the raw token in a local; this is what keeps it out."""
        transport = sentry()

        def inner():
            raw_reset_token = FAKE_TOKEN  # noqa: F841
            raise RuntimeError("locals check")

        try:
            inner()
        except RuntimeError:
            sentry_sdk.capture_exception()

        event = transport.events[-1]
        assert FAKE_TOKEN not in _blob(event)
        frames = event["exception"]["values"][0]["stacktrace"]["frames"]
        assert all("vars" not in f for f in frames), frames


# ---------------------------------------------------------------------------
# D. FastAPI
# ---------------------------------------------------------------------------


class TestFastApiCapture:
    """A minimal synthetic app, so this tests the integration rather
    than any particular production route."""

    def _app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/boom")
        def boom():
            raise RuntimeError("synthetic unhandled 500")

        @app.get("/not-found")
        def not_found():
            raise HTTPException(status_code=404, detail="No such thing.")

        @app.get("/forbidden")
        def forbidden():
            raise HTTPException(status_code=403, detail="Access denied.")

        @app.get("/fine")
        def fine():
            return {"ok": True}

        return app

    def test_an_unhandled_error_is_captured(self, sentry):
        transport = sentry()
        client = TestClient(self._app(), raise_server_exceptions=False)
        res = client.get("/boom")
        assert res.status_code == 500
        assert transport.events, "the unhandled 500 was not captured"
        event = transport.events[-1]
        assert event["exception"]["values"][-1]["type"] == "RuntimeError"
        assert event["tags"]["component"] == "fc-api"
        assert "boom" in str(event.get("transaction", ""))

    @pytest.mark.parametrize("path,code", [
        ("/not-found", 404), ("/forbidden", 403),
    ])
    def test_a_handled_http_exception_is_not_captured(
        self, sentry, path, code,
    ):
        """Ordinary member mistakes — a wrong password, a stale invite
        link — must not become issues. These are the bulk of 4xx
        traffic and would bury everything else."""
        transport = sentry()
        client = TestClient(self._app(), raise_server_exceptions=False)
        assert client.get(path).status_code == code
        assert transport.events == [], transport.events

    def test_a_successful_request_captures_nothing(self, sentry):
        transport = sentry()
        client = TestClient(self._app())
        assert client.get("/fine").status_code == 200
        assert transport.events == []

    def test_the_failed_request_range_is_not_widened(self, sentry):
        """The SDK's default is 500-599. Widening it to include 4xx is
        the single easiest way to make this unusable, so it is pinned."""
        sentry()
        from sentry_sdk.integrations.starlette import StarletteIntegration

        integrations = sentry_sdk.get_client().integrations
        starlette = integrations.get(StarletteIntegration.identifier)
        assert starlette is not None, integrations.keys()
        codes = starlette.failed_request_status_codes
        assert 500 in codes
        assert 404 not in codes
        assert 403 not in codes
        assert 401 not in codes
        assert 429 not in codes

    def test_request_details_are_scrubbed_on_a_captured_request(self, sentry):
        transport = sentry()
        client = TestClient(self._app(), raise_server_exceptions=False)
        client.get(
            f"/boom?token={FAKE_TOKEN}",
            headers={
                "Authorization": FAKE_BEARER,
                "Cookie": FAKE_COOKIE,
                "X-Internal-Token": "FAKE_INTERNAL",
            },
        )
        assert transport.events
        _assert_no_secrets(transport.events[-1])


# ---------------------------------------------------------------------------
# E. Logging integration
# ---------------------------------------------------------------------------


class TestLoggingIntegration:
    """The 65 ``logger.exception`` sites. One integration point, no
    per-site edits — that was the whole point of doing it this way."""

    def test_logger_exception_becomes_an_event(self, sentry):
        transport = sentry()
        log = logging.getLogger("test.observability.exception")
        try:
            raise RuntimeError("a log-and-continue failure")
        except RuntimeError:
            log.exception("comms: could not send")

        assert transport.events, "logger.exception produced no event"
        event = transport.events[-1]
        assert event["exception"]["values"][-1]["type"] == "RuntimeError"
        assert event["tags"]["component"] == "fc-api"

    def test_logger_error_becomes_an_event(self, sentry):
        transport = sentry()
        logging.getLogger("test.observability.error").error("a hard error")
        assert transport.events

    @pytest.mark.parametrize("level", ["info", "warning", "debug"])
    def test_info_and_warning_do_not_become_events(self, sentry, level):
        """``event_level`` stays at ERROR. The platform logs at INFO
        constantly — every emit, every sweep summary — and promoting
        those would be indistinguishable from an outage."""
        transport = sentry()
        getattr(logging.getLogger("test.observability.quiet"), level)(
            "routine: nothing is wrong",
        )
        assert transport.events == [], transport.events

    def test_a_log_event_is_scrubbed_too(self, sentry):
        """Same scrubber, different channel — the message arrives in
        ``logentry`` rather than ``exception``."""
        transport = sentry()
        logging.getLogger("test.observability.scrub").error(
            "failed for %s with token=%s", FAKE_EMAIL, FAKE_TOKEN,
        )
        assert transport.events
        _assert_no_secrets(transport.events[-1])

    def test_the_logger_name_survives(self, sentry):
        """Which subsystem failed is the first thing you want.

        Uses a test-only logger name rather than a real one like
        ``app.comms.worker``. Another suite reconfigures levels and
        handlers across the ``app.*`` hierarchy, so borrowing a
        production logger name made this pass alone and fail in the
        full run — a property of the test, not of the integration.
        """
        transport = sentry()
        name = "fc.test.observability.named"
        logging.getLogger(name).error("dispatch failed")
        assert transport.events[-1]["logger"] == name


# ---------------------------------------------------------------------------
# Operational shape
# ---------------------------------------------------------------------------


class TestWiring:
    def test_init_runs_before_the_app_is_constructed(self):
        """The SDK patches Starlette's middleware stack at init. An app
        built first is not instrumented, and the failure is silent."""
        source = (BACKEND / "app/main.py").read_text(encoding="utf-8")
        assert "init_sentry(\"fc-api\")" in source
        assert source.index("init_sentry(\"fc-api\")") < source.index(
            "app = FastAPI("
        ), "init_sentry must come before FastAPI(...)"

    def test_no_custom_sentry_middleware_was_added(self):
        """The integration already covers unhandled requests. A second
        mechanism would double-report."""
        source = (BACKEND / "app/main.py").read_text(encoding="utf-8")
        assert "SentryAsgiMiddleware" not in source

    def test_no_per_site_capture_calls_were_added(self):
        """Phase 1 is one integration point, not 65 edits."""
        offenders = []
        for path in sorted(BACKEND.glob("app/**/*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if rel == "app/core/observability.py":
                continue
            text = path.read_text(encoding="utf-8")
            for name in ("capture_exception", "capture_message"):
                if name in text:
                    offenders.append(f"{rel}: {name}")
        assert offenders == [], offenders

    def test_the_sdk_is_pinned(self):
        requirements = (BACKEND / "requirements.txt").read_text()
        line = next(
            l for l in requirements.splitlines() if l.startswith("sentry-sdk")
        )
        assert re.match(r"^sentry-sdk\[fastapi\]==\d+\.\d+\.\d+$", line), line

    def test_the_blueprint_declares_the_dsn_for_fc_api_only(self):
        """Phase 1 scope, enforced. The seven crons get theirs in
        Phase 2 and this fails if one is added early."""
        import yaml

        data = yaml.safe_load((BACKEND.parent / "render.yaml").read_text())
        with_dsn = sorted(
            s["name"] for s in data["services"]
            if any(e["key"] == "SENTRY_DSN" for e in s.get("envVars", []))
        )
        assert with_dsn == ["fc-api"], with_dsn

        api = next(s for s in data["services"] if s["name"] == "fc-api")
        entry = next(e for e in api["envVars"] if e["key"] == "SENTRY_DSN")
        assert entry.get("sync") is False
        assert "value" not in entry, "the DSN must not be committed"

    def test_no_sentry_environment_variable_is_declared(self):
        """Derived from APP_ENV instead, so the two cannot drift."""
        # Comments stripped: the block explaining *why* these are not
        # declared names them, and a raw substring check fails on its
        # own explanation.
        blueprint = "\n".join(
            line.split("#", 1)[0]
            for line in (BACKEND.parent / "render.yaml").read_text().splitlines()
        )
        assert "SENTRY_ENVIRONMENT" not in blueprint
        assert "SENTRY_RELEASE" not in blueprint

    def test_there_is_no_debug_route(self):
        """A permanent endpoint that makes production raise is not an
        acceptable way to test error reporting."""
        for path in sorted(BACKEND.glob("app/**/*.py")):
            text = path.read_text(encoding="utf-8")
            assert "sentry-debug" not in text, path
            assert "sentry_debug" not in text, path

    def test_the_smoke_test_script_is_not_scheduled_and_not_imported(self):
        blueprint = (BACKEND.parent / "render.yaml").read_text()
        assert "sentry_smoke_test" not in blueprint
        for path in sorted(BACKEND.glob("app/**/*.py")):
            assert "sentry_smoke_test" not in path.read_text(), path

    def test_the_smoke_test_uses_only_fake_credentials(self):
        """It must not read or print a real secret. Every value it
        sends is a literal in the file, and the address is on a
        reserved TLD that cannot resolve."""
        source = (BACKEND / "scripts/sentry_smoke_test.py").read_text()
        assert "example.invalid" in source
        assert "FAKE_" in source
        # Reads only these two, both non-secret.
        env_reads = re.findall(r"os\.environ(?:\.get)?[\(\[]\s*['\"](\w+)", source)
        assert set(env_reads) <= {
            "APP_ENV", "RENDER_GIT_COMMIT", "FC_SERVICE_ROLE",
        }, env_reads
        assert "SENTRY_DSN" not in source.replace(
            "SENTRY_DSN is not set", "",
        ).replace("``SENTRY_DSN``", ""), "the script must not read the DSN itself"

    def test_observability_imports_nothing_from_the_app(self):
        """Dependency-free, so a cron can call it first and no import
        order can reintroduce a cycle. Same rule as url_policy.py."""
        import ast

        tree = ast.parse((BACKEND / "app/core/observability.py").read_text())
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"):
                found.append(node.module)
            elif isinstance(node, ast.Import):
                found += [a.name for a in node.names if a.name.startswith("app")]
        assert found == [], found
