"""The aggregate verifier: what it finds, and where it says it.

Two defects are pinned here, both found in production.

**A metric added after the last rebuild was reported as a mismatch.**
The four Creators journey metrics had no stored rows because they did
not exist when the rebuild ran, and the script called each absence a
mismatch — 125 of them. "Nobody has built this yet" and "the stored
figure is wrong" need different answers, and only the second is a
defect.

**Findings went out as Sentry incidents.** Every line went through
``logger.error``, which the Sentry logging integration turns into an
event, so one verification run put roughly sixty issues into the
production queue. A diagnostic that reports problems is expected to
report problems; its findings belong on stdout, and the error channel
belongs to the script falling over.
"""
from __future__ import annotations

import ast
import logging
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest

import app.models.community_care  # noqa: F401
from app.models.platform import SpaceMembership, SpaceMembershipStatus, SpaceRole
from app.models.reporting_aggregate import MetricDaily
from app.reporting import aggregates
from app.reporting.registry import REGISTRY

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "reporting" / "verify_aggregates.py"
)


def _load_script():
    """Import the script as a module, without running ``main``.

    Registered in ``sys.modules`` before execution: ``@dataclass``
    resolves annotations through ``sys.modules[cls.__module__]``, and
    a module that is not there yet fails with an unhelpful
    ``NoneType`` error.
    """
    import importlib.util
    import sys as _sys

    if "verify_aggregates" in _sys.modules:
        return _sys.modules["verify_aggregates"]
    spec = importlib.util.spec_from_file_location("verify_aggregates", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    _sys.modules["verify_aggregates"] = module
    spec.loader.exec_module(module)
    return module


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _join(db, user, space):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        joined_at=datetime(2026, 1, 1),
    ))
    db.flush()


DAY = date(2026, 10, 20)


@pytest.fixture
def verifier():
    return _load_script()


class TestItTellsTheThreeOutcomesApart:
    def _build(self, db, make_space, make_user):
        space = make_space(name="A")
        _join(db, make_user(), space)
        aggregates.rebuild_day(db, DAY, space_ids=[space.id])
        db.flush()
        db.expire_all()
        return space

    def test_matching_data_is_clean(self, db, verifier, make_space, make_user):
        space = self._build(db, make_space, make_user)
        found = verifier.verify(db, [DAY], [(space.id, "A")])
        assert found.checked > 0
        assert found.mismatches == []
        assert found.gaps == []
        assert not found.failed

    def test_a_wrong_stored_figure_is_a_mismatch_and_fails(
        self, db, verifier, make_space, make_user,
    ):
        space = self._build(db, make_space, make_user)
        row = db.query(MetricDaily).filter(
            MetricDaily.metric_key == "unique_members",
            MetricDaily.reporting_date == DAY,
            MetricDaily.dimension == aggregates.space_dimension(space.id),
        ).one()
        row.value = row.value + 99
        db.flush()

        found = verifier.verify(db, [DAY], [(space.id, "A")])
        assert len(found.mismatches) == 1
        assert "unique_members" in found.mismatches[0]
        assert found.failed

    def test_a_metric_never_built_is_not_a_mismatch(
        self, db, verifier, make_space, make_user,
    ):
        """The 125. They had no rows because they did not exist yet."""
        space = self._build(db, make_space, make_user)
        # Remove every row for one metric, so it looks newly added.
        db.query(MetricDaily).filter(
            MetricDaily.metric_key == "memberships_started"
        ).delete()
        db.flush()

        found = verifier.verify(db, [DAY], [(space.id, "A")])
        assert found.mismatches == [], "a new metric is not a wrong figure"
        assert found.gaps == [], "nor a gap — it has no rows anywhere"
        assert found.never_built["memberships_started"] > 0
        assert not found.failed, "a never-built metric must not fail the run"

    def test_a_hole_in_a_built_metric_is_a_gap_and_fails(
        self, db, verifier, make_space, make_user,
    ):
        """Rows on other dates but not this one — something was skipped."""
        space = self._build(db, make_space, make_user)
        other = date(2026, 10, 19)
        aggregates.rebuild_day(db, other, space_ids=[space.id])
        db.flush()
        db.query(MetricDaily).filter(
            MetricDaily.metric_key == "memberships_started",
            MetricDaily.reporting_date == DAY,
        ).delete()
        db.flush()
        db.expire_all()

        found = verifier.verify(db, [DAY], [(space.id, "A")])
        assert found.never_built == {}, "it has rows on another date"
        assert any("memberships_started" in g for g in found.gaps)
        assert found.failed

    def test_observation_only_metrics_are_skipped_not_checked(
        self, db, verifier, make_space, make_user,
    ):
        space = self._build(db, make_space, make_user)
        found = verifier.verify(db, [DAY], [(space.id, "A")])
        assert found.skipped_observation > 0
        observation_keys = [
            m.key for m in aggregates.storable_metrics() if m.observation_only
        ]
        assert observation_keys, "the fixture assumes some exist"
        for key in observation_keys:
            assert not any(key in m for m in found.mismatches), (
                f"{key} is observation-only — recomputing it would mean "
                "overwriting the only record that the day was seen"
            )


