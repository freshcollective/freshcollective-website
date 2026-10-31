"""Observed figures, and the honest absence of ones nobody recorded.

Two kinds of snapshot
---------------------
``unique_members`` is **reconstructable**. Membership rows carry
``joined_at`` and ``removed_at``, so last March's figure can be worked
out today, and a rebuild of March is a recalculation.

A Collective count is **observable only**. ``spaces.status`` holds one
value with no history behind it, there is no ``archived_at``, and a
creation date is not a publication date. The only honest figure for a
past day is one that was written down at the time — so asked about a day
it cannot have seen, the metric says it cannot answer, and the daily
series carries a gap a chart can draw as a gap.

That distinction drives two behaviours these tests pin down:

* a past day with no recorded observation returns **unavailable**, never
  today's count wearing an old date;
* a day that *was* observed is written **once**, so a later rebuild
  cannot replace a true observation with the current count.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.periods import completed_reporting_date, reporting_date_bounds
from app.reporting import aggregates
from app.reporting.classification import ALL_CLASSES, SUPPORTED_CLASSES, TEST
from app.reporting.registry import REGISTRY, Grain, Window
from app.reporting.scope import platform_scope

COLLECTIVE_COUNTS = (
    "total_collectives",
    "active_collectives",
    "draft_collectives",
    "archived_collectives",
)


def _day_window(day: date) -> Window:
    starts_at, ends_at = reporting_date_bounds(day)
    return Window(starts_at, ends_at, day.isoformat())


def val(db, key, window=None):
    return REGISTRY.get(key).evaluate(db, platform_scope(), window or Window())


@pytest.fixture
def today() -> date:
    return completed_reporting_date(datetime.utcnow())


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------

class TestTheRegistrySaysWhichKindItIs:
    @pytest.mark.parametrize("key", COLLECTIVE_COUNTS)
    def test_a_collective_count_declares_itself_observation_only(self, key):
        m = REGISTRY.get(key)
        assert m.observation_only is True
        assert m.grain is Grain.snapshot

    @pytest.mark.parametrize(
        "key", ("unique_members", "total_memberships", "registered_users"),
    )
    def test_a_reconstructable_snapshot_does_not(self, key):
        assert REGISTRY.get(key).observation_only is False

    @pytest.mark.parametrize("key", COLLECTIVE_COUNTS)
    def test_the_limitation_is_stated_rather_than_left_to_be_discovered(self, key):
        m = REGISTRY.get(key)
        assert m.limitations, f"{key} must say what it cannot tell you"
        assert "observ" in m.limitations.lower()

    def test_no_money_metric_is_observation_only(self):
        """Money is always reconstructable — it has dates. If a financial
        metric ever claims otherwise it is hiding a missing timestamp
        rather than an unknowable fact."""
        for m in REGISTRY.all():
            if m.key.endswith("_cents"):
                assert not m.observation_only, m.key


# ---------------------------------------------------------------------------
# Asked about a day it cannot have seen
# ---------------------------------------------------------------------------

class TestAnUnobservedDayIsNotInvented:
    @pytest.mark.parametrize("key", COLLECTIVE_COUNTS)
    def test_a_long_past_day_is_unavailable_not_todays_count(
        self, db, make_space, key, today,
    ):
        make_space()
        m = val(db, key, _day_window(today - timedelta(days=90)))
        assert m.value is None, "today's count must not wear an old date"
        assert m.unavailable_reason
        assert "reconstruct" in m.unavailable_reason

    @pytest.mark.parametrize("key", COLLECTIVE_COUNTS)
    def test_the_live_figure_still_answers(self, db, make_space, key):
        make_space()
        m = val(db, key)
        assert m.value is not None
        assert m.qualifiers["provenance"] == "observed"
        assert m.qualifiers["as_at"] == "now"

    def test_the_last_completed_day_is_a_genuine_observation(
        self, db, make_space, today,
    ):
        make_space()
        m = val(db, "total_collectives", _day_window(today))
        assert m.value is not None
        assert m.qualifiers["provenance"] == "observed"

    def test_a_missed_night_can_still_be_recorded_but_says_it_was_late(
        self, db, make_space, today,
    ):
        """The lookback exists so a failed night repairs itself. One day
        late is the only observation that will ever exist for that day,
        which beats a gap — but it is labelled, not passed off as
        taken on time."""
        make_space()
        m = val(db, "total_collectives", _day_window(today - timedelta(days=1)))
        assert m.value is not None
        assert m.qualifiers["provenance"] == "observed_late"

    def test_a_day_that_has_not_finished_has_no_end_of_day_count(
        self, db, make_space, today,
    ):
        make_space()
        m = val(db, "total_collectives", _day_window(today + timedelta(days=2)))
        assert m.value is None
        assert "has not finished" in m.unavailable_reason

    def test_the_grace_boundary_is_where_the_registry_says_it_is(
        self, db, make_space, today,
    ):
        from app.reporting.metrics import OBSERVATION_GRACE_DAYS

        make_space()
        # The grace covers the nightly lookback, so a failed night can
        # still be recorded. One day past it there is nothing to observe.
        assert OBSERVATION_GRACE_DAYS >= aggregates.DEFAULT_LOOKBACK_DAYS, (
            "the grace must cover the lookback, or the nightly job would "
            "skip days it was built to record"
        )
        edge = today - timedelta(days=OBSERVATION_GRACE_DAYS)
        beyond = today - timedelta(days=OBSERVATION_GRACE_DAYS + 1)
        assert val(db, "total_collectives", _day_window(edge)).value is not None
        assert val(db, "total_collectives", _day_window(beyond)).value is None


# ---------------------------------------------------------------------------
# Storage: a gap stays a gap, an observation stays put
# ---------------------------------------------------------------------------

class TestTheStoredSeriesIsHonest:
    def test_an_unobservable_day_writes_no_row(self, db, make_space, today):
        make_space()
        old = today - timedelta(days=120)
        result = aggregates.rebuild_day(db, old)
        db.commit()
        db.expire_all()

        for key in COLLECTIVE_COUNTS:
            assert any(s.startswith(key) for s in result.skipped), (
                f"{key} should be recorded as skipped for {old}"
            )
            assert aggregates.series(db, key, old, old) == [], (
                f"{key} must leave a gap rather than a fabricated value"
            )

    def test_an_unobservable_day_does_not_stop_the_rest_of_the_day(
        self, db, make_space, today,
    ):
        """A day of financial history is still worth rebuilding when the
        Collective counts cannot be part of it."""
        make_space()
        old = today - timedelta(days=120)
        result = aggregates.rebuild_day(db, old)
        assert result.rows_written > 0
        db.commit()
        db.expire_all()
        assert aggregates.series(
            db, "gross_collective_sales_cents", old, old,
        ) != []

    def test_an_observation_is_not_overwritten_by_a_later_rebuild(
        self, db, make_space, today,
    ):
        """The heart of it. Two Collectives existed when the day was
        observed; a third arrives afterwards. Rebuilding that day must
        not retrospectively claim there were three."""
        # Relative to whatever the migration-seeded table already holds,
        # rather than assuming an empty one.
        make_space()
        make_space()
        observed = val(db, "total_collectives").value
        aggregates.rebuild_day(db, today)
        db.commit()
        db.expire_all()
        first = aggregates.series(db, "total_collectives", today, today)
        assert [p["value"] for p in first] == [observed]

        make_space()
        assert val(db, "total_collectives").value == observed + 1
        result = aggregates.rebuild_day(db, today)
        db.commit()
        db.expire_all()

        again = aggregates.series(db, "total_collectives", today, today)
        assert [p["value"] for p in again] == [observed], (
            "a rebuild replaced a genuine observation with the current count"
        )
        assert any(s.startswith("total_collectives") for s in result.preserved)

    def test_a_reconstructable_snapshot_is_still_recalculated(
        self, db, make_space, make_user, today,
    ):
        """Write-once applies to observations only. A membership count
        for a past day genuinely improves when a correction lands, so it
        must keep overwriting."""
        space = make_space()
        aggregates.rebuild_day(db, today, space_ids=[space.id])
        db.commit()
        db.expire_all()
        before = aggregates.series(db, "total_memberships", today, today)

        from app.models.platform import (
            SpaceMembership,
            SpaceMembershipStatus,
            SpaceRole,
        )

        starts_at, _ = reporting_date_bounds(today)
        db.add(SpaceMembership(
            id=f"sm_{uuid.uuid4().hex[:12]}",
            user_id=make_user().id,
            space_id=space.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            joined_at=starts_at,
        ))
        db.flush()

        aggregates.rebuild_day(db, today, space_ids=[space.id])
        db.commit()
        db.expire_all()
        after = aggregates.series(db, "total_memberships", today, today)
        assert after[0]["value"] > (before[0]["value"] if before else -1)

    def test_the_run_reports_preserved_rows_separately_from_written_ones(
        self, db, make_space, today,
    ):
        """A preserved observation is neither a write nor a failure, and a
        run that counted it as a write would overstate what it did."""
        make_space()
        aggregates.rebuild_day(db, today)
        db.commit()
        second = aggregates.rebuild_day(db, today)
        assert second.preserved, "nothing reported as preserved"
        written_keys = {s.split(":")[0] for s in second.skipped}
        assert not (set(COLLECTIVE_COUNTS) & written_keys), (
            "a preserved observation must not be reported as skipped"
        )

    def test_a_stored_observation_records_how_it_was_obtained(
        self, db, make_space, today,
    ):
        make_space()
        aggregates.rebuild_day(db, today)
        db.commit()
        db.expire_all()
        points = aggregates.series(db, "total_collectives", today, today)
        assert points[0]["provenance"] in ("observed", "observed_late")


# ---------------------------------------------------------------------------
# The classification vocabulary
# ---------------------------------------------------------------------------

class TestTheTestClassification:
    def test_test_is_a_supported_value(self):
        assert TEST in SUPPORTED_CLASSES
        assert TEST in ALL_CLASSES

    def test_the_four_classes_are_distinct_and_complete(self):
        assert SUPPORTED_CLASSES == (
            "production", "internal_operations", "demonstration", "test",
        )
        assert len(set(SUPPORTED_CLASSES)) == 4

    @pytest.mark.parametrize("table", ("spaces", "users"))
    @pytest.mark.parametrize("value", SUPPORTED_CLASSES)
    def test_the_database_accepts_every_declared_class(
        self, db, make_space, make_user, table, value,
    ):
        """The vocabulary and the CHECK constraint must agree. A class the
        code offers and the database rejects is a runtime failure waiting
        for whoever assigns it."""
        row = make_space() if table == "spaces" else make_user()
        db.execute(
            text(f"UPDATE {table} SET reporting_class = :v WHERE id = :id"),
            {"v": value, "id": row.id},
        )
        db.flush()

    @pytest.mark.parametrize("table", ("spaces", "users"))
    def test_an_invented_class_is_still_refused(
        self, db, make_space, make_user, table,
    ):
        from sqlalchemy.exc import IntegrityError

        row = make_space() if table == "spaces" else make_user()
        with pytest.raises(IntegrityError):
            db.execute(
                text(f"UPDATE {table} SET reporting_class = :v WHERE id = :id"),
                {"v": "whatever", "id": row.id},
            )
            db.flush()

    def test_a_class_changes_how_money_reads_and_never_whether_it_counts(
        self, db, make_space, make_user,
    ):
        """The rule the whole framework rests on. A test Collective's
        live charge is a real financial movement."""
        from app.models.payment import (
            ConnectTransferStatus,
            PaymentTransaction,
            PaymentTransactionStatus,
            PaymentTransactionType,
            PayoutModel,
            PayoutStatus,
        )

        creator = make_user(role="creator")
        space = make_space(creator=creator, reporting_class=TEST)
        db.add(PaymentTransaction(
            id=f"txn_{uuid.uuid4().hex[:12]}",
            transaction_type=(
                PaymentTransactionType.member_payment_option_purchase
            ),
            status=PaymentTransactionStatus.succeeded,
            payer_user_id=make_user().id,
            creator_user_id=creator.id,
            space_id=space.id,
            currency="AUD",
            gross_amount_cents=10000,
            platform_fee_basis_points=1000,
            platform_fee_cents=1000,
            net_creator_amount_cents=9000,
            payout_status=PayoutStatus.pending,
            payout_model=PayoutModel.manual,
            connect_transfer_status=ConnectTransferStatus.not_applicable,
            stripe_mode="test",
            settled_at=datetime.utcnow() - timedelta(days=1),
        ))
        db.flush()

        assert val(db, "gross_collective_sales_cents").value == 10000
        owed = val(db, "outstanding_payouts_cents")
        assert owed.value == 9000
        assert owed.qualifiers["by_reporting_class_cents"][TEST] == 9000


class TestALiveWindowIsAnswerable:
    """"This month" ends now, and "how many right now" has an answer.

    The defect: ``_observation_quality`` compared the window's closing
    instant against the last *completed* reporting day, so a window
    ending at this moment looked like a day that had not finished and
    was refused. Every Collective-status card therefore read "Not yet"
    under ``this_month`` and ``this_fy`` — the two periods a reader
    actually looks at — while the figure was sitting there to be
    counted.

    The guard it must not break is the one next door: a *past* day's
    Collective status still cannot be reconstructed, and the nightly
    job asking for today must still decline.
    """

    STATUS_KEYS = (
        "total_collectives", "active_collectives",
        "draft_collectives", "archived_collectives",
    )

    def _window(self, period):
        from app.core.periods import resolve_period
        current, _ = resolve_period(period)
        return Window(current.starts_at, current.ends_at, current.label)

    @pytest.mark.parametrize("period", ["this_month", "this_fy", "all_time"])
    def test_a_period_ending_now_gets_the_live_count(
        self, db, make_space, period,
    ):
        make_space(status="active")
        for key in self.STATUS_KEYS:
            v = REGISTRY.get(key).evaluate(db, platform_scope(), self._window(period))
            assert v.available, f"{key} under {period}: {v.unavailable_reason}"
            assert v.qualifiers["provenance"] == "observed"

    def test_a_closed_past_period_is_still_unavailable(self, db, make_space):
        """Not a regression — the honest answer. Collective status is
        one column with no history, so the end of last month cannot be
        reconstructed and must not be answered with today's count."""
        make_space(status="active")
        v = REGISTRY.get("active_collectives").evaluate(
            db, platform_scope(), self._window("last_month"),
        )
        assert not v.available
        assert "not kept as history" in v.unavailable_reason

    def test_the_nightly_still_declines_a_day_that_has_not_finished(self, db):
        """Its window closes at tomorrow's local midnight, which is in
        the future, so there is nothing to observe yet."""
        from app.core.periods import completed_reporting_date, reporting_date_bounds

        today = completed_reporting_date(datetime.utcnow()) + timedelta(days=1)
        starts_at, ends_at = reporting_date_bounds(today)
        v = REGISTRY.get("active_collectives").evaluate(
            db, platform_scope(), Window(starts_at, ends_at, "today"),
        )
        assert not v.available
        assert "has not finished yet" in v.unavailable_reason

    def test_a_past_day_is_still_refused_so_no_observation_is_invented(self, db):
        from app.core.periods import reporting_date_bounds

        starts_at, ends_at = reporting_date_bounds(date(2026, 3, 2))
        v = REGISTRY.get("active_collectives").evaluate(
            db, platform_scope(), Window(starts_at, ends_at, "march"),
        )
        assert not v.available
