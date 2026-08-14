"""Member Series ``payment-options`` endpoint — the ``is_member_checkoutable``
flag on each schedule.

Guarantees the multi-schedule structural readiness introduced in the M1
palette/hero refinement pass:

  * Published pay_in_full schedules are exposed with the flag True.
  * Published recurring_installments schedules are exposed alongside
    them with the flag False (kept in the payload so the frontend can
    render them once the Commerce milestone lands, but not surfaced
    as a member CTA today).
  * Draft schedules are still excluded at the query level.
  * An option whose only published schedule is recurring_installments
    is hidden entirely from the member endpoint.

The endpoint under test is invoked directly rather than via TestClient
because the SAVEPOINT-scoped ``db`` fixture is not visible through the
HTTP stack — matches the pattern in ``test_checkout_unified.py`` +
``test_event_about_blocks.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EventSeries
from app.spaces._series_member_routes import list_member_series_payment_options


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_series(db, space, *, title: str = "Term 3 2026") -> EventSeries:
    starts_at = datetime.utcnow() + timedelta(days=7)
    s = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(days=90),
        status="published",
    )
    db.add(s)
    db.flush()
    return s


def _make_option_with_series_grant(db, space, series, *, name: str) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=None,
        # Grant-native rows still need a legacy attaches_to link; a
        # dummy pointer at the series itself is fine — nothing on the
        # member endpoint reads it.
        attaches_to_kind="event_series",
        attaches_to_id=series.id,
        name=name,
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=20000,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    grant = PaymentOptionGrant(
        payment_option_id=opt.id,
        grant_kind="event_series",
        series_id=series.id,
        sessions_per_week=2,
        total_sessions=20,
    )
    db.add(grant)
    db.flush()
    return opt


def _make_schedule(
    db,
    option,
    *,
    name: str,
    schedule_type: str,
    status: str = "published",
    total: int = 20000,
    inst_amount: int | None = None,
    inst_count: int | None = None,
    interval: str | None = None,
) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        payment_option_id=option.id,
        name=name,
        schedule_type=schedule_type,
        status=status,
        total_amount_cents=total,
        installment_amount_cents=inst_amount,
        installment_count=inst_count,
        interval=interval,
        currency="AUD",
    )
    db.add(s)
    db.flush()
    return s


class TestMemberSeriesScheduleFlag:
    def test_pay_in_full_is_member_checkoutable_true(self, db, make_space):
        space = make_space()
        series = _make_series(db, space)
        opt = _make_option_with_series_grant(db, space, series, name="Awaken")
        _make_schedule(db, opt, name="Pay in full", schedule_type="pay_in_full")
        db.flush()

        out = list_member_series_payment_options(
            slug=space.slug,
            series_slug=series.slug,
            db=db,
            current_user=None,
        )
        assert len(out) == 1
        assert out[0].name == "Awaken"
        assert len(out[0].schedules) == 1
        s = out[0].schedules[0]
        assert s.schedule_type == "pay_in_full"
        assert s.is_member_checkoutable is True

    def test_recurring_instalments_returned_but_not_checkoutable(
        self, db, make_space,
    ):
        space = make_space()
        series = _make_series(db, space)
        opt = _make_option_with_series_grant(db, space, series, name="Awaken")
        _make_schedule(db, opt, name="Pay in full", schedule_type="pay_in_full")
        _make_schedule(
            db, opt, name="Weekly \u00d7 10",
            schedule_type="recurring_installments",
            total=20000, inst_amount=2000, inst_count=10, interval="week",
        )
        db.flush()

        out = list_member_series_payment_options(
            slug=space.slug,
            series_slug=series.slug,
            db=db,
            current_user=None,
        )
        assert len(out) == 1
        types = {s.schedule_type: s for s in out[0].schedules}
        # Both schedules ship — frontend chooses what to render.
        assert set(types) == {"pay_in_full", "recurring_installments"}
        assert types["pay_in_full"].is_member_checkoutable is True
        assert types["recurring_installments"].is_member_checkoutable is False
        # Instalment shape is preserved for future rendering.
        r = types["recurring_installments"]
        assert r.installment_amount_cents == 2000
        assert r.installment_count == 10
        assert r.interval == "week"

    def test_draft_schedule_hidden(self, db, make_space):
        space = make_space()
        series = _make_series(db, space)
        opt = _make_option_with_series_grant(db, space, series, name="Awaken")
        _make_schedule(db, opt, name="Pay in full", schedule_type="pay_in_full")
        _make_schedule(
            db, opt, name="Weekly (draft)",
            schedule_type="recurring_installments",
            status="draft",
            total=20000, inst_amount=2000, inst_count=10, interval="week",
        )
        db.flush()

        out = list_member_series_payment_options(
            slug=space.slug,
            series_slug=series.slug,
            db=db,
            current_user=None,
        )
        # Only the published schedule survived the DB-level status
        # filter — draft rows never travel to the member surface.
        assert [s.schedule_type for s in out[0].schedules] == ["pay_in_full"]

    def test_option_hidden_when_only_schedule_is_recurring(self, db, make_space):
        space = make_space()
        series = _make_series(db, space)
        opt = _make_option_with_series_grant(db, space, series, name="Plan-only")
        _make_schedule(
            db, opt, name="Weekly",
            schedule_type="recurring_installments",
            total=20000, inst_amount=2000, inst_count=10, interval="week",
        )
        db.flush()

        out = list_member_series_payment_options(
            slug=space.slug,
            series_slug=series.slug,
            db=db,
            current_user=None,
        )
        # An option whose only published schedule can't complete
        # checkout today must not surface at all — the sidebar
        # would render an empty card otherwise.
        assert out == []