class TestFindingsAreOutputNotIncidents:
    def test_the_report_is_printed_rather_than_logged(self, verifier, capsys):
        found = verifier.Findings(
            checked=3,
            mismatches=["2026-10-20  platform  unique_members: stored 1, source records give 2"],
        )
        verifier.report(found, [DAY], 1)
        printed = capsys.readouterr().out
        assert "MISMATCHED" in printed
        assert "unique_members" in printed
        assert "RESULT: FAILED" in printed

    def test_no_finding_is_logged_at_error(self, verifier, caplog):
        """ERROR becomes a Sentry event. A finding is not an incident."""
        found = verifier.Findings(
            checked=1,
            mismatches=["a mismatch"],
            gaps=["a gap"],
            never_built={"some_metric": 4},
        )
        with caplog.at_level(logging.DEBUG, logger="reporting.verify"):
            verifier.report(found, [DAY], 1)
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors == [], (
            "findings must not reach the error channel — that is what put "
            "sixty issues in the production queue"
        )

    def test_the_script_never_calls_logger_error_for_a_finding(self):
        """Read as source, so a future edit cannot reintroduce it.

        Parsed rather than grepped: the module docstring explains the
        defect and names ``logger.error``, and a substring scan would
        read the explanation as the offence.
        """
        tree = ast.parse(SCRIPT.read_text())
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "error"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ]
        assert calls == [], (
            "logger.error becomes a Sentry event; findings belong on stdout"
        )

    def test_a_fatal_failure_still_reaches_the_error_channel(self):
        """The one thing here that genuinely is an incident."""
        tree = ast.parse(SCRIPT.read_text())
        exceptions = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "exception"
        ]
        assert exceptions, (
            "an unexpected failure must still be reported — only expected "
            "findings were moved off the error channel"
        )

    def test_the_summary_counts_every_category(self, verifier, capsys):
        found = verifier.Findings(
            checked=10, skipped_observation=4,
            mismatches=["m"], gaps=["g"], never_built={"k": 2},
        )
        verifier.report(found, [DAY], 2)
        printed = capsys.readouterr().out
        for label in (
            "checked against source records", "mismatched",
            "missing (gap in a built metric)", "not yet built",
            "skipped, observation-only",
        ):
            assert label in printed, f"{label} missing from the summary"

    def test_a_clean_run_says_so_plainly(self, verifier, capsys):
        verifier.report(verifier.Findings(checked=5), [DAY], 1)
        printed = capsys.readouterr().out
        assert "RESULT: OK" in printed
        assert "FAILED" not in printed

    def test_a_never_built_metric_is_reported_with_the_fix(
        self, verifier, capsys,
    ):
        verifier.report(
            verifier.Findings(checked=1, never_built={"creators_earning": 5}),
            [DAY], 1,
        )
        printed = capsys.readouterr().out
        assert "NOT YET BUILT" in printed
        assert "creators_earning" in printed
        assert "rebuild_daily.py" in printed
        assert "RESULT: OK" in printed, "not a defect, so not a failure"


class TestTheCreatorJourneyIsPlatformLevel:
    """Why the 125 was 125.

    Three of the four stages declared a ``space_id`` dimension, so the
    loader would have written twenty-one per-Collective rows a day
    beside the four that mean something — and per Collective the figure
    degenerates to a boolean. Platform-level now, which is both the
    honest shape and a twentieth of the rows.
    """

    STAGES = (
        "creators_registered",
        "creators_with_a_collective",
        "creators_with_a_member",
        "creators_earning",
    )

    def test_no_stage_is_broken_down_by_collective(self):
        for key in self.STAGES:
            assert "space_id" not in REGISTRY.get(key).dimensions, key

    def test_they_are_still_stored_daily(self):
        storable = {m.key for m in aggregates.storable_metrics()}
        for key in self.STAGES:
            assert key in storable, f"{key} should be stored, not recomputed"

    def test_a_days_rebuild_writes_one_row_per_stage(
        self, db, make_space, make_user,
    ):
        space = make_space(name="A")
        _join(db, make_user(), space)
        aggregates.rebuild_day(db, DAY, space_ids=[space.id])
        db.flush()
        db.expire_all()
        for key in self.STAGES:
            rows = db.query(MetricDaily).filter(
                MetricDaily.metric_key == key,
                MetricDaily.reporting_date == DAY,
            ).all()
            assert len(rows) == 1, f"{key} wrote {len(rows)} rows"
            assert rows[0].dimension == aggregates.PLATFORM_DIMENSION
