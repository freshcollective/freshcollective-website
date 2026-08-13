"""B2 — parity + idempotency tests for the grants backfill.

Proves that ``PaymentOptionGrant`` rows produced by
``app.commerce.backfill_grants.run_backfill`` faithfully represent
the meaning of every existing legacy ``PaymentOption`` shape,
without mutating any legacy fields.

Coverage:

  * Pathway-only option → one Pathway grant.
  * Series-only option → one Series grant with correct
    sessions_per_week / total_sessions / window semantics.
  * Series + bundled Pathway → one Series grant + one Pathway grant.
  * draft / published / archived options all get backfilled.
  * Options with and without PaymentOptionSchedules are indifferent
    (schedules don't influence grants).
  * Rerunning the backfill is a no-op.
  * Malformed rows (empty attaches_to_kind, unknown kind, missing
    Series target) are reported as warnings and skipped safely
    rather than silently inventing meaning.
  * Legacy PaymentOption columns are NOT mutated by the backfill.
  * Access-window semantics are preserved *exactly* per the
    current webhook rule:
       valid_from  = series.starts_at        (never overridden)
       valid_until = series.ends_at
                     OR option.term_end_date  (only when series is ongoing)
                     OR NULL
    Bundled Pathway grants do not inherit Series windows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from app.commerce.backfill_grants import (
    DerivedGrant,
    derive_grants_for_option,
    run_backfill,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EventSeries, Pathway, PathwayType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_pathway(db, space, *, title: str = "Practice") -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        status="active",
        access_type="free",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def _make_series(
    db, space, *, title: str = "Term",
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    status: str = "published",
) -> EventSeries:
    starts_at = starts_at or (datetime.utcnow() + timedelta(days=7))
    s = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title,
        starts_at=starts_at,
        # Explicit None allowed here to model "ongoing" series.
        ends_at=ends_at,
        status=status,
    )
    db.add(s)
    db.flush()
    return s


def _make_pathway_attached_option(
    db, space, pathway, *,
    name: str = "Course access",
    status: PaymentOptionStatus = PaymentOptionStatus.published,
    payment_type: PaymentOptionType = PaymentOptionType.one_time,
    sessions_per_week: int | None = None,
    total_sessions: int | None = None,
    term_start_date: date | None = None,
    term_end_date: date | None = None,
) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=pathway.id,
        attaches_to_kind="pathway",
        attaches_to_id=pathway.id,
        name=name,
        payment_type=payment_type,
        status=status,
        sessions_per_week=sessions_per_week,
        total_sessions=total_sessions,
        term_start_date=term_start_date,
        term_end_date=term_end_date,
        calculated_total_cents=10000,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _make_series_attached_option(
    db, space, series, *,
    name: str = "Awaken",
    status: PaymentOptionStatus = PaymentOptionStatus.published,
    sessions_per_week: int | None = 1,
    total_sessions: int | None = 10,
    term_end_date: date | None = None,
    grants_pathway_id: str | None = None,
) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=None,
        attaches_to_kind="event_series",
        attaches_to_id=series.id,
        grants_pathway_id=grants_pathway_id,
        name=name,
        payment_type=PaymentOptionType.term_pass,
        status=status,
        # Term dates mirror the series window today by convention.
        term_start_date=series.starts_at.date(),
        term_end_date=term_end_date if term_end_date is not None
                      else (series.ends_at.date() if series.ends_at else None),
        sessions_per_week=sessions_per_week,
        total_sessions=total_sessions,
        calculated_total_cents=60000,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    return opt


def _make_schedule(db, option, *, name: str = "Pay in full") -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        payment_option_id=option.id,
        name=name,
        schedule_type="pay_in_full",
        status="published",
        total_amount_cents=option.calculated_total_cents,
        currency=option.currency,
    )
    db.add(s)
    db.flush()
    return s


def _snapshot_option(opt: PaymentOption) -> dict:
    """Full field snapshot so tests can prove nothing on the row
    changed after the backfill. Excludes the auto-updated
    ``updated_at`` (SQLAlchemy's ``onupdate=func.now()`` would fire
    only on an actual mutation — but include it so we catch that too)."""
    return {
        "id": opt.id,
        "space_id": opt.space_id,
        "pathway_id": opt.pathway_id,
        "attaches_to_kind": opt.attaches_to_kind,
        "attaches_to_id": opt.attaches_to_id,
        "grants_pathway_id": opt.grants_pathway_id,
        "name": opt.name,
        "description": opt.description,
        "payment_type": opt.payment_type,
        "status": opt.status,
        "term_start_date": opt.term_start_date,
        "term_end_date": opt.term_end_date,
        "sessions_per_week": opt.sessions_per_week,
        "total_sessions": opt.total_sessions,
        "price_per_session_cents": opt.price_per_session_cents,
        "calculated_total_cents": opt.calculated_total_cents,
        "override_total_cents": opt.override_total_cents,
        "currency": opt.currency,
        "buyer_note": opt.buyer_note,
        "internal_note": opt.internal_note,
        "position": opt.position,
        "created_at": opt.created_at,
        "updated_at": opt.updated_at,
    }


def _grants_for(db, option_id: str) -> list[PaymentOptionGrant]:
    return (
        db.query(PaymentOptionGrant)
        .filter(PaymentOptionGrant.payment_option_id == option_id)
        .order_by(PaymentOptionGrant.position, PaymentOptionGrant.created_at)
        .all()
    )


# ---------------------------------------------------------------------------
# Derivation — pure function
# ---------------------------------------------------------------------------


class TestDerivePathwayAttached:
    def test_produces_one_pathway_grant(self, db, make_space):
        space = make_space()
        pw = _make_pathway(db, space, title="Home Practice")
        opt = _make_pathway_attached_option(db, space, pw)

        grants, warnings = derive_grants_for_option(opt, db)
        assert len(grants) == 1
        assert grants[0] == DerivedGrant(grant_kind="pathway", pathway_id=pw.id)
        assert warnings == []

    def test_pathway_attached_term_pass_warns_about_credits_but_captures_end(
        self, db, make_space,
    ):
        """A pathway-attached term_pass option carries
        ``sessions_per_week`` / ``total_sessions`` (Series-only,
        cannot be represented — warning) AND ``term_end_date``
        (the entitlement's end, now capturable on the Pathway grant
        as ``valid_until_override``)."""
        space = make_space()
        pw = _make_pathway(db, space, title="EMBODY Practice")
        opt = _make_pathway_attached_option(
            db, space, pw,
            payment_type=PaymentOptionType.term_pass,
            sessions_per_week=1, total_sessions=10,
            term_start_date=date(2026, 8, 1),
            term_end_date=date(2026, 10, 31),
        )

        grants, warnings = derive_grants_for_option(opt, db)
        assert len(grants) == 1
        g = grants[0]
        assert g.grant_kind == "pathway"
        assert g.pathway_id == pw.id
        assert g.sessions_per_week is None      # Series-only, not carried
        assert g.total_sessions is None         # Series-only, not carried
        # The entitlement window IS carried, so future fulfilment
        # gets the same end date the current webhook produces.
        assert g.valid_until_override == datetime(2026, 10, 31, 0, 0, 0)
        assert g.valid_from_override is None     # NULL means "starts NOW"
        # Warning still fired because credits are Series-only.
        assert len(warnings) == 1
        assert "sessions_per_week" in warnings[0]


class TestDeriveSeriesAttached:
    def test_series_only_carries_credits_and_no_window_override(
        self, db, make_space,
    ):
        """Series with a defined end → valid_until_override stays
        NULL; grants-model read path inherits from series.ends_at
        (matching the webhook's ``ap_valid_until = series.ends_at``
        branch)."""
        space = make_space()
        starts = datetime(2026, 8, 1)
        series = _make_series(
            db, space, starts_at=starts, ends_at=starts + timedelta(days=90),
        )
        opt = _make_series_attached_option(
            db, space, series,
            sessions_per_week=1, total_sessions=10,
        )

        grants, warnings = derive_grants_for_option(opt, db)
        assert warnings == []
        assert len(grants) == 1
        g = grants[0]
        assert g.grant_kind == "event_series"
        assert g.series_id == series.id
        assert g.sessions_per_week == 1
        assert g.total_sessions == 10
        assert g.valid_from_override is None   # always inherits from series.starts_at
        assert g.valid_until_override is None  # series has ends_at → inherit

    def test_ongoing_series_with_option_term_end_gets_valid_until_override(
        self, db, make_space,
    ):
        """Ongoing Series (ends_at IS NULL) + option.term_end_date
        → the option's term_end_date is the effective cap the
        current webhook applies. Capture it as an explicit override
        so the grants-model read path (B3+) sees the same window."""
        space = make_space()
        starts = datetime(2026, 8, 1)
        series = _make_series(
            db, space, starts_at=starts, ends_at=None,  # ongoing
        )
        opt = _make_series_attached_option(
            db, space, series,
            sessions_per_week=1, total_sessions=10,
            term_end_date=date(2026, 12, 31),
        )

        [g] = derive_grants_for_option(opt, db)[0]
        assert g.valid_until_override == datetime(2026, 12, 31, 0, 0, 0)

    def test_ongoing_series_with_no_option_term_end_stays_perpetual(
        self, db, make_space,
    ):
        space = make_space()
        series = _make_series(
            db, space, starts_at=datetime(2026, 8, 1), ends_at=None,
        )
        # Explicitly clear the option's term_end_date (helper defaults
        # to series.ends_at which is None here anyway).
        opt = _make_series_attached_option(
            db, space, series,
            sessions_per_week=1, total_sessions=10,
            term_end_date=None,
        )
        [g] = derive_grants_for_option(opt, db)[0]
        assert g.valid_until_override is None

    def test_series_plus_bundled_pathway_produces_two_grants(
        self, db, make_space,
    ):
        """The EMBODY case: Series-attached option that also grants
        the EMBODY Practice pathway on purchase.

        Series parity:
          * Series grant carries per-tier ``sessions_per_week`` /
            ``total_sessions``.
          * ``valid_from_override`` = NULL (AccessPass inherits
            ``series.starts_at``).
          * ``valid_until_override`` = NULL when Series has ``ends_at``
            (AccessPass inherits it).

        Bundled Pathway parity:
          * ``valid_from_override`` = NULL (PathwayEntitlement gets
            ``starts_at=now`` at fulfilment — immediate access).
          * ``valid_until_override`` = ``series.ends_at`` (the
            entitlement expires with the term).
          * Booking allowances (credits) do NOT appear on the
            Pathway grant — those stay Series-grant-only.
        """
        space = make_space()
        practice = _make_pathway(db, space, title="The EMBODY Practice")
        starts = datetime(2026, 8, 1)
        series = _make_series(
            db, space, title="EMBODY Term 3 2026",
            starts_at=starts, ends_at=starts + timedelta(days=90),
        )
        opt = _make_series_attached_option(
            db, space, series,
            name="Awaken", sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
        )

        grants, warnings = derive_grants_for_option(opt, db)
        assert warnings == []
        assert len(grants) == 2
        kinds = {g.grant_kind for g in grants}
        assert kinds == {"event_series", "pathway"}

        series_grant = next(g for g in grants if g.grant_kind == "event_series")
        pathway_grant = next(g for g in grants if g.grant_kind == "pathway")

        assert series_grant.series_id == series.id
        assert series_grant.sessions_per_week == 1
        assert series_grant.total_sessions == 10
        assert series_grant.valid_from_override is None
        assert series_grant.valid_until_override is None

        assert pathway_grant.pathway_id == practice.id
        assert pathway_grant.sessions_per_week is None
        assert pathway_grant.total_sessions is None
        # Pathway grant ``valid_from_override`` stays NULL → means
        # "starts NOW at fulfilment" (matches current webhook).
        assert pathway_grant.valid_from_override is None
        # Pathway grant carries the effective term end so fulfilment
        # never has to infer it from other grants on the same Option.
        assert pathway_grant.valid_until_override == series.ends_at

    def test_bundled_pathway_grant_end_falls_back_to_option_term_end_when_series_ongoing(
        self, db, make_space,
    ):
        """Ongoing Series (no ``ends_at``) + option carrying a
        term_pass ``term_end_date`` → bundled Pathway grant's
        ``valid_until_override`` is the option's ``term_end_date``
        (mirrors the current webhook's fallback rule)."""
        space = make_space()
        practice = _make_pathway(db, space, title="Practice")
        series = _make_series(
            db, space, starts_at=datetime(2026, 8, 1), ends_at=None,
        )
        opt = _make_series_attached_option(
            db, space, series,
            sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
            term_end_date=date(2026, 12, 31),
        )

        grants = derive_grants_for_option(opt, db)[0]
        pathway_grant = next(g for g in grants if g.grant_kind == "pathway")
        assert pathway_grant.valid_until_override == datetime(2026, 12, 31, 0, 0, 0)

    def test_bundled_pathway_grant_is_perpetual_when_series_ongoing_and_no_option_term_end(
        self, db, make_space,
    ):
        space = make_space()
        practice = _make_pathway(db, space, title="Practice")
        series = _make_series(
            db, space, starts_at=datetime(2026, 8, 1), ends_at=None,
        )
        opt = _make_series_attached_option(
            db, space, series,
            sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
            term_end_date=None,
        )

        grants = derive_grants_for_option(opt, db)[0]
        pathway_grant = next(g for g in grants if g.grant_kind == "pathway")
        assert pathway_grant.valid_until_override is None

    def test_missing_series_row_reports_warning_but_still_inserts(
        self, db, make_space,
    ):
        space = make_space()
        series = _make_series(db, space)
        opt = _make_series_attached_option(
            db, space, series,
            sessions_per_week=1, total_sessions=10,
        )
        # Point the option at a non-existent series (simulating a
        # stale row). Sqlalchemy allows this because there's no FK
        # on attaches_to_id.
        opt.attaches_to_id = "es_does_not_exist"
        db.flush()

        grants, warnings = derive_grants_for_option(opt, db)
        assert len(grants) == 1
        assert grants[0].series_id == "es_does_not_exist"
        assert grants[0].valid_until_override is None
        assert warnings and "unknown event_series" in warnings[0]


class TestDeriveMalformed:
    def test_empty_attaches_to_kind_skipped_with_warning(
        self, db, make_space,
    ):
        space = make_space()
        pw = _make_pathway(db, space)
        opt = _make_pathway_attached_option(db, space, pw)
        opt.attaches_to_kind = ""
        opt.attaches_to_id = ""
        db.flush()

        grants, warnings = derive_grants_for_option(opt, db)
        assert grants == []
        assert warnings and "empty attaches_to_kind" in warnings[0]

    def test_unknown_kind_skipped_with_warning(self, db, make_space):
        space = make_space()
        pw = _make_pathway(db, space)
        opt = _make_pathway_attached_option(db, space, pw)
        opt.attaches_to_kind = "bundle"  # never valid
        db.flush()

        grants, warnings = derive_grants_for_option(opt, db)
        assert grants == []
        assert warnings and "unknown attaches_to_kind" in warnings[0]


# ---------------------------------------------------------------------------
# run_backfill — end-to-end
# ---------------------------------------------------------------------------


class TestRunBackfill:
    def test_creates_expected_grants_from_mixed_options(
        self, db, make_space,
    ):
        space = make_space()
        pw_solo = _make_pathway(db, space, title="Home Practice")
        pw_bundled = _make_pathway(db, space, title="The EMBODY Practice")
        series = _make_series(db, space, title="EMBODY Term 3 2026")

        _make_pathway_attached_option(
            db, space, pw_solo, name="Home Practice — one-off",
        )
        _make_series_attached_option(
            db, space, series, name="Awaken",
            sessions_per_week=1, total_sessions=10,
            grants_pathway_id=pw_bundled.id,
        )
        _make_series_attached_option(
            db, space, series, name="Empower",
            sessions_per_week=None, total_sessions=None,
            grants_pathway_id=pw_bundled.id,
        )
        db.commit()

        report = run_backfill(db)
        assert report.options_scanned == 3
        # 3 pathway grants (Home Practice solo + two bundled Practice)
        assert report.grants_created_pathway == 3
        # 2 series grants (Awaken + Empower)
        assert report.grants_created_event_series == 2
        assert report.grants_created_gathering == 0
        assert report.grants_already_present == 0

    def test_covers_draft_published_archived(self, db, make_space):
        space = make_space()
        pw = _make_pathway(db, space)
        for st in (
            PaymentOptionStatus.draft,
            PaymentOptionStatus.published,
            PaymentOptionStatus.archived,
        ):
            _make_pathway_attached_option(db, space, pw, name=st.value, status=st)
        # Same pathway across three options — allowed by the
        # per-(option, target) unique index.
        db.commit()

        report = run_backfill(db)
        assert report.options_scanned == 3
        assert report.grants_created_pathway == 3

    def test_schedules_do_not_influence_grants(self, db, make_space):
        space = make_space()
        pw = _make_pathway(db, space)
        with_sched = _make_pathway_attached_option(
            db, space, pw, name="with schedule",
        )
        _make_schedule(db, with_sched)
        _make_pathway_attached_option(db, space, pw, name="without schedule")
        db.commit()

        report = run_backfill(db)
        assert report.grants_created_pathway == 2

    def test_dry_run_writes_nothing(self, db, make_space):
        space = make_space()
        pw = _make_pathway(db, space)
        _make_pathway_attached_option(db, space, pw)
        db.commit()

        before = db.query(PaymentOptionGrant).count()
        report = run_backfill(db, dry_run=True)
        after = db.query(PaymentOptionGrant).count()
        assert before == 0
        assert after == 0
        # Report still reflects what *would* have been created.
        assert report.grants_created_pathway == 1


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_rerun_produces_no_new_grants(self, db, make_space):
        space = make_space()
        pw = _make_pathway(db, space)
        series = _make_series(db, space)
        _make_pathway_attached_option(db, space, pw)
        _make_series_attached_option(
            db, space, series,
            grants_pathway_id=pw.id,
        )
        db.commit()

        first = run_backfill(db)
        assert first.grants_already_present == 0
        first_total = first.grants_created_pathway + first.grants_created_event_series

        second = run_backfill(db)
        # Second run creates nothing.
        assert second.grants_created_pathway == 0
        assert second.grants_created_event_series == 0
        # Every derived grant is now skipped.
        assert second.grants_already_present == first_total

        # Final grants set is the same size as after the first run.
        assert db.query(PaymentOptionGrant).count() == first_total

    def test_partial_state_converges(self, db, make_space):
        """Simulate an interrupted first run: one grant already
        present, the rest missing. Backfill inserts only the
        missing ones."""
        space = make_space()
        pw = _make_pathway(db, space)
        series = _make_series(db, space)
        opt_a = _make_pathway_attached_option(db, space, pw, name="A")
        opt_b = _make_series_attached_option(db, space, series, name="B")
        db.commit()

        # Pre-seed the grant for opt_a only.
        db.add(PaymentOptionGrant(
            payment_option_id=opt_a.id,
            grant_kind="pathway", pathway_id=pw.id,
        ))
        db.commit()

        report = run_backfill(db)
        assert report.grants_already_present == 1  # opt_a's pathway grant
        assert report.grants_created_event_series == 1  # opt_b's series grant
        assert report.grants_created_pathway == 0

    def test_run_backfill_never_mutates_legacy_option_fields(
        self, db, make_space,
    ):
        """Snapshot every PaymentOption column before and after
        the backfill and assert every field is byte-for-byte
        identical."""
        space = make_space()
        pw = _make_pathway(db, space)
        practice = _make_pathway(db, space, title="Practice")
        series = _make_series(db, space)

        options = [
            _make_pathway_attached_option(db, space, pw, name="P"),
            _make_series_attached_option(
                db, space, series, name="S",
                grants_pathway_id=practice.id,
            ),
        ]
        db.commit()

        before = {opt.id: _snapshot_option(opt) for opt in options}
        run_backfill(db)
        # Reload from DB to force any onupdate=func.now() to surface.
        for opt in options:
            db.refresh(opt)
        after = {opt.id: _snapshot_option(opt) for opt in options}

        assert before == after, (
            "Backfill mutated a PaymentOption row. Legacy columns must "
            "remain the source of truth through B2."
        )

    def test_second_run_never_mutates_legacy_option_fields(
        self, db, make_space,
    ):
        space = make_space()
        pw = _make_pathway(db, space)
        _make_pathway_attached_option(db, space, pw)
        db.commit()

        run_backfill(db)   # first
        opt = db.query(PaymentOption).first()
        assert opt is not None
        before = _snapshot_option(opt)

        run_backfill(db)   # second
        db.refresh(opt)
        after = _snapshot_option(opt)
        assert before == after


# ---------------------------------------------------------------------------
# Parity — the *meaning* of legacy fields matches the meaning of the
# derived grants for the scenarios we care about.
# ---------------------------------------------------------------------------


class TestParityWithWebhookSemantics:
    """These tests describe the invariants the B3 code-flip must
    honour when it switches the webhook to read from grants. Each
    case pins the exact grant shape a specific legacy option
    produces, so a future regression in derivation would be caught
    here."""

    def test_pathway_only_option_produces_pathway_grant_only(
        self, db, make_space,
    ):
        space = make_space()
        pw = _make_pathway(db, space, title="Home Practice")
        opt = _make_pathway_attached_option(db, space, pw)
        db.commit()

        run_backfill(db)
        grants = _grants_for(db, opt.id)
        assert len(grants) == 1
        assert grants[0].grant_kind == "pathway"
        assert grants[0].pathway_id == pw.id

    def test_series_only_option_produces_series_grant_only(
        self, db, make_space,
    ):
        space = make_space()
        series = _make_series(db, space, title="Term 3")
        opt = _make_series_attached_option(
            db, space, series,
            name="Awaken", sessions_per_week=1, total_sessions=10,
        )
        db.commit()

        run_backfill(db)
        grants = _grants_for(db, opt.id)
        assert len(grants) == 1
        g = grants[0]
        assert g.grant_kind == "event_series"
        assert g.series_id == series.id
        assert g.sessions_per_week == 1
        assert g.total_sessions == 10

    def test_series_plus_bundled_pathway_produces_both_grants(
        self, db, make_space,
    ):
        space = make_space()
        practice = _make_pathway(db, space, title="The EMBODY Practice")
        series = _make_series(db, space, title="EMBODY Term 3 2026")
        opt = _make_series_attached_option(
            db, space, series,
            name="Awaken", sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
        )
        db.commit()

        run_backfill(db)
        grants = _grants_for(db, opt.id)
        assert len(grants) == 2
        kinds = {g.grant_kind for g in grants}
        assert kinds == {"event_series", "pathway"}

        series_grant = next(g for g in grants if g.grant_kind == "event_series")
        pathway_grant = next(g for g in grants if g.grant_kind == "pathway")
        assert series_grant.series_id == series.id
        assert series_grant.sessions_per_week == 1
        assert series_grant.total_sessions == 10
        assert pathway_grant.pathway_id == practice.id
        # Pathway grant does NOT carry Series windowing.
        assert pathway_grant.valid_from_override is None
        assert pathway_grant.valid_until_override is None

    def test_bundled_pathway_grant_does_not_inherit_series_start(
        self, db, make_space,
    ):
        """Regression guard for the user's clarification:
        the bundled Pathway grant does not silently get the
        Series' start date. Under the current webhook the pathway
        entitlement always starts NOW; a Pathway grant with
        ``valid_from_override IS NULL`` means the same thing."""
        space = make_space()
        practice = _make_pathway(db, space, title="Practice")
        # A Series that starts a month in the future.
        future_start = datetime.utcnow() + timedelta(days=30)
        series = _make_series(
            db, space, starts_at=future_start,
            ends_at=future_start + timedelta(days=60),
        )
        opt = _make_series_attached_option(
            db, space, series,
            grants_pathway_id=practice.id,
        )
        db.commit()

        run_backfill(db)
        pathway_grant = next(
            g for g in _grants_for(db, opt.id) if g.grant_kind == "pathway"
        )
        # ``valid_from_override IS NULL`` → fulfilment uses NOW for
        # the entitlement's ``starts_at`` (immediate access even
        # while the Series is still in the future).
        assert pathway_grant.valid_from_override is None
        # ``valid_until_override`` IS set — it's the Series end.
        # The Pathway grant does NOT inherit the Series *start*,
        # but it does capture the Series *end* so the entitlement
        # expires with the term.
        assert pathway_grant.valid_until_override == series.ends_at

    def test_embody_shape_parity(self, db, make_space):
        """Full EMBODY Series+Pathway parity contract:

          * Series AccessPass starts at Series start
              → Series grant ``valid_from_override IS NULL``
                (fulfilment inherits ``series.starts_at``).
          * Series AccessPass ends at Series end
              → Series grant ``valid_until_override IS NULL``
                (fulfilment inherits ``series.ends_at``).
          * Pathway entitlement starts immediately
              → Pathway grant ``valid_from_override IS NULL``
                (fulfilment uses ``NOW()``).
          * Pathway entitlement ends at effective Series/term end
              → Pathway grant ``valid_until_override == series.ends_at``
                (self-contained; fulfilment doesn't have to look at
                any other grant on the Option to know when the
                bundled Pathway access expires).
          * Series booking allowances per tier
              → Series grant carries ``sessions_per_week`` /
                ``total_sessions`` from the option row.
        """
        space = make_space()
        practice = _make_pathway(db, space, title="The EMBODY Practice")
        starts = datetime(2026, 8, 1)
        series = _make_series(
            db, space, title="EMBODY Term 3 2026",
            starts_at=starts, ends_at=starts + timedelta(days=90),
        )
        awaken = _make_series_attached_option(
            db, space, series, name="Awaken",
            sessions_per_week=1, total_sessions=10,
            grants_pathway_id=practice.id,
        )
        activate = _make_series_attached_option(
            db, space, series, name="Activate",
            sessions_per_week=2, total_sessions=20,
            grants_pathway_id=practice.id,
        )
        empower = _make_series_attached_option(
            db, space, series, name="Empower",
            sessions_per_week=3, total_sessions=30,
            grants_pathway_id=practice.id,
        )
        db.commit()

        run_backfill(db)

        for opt, spw, tot in (
            (awaken, 1, 10),
            (activate, 2, 20),
            (empower, 3, 30),
        ):
            grants = _grants_for(db, opt.id)
            assert len(grants) == 2, f"{opt.name}: expected 2 grants"
            series_grant = next(g for g in grants if g.grant_kind == "event_series")
            pathway_grant = next(g for g in grants if g.grant_kind == "pathway")

            # Series parity.
            assert series_grant.series_id == series.id
            assert series_grant.sessions_per_week == spw
            assert series_grant.total_sessions == tot
            assert series_grant.valid_from_override is None
            assert series_grant.valid_until_override is None

            # Bundled Pathway parity.
            assert pathway_grant.pathway_id == practice.id
            assert pathway_grant.sessions_per_week is None
            assert pathway_grant.total_sessions is None
            # NULL from-override → starts NOW at fulfilment
            assert pathway_grant.valid_from_override is None
            # End IS pinned to Series end so fulfilment does not have
            # to infer it from other grants on the same Option.
            assert pathway_grant.valid_until_override == series.ends_at

    def test_series_end_wins_over_option_term_end_when_both_set(
        self, db, make_space,
    ):
        """Series.ends_at is the effective end today; the option's
        term_end_date only kicks in as a fallback for ongoing
        series. When both are set, the grant carries no override
        so the read path inherits series.ends_at."""
        space = make_space()
        starts = datetime(2026, 8, 1)
        series = _make_series(
            db, space, starts_at=starts, ends_at=starts + timedelta(days=90),
        )
        opt = _make_series_attached_option(
            db, space, series,
            sessions_per_week=1, total_sessions=10,
            term_end_date=date(2027, 1, 1),  # differs from series.ends_at
        )
        db.commit()

        run_backfill(db)
        series_grant = next(
            g for g in _grants_for(db, opt.id) if g.grant_kind == "event_series"
        )
        assert series_grant.valid_until_override is None
