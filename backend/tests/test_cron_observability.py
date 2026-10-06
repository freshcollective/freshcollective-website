"""Error reporting for the seven crons, including the failures that exit 0.

What Phase 2 is actually for
----------------------------
Render already shouts when a cron exits non-zero, and that stays the
primary alarm. The gap is the other shape of failure: a sweep that runs
exactly as designed, exits 0, and leaves a creator unpaid or a refund's
outcome unknown. Render sees a healthy cron. Nobody finds out.

So this file is mostly about two opposite risks, and they pull against
each other:

* a run that needed a person produced no event — the gap above;
* a routine run produced one — which is how a monitoring system becomes
  something people mute.

Both are asserted against real SDK machinery: a capturing ``Transport``
receives the envelope that would genuinely have left the process, after
``before_send`` and every default integration.

The third risk is the Phase 1 one, now spread across eight processes
instead of one: that an event carries something it should not. The
summaries are built from a helper that accepts counts and nothing else,
and that is asserted here rather than trusted.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_cron_observability.py
"""

from __future__ import annotations

import ast
import collections
import contextlib
import importlib.util
import json
import logging
import os
import pathlib
import warnings

import pytest
import sentry_sdk
import yaml

from app.core.observability import (
    DROPPED_NOT_A_COUNT,
    FLUSH_TIMEOUT_SECONDS,
    JOB_SUMMARY_LEVELS,
    REDACTED,
    RENDER_ONLY_LOGGER_SUFFIX,
    capture_job_summary,
    flush_sentry,
    init_sentry,
)
from tests.test_observability import (
    ALL_FAKE_SECRETS,
    FAKE_BEARER,
    FAKE_DSN,
    FAKE_EMAIL,
    FAKE_SIG,
    FAKE_TOKEN,
    CapturingTransport,
)

BACKEND = pathlib.Path(__file__).resolve().parent.parent
BLUEPRINT = BACKEND.parent / "render.yaml"

RELEASE = "5f0dadaf02f72f74bbfeb1b8019c4cf856bb7d14"

#: Payment-transaction ids are what the Connect sweepers hold when a
#: transfer is still owed. Shaped like the real ones so a leak looks
#: like a leak.
FAKE_TXN_IDS = [f"txn_FAKE{n:04d}abcdef" for n in range(25)]


# ---------------------------------------------------------------------------
# The blueprint is the source of truth for which crons exist
# ---------------------------------------------------------------------------


def _services() -> list[dict]:
    return yaml.safe_load(BLUEPRINT.read_text(encoding="utf-8"))["services"]


def _crons() -> list[dict]:
    return [
        s for s in _services()
        if s.get("type") == "cron" and s.get("runtime") == "python"
    ]


def _script_for(service: dict) -> pathlib.Path:
    """The file a cron's ``startCommand`` actually runs."""
    return BACKEND / service["startCommand"].split()[1]


def _env_of(service: dict) -> dict[str, str | None]:
    return {e["key"]: e.get("value") for e in service.get("envVars", [])}


CRONS = _crons()
CRON_NAMES = [s["name"] for s in CRONS]

#: Named so the inventory in the brief is checked rather than assumed —
#: a cron added to the blueprint without being considered here fails
#: ``test_the_inventory_is_complete``.
EXPECTED_CRONS = {
    "fc-fip3-grace-reconciler",
    "fc-refund-reconciler",
    "fc-creator-subscription-grace-reconciler",
    "fc-creator-grant-expiry",
    "fc-gathering-reminders",
    "fc-connect-transfer-sweeper",
    "fc-connect-recovery-sweeper",
}


