"""Editing a published payment plan recomputes its total.

Reported against EMBODY — All sessions: an existing plan of $42.00/week
× 10 was edited to $37.80/week × 10 and refused to save with

    total_amount_cents (42000) does not equal
    installment_amount_cents × installment_count (37800)

``apply_recurring_derivations`` only fills ``total_amount_cents`` when
it is NULL, on the assumption that a caller who supplied one meant it.
On an update applied to an ORM row that assumption breaks: a non-NULL
total may simply be the old stored value, and the helper cannot tell
the two apart. The per-payment amount moved, the total did not, and the
strict v1 cross-check rejected the pair.

Nothing about the wider payments architecture changes here. The strict
equality rule stays strict; Stripe stays downstream of Creator Studio;
existing purchases are untouched.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.schedule_validation import (
    apply_recurring_derivations,
    apply_recurring_update_derivations,
    validate_recurring_installments_row,
)


class _Row:
    """Stand-in for a merged ``PaymentOptionSchedule``. The helpers read
    and write plain attributes, so this exercises them exactly as the
    ORM row does."""

    def __init__(self, **kw):
        self.schedule_type = "recurring_installments"
        self.installment_amount_cents = None
        self.installment_count = None
        self.interval = "week"
        self.stripe_interval = None
        self.stripe_interval_count = None
        self.total_amount_cents = None
        self.currency = "AUD"
        self.status = "published"
        for k, v in kw.items():
            setattr(self, k, v)


def _existing_plan() -> _Row:
    """The plan as saved before the edit: $42.00/week × 10."""
    row = _Row(
        installment_amount_cents=4200,
        installment_count=10,
        total_amount_cents=42000,
        stripe_interval="week",
        stripe_interval_count=1,
    )
    validate_recurring_installments_row(row)   # sanity: starts valid
    return row


# ---------------------------------------------------------------------------
# The reported bug
# ---------------------------------------------------------------------------


class TestReportedScenario:
    def test_changing_the_instalment_amount_recomputes_the_total(self):
        """$42.00 × 10 → $37.80 × 10 must save."""
        row = _existing_plan()
        # What the Creator Studio patch sends: amount, count, interval —
        # never a total.
        row.installment_amount_cents = 3780
        supplied = {"installment_amount_cents", "installment_count", "interval"}

        apply_recurring_update_derivations(row, supplied_fields=supplied)

        assert row.total_amount_cents == 37800
        validate_recurring_installments_row(row)

    def test_the_old_behaviour_would_have_failed(self):
        """Pins the root cause: the plain helper preserves the stale
        total, which is what produced the 42000 vs 37800 error."""
        row = _existing_plan()
        row.installment_amount_cents = 3780

        apply_recurring_derivations(row)      # the pre-fix path

        assert row.total_amount_cents == 42000
        with pytest.raises(Exception) as exc:
            validate_recurring_installments_row(row)
        assert "42000" in str(exc.value) and "37800" in str(exc.value)

    def test_changing_the_number_of_payments_recomputes_the_total(self):
        row = _existing_plan()
        row.installment_count = 6
        apply_recurring_update_derivations(
            row, supplied_fields={"installment_count"},
        )
        assert row.total_amount_cents == 25200      # 4200 × 6
        validate_recurring_installments_row(row)

    def test_changing_both_at_once_recomputes_the_total(self):
        row = _existing_plan()
        row.installment_amount_cents = 3780
        row.installment_count = 12
        apply_recurring_update_derivations(
            row,
            supplied_fields={"installment_amount_cents", "installment_count"},
        )
        assert row.total_amount_cents == 45360      # 3780 × 12
        validate_recurring_installments_row(row)


# ---------------------------------------------------------------------------
# Scope — nothing else may shift
# ---------------------------------------------------------------------------


class TestScope:
    def test_an_explicit_total_is_still_respected(self):
        """A caller that genuinely sends a total keeps it. If it
        disagrees, validation says so — this helper must not silently
        overwrite a Creator's number."""
        row = _existing_plan()
        row.installment_amount_cents = 3780
        row.total_amount_cents = 99999
        apply_recurring_update_derivations(
            row,
            supplied_fields={"installment_amount_cents", "total_amount_cents"},
        )
        assert row.total_amount_cents == 99999
        with pytest.raises(Exception):
            validate_recurring_installments_row(row)

    def test_a_patch_touching_neither_input_leaves_the_total_alone(self):
        """Renaming a plan, or republishing it, must not recompute
        anything."""
        row = _existing_plan()
        apply_recurring_update_derivations(
            row, supplied_fields={"name", "status"},
        )
        assert row.total_amount_cents == 42000
        validate_recurring_installments_row(row)

    def test_interval_only_change_leaves_the_total_alone(self):
        row = _existing_plan()
        row.interval = "fortnight"
        apply_recurring_update_derivations(
            row, supplied_fields={"interval"},
        )
        assert row.total_amount_cents == 42000

    def test_pay_in_full_schedules_are_untouched(self):
        row = _Row(
            schedule_type="pay_in_full", total_amount_cents=42000,
            installment_amount_cents=None, installment_count=None,
        )
        apply_recurring_update_derivations(
            row, supplied_fields={"total_amount_cents"},
        )
        assert row.total_amount_cents == 42000

    def test_create_path_behaviour_is_unchanged(self):
        """``apply_recurring_derivations`` keeps its original contract —
        the create path still derives only into a NULL total."""
        fresh = _Row(installment_amount_cents=3780, installment_count=10)
        apply_recurring_derivations(fresh)
        assert fresh.total_amount_cents == 37800

        explicit = _Row(
            installment_amount_cents=3780, installment_count=10,
            total_amount_cents=37800,
        )
        apply_recurring_derivations(explicit)
        assert explicit.total_amount_cents == 37800

    def test_cadence_derivation_still_runs_on_update(self):
        row = _Row(
            installment_amount_cents=3780, installment_count=10,
            interval="week",
        )
        apply_recurring_update_derivations(
            row, supplied_fields={"installment_amount_cents"},
        )
        assert row.stripe_interval == "week"
        assert row.stripe_interval_count == 1
        assert row.total_amount_cents == 37800

    def test_strict_equality_rule_is_not_relaxed(self):
        """The v1 cross-check must stay strict — no tolerance crept in."""
        row = _Row(
            installment_amount_cents=3333, installment_count=3,
            total_amount_cents=10000,        # 9999 expected, off by one cent
        )
        with pytest.raises(Exception) as exc:
            validate_recurring_installments_row(row)
        assert "10000" in str(exc.value)


