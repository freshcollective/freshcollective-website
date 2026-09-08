"""End-to-end validation of the embody / term-4-2026 repair.

Seeds a disposable copy of the 27 production rows into the
SAVEPOINT-scoped test session, runs the exact repair logic
(``run_repair``), and asserts the final state:

  * Exactly 30 events in the series.
  * 10 Mondays, 10 Thursdays, 10 Saturdays.
  * Each occurrence at the correct Melbourne wall-clock time
    (Mon/Thu 6-7 pm, Sat 9-10 am AEDT).
  * The 27 original IDs are preserved.
  * The 3 new rows inherit the sibling's config.
  * booking_closes_at is shifted by the same delta as starts_at
    on rows where it was non-null.
  * The insertion inherits the sibling's booking_closes_at OFFSET
    (booking_closes_at - starts_at), applied to the new starts_at.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

# Cross-file model registration for the SAVEPOINT session.
import app.models.community_care  # noqa: F401

from app.creator.term4_2026_repair import CORRECTIONS, NEW_ROWS, run_repair
from app.models.platform import Event, EventSeries, Space


MEL = ZoneInfo("Australia/Melbourne")


def _local(dt_utc_naive: datetime) -> datetime:
    return dt_utc_naive.replace(tzinfo=timezone.utc).astimezone(MEL)


@pytest.fixture
def seeded_series(db: Session, make_user, make_space):
    """Seed a stand-in for the embody / term-4-2026 series in the
    SAVEPOINT-scoped session. Uses the exact production IDs +
    timestamps + recurrence metadata from the CORRECTIONS table."""
    creator = make_user(role="creator")
    space = make_space(creator=creator, slug="embody", timezone="Australia/Melbourne")

    series = EventSeries(
        id=str(uuid.uuid4()),
        space_id=space.id,
        slug="term-4-2026",
        title="Term 4 2026",
        starts_at=datetime(2026, 10, 5, 7, 0, 0),
        ends_at=datetime(2026, 12, 12, 23, 0, 0),
        status="active",
    )
    db.add(series)
    db.flush()

    # Bulk-tag UUIDs — one per track, matching what the recurrence
    # generator would have produced originally.
    tag_by_label = {
        "EMBODY - Term 4 - Mondays":   str(uuid.uuid4()),
        "EMBODY - Term 4 - Thursdays": str(uuid.uuid4()),
        "EMBODY - Term 4 - Saturdays": str(uuid.uuid4()),
    }
    # Label lookup by row position in CORRECTIONS
    labels_ordered = (
        ["EMBODY - Term 4 - Mondays"]   * 9
        + ["EMBODY - Term 4 - Thursdays"] * 9
        + ["EMBODY - Term 4 - Saturdays"] * 9
    )
    for (eid, cur_s, cur_e, _new_s, _new_e), label in zip(CORRECTIONS, labels_ordered):
        # recurrence_index derived from the row's position in its track
        # (1..9 per track, in the order CORRECTIONS lists them).
        idx = (labels_ordered.index(label) % 9)
        for i, l in enumerate(labels_ordered):
            if l == label and CORRECTIONS[i][0] == eid:
                idx = (i % 9) + 1
                break
        db.add(Event(
            id=eid,
            space_id=space.id,
            created_by_id=creator.id,
            title=label.replace("EMBODY - Term 4 - ", "") + " - Term 4",
            starts_at=datetime.fromisoformat(cur_s),
            ends_at=datetime.fromisoformat(cur_e),
            location_type="in_person",
            is_published=True,
            is_public=True,
            requires_booking=True,
            capacity=16,
            gathering_type="workshop",
            attendance_format="in_person",
            venue_name="Studio",
            venue_locality="Melbourne VIC",
            booking_access_type="included_with_collective",
            recurrence_series_id=tag_by_label[label],
            recurrence_label=label,
            recurrence_index=idx,
            recurrence_total=9,
            series_id=series.id,
            status="active",
            # Seed a mix of booking_closes_at: siblings 9/9 get a
            # non-null 5h-before-start deadline; everyone else NULL.
            booking_closes_at=(
                datetime.fromisoformat(cur_s) - timedelta(hours=5)
                if idx == 9 else None
            ),
        ))
    db.flush()
    return {"space": space, "series": series, "creator": creator, "tag_by_label": tag_by_label}


def test_full_repair_produces_10_per_track_at_correct_times(
    db: Session, seeded_series,
):
    """The workhorse assertion: after run_repair, we have exactly 30
    events in the series, 10 per track, each at the intended
    Melbourne wall-clock time. IDs of the 27 original rows are
    preserved; 3 new IDs are generated. booking_closes_at semantics
    stay consistent."""
    space = seeded_series["space"]
    series = seeded_series["series"]

    # Snapshot the sibling (9/9) booking_closes_at offsets so we can
    # assert the new (10/10) rows inherit correctly.
    pre_ninth = {}
    for label in ("EMBODY - Term 4 - Mondays", "EMBODY - Term 4 - Thursdays", "EMBODY - Term 4 - Saturdays"):
        row = db.query(Event).filter(
            Event.series_id == series.id,
            Event.recurrence_label == label,
            Event.recurrence_index == 9,
        ).one()
        pre_ninth[label] = {
            "id": row.id,
            "starts_at": row.starts_at,
            "booking_closes_at": row.booking_closes_at,
            "offset": row.booking_closes_at - row.starts_at if row.booking_closes_at else None,
        }

    result = run_repair(db)

    # The repair used raw SQL; force the ORM identity map to re-read
    # from the DB rather than serve stale cached Event instances.
    db.expire_all()

    # Success return
    assert result["corrections_applied"] == 27
    assert result["recurrence_total_bumped"] == 27
    assert result["insertions"] == 3

    # Row count
    rows = db.query(Event).filter(Event.series_id == series.id).all()
    assert len(rows) == 30

    # Per-track: exactly 10 sessions each
    by_label = {}
    for r in rows:
        by_label.setdefault(r.recurrence_label, []).append(r)
    assert len(by_label["EMBODY - Term 4 - Mondays"]) == 10
    assert len(by_label["EMBODY - Term 4 - Thursdays"]) == 10
    assert len(by_label["EMBODY - Term 4 - Saturdays"]) == 10

    # Per-track: recurrence_total is 10 on every row
    for label, group in by_label.items():
        for r in group:
            assert r.recurrence_total == 10, f"{label} {r.recurrence_index}/{r.recurrence_total}"

    # Per-track: recurrence_index runs 1..10 with no gaps
    for label, group in by_label.items():
        indices = sorted(r.recurrence_index for r in group)
        assert indices == list(range(1, 11)), f"{label} indices: {indices}"

    # Every occurrence at the correct Melbourne wall-clock time
    for label, group in by_label.items():
        expected_weekday, expected_hour = {
            "EMBODY - Term 4 - Mondays":   (0, 18),
            "EMBODY - Term 4 - Thursdays": (3, 18),
            "EMBODY - Term 4 - Saturdays": (5, 9),
        }[label]
        for r in group:
            local = _local(r.starts_at)
            assert local.weekday() == expected_weekday, (
                f"{label} {r.recurrence_index}/10: expected weekday "
                f"{expected_weekday}, got {local.weekday()} ({local.isoformat()})"
            )
            assert local.hour == expected_hour and local.minute == 0
            # ends_at is exactly 1 hour later
            local_end = _local(r.ends_at)
            assert local_end - local == timedelta(hours=1)

    # Original 27 IDs preserved
    remaining_original_ids = {r.id for r in rows} & {c[0] for c in CORRECTIONS}
    assert len(remaining_original_ids) == 27

    # New 3 rows: recurrence_index == 10 across all three tracks
    new_rows = [r for r in rows if r.recurrence_index == 10]
    assert len(new_rows) == 3
    for nr in new_rows:
        # New IDs aren't in the CORRECTIONS table
        assert nr.id not in {c[0] for c in CORRECTIONS}
        # Sibling config inherited: same space, same series, same
        # recurrence_series_id as the ninth sibling on the same track.
        sibling_snapshot = pre_ninth[nr.recurrence_label]
        sibling = db.query(Event).filter(Event.id == sibling_snapshot["id"]).one()
        assert nr.space_id == sibling.space_id
        assert nr.created_by_id == sibling.created_by_id
        assert nr.recurrence_series_id == sibling.recurrence_series_id
        assert nr.series_id == sibling.series_id
        assert nr.venue_name == sibling.venue_name
        assert nr.venue_locality == sibling.venue_locality
        assert nr.capacity == sibling.capacity
        assert nr.gathering_type == sibling.gathering_type
        assert nr.booking_access_type == sibling.booking_access_type

    # booking_closes_at on the sibling (9/9) shifts by the same delta
    # as starts_at (preserving the semantic 5h offset).
    for label, snap in pre_ninth.items():
        corrected = db.query(Event).filter(Event.id == snap["id"]).one()
        assert corrected.booking_closes_at is not None
        # 5h offset preserved
        assert corrected.booking_closes_at - corrected.starts_at == snap["offset"]

    # booking_closes_at on the new (10/10) row inherits the sibling's
    # offset, applied to the new starts_at.
    for nr in new_rows:
        sibling_snap = pre_ninth[nr.recurrence_label]
        assert nr.booking_closes_at is not None
        assert nr.booking_closes_at - nr.starts_at == sibling_snap["offset"]


def test_repair_refuses_on_missing_row(db: Session, seeded_series):
    """If the scope check finds fewer than 27 rows (e.g. someone
    deleted one between report and run), the whole transaction refuses
    to run — nothing is written."""
    # Delete one row before running
    doomed_id = CORRECTIONS[0][0]
    db.query(Event).filter(Event.id == doomed_id).delete()
    db.flush()

    with pytest.raises(SystemExit, match="Scope check FAILED"):
        run_repair(db)

    # Prove no side effects: still 26 rows in the series, no new inserts
    remaining = db.query(Event).filter(Event.series_id == seeded_series["series"].id).all()
    assert len(remaining) == 26


def test_rollback_restores_and_deletes(db: Session, seeded_series):
    """Repair then rollback returns the DB to its pre-repair state
    for the 27 existing rows and removes the 3 additions."""
    series = seeded_series["series"]

    # Snapshot pre-repair values
    pre = {r.id: (r.starts_at, r.ends_at, r.booking_closes_at, r.recurrence_total)
           for r in db.query(Event).filter(Event.series_id == series.id).all()}
    assert len(pre) == 27

    result = run_repair(db)
    db.expire_all()
    assert result["insertions"] == 3

    from app.creator.term4_2026_rollback import run_rollback
    new_ids = [r["id"] for r in result["new_ids"]]
    rollback = run_rollback(db, new_ids)
    db.expire_all()

    assert rollback["restorations"] == 27
    assert rollback["deletions"] == 3

    # After rollback, 27 rows remain, all with pre-repair values.
    remaining = db.query(Event).filter(Event.series_id == series.id).all()
    assert len(remaining) == 27
    for r in remaining:
        pre_starts, pre_ends, pre_bca, pre_total = pre[r.id]
        assert r.starts_at == pre_starts
        assert r.ends_at == pre_ends
        assert r.booking_closes_at == pre_bca
        assert r.recurrence_total == pre_total


def test_rollback_refuses_when_new_row_has_bookings(db: Session, seeded_series, make_user):
    """If a booking has been created against one of the new rows
    since the repair, the whole rollback refuses so no booking is
    silently orphaned by the delete."""
    from app.models.platform import BookingStatus, EventBooking

    result = run_repair(db)
    db.expire_all()

    # Simulate a booking against the new Mondays row.
    new_id = next(r["id"] for r in result["new_ids"] if "Mondays" in r["label"])
    booker = make_user()
    db.add(EventBooking(
        id="b-rollback-guard-" + booker.id[-6:],
        event_id=new_id,
        user_id=booker.id,
        status=BookingStatus.confirmed,
        booked_at=datetime(2026, 12, 1),
        source="member",
    ))
    db.flush()

    from app.creator.term4_2026_rollback import run_rollback
    with pytest.raises(SystemExit, match="Booking guard REFUSED"):
        run_rollback(db, [r["id"] for r in result["new_ids"]])

    # Existing 27 rows still hold the POST-repair values (untouched by
    # the refused rollback).
    remaining = db.query(Event).filter(Event.recurrence_total == 10).all()
    assert len(remaining) >= 27


def test_repair_refuses_on_stale_timestamp(db: Session, seeded_series):
    """If a concurrent editor changed one row's starts_at between the
    report and the run, the pre-flight assertion refuses and the
    transaction rolls back."""
    stale_target = CORRECTIONS[0][0]
    row = db.query(Event).filter(Event.id == stale_target).one()
    row.starts_at = row.starts_at + timedelta(hours=1)
    db.flush()

    with pytest.raises(SystemExit, match="moved since the report"):
        run_repair(db)

    remaining = db.query(Event).filter(Event.series_id == seeded_series["series"].id).all()
    assert len(remaining) == 27  # no insertions, no deletions