@contextlib.contextmanager
def _import_sandbox():
    """Import a script without letting it change the environment.

    Two things need containing. ``SENTRY_DSN`` has to be *absent*,
    because these scripts call ``init_sentry`` at module scope and
    importing one with a DSN present would replace the active client
    with a transport that tries to reach the network. And whatever a
    script sets for itself has to be undone: the smoke test does
    ``os.environ.setdefault("FC_SERVICE_ROLE", "job")``, and leaking
    that into the session makes the production boot guards in
    ``test_r2_boot_guard`` and ``test_stripe_boot_guard`` stop firing —
    found by running the full suite, not this file.
    """
    snapshot = dict(os.environ)
    os.environ.pop("SENTRY_DSN", None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


def _load(service: dict):
    """Import a cron script as a module."""
    path = _script_for(service)
    with _import_sandbox():
        spec = importlib.util.spec_from_file_location(
            f"_cron_{path.stem}", str(path),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def _by_name(name: str) -> dict:
    return next(s for s in CRONS if s["name"] == name)


TRANSFER_SWEEPER = _load(_by_name("fc-connect-transfer-sweeper"))
RECOVERY_SWEEPER = _load(_by_name("fc-connect-recovery-sweeper"))
REFUND_RECONCILER = _load(_by_name("fc-refund-reconciler"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sentry(monkeypatch):
    """A real, initialised SDK for one component, captured locally."""
    previous = sentry_sdk.get_client()
    transport = CapturingTransport()

    monkeypatch.setenv("SENTRY_DSN", FAKE_DSN)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RENDER_GIT_COMMIT", RELEASE)

    def _start(component: str = "fc-refund-reconciler", **overrides):
        real_init = sentry_sdk.init

        def init_with_transport(**kwargs):
            kwargs["transport"] = transport
            kwargs.update(overrides)
            return real_init(**kwargs)

        monkeypatch.setattr(sentry_sdk, "init", init_with_transport)
        assert init_sentry(component) is True
        return transport

    yield _start

    sentry_sdk.get_global_scope().clear()
    sentry_sdk.get_isolation_scope().clear()
    sentry_sdk.Scope.get_global_scope().set_client(previous)


def _blob(event: dict) -> str:
    return json.dumps(event, default=str)


def _assert_clean(event: dict) -> None:
    """No fake secret, and no payment id, anywhere in the event."""
    blob = _blob(event)
    for secret in ALL_FAKE_SECRETS:
        assert secret not in blob, f"{secret!r} survived:\n{blob[:2000]}"
    for txn_id in FAKE_TXN_IDS:
        assert txn_id not in blob, f"{txn_id!r} survived:\n{blob[:2000]}"


#: One logging call site: which object it was called on, at what
#: level, with what message template.
LogCall = collections.namedtuple("LogCall", "receiver level message")

LOG_LEVELS = ("debug", "info", "warning", "error", "exception", "critical")


def _log_calls(path: pathlib.Path) -> list[LogCall]:
    """Every logging call in a module, parsed.

    Parsed rather than grepped, for the reason the project learned the
    hard way: these modules explain in prose why a particular level was
    chosen, and a substring search cannot tell an explanation from a
    call.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in LOG_LEVELS:
            continue
        receiver = getattr(func.value, "id", None) or getattr(
            func.value, "attr", None,
        )
        message = ""
        if node.args and isinstance(node.args[0], ast.Constant):
            if isinstance(node.args[0].value, str):
                message = node.args[0].value
        found.append(LogCall(receiver, func.attr, message))
    return found


def _logger_calls(path: pathlib.Path, level: str) -> list[str]:
    """The message templates logged at one level."""
    return [c.message for c in _log_calls(path) if c.level == level and c.message]


def _render_only_logger_names(path: pathlib.Path) -> list[str]:
    """The name every ``*_logger = logging.getLogger(...)`` is built
    from, for assignments whose target looks like a Render-only one."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [getattr(t, "id", None) for t in node.targets]
        if "id_logger" not in targets:
            continue
        names.append(ast.unparse(node.value))
    return names


# ---------------------------------------------------------------------------
# A. Every cron initialises, with its own name
# ---------------------------------------------------------------------------


class TestEveryCronIsWired:
    def test_the_inventory_is_complete(self):
        """The seven from the brief, and nothing unaccounted for."""
        assert set(CRON_NAMES) == EXPECTED_CRONS, set(CRON_NAMES) ^ EXPECTED_CRONS

    @pytest.mark.parametrize("service", CRONS, ids=CRON_NAMES)
    def test_it_initialises_with_its_render_service_name(self, service):
        """The component tag has to be the name on the Render service,
        or an issue cannot be traced back to the job that raised it."""
        source = _script_for(service).read_text(encoding="utf-8")
        expected = f'init_sentry("{service["name"]}")'
        assert source.count(expected) == 1, (
            f"{service['startCommand']} must call {expected} exactly once"
        )

    @pytest.mark.parametrize("service", CRONS, ids=CRON_NAMES)
    def test_it_initialises_before_it_imports_the_app(self, service):
        """The first thing that can fail in a cron is ``Settings``
        refusing to construct, and that happens while these imports
        run. Initialising afterwards would miss exactly the class of
        failure that took fc-api down on 9cfaf92."""
        source = _script_for(service).read_text(encoding="utf-8")
        init_at = source.index("init_sentry(")
        heavy = [
            source.index(marker)
            for marker in ("import app.main", "from app.db.base import Base")
            if marker in source
        ]
        assert heavy, "no model-registry import found to order against"
        assert init_at < min(heavy)

    @pytest.mark.parametrize("service", CRONS, ids=CRON_NAMES)
    def test_logging_is_configured_before_it_initialises(self, service):
        """So that ``SENTRY_DSN is not set`` is actually printed.

        With no handler installed yet, Python's last-resort handler
        drops anything below WARNING — and that INFO line matters on
        exactly one deploy: the one where somebody forgot the variable
        and is wondering why Sentry is empty.
        """
        source = _script_for(service).read_text(encoding="utf-8")
        assert "logging.basicConfig(" in source, service["name"]
        assert source.index("logging.basicConfig(") < source.index(
            "init_sentry("
        ), service["name"]

    def test_the_components_are_distinct(self):
        names = [s["name"] for s in CRONS]
        assert len(names) == len(set(names))

    def test_no_cron_borrows_another_components_name(self):
        """A copy-pasted script with the wrong name would report a real
        failure under a job that is actually healthy."""
        for service in CRONS:
            source = _script_for(service).read_text(encoding="utf-8")
            for other in CRON_NAMES:
                if other == service["name"]:
                    continue
                assert f'init_sentry("{other}")' not in source, service["name"]

    def test_importing_a_script_changes_no_environment_variable(self):
        """This file imports the scripts to test their real functions,
        and one of them sets ``FC_SERVICE_ROLE=job`` for itself at
        import. Leaking that into the session makes the production boot
        guards in ``test_r2_boot_guard`` and ``test_stripe_boot_guard``
        stop firing — they pass alone and fail in the full run, which
        is the worst way for a test to be wrong.
        """
        before = dict(os.environ)
        _load_smoke()
        _load(_by_name("fc-refund-reconciler"))
        assert dict(os.environ) == before

    def test_the_smoke_test_knows_every_component(self):
        """One verification script for eight processes. If a component
        it cannot name were added, the only way to verify that service
        would be to edit the script under pressure."""
        smoke = _load_smoke()
        assert set(smoke.COMPONENTS) == EXPECTED_CRONS | {"fc-api"}
        assert smoke.COMPONENTS[0] == "fc-api", "the default must come first"
        assert len(smoke.COMPONENTS) == len(set(smoke.COMPONENTS))


def _load_smoke():
    with _import_sandbox():
        spec = importlib.util.spec_from_file_location(
            "_sentry_smoke_test", str(BACKEND / "scripts/sentry_smoke_test.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


# ---------------------------------------------------------------------------
# B. No DSN — every local and ad-hoc run
# ---------------------------------------------------------------------------


class TestWithoutADsn:
    @pytest.mark.parametrize("name", sorted(EXPECTED_CRONS))
    def test_init_is_a_clean_no_op(self, name, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        assert init_sentry(name) is False

    def test_flushing_without_a_client_is_harmless(self, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        init_sentry("fc-refund-reconciler")
        flush_sentry()   # must not raise

    def test_a_summary_without_a_client_is_harmless(self, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        init_sentry("fc-refund-reconciler")
        assert capture_job_summary("nothing listening", failed=1) is None

    def test_the_sweeper_report_paths_are_inert(self, monkeypatch):
        """The summary helpers are called on the normal success path of
        a job with something to report. With no DSN they must behave
        like ordinary code — no client, no network, no raise."""
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        init_sentry("fc-connect-transfer-sweeper")
        report = _transfer_report(failed=1)
        assert TRANSFER_SWEEPER.report_partial_failures(report) is None


# ---------------------------------------------------------------------------
# Report builders — the real dataclasses, not stand-ins
# ---------------------------------------------------------------------------


def _transfer_report(**kwargs):
    from app.services.connect_transfer_sweeper import SweepReport

    report = SweepReport()
    for key, value in kwargs.items():
        setattr(report, key, value)
    return report


def _recovery_report(**kwargs):
    from app.services.connect_recovery_sweeper import RecoverySweepReport

    report = RecoverySweepReport()
    for key, value in kwargs.items():
        setattr(report, key, value)
    return report


def _refund_summary(**kwargs):
    summary = {
        "in_flight_reconciled": 0,
        "in_flight_transient": 0,
        "accepted_reconciled": 0,
        "accepted_transient": 0,
    }
    summary.update(kwargs)
    return summary


# ---------------------------------------------------------------------------
# C. Fatal failures — Render's semantics are not ours to change
# ---------------------------------------------------------------------------


class TestFatalFailures:
    def test_a_fatal_error_reports_once_and_keeps_its_exit_code(self, sentry):
        """What every script's ``except`` branch does: log the exception
        and return non-zero. One event, and the cron still fails."""
        transport = sentry("fc-refund-reconciler")
        logger = logging.getLogger("test_cron_fatal")

        def main() -> int:
            try:
                raise RuntimeError("the sweep could not finish")
            except Exception:
                logger.exception("refund reconcile failed")
                return 1

        assert main() == 1
        assert len(transport.events) == 1, [
            e.get("logentry", e.get("exception")) for e in transport.events
        ]
        event = transport.events[0]
        assert event["tags"]["component"] == "fc-refund-reconciler"
        assert event["environment"] == "production"
        assert event["release"] == RELEASE
        assert "RuntimeError" in _blob(event)
        assert "the sweep could not finish" in _blob(event)

    @pytest.mark.parametrize("service", CRONS, ids=CRON_NAMES)
    def test_no_script_also_captures_its_fatal_error_by_hand(self, service):
        """``logger.exception`` already becomes an event through the
        logging integration. A ``capture_exception`` beside it would
        file the same failure twice."""
        source = _script_for(service).read_text(encoding="utf-8")
        assert "capture_exception" not in source, service["name"]

    @pytest.mark.parametrize("service", CRONS, ids=CRON_NAMES)
    def test_no_script_swallows_a_fatal_error_to_report_it(self, service):
        """The dangerous version of this change: catch, send to Sentry,
        return 0, and Render stops noticing. Every script's fatal branch
        must still hand back a non-zero code."""
        tree = ast.parse(_script_for(service).read_text(encoding="utf-8"))
        main = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        handlers = [
            node for node in ast.walk(main) if isinstance(node, ast.ExceptHandler)
        ]
        assert handlers, f"{service['name']} has no fatal handler"
        for handler in handlers:
            returns = [
                node for node in ast.walk(handler)
                if isinstance(node, ast.Return)
            ]
            assert returns, "a fatal handler that returns nothing exits 0"
            for node in returns:
                assert isinstance(node.value, ast.Constant), ast.dump(node)
                assert node.value.value != 0, (
                    f"{service['name']} returns 0 from a fatal handler"
                )

    @pytest.mark.parametrize("service", CRONS, ids=CRON_NAMES)
    def test_it_flushes_on_the_way_out(self, service):
        """A cron can exit before the SDK's background worker has sent
        anything, and the event most worth having is the one from the
        run that just died."""
        source = _script_for(service).read_text(encoding="utf-8")
        tail = source[source.index('if __name__ == "__main__":'):]
        assert "finally:" in tail, service["name"]
        assert "flush_sentry()" in tail, service["name"]
        # In the finally, so the failure path flushes too.
        assert tail.index("finally:") < tail.index("flush_sentry()")

    def test_the_flush_is_bounded(self, sentry, monkeypatch):
        """A job must not hang waiting on error reporting."""
        sentry("fc-refund-reconciler")
        seen = {}

        def fake_flush(timeout=None, callback=None):
            seen["timeout"] = timeout

        monkeypatch.setattr(sentry_sdk, "flush", fake_flush)
        flush_sentry()
        assert seen["timeout"] == FLUSH_TIMEOUT_SECONDS
        assert 0 < FLUSH_TIMEOUT_SECONDS <= 10

    def test_a_failing_flush_cannot_fail_the_job(self, sentry, monkeypatch):
        """Sentry being unreachable must not turn a successful
        reconciliation into a failed cron."""
        sentry("fc-refund-reconciler")

        def exploding_flush(*args, **kwargs):
            raise OSError("network unreachable")

        monkeypatch.setattr(sentry_sdk, "flush", exploding_flush)
        assert flush_sentry() is None


# ---------------------------------------------------------------------------
# D. A routine run says nothing at all
# ---------------------------------------------------------------------------


class TestRoutineRunsAreSilent:
    def test_a_clean_transfer_sweep_reports_nothing(self, sentry):
        transport = sentry("fc-connect-transfer-sweeper")
        report = _transfer_report(considered=4, sent=4, fee_resolved=1)
        assert TRANSFER_SWEEPER.report_partial_failures(report) is None
        assert transport.events == []

    def test_an_empty_transfer_sweep_reports_nothing(self, sentry):
        """due=0. The common case, every fifteen minutes, forever."""
        transport = sentry("fc-connect-transfer-sweeper")
        assert TRANSFER_SWEEPER.report_partial_failures(
            _transfer_report()
        ) is None
        assert transport.events == []

    def test_skipped_and_cooling_rows_are_not_failures(self, sentry):
        """Expected states: a row another worker finished, a row inside
        its backoff. Reporting these would make the issue list useless
        within a day."""
        transport = sentry("fc-connect-recovery-sweeper")
        report = _recovery_report(
            skipped=6, cooling_off=3, outstanding_cents=12_000,
        )
        assert RECOVERY_SWEEPER.report_partial_failures(report) is None
        assert transport.events == []

    def test_a_fully_reconciled_refund_pass_reports_nothing(self, sentry):
        transport = sentry("fc-refund-reconciler")
        summary = _refund_summary(
            in_flight_reconciled=2, accepted_reconciled=1,
        )
        assert REFUND_RECONCILER.report_partial_failures(summary) is None
        assert transport.events == []

    def test_an_empty_refund_pass_reports_nothing(self, sentry):
        transport = sentry("fc-refund-reconciler")
        assert REFUND_RECONCILER.report_partial_failures(
            _refund_summary()
        ) is None
        assert transport.events == []

    @pytest.mark.parametrize("level", ["debug", "info", "warning"])
    def test_routine_job_logging_is_not_an_event(self, sentry, level):
        """The sweeps log a summary line on every run. Promoting those
        would be indistinguishable from an outage."""
        transport = sentry("fc-connect-transfer-sweeper")
        logger = logging.getLogger("test_cron_routine")
        getattr(logger, level)("sweep complete: %s", {"sent": 0})
        assert transport.events == []

    def test_a_summary_is_never_informational(self):
        """``info`` is not an available level, structurally. A run with
        nothing to act on must send nothing at all, and the way to keep
        that true is to make the alternative unavailable."""
        assert "info" not in JOB_SUMMARY_LEVELS
        assert set(JOB_SUMMARY_LEVELS) == {"warning", "error"}

    def test_an_unknown_level_does_not_become_informational(self, sentry):
        transport = sentry("fc-refund-reconciler")
        capture_job_summary("typo", level="informational", failed=1)
        assert transport.events[-1]["level"] == "warning"


# ---------------------------------------------------------------------------
# E. The partial failures that exit 0 — the reason Phase 2 exists
# ---------------------------------------------------------------------------


class TestTransferSweeperPartialFailures:
    def test_rows_needing_attention_produce_one_warning(self, sentry):
        transport = sentry("fc-connect-transfer-sweeper")
        report = _transfer_report(
            considered=5, sent=2, still_pending=3,
            needs_attention=FAKE_TXN_IDS[:3],
        )
        event_id = TRANSFER_SWEEPER.report_partial_failures(report)

        assert event_id is not None
        assert len(transport.events) == 1
        event = transport.events[0]
        assert event["level"] == "warning"
        assert event["tags"]["component"] == "fc-connect-transfer-sweeper"
        assert event["extra"]["needs_attention"] == 3
        assert event["extra"]["sent"] == 2
        _assert_clean(event)

    def test_a_terminal_failure_is_an_error_not_a_warning(self, sentry):
        """``failed`` means the transfer will not be retried. A creator
        is owed money that nothing will move on its own."""
        transport = sentry("fc-connect-transfer-sweeper")
        report = _transfer_report(considered=2, failed=1, sent=1)
        TRANSFER_SWEEPER.report_partial_failures(report)

        event = transport.events[-1]
        assert event["level"] == "error"
        assert event["extra"]["failed"] == 1

    def test_one_event_per_run_not_one_per_transaction(self, sentry):
        """Twenty-five owed transfers are one condition, not twenty-five
        issues. Sentry groups on the message, so a condition that
        persists becomes one issue with a rising count."""
        transport = sentry("fc-connect-transfer-sweeper")
        report = _transfer_report(
            considered=25, needs_attention=list(FAKE_TXN_IDS),
        )
        TRANSFER_SWEEPER.report_partial_failures(report)

        assert len(transport.events) == 1
        assert transport.events[0]["extra"]["needs_attention"] == 25
        _assert_clean(transport.events[0])

    def test_the_payment_ids_do_not_travel(self, sentry):
        """They are in the Render log, where acting on them means
        opening those transactions anyway. What Sentry needs is the
        count that makes someone go and look."""
        transport = sentry("fc-connect-transfer-sweeper")
        report = _transfer_report(needs_attention=FAKE_TXN_IDS[:2], failed=1)
        TRANSFER_SWEEPER.report_partial_failures(report)
        _assert_clean(transport.events[-1])

    def test_a_dispute_hold_alone_is_not_reported(self, sentry):
        """Held while the charge is contested is a correct state, not a
        failure."""
        transport = sentry("fc-connect-transfer-sweeper")
        report = _transfer_report(considered=1, held_by_dispute=1)
        assert TRANSFER_SWEEPER.report_partial_failures(report) is None
        assert transport.events == []


class TestRecoverySweeperPartialFailures:
    def test_rows_still_owed_produce_one_warning(self, sentry):
        transport = sentry("fc-connect-recovery-sweeper")
        report = _recovery_report(
            attempted=2, still_retryable=2, outstanding_cents=9_000,
            needs_attention=FAKE_TXN_IDS[:2],
        )
        event_id = RECOVERY_SWEEPER.report_partial_failures(report)

        assert event_id is not None
        assert len(transport.events) == 1
        event = transport.events[0]
        assert event["level"] == "warning"
        assert event["tags"]["component"] == "fc-connect-recovery-sweeper"
        assert event["extra"]["needs_attention"] == 2
        assert event["extra"]["outstanding_cents"] == 9_000
        _assert_clean(event)

    def test_an_aggregate_amount_is_allowed_where_a_row_is_not(self, sentry):
        """How much is still owed tells you whether to care. Which rows
        they are tells you nothing you can act on from Sentry."""
        transport = sentry("fc-connect-recovery-sweeper")
        report = _recovery_report(
            needs_attention=FAKE_TXN_IDS[:1], outstanding_cents=450_00,
        )
        RECOVERY_SWEEPER.report_partial_failures(report)
        event = transport.events[-1]
        assert event["extra"]["outstanding_cents"] == 450_00
        _assert_clean(event)


class TestRefundReconcilerPartialFailures:
    def test_transient_operations_produce_one_warning(self, sentry):
        transport = sentry("fc-refund-reconciler")
        summary = _refund_summary(
            in_flight_transient=1, accepted_transient=2,
            accepted_reconciled=4,
        )
        event_id = REFUND_RECONCILER.report_partial_failures(summary)

        assert event_id is not None
        assert len(transport.events) == 1
        event = transport.events[0]
        assert event["level"] == "warning"
        assert event["tags"]["component"] == "fc-refund-reconciler"
        assert event["extra"]["in_flight_transient"] == 1
        assert event["extra"]["accepted_transient"] == 2
        assert event["extra"]["accepted_reconciled"] == 4
        _assert_clean(event)

    @pytest.mark.parametrize(
        "field", ["in_flight_transient", "accepted_transient"],
    )
    def test_either_kind_of_transient_is_enough(self, sentry, field):
        transport = sentry("fc-refund-reconciler")
        REFUND_RECONCILER.report_partial_failures(_refund_summary(**{field: 1}))
        assert len(transport.events) == 1


class TestTheSummaryHelperCannotLeak:
    def test_only_counts_survive(self, sentry):
        """The structural guarantee. A caller who passes the ids
        themselves — the obvious mistake, and the one the Connect
        sweepers were one line away from making — gets a dropped
        field, not an event full of payment ids."""
        transport = sentry("fc-connect-transfer-sweeper")
        capture_job_summary(
            "deliberate misuse",
            needs_attention=list(FAKE_TXN_IDS),
            failed=2,
        )
        event = transport.events[-1]
        assert event["extra"]["failed"] == 2
        assert event["extra"]["needs_attention"] == DROPPED_NOT_A_COUNT
        _assert_clean(event)

    @pytest.mark.parametrize(
        "value",
        [
            FAKE_EMAIL,
            FAKE_TOKEN,
            FAKE_BEARER,
            FAKE_SIG,
            {"customer": FAKE_EMAIL, "amount": 1000},
            ["ch_FAKE123", FAKE_TOKEN],
            3.5,
            None,
        ],
    )
    def test_anything_that_is_not_a_count_is_dropped(self, sentry, value):
        transport = sentry("fc-refund-reconciler")
        capture_job_summary("deliberate misuse", detail=value)
        event = transport.events[-1]
        assert event["extra"]["detail"] == DROPPED_NOT_A_COUNT
        _assert_clean(event)

    def test_a_sensitive_field_name_is_still_redacted(self, sentry):
        """Belt and braces: the Phase 1 scrubber runs on these events
        too, so even a count under a credential-shaped name is
        redacted rather than shown."""
        transport = sentry("fc-refund-reconciler")
        capture_job_summary("naming mistake", reset_token=4)
        assert transport.events[-1]["extra"]["reset_token"] == REDACTED

    def test_the_message_itself_is_scrubbed(self, sentry):
        transport = sentry("fc-refund-reconciler")
        capture_job_summary(
            f"left {FAKE_EMAIL} waiting with token={FAKE_TOKEN}", failed=1,
        )
        _assert_clean(transport.events[-1])

    def test_a_summary_does_not_leak_into_later_events(self, sentry):
        """Each summary builds its own scope. Otherwise one run's counts
        would ride along on the next unrelated exception."""
        transport = sentry("fc-connect-transfer-sweeper")
        capture_job_summary("first", failed=1)
        logging.getLogger("test_cron_isolation").error("something else")

        assert len(transport.events) == 2
        assert "failed" not in (transport.events[1].get("extra") or {})

    def test_the_component_tag_is_on_every_summary(self, sentry):
        transport = sentry("fc-gathering-reminders")
        capture_job_summary("tagged", failed=1)
        assert transport.events[-1]["tags"]["component"] == "fc-gathering-reminders"


# ---------------------------------------------------------------------------
# F. fc-fip3 — the cron that was reporting as development
# ---------------------------------------------------------------------------


def _production_without_the_job_pair(service: dict) -> list[str]:
    """Which half of the production job contract a service is missing.

    A predicate rather than an inline assertion so it can be pointed at
    a deliberately broken service in the test below. A guard nobody has
    seen fail is not a guard.
    """
    env = _env_of(service)
    if env.get("APP_ENV") != "production":
        return []
    problems = []
    if env.get("FC_SERVICE_ROLE") != "job":
        problems.append(
            "APP_ENV=production without FC_SERVICE_ROLE=job — the web role "
            "then requires the full R2 credential set"
        )
    if "STRIPE_SECRET_KEY" not in env and env.get(
        "FC_JOB_REQUIRES_STRIPE"
    ) != "false":
        problems.append(
            "APP_ENV=production with no Stripe key and no "
            "FC_JOB_REQUIRES_STRIPE=false — boot requires the key"
        )
    return problems


class TestTheProductionJobContract:
    @pytest.mark.parametrize("service", CRONS, ids=CRON_NAMES)
    def test_app_env_never_arrives_alone(self, service):
        """``APP_ENV=production`` on a cron is not a single setting. It
        is one of three, and setting it by itself stops the job
        booting — which is what fc-fip3 was one edit away from."""
        assert _production_without_the_job_pair(service) == []

    def test_the_guard_catches_app_env_added_alone(self):
        """Proving the test above can fail."""
        assert _production_without_the_job_pair({
            "name": "pretend",
            "envVars": [{"key": "APP_ENV", "value": "production"}],
        }) != []

    def test_the_guard_catches_a_missing_stripe_opt_out(self):
        assert _production_without_the_job_pair({
            "name": "pretend",
            "envVars": [
                {"key": "APP_ENV", "value": "production"},
                {"key": "FC_SERVICE_ROLE", "value": "job"},
            ],
        }) != []

    def test_the_guard_accepts_a_job_that_does_use_stripe(self):
        """The refund reconciler and both Connect sweepers genuinely
        call Stripe and carry the key. They must not be asked for the
        opt-out as well."""
        assert _production_without_the_job_pair({
            "name": "pretend",
            "envVars": [
                {"key": "APP_ENV", "value": "production"},
                {"key": "FC_SERVICE_ROLE", "value": "job"},
                {"key": "STRIPE_SECRET_KEY"},
            ],
        }) == []

    def test_app_env_alone_really_does_refuse_to_boot(self, monkeypatch):
        """Not a convention — the actual consequence. ``Settings``
        raises, Render aborts the deploy, and the cron stops running."""
        from app.core.config import Settings

        for key in (
            "FC_SERVICE_ROLE", "FC_JOB_REQUIRES_STRIPE", "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY", "R2_BUCKET_PRIVATE", "R2_BUCKET_PUBLIC",
            "R2_PUBLIC_BASE_URL",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("PUBLIC_APP_URL", "https://freshcollective.au")
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
        monkeypatch.setenv("JWT_SECRET", "x" * 32)

        with pytest.raises(Exception) as caught:
            Settings(_env_file=None)
        assert "R2" in str(caught.value) or "Stripe" in str(caught.value)


class TestFip3:
    @property
    def service(self) -> dict:
        return _by_name("fc-fip3-grace-reconciler")

    def test_it_declares_all_three_settings(self):
        env = _env_of(self.service)
        assert env["APP_ENV"] == "production"
        assert env["FC_SERVICE_ROLE"] == "job"
        assert env["FC_JOB_REQUIRES_STRIPE"] == "false"

    def test_it_is_still_given_nothing_it_does_not_need(self):
        """The reason for ``FC_SERVICE_ROLE=job`` is to make the
        production R2 requirement not apply — not to then satisfy it."""
        env = _env_of(self.service)
        assert not [k for k in env if k.startswith("R2_")], env
        assert "STRIPE_SECRET_KEY" not in env
        assert "STRIPE_WEBHOOK_SECRET" not in env
        assert "RESEND_API_KEY" not in env
        assert "INTERNAL_COMMS_SECRET" not in env

    def test_its_settings_validate_as_a_db_only_production_job(self, monkeypatch):
        from app.core.config import Settings

        for key in (
            "APP_ENV", "FC_SERVICE_ROLE", "FC_JOB_REQUIRES_STRIPE",
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "R2_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_PRIVATE",
            "R2_BUCKET_PUBLIC", "R2_PUBLIC_BASE_URL", "PUBLIC_APP_URL",
            "FRONTEND_ORIGIN", "DATABASE_URL", "JWT_SECRET",
        ):
            monkeypatch.delenv(key, raising=False)
        for key, value in _env_of(self.service).items():
            if value is None:
                value = {
                    "DATABASE_URL": "postgresql://u:p@localhost/db",
                    "JWT_SECRET": "x" * 32,
                }.get(key, "stub")
            monkeypatch.setenv(key, str(value))

        settings = Settings(_env_file=None)
        assert settings.app_env == "production"
        assert settings.fc_service_role == "job"
        assert settings.fc_job_requires_stripe is False
        assert settings.stripe_api_enabled is False
        assert settings.resolved_public_app_url == "https://freshcollective.au"

    def test_it_now_reports_as_production(self, monkeypatch):
        """The whole reason the three settings had to be fixed before
        this cron could report anything: it had no ``APP_ENV``, so its
        issues would have arrived tagged ``development`` while it ran
        against the production database."""
        transport = CapturingTransport()
        previous = sentry_sdk.get_client()
        monkeypatch.setenv("SENTRY_DSN", FAKE_DSN)
        monkeypatch.setenv("RENDER_GIT_COMMIT", RELEASE)
        monkeypatch.setenv("APP_ENV", _env_of(self.service)["APP_ENV"])

        real_init = sentry_sdk.init
        monkeypatch.setattr(
            sentry_sdk, "init",
            lambda **kw: real_init(**{**kw, "transport": transport}),
        )
        try:
            assert init_sentry("fc-fip3-grace-reconciler") is True
            sentry_sdk.capture_message("fip3 shape", level="warning")
            event = transport.events[-1]
            assert event["environment"] == "production"
            assert event["release"] == RELEASE
            assert event["tags"]["component"] == "fc-fip3-grace-reconciler"
        finally:
            sentry_sdk.get_global_scope().clear()
            sentry_sdk.get_isolation_scope().clear()
            sentry_sdk.Scope.get_global_scope().set_client(previous)


# ---------------------------------------------------------------------------
# G. Privacy, through the pipeline a job actually uses
# ---------------------------------------------------------------------------


class TestPrivacyFromAJob:
    def test_a_job_exception_is_scrubbed_like_an_api_one(self, sentry):
        """The scrubber is shared, and this proves the sharing rather
        than assuming it: same fake credentials, same assertions, a
        cron's logger instead of a request."""
        transport = sentry("fc-gathering-reminders")
        logger = logging.getLogger("test_cron_privacy")
        try:
            raise RuntimeError(
                f"reminder failed for {FAKE_EMAIL} using token={FAKE_TOKEN} "
                f"({FAKE_BEARER})"
            )
        except RuntimeError:
            logger.exception("gathering_reminder_sweep: failed")

        event = transport.events[-1]
        _assert_clean(event)
        # And the useful half survived.
        assert "RuntimeError" in _blob(event)
        assert event["tags"]["component"] == "fc-gathering-reminders"
        assert event["environment"] == "production"
        assert event["release"] == RELEASE

    def test_a_stripe_signature_and_payment_payload_do_not_survive(self, sentry):
        transport = sentry("fc-refund-reconciler")
        with sentry_sdk.new_scope() as scope:
            scope.set_extra("stripe-signature", FAKE_SIG)
            scope.set_extra("authorization", FAKE_BEARER)
            scope.set_extra(
                "charge", {"customer_email": FAKE_EMAIL, "id": "ch_FAKE123"},
            )
            scope.set_extra("harmless_detail", "this one should survive")
            sentry_sdk.capture_message("refund reconcile detail", level="error")

        event = transport.events[-1]
        _assert_clean(event)
        assert event["extra"]["harmless_detail"] == "this one should survive"

    @pytest.mark.parametrize(
        "text, survives",
        [
            ("auth failed with Bearer FAKE_JWT_xyz789", False),
            ("Authorization: bearer FAKE_JWT_xyz789", False),
            # Over-reach check: these must come through untouched.
            ("transfer tr_1Nxyz failed for account acct_1Abc", True),
            ("bearer", True),
        ],
    )
    def test_a_bearer_value_in_free_text_is_redacted(self, text, survives):
        """Found by writing the job-side privacy test: a header value
        interpolated into an exception message is not ``key=value``, so
        the inline-secret pattern could not see it. The word announces
        the credential where no key name does.
        """
        from app.core.observability import redact_text

        redacted = redact_text(text)
        if survives:
            assert redacted == text
        else:
            assert "FAKE_JWT_xyz789" not in redacted
            assert REDACTED in redacted

    def test_frame_locals_from_a_job_are_not_attached(self, sentry):
        """A cron's frames hold Stripe objects and member rows."""
        transport = sentry("fc-connect-transfer-sweeper")
        logger = logging.getLogger("test_cron_locals")

        def failing_step():
            secret_local = FAKE_TOKEN   # noqa: F841 — the point of the test
            member_email = FAKE_EMAIL   # noqa: F841
            raise RuntimeError("transfer step failed")

        try:
            failing_step()
        except RuntimeError:
            logger.exception("connect transfer sweep failed")

        _assert_clean(transport.events[-1])

    def test_performance_features_stay_off_for_jobs(self, sentry):
        sentry("fc-creator-grant-expiry")
        options = sentry_sdk.get_client().options
        assert options["traces_sample_rate"] == 0
        assert options["profiles_sample_rate"] == 0
        assert options["send_default_pii"] is False
        assert options["include_local_variables"] is False
        assert options["max_request_body_size"] == "never"


# ---------------------------------------------------------------------------
# H. One signal per condition
# ---------------------------------------------------------------------------


class TestNoDuplicateIssues:
    @pytest.mark.parametrize(
        "path",
        [
            "app/services/connect_transfer_sweeper.py",
            "app/services/connect_recovery_sweeper.py",
            "scripts/fc_connect_transfer_sweeper.py",
            "scripts/fc_connect_recovery_sweeper.py",
        ],
    )
    def test_the_owed_rows_are_logged_below_error(self, path):
        """Both the service and the script log this same condition, and
        both used to log it at ERROR. With the logging integration on,
        that is two Sentry issues for one problem, each listing payment
        ids. The counted summary is the single signal; the ids stay in
        the Render log at WARNING.
        """
        file = BACKEND / path

        def about_the_attention_threshold(message: str) -> bool:
            return "owed" in message and "attempts" in message

        offenders = [
            m for m in _logger_calls(file, "error")
            if about_the_attention_threshold(m)
        ]
        assert offenders == [], offenders
        assert any(
            about_the_attention_threshold(m)
            for m in _logger_calls(file, "warning")
        ), f"{path} no longer reports owed rows at all"

    @pytest.mark.parametrize(
        "path",
        [
            "app/services/connect_transfer_sweeper.py",
            "app/services/connect_recovery_sweeper.py",
            "scripts/fc_connect_transfer_sweeper.py",
            "scripts/fc_connect_recovery_sweeper.py",
        ],
    )
    def test_the_owed_ids_are_logged_on_the_render_only_logger(self, path):
        """The level is not enough on its own. A WARNING on an ordinary
        logger still becomes a breadcrumb, and the ids would then ride
        along on the summary that deliberately counts them instead. So
        the call has to be on the ``.ids`` logger specifically.
        """
        file = BACKEND / path
        owed = [
            call for call in _log_calls(file)
            if "owed" in call.message and "attempts" in call.message
        ]
        assert owed, f"{path} no longer reports owed rows at all"
        for call in owed:
            assert call.receiver == "id_logger", (
                f"{path}: logged on {call.receiver!r}, which is reported"
            )

        declared = _render_only_logger_names(file)
        assert declared, f"{path} declares no id_logger"
        for expression in declared:
            assert RENDER_ONLY_LOGGER_SUFFIX in expression, expression

    def test_the_sweeper_services_send_nothing_themselves(self):
        """The decision about what reaches Sentry belongs at the job
        boundary, where ``init_sentry`` was called. A service that
        reports for itself cannot be reused by anything that wants to
        report differently."""
        for path in (
            "app/services/connect_transfer_sweeper.py",
            "app/services/connect_recovery_sweeper.py",
            "app/services/refund_reconciliation.py",
        ):
            tree = ast.parse((BACKEND / path).read_text(encoding="utf-8"))
            imported = []
            called = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imported.append(node.module or "")
                elif isinstance(node, ast.Import):
                    imported += [a.name for a in node.names]
                elif isinstance(node, ast.Call):
                    func = node.func
                    name = getattr(func, "attr", None) or getattr(
                        func, "id", None,
                    )
                    if name:
                        called.append(name)
            # Parsed, not grepped: these modules now explain in prose
            # why they log the way they do, and the word "Sentry"
            # appears in that explanation.
            assert not [m for m in imported if "sentry" in m], path
            assert not [
                m for m in imported if m.endswith("observability")
            ], path
            assert "capture_job_summary" not in called, path
            assert not [c for c in called if c.startswith("capture_")], path

    def test_the_owed_ids_leave_no_trace_at_all(self, sentry):
        """The channel a test found rather than a reviewer: a WARNING
        becomes a breadcrumb on the *next* event, so the counted
        summary went out clean and the same payment ids arrived
        attached to it. The ``.ids`` logger produces neither.
        """
        transport = sentry("fc-connect-transfer-sweeper")
        ids_logger = logging.getLogger("test_cron_detail.ids")

        ids_logger.warning(
            "still owed after repeated attempts: %s", ", ".join(FAKE_TXN_IDS),
        )
        ids_logger.error("and not even at ERROR: %s", FAKE_TXN_IDS[0])
        capture_job_summary("counted summary", needs_attention=25)

        assert len(transport.events) == 1, "the ids logger raised an issue"
        event = transport.events[0]
        assert event["extra"]["needs_attention"] == 25
        assert event.get("breadcrumbs", {"values": []})["values"] == []
        _assert_clean(event)

    def test_an_ordinary_job_logger_still_leaves_breadcrumbs(self, sentry):
        """The suffix is a narrow exemption, not a blanket one. A
        sweep's ordinary progress logging is useful context on an
        exception and must still be collected."""
        transport = sentry("fc-connect-transfer-sweeper")
        logging.getLogger("test_cron_ordinary").warning("fee resolved from Stripe")
        capture_job_summary("counted summary", failed=1)

        crumbs = transport.events[-1]["breadcrumbs"]["values"]
        assert any("fee resolved" in (c.get("message") or "") for c in crumbs)

    def test_a_reported_partial_failure_is_one_event_not_two(self, sentry):
        """The script logs the ids and reports the counts. Only the
        second of those may become an issue."""
        transport = sentry("fc-connect-transfer-sweeper")
        ids_logger = logging.getLogger("test_cron_one_signal.ids")
        report = _transfer_report(needs_attention=FAKE_TXN_IDS[:2])

        ids_logger.warning(
            "still owed after repeated attempts: %s",
            ", ".join(report.needs_attention),
        )
        TRANSFER_SWEEPER.report_partial_failures(report)

        assert len(transport.events) == 1
        _assert_clean(transport.events[0])


# ---------------------------------------------------------------------------
# SDK 2.71 data_collection
# ---------------------------------------------------------------------------


class TestDataCollection:
    """SDK 2.71 adds a structured ``data_collection`` option that
    supersedes ``send_default_pii``. We deliberately do not set it, and
    these tests are the reason that decision stays safe: they assert the
    *resolved* configuration, so an SDK upgrade that changes the mapping
    fails here instead of quietly starting to collect.
    """

    def test_we_do_not_set_it(self):
        """Setting it wins over ``send_default_pii`` outright, and every
        field omitted from the dict defaults to the permissive value —
        ``user_info``, ``stack_frame_variables`` and
        ``database_query_data`` all become ``True``. A partial dict
        written to mean "collect less" collects more."""
        tree = ast.parse(
            (BACKEND / "app/core/observability.py").read_text(encoding="utf-8")
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                names = [kw.arg for kw in node.keywords]
                assert "data_collection" not in names, (
                    "data_collection would override send_default_pii; see the "
                    "module docstring"
                )

    def test_our_options_resolve_to_the_restrictive_configuration(self, sentry):
        """What ``send_default_pii=False`` plus
        ``include_local_variables=False`` actually mean once the SDK has
        resolved them. Field by field, because the whole argument for
        not adopting the new option is that this mapping is already
        correct."""
        sentry("fc-refund-reconciler")
        resolved = sentry_sdk.get_client().options["data_collection"]

        assert resolved["provided_by_user"] is False
        assert resolved["user_info"] is False
        assert resolved["stack_frame_variables"] is False
        assert resolved["database_query_data"] is False
        assert resolved["queues"] is False
        assert resolved["graphql"] == {"document": False, "variables": False}
        assert resolved["gen_ai"] == {"inputs": False, "outputs": False}
        # Headers and query params are collected with the sensitive
        # denylist applied; our own scrubber then redacts the five
        # names that matter to this platform.
        assert resolved["cookies"]["mode"] == "denylist"
        assert resolved["http_headers"]["request"]["mode"] == "denylist"
        assert resolved["url_query_params"]["mode"] == "denylist"

    def test_bodies_are_still_refused_by_the_options_we_do_set(self, sentry):
        """``http_bodies`` lists every body type in both PII modes —
        it is ``max_request_body_size`` that refuses them, and the
        scrubber that removes the key regardless."""
        sentry("fc-refund-reconciler")
        options = sentry_sdk.get_client().options
        assert options["max_request_body_size"] == "never"

    def test_our_init_emits_no_deprecation_warning(self, sentry):
        """Setting both options at once deprecates ``send_default_pii``.
        A warning here would mean we had started doing that."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            sentry("fc-refund-reconciler")
        relevant = [
            w for w in caught
            if issubclass(w.category, DeprecationWarning)
            and "send_default_pii" in str(w.message)
        ]
        assert relevant == [], [str(w.message) for w in relevant]