# ---------------------------------------------------------------------------
# Through the real endpoint
# ---------------------------------------------------------------------------


class TestEndToEndThroughTheRoute:
    @pytest.fixture
    def plan(self, db, make_space):
        from app.models.payment_option import PaymentOption
        from app.models.payment_option_schedule import PaymentOptionSchedule
        space = make_space()
        opt = PaymentOption(
            id=f"po_{uuid.uuid4().hex[:10]}",
            space_id=space.id,
            name="EMBODY — All sessions",
            status="published",
            attaches_to_kind="space",
            attaches_to_id=space.id,
        )
        db.add(opt)
        db.flush()
        sched = PaymentOptionSchedule(
            id=f"pos_{uuid.uuid4().hex[:10]}",
            payment_option_id=opt.id,
            name="Weekly plan",
            schedule_type="recurring_installments",
            status="published",
            currency="AUD",
            installment_amount_cents=4200,
            installment_count=10,
            total_amount_cents=42000,
            interval="week",
            stripe_interval="week",
            stripe_interval_count=1,
        )
        db.add(sched)
        db.flush()
        return space, opt, sched

    def test_route_saves_the_reported_edit(self, db, plan, make_user):
        """Drives the merge + derive + validate sequence the endpoint
        performs, on a real ORM row."""
        from app.services.schedule_validation import (
            validate_recurring_installments_payload,
        )
        _, _, sched = plan

        # The exact patch Creator Studio sends for this edit.
        updates = {
            "installment_amount_cents": 3780,
            "installment_count": 10,
            "interval": "week",
        }
        for field, val in updates.items():
            setattr(sched, field, val)

        apply_recurring_update_derivations(
            sched, supplied_fields=updates.keys(),
        )
        validate_recurring_installments_payload(sched)   # must not raise

        assert sched.total_amount_cents == 37800
        db.flush()

    def test_saved_values_survive_a_reload(self, db, plan):
        from app.models.payment_option_schedule import PaymentOptionSchedule
        _, _, sched = plan
        sched_id = sched.id

        updates = {"installment_amount_cents": 3780, "installment_count": 10}
        for field, val in updates.items():
            setattr(sched, field, val)
        apply_recurring_update_derivations(
            sched, supplied_fields=updates.keys(),
        )
        db.flush()
        db.expire_all()

        reloaded = db.query(PaymentOptionSchedule).filter(
            PaymentOptionSchedule.id == sched_id,
        ).one()
        assert reloaded.installment_amount_cents == 3780
        assert reloaded.installment_count == 10
        assert reloaded.total_amount_cents == 37800
        # Still published and available.
        assert reloaded.status == "published"
        validate_recurring_installments_row(reloaded)

    def test_both_update_routes_use_the_update_aware_helper(self):
        """Two endpoints patch schedules; both had the bug, so both must
        use the update-aware helper."""
        import inspect
        from app.creator import routes as creator_routes
        from app.creator import _space_payment_options_routes as po_routes

        for fn in (
            creator_routes.update_payment_option_schedule,
            po_routes.update_commerce_payment_option_schedule,
        ):
            src = inspect.getsource(fn)
            assert "apply_recurring_update_derivations(" in src, fn.__name__
            assert "apply_recurring_derivations(sched)" not in src, fn.__name__
