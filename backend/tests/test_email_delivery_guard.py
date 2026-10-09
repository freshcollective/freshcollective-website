"""Automated tests cannot send real email. Proven, not assumed.

Written after a test-suite run sent real booking confirmations through
the live Resend account on 2026-10-09. See
``app/comms/delivery_guard.py`` for the chain that allowed it.

Two things are being protected here, and they pull in opposite
directions, which is why both get explicit tests:

* A test must never reach a real provider — whatever the recipient
  address, whatever ``APP_ENV`` claims, whatever opt-in flags a
  developer has exported. No override exists, and
  ``test_no_opt_in_can_lift_the_test_process_block`` is what stops one
  being added quietly.
* Production must keep sending. A guard that blocks real member email
  is a worse outage than the one it prevents, so
  ``TestProductionStillSends`` pins the allow path from the opposite
  direction.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_email_delivery_guard.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

from app.comms import delivery_guard as dg
from app.comms.providers.base import RenderedPayload
from app.comms.providers.resend import ResendProvider
from app.core.config import settings
from tests.conftest import FAKE_RESEND_KEY, RealEmailSendAttempted

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _payload(to: str = "member@freshcollective.au") -> RenderedPayload:
    return RenderedPayload(
        to=to,
        subject="Booked: Circle",
        body_html="<p>See you there.</p>",
    )


@pytest.fixture
def outside_a_test_process(monkeypatch):
    """Simulate a non-test process, for the layers below layer 1.

    The guard's first layer reads environment variables, so testing
    layers 2 and 3 means clearing them first — otherwise layer 1
    answers and the assertion proves nothing about the layer under
    test.

    Returns a callable to invoke *inside the test body* rather than
    doing the work at fixture time, and that is not a style choice:
    pytest re-sets ``PYTEST_CURRENT_TEST`` at the start of every test
    phase, so anything a fixture unsets during setup is back in place
    by the time the body runs. Which is a quietly reassuring property
    of the guard — a test cannot disarm it from a fixture even when it
    is trying to.
    """

    def _apply() -> None:
        monkeypatch.delenv(dg.TEST_MODE_ENV_VAR, raising=False)
        monkeypatch.delenv(dg.PYTEST_MARKER_ENV_VAR, raising=False)
        monkeypatch.delenv(dg.ALLOW_REAL_EMAIL_ENV_VAR, raising=False)
        assert not dg.running_in_test_process()

    return _apply


# ---------------------------------------------------------------------------
# Layer 1 — the test suite, unconditionally
# ---------------------------------------------------------------------------


class TestTheSuiteCannotReachResend:
    """The enforcement that actually stops the suite emailing anyone.

    It sits on the SDK's send functions, installed by ``conftest`` at
    import time — not on a policy check inside the provider. The first
    attempt put it in the provider and it broke 38 comms tests that
    legitimately drive dispatch against their own stub; see
    ``app/comms/delivery_guard.outbound_email_block``. Guarding the
    network boundary instead protects the thing that actually matters
    and leaves stubs alone.
    """

    def test_this_process_is_recognised_as_a_test_process(self):
        assert dg.running_in_test_process()

    def test_the_sdk_send_is_tripwired(self):
        import resend

        with pytest.raises(RealEmailSendAttempted):
            resend.Emails.send({"to": ["member@freshcollective.au"]})

    def test_batch_send_is_tripwired_too(self):
        import resend

        with pytest.raises(RealEmailSendAttempted):
            resend.Batch.send([{"to": ["member@freshcollective.au"]}])

    def test_the_tripwire_is_not_swallowed_by_broad_except_clauses(self):
        # ``schedule_routing_if_needed`` promises never to raise and
        # catches Exception to keep that promise, and
        # ``ResendProvider.send`` wraps the SDK call in its own
        # ``except Exception``. An ordinary exception would therefore be
        # logged as a failed delivery and the test would pass, which is
        # precisely the silence this whole exercise is about.
        assert issubclass(RealEmailSendAttempted, BaseException)
        assert not issubclass(RealEmailSendAttempted, Exception)

    def test_a_test_that_forgets_to_stub_fails_loudly(self, monkeypatch):
        # The end-to-end property: a test reaching the provider without
        # stubbing the SDK gets a hard failure, not a sent email. This
        # is what would have caught the 2026-10-09 incident at the
        # moment it happened.
        monkeypatch.setattr(settings, "email_from", "hello@freshcollective.au")
        with pytest.raises(RealEmailSendAttempted):
            ResendProvider().send(_payload())

    def test_the_guard_defers_inside_a_test_process(self):
        # Documents the division of responsibility: the policy layers
        # protect real processes, the tripwire protects the suite.
        assert dg.outbound_email_block("member@freshcollective.au") is None

    def test_the_marker_env_var_alone_marks_a_test_process(self, monkeypatch):
        monkeypatch.delenv(dg.TEST_MODE_ENV_VAR, raising=False)
        monkeypatch.setenv(dg.PYTEST_MARKER_ENV_VAR, "some::test")
        assert dg.running_in_test_process()

    def test_fc_test_mode_alone_marks_a_test_process(self, monkeypatch):
        monkeypatch.delenv(dg.PYTEST_MARKER_ENV_VAR, raising=False)
        monkeypatch.setenv(dg.TEST_MODE_ENV_VAR, "1")
        assert dg.running_in_test_process()


# ---------------------------------------------------------------------------
# Layer 2 — reserved domains, in every environment
# ---------------------------------------------------------------------------


class TestReservedDomains:
    @pytest.mark.parametrize(
        "recipient",
        [
            "m0-abc123@example.test",
            "m1-def456@example.test",
            "someone@sub.domain.test",
            "someone@thing.invalid",
            "someone@thing.example",
            "someone@localhost",
            "someone@example.com",
            "someone@example.net",
            "someone@example.org",
            "someone@mail.example.com",
            "SOMEONE@EXAMPLE.TEST",
            "someone@example.test.",
        ],
    )
    def test_reserved_recipients_are_recognised(self, recipient):
        assert dg.is_reserved_recipient(recipient)

    @pytest.mark.parametrize(
        "recipient",
        [
            "member@freshcollective.au",
            "lindsey.wd@gmail.com",
            "someone@testing.com.au",      # "test" inside a real name
            "someone@contest.org",         # endswith "test" but not ".test"
            "someone@example.company",     # not the reserved name
        ],
    )
    def test_real_recipients_are_not_mistaken_for_reserved(self, recipient):
        assert not dg.is_reserved_recipient(recipient)

    def test_reserved_domains_are_refused_even_in_production(
        self, outside_a_test_process, monkeypatch,
    ):
        outside_a_test_process()
        # The incident's addresses hard-bounce, and a hard bounce costs
        # sending reputation. Refusing is the correct behaviour in
        # production too, not a test-only nicety.
        monkeypatch.setattr(settings, "app_env", "production")
        block = dg.outbound_email_block("m0-abc123@example.test")
        assert block is not None
        assert block.error_class == "reserved_domain"

    def test_an_empty_recipient_is_not_treated_as_reserved(self):
        # It is refused for other reasons; mislabelling it here would
        # make the audit trail say something untrue.
        assert not dg.is_reserved_recipient("")
        assert not dg.is_reserved_recipient(None)


# ---------------------------------------------------------------------------
# Layer 3 — development must opt in explicitly
# ---------------------------------------------------------------------------


class TestDevelopmentNeedsAnExplicitOptIn:
    def test_development_is_blocked_by_default(
        self, outside_a_test_process, monkeypatch,
    ):
        outside_a_test_process()
        monkeypatch.setattr(settings, "app_env", "development")
        block = dg.outbound_email_block("member@freshcollective.au")
        assert block is not None
        assert block.error_class == "non_production_env"

    def test_staging_is_blocked_by_default(
        self, outside_a_test_process, monkeypatch,
    ):
        outside_a_test_process()
        monkeypatch.setattr(settings, "app_env", "staging")
        block = dg.outbound_email_block("member@freshcollective.au")
        assert block is not None
        assert block.error_class == "non_production_env"

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " 1 "])
    def test_the_opt_in_allows_deliberate_local_delivery(
        self, outside_a_test_process, monkeypatch, value,
    ):
        outside_a_test_process()
        # The controlled method for testing real delivery: an env var,
        # so nothing has to be edited and accidentally committed.
        monkeypatch.setattr(settings, "app_env", "development")
        monkeypatch.setenv(dg.ALLOW_REAL_EMAIL_ENV_VAR, value)
        assert dg.outbound_email_block("member@freshcollective.au") is None

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "maybe"])
    def test_a_non_affirmative_opt_in_value_does_not_count(
        self, outside_a_test_process, monkeypatch, value,
    ):
        outside_a_test_process()
        monkeypatch.setattr(settings, "app_env", "development")
        monkeypatch.setenv(dg.ALLOW_REAL_EMAIL_ENV_VAR, value)
        block = dg.outbound_email_block("member@freshcollective.au")
        assert block is not None
        assert block.error_class == "non_production_env"

    def test_the_opt_in_does_not_unlock_reserved_domains(
        self, outside_a_test_process, monkeypatch,
    ):
        outside_a_test_process()
        monkeypatch.setattr(settings, "app_env", "development")
        monkeypatch.setenv(dg.ALLOW_REAL_EMAIL_ENV_VAR, "1")
        block = dg.outbound_email_block("m0-abc@example.test")
        assert block is not None
        assert block.error_class == "reserved_domain"


# ---------------------------------------------------------------------------
# Production is unchanged
# ---------------------------------------------------------------------------


class TestProductionStillSends:
    def test_production_with_a_real_recipient_is_allowed(
        self, outside_a_test_process, monkeypatch,
    ):
        outside_a_test_process()
        # The guard's whole value depends on this staying true. A
        # protection that blocks real member email is a worse incident
        # than the one it prevents.
        monkeypatch.setattr(settings, "app_env", "production")
        assert dg.outbound_email_block("member@freshcollective.au") is None

    def test_production_needs_no_opt_in(
        self, outside_a_test_process, monkeypatch,
    ):
        outside_a_test_process()
        monkeypatch.setattr(settings, "app_env", "production")
        monkeypatch.delenv(dg.ALLOW_REAL_EMAIL_ENV_VAR, raising=False)
        assert dg.outbound_email_block("member@freshcollective.au") is None


# ---------------------------------------------------------------------------
# The provider honours the guard, and never reaches the network
# ---------------------------------------------------------------------------


class TestProviderHonoursTheGuard:
    def test_a_reserved_recipient_is_refused_without_reaching_the_sdk(
        self, monkeypatch,
    ):
        # The incident's own addresses. Fully configured on purpose, so
        # the only thing stopping this is the guard — and if the guard
        # let it through, the tripwire would raise rather than this
        # returning a result.
        monkeypatch.delenv(dg.TEST_MODE_ENV_VAR, raising=False)
        monkeypatch.delenv(dg.PYTEST_MARKER_ENV_VAR, raising=False)
        monkeypatch.setattr(settings, "resend_api_key", "re_not_a_real_key")
        monkeypatch.setattr(settings, "email_from", "hello@freshcollective.au")

        result = ResendProvider().send(_payload("m0-abc123@example.test"))

        assert result.accepted is False
        assert result.error_class == "reserved_domain"

    def test_a_development_send_is_refused_without_reaching_the_sdk(
        self, monkeypatch,
    ):
        monkeypatch.delenv(dg.TEST_MODE_ENV_VAR, raising=False)
        monkeypatch.delenv(dg.PYTEST_MARKER_ENV_VAR, raising=False)
        monkeypatch.delenv(dg.ALLOW_REAL_EMAIL_ENV_VAR, raising=False)
        monkeypatch.setattr(settings, "app_env", "development")
        monkeypatch.setattr(settings, "resend_api_key", "re_not_a_real_key")
        monkeypatch.setattr(settings, "email_from", "hello@freshcollective.au")

        result = ResendProvider().send(_payload())

        assert result.accepted is False
        assert result.error_class == "non_production_env"

    def test_the_guard_runs_before_the_api_key_check(self):
        # Order matters: if the key check came first, a configured
        # developer environment would fall straight through to the
        # network. Asserted on the parsed function body rather than a
        # substring search, because the docstrings in this area discuss
        # both checks by name.
        source = (BACKEND_ROOT / "app/comms/providers/resend.py").read_text()
        tree = ast.parse(source)
        send = next(
            node
            for cls in tree.body
            if isinstance(cls, ast.ClassDef) and cls.name == "ResendProvider"
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "send"
        )
        statements = [n for n in send.body if not _is_docstring(n)]

        guard_at = _first_index(
            statements, lambda n: "outbound_email_block" in ast.dump(n)
        )
        key_at = _first_index(
            statements, lambda n: "resend_api_key" in ast.dump(n)
        )
        assert guard_at is not None, "send() no longer consults the guard"
        assert key_at is not None
        assert guard_at < key_at, (
            "the delivery guard must be the first thing send() does"
        )


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def _first_index(statements, predicate) -> int | None:
    for i, node in enumerate(statements):
        if predicate(node):
            return i
    return None


class TestProductionDeliveryStillReachesTheProvider:
    """The guard must not have broken real sending.

    Every other test here runs inside a test process, where layer 1
    answers first — so none of them can show that ``send`` proceeds all
    the way to the provider when it should. This one runs in a
    subprocess with no pytest markers in its environment, which is the
    only way to observe the allow path end to end.
    """

    def test_a_production_send_reaches_the_resend_client(self, tmp_path):
        import subprocess
        import textwrap

        # A stand-in ``resend`` that records instead of sending, placed
        # first on sys.path so it shadows the real package.
        (tmp_path / "resend.py").write_text(
            textwrap.dedent(
                """
                api_key = None
                calls = []

                class Emails:
                    @staticmethod
                    def send(request, options=None):
                        calls.append((request, options))
                        return {"id": "stub-message-id"}
                """
            )
        )

        script = textwrap.dedent(
            """
            import os, sys

            from app.comms.providers.base import RenderedPayload
            from app.comms.providers.resend import ResendProvider
            from app.core.config import settings
            from app.comms.delivery_guard import running_in_test_process

            assert not running_in_test_process(), "subprocess looks like a test"

            # Set on the loaded settings rather than in the environment:
            # APP_ENV=production triggers this repo's unrelated boot
            # guards (R2 and a live Stripe key), which a developer
            # machine cannot satisfy. The branch under test is the same
            # one either way.
            settings.app_env = "production"
            settings.resend_api_key = "re_stub_key"
            settings.email_from = "hello@freshcollective.au"

            result = ResendProvider().send(
                RenderedPayload(
                    to="member@freshcollective.au",
                    subject="Booked: Circle",
                    body_html="<p>See you there.</p>",
                )
            )

            import resend
            assert len(resend.calls) == 1, (
                f"provider did not reach the client: {result!r}"
            )
            request = resend.calls[0][0]
            assert request["to"] == ["member@freshcollective.au"], request["to"]
            assert result.accepted is True, result
            print("PRODUCTION_SEND_OK")
            """
        )

        env = dict(os.environ)
        # Strip every marker that would make the subprocess look like a
        # test, including the ones pytest exports to children.
        for name in (
            "FC_TEST_MODE",
            "PYTEST_CURRENT_TEST",
            "FC_ALLOW_REAL_EMAIL",
            "PYTEST_VERSION",
        ):
            env.pop(name, None)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(tmp_path), str(BACKEND_ROOT), env.get("PYTHONPATH", "")]
        )

        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, cwd=str(BACKEND_ROOT), env=env,
            timeout=120,
        )
        assert "PRODUCTION_SEND_OK" in proc.stdout, (
            f"production send path is broken.\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )


class TestRefusalsDoNotLeakAddresses:
    """A refusal is logged, and on fc-api a WARNING becomes a Sentry
    breadcrumb. The address must not ride along."""

    @pytest.mark.parametrize(
        "recipient,expected",
        [
            ("m0-abc123@example.test", "***@example.test"),
            ("member@freshcollective.au", "***@freshcollective.au"),
            ("someone@localhost", "***@localhost"),
            ("not-an-address", "***"),
            ("", "(no recipient)"),
            (None, "(no recipient)"),
        ],
    )
    def test_only_the_domain_survives(self, recipient, expected):
        assert dg.redact_recipient(recipient) == expected

    def test_the_local_part_never_appears(self):
        for address in (
            "lindsey.wd@gmail.com",
            "playwright-test@fresh-collective.test",
            "m0-abc123@example.test",
        ):
            local = address.split("@")[0]
            assert local not in dg.redact_recipient(address)

    def test_the_provider_logs_the_redacted_form_not_the_address(self):
        """The provider's refusal log must pass the recipient through
        ``redact_recipient``.

        Asserted on the parsed call rather than by capturing the log.
        Capture proved unreliable in the full suite — something ahead of
        this file leaves the provider's logger emitting nothing, so the
        test passed alone and failed in the suite, which is the worst of
        both worlds. Reading the source is deterministic and is anyway
        the stronger claim: it pins what the code does, not what one run
        happened to observe.
        """
        source = (BACKEND_ROOT / "app/comms/providers/resend.py").read_text()
        tree = ast.parse(source)
        send = next(
            node
            for cls in tree.body
            if isinstance(cls, ast.ClassDef) and cls.name == "ResendProvider"
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "send"
        )

        # The logging call inside the guard's refusal branch.
        guard_branch = next(
            n for n in send.body
            if isinstance(n, ast.If) and "block" in ast.dump(n.test)
        )
        log_calls = [
            n.value for n in ast.walk(guard_branch)
            if isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call)
            and "logger" in ast.dump(n.value.func)
        ]
        assert log_calls, "the refusal branch no longer logs anything"

        for call in log_calls:
            dumped = ast.dump(call)
            assert "redact_recipient" in dumped, (
                "the refusal log must redact the recipient"
            )
            # ``payload.to`` must not be passed raw alongside it.
            raw = [
                a for a in call.args
                if isinstance(a, ast.Attribute)
                and a.attr == "to"
                and isinstance(a.value, ast.Name)
                and a.value.id == "payload"
            ]
            assert not raw, "the refusal log passes payload.to unredacted"


# ---------------------------------------------------------------------------
# The conftest kill-switch itself
# ---------------------------------------------------------------------------


class TestConftestKillSwitch:
    def test_fc_test_mode_is_set_for_the_whole_session(self):
        assert os.environ.get("FC_TEST_MODE") == "1"

    def test_the_developers_real_key_is_replaced_with_a_fake(self):
        # Even though a developer's .env carries a live key — which is
        # exactly the situation that caused the incident. The value is
        # deliberately a recognisable fake rather than empty: blanking
        # it makes the provider short-circuit and stops the comms suite
        # exercising dispatch at all.
        assert os.environ.get("RESEND_API_KEY") == FAKE_RESEND_KEY
        assert settings.resend_api_key == FAKE_RESEND_KEY
        assert "FAKE" in (settings.resend_api_key or "")

    def test_the_real_delivery_opt_in_is_not_set(self):
        # A flag left exported in a shell must not follow the developer
        # into a test run.
        assert not os.environ.get("FC_ALLOW_REAL_EMAIL")

    def test_conftest_sets_these_before_importing_the_app(self):
        # Ordering is the part that cannot be verified at runtime: by
        # the time any test executes, the app is long since imported.
        # If these moved below the first app import, a module-level
        # ``settings`` would already have captured the live key.
        source = (BACKEND_ROOT / "tests/conftest.py").read_text()
        tree = ast.parse(source)

        def line_of_env_write(name: str) -> int:
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Subscript)
                    and "environ" in ast.dump(node.value)
                    and isinstance(node.slice, ast.Constant)
                    and node.slice.value == name
                ):
                    return node.lineno
            raise AssertionError(f"conftest no longer sets {name}")

        def imports_app(node: ast.AST) -> bool:
            if isinstance(node, ast.ImportFrom):
                return (node.module or "").startswith("app")
            if isinstance(node, ast.Import):
                return any(a.name.startswith("app") for a in node.names)
            return False

        app_imports = [n.lineno for n in ast.walk(tree) if imports_app(n)]
        assert app_imports, "expected conftest to import app modules somewhere"
        first_app_import = min(app_imports)

        assert line_of_env_write("FC_TEST_MODE") < first_app_import
        assert line_of_env_write("RESEND_API_KEY") < first_app_import

    def test_the_tripwire_is_installed_at_conftest_import_time(self):
        # Not in a fixture: background comms routing runs on its own
        # stack, and collection-time code runs before any fixture.
        source = (BACKEND_ROOT / "tests/conftest.py").read_text()
        tree = ast.parse(source)
        top_level_calls = [
            n.value.func.id
            for n in tree.body
            if isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name)
        ]
        assert "_install_resend_tripwire" in top_level_calls
