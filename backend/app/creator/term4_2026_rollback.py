"""Roll back the embody / term-4-2026 repair.

Reverses ``term4_2026_repair.run_repair``:

  * Restores each of the 27 rows' ``starts_at``, ``ends_at``,
    ``booking_closes_at``, ``recurrence_total`` to their pre-repair
    values.
  * Deletes the 3 new rows.

Safety envelope:
  * One transaction. All 30 reversions apply, or none does.
  * ``SELECT … FOR UPDATE`` row-lock before any write.
  * Pre-flight assertion: each of the 27 existing rows must currently
    hold the POST-repair value from ``CORRECTIONS`` and each of the 3
    new IDs supplied by the operator must exist. Refuses to run
    otherwise (rows have moved since the repair — investigate before
    reversing).
  * **Booking guard:** if ANY of the 3 new rows has acquired bookings
    since the repair ran, the whole rollback refuses. Operator can
    then decide manually whether to cancel the bookings first or
    restore only the 27 timestamps and leave the additions in place.

Takes the 3 new UUIDs as an explicit argument — the operator pastes
them from the repair's log output.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.creator.term4_2026_repair import CORRECTIONS, NEW_ROWS


def run_rollback(db: Session, new_row_ids: list[str]) -> dict[str, Any]:
    """Reverse the repair. ``new_row_ids`` is the list of three UUIDs
    the operator captured from the repair's log output — one per track.
    """
    if len(new_row_ids) != 3:
        raise SystemExit(
            f"Expected exactly 3 new_row_ids from the repair's log, got {len(new_row_ids)}."
        )
    expected_existing_ids = {row[0] for row in CORRECTIONS}
    expected_new_ids = set(new_row_ids)

    # --- 1. Scope check --------------------------------------------------
    scoped = {r[0] for r in db.execute(text("""
        SELECT e.id
        FROM events e
        JOIN spaces s ON s.id = e.space_id
        JOIN event_series es ON es.id = e.series_id
        WHERE s.slug = 'embody' AND es.slug = 'term-4-2026'
    """)).all()}
    expected_all = expected_existing_ids | expected_new_ids
    if scoped != expected_all:
        raise SystemExit(
            "Scope check FAILED.\n"
            f"  Existing 27 IDs expected in DB: {sorted(expected_existing_ids)}\n"
            f"  3 new IDs expected in DB:       {sorted(expected_new_ids)}\n"
            f"  Actually in DB: {sorted(scoped)}\n"
            f"  Missing from DB: {sorted(expected_all - scoped)}\n"
            f"  Extra in DB:     {sorted(scoped - expected_all)}"
        )
    print(f"Scope check OK — 30 rows matched by primary key (27 existing + 3 new).\n")

    # --- 2. Row-lock all 30 rows ----------------------------------------
    locked = db.execute(text("""
        SELECT id, starts_at, ends_at, booking_closes_at, recurrence_total
        FROM events
        WHERE id = ANY(:ids)
        FOR UPDATE
    """), {"ids": list(expected_all)}).all()
    snapshot = {r[0]: {
        "starts_at": r[1], "ends_at": r[2],
        "booking_closes_at": r[3], "recurrence_total": r[4],
    } for r in locked}
    print(f"Row-locks acquired on {len(snapshot)} rows.\n")

    # --- 3. Pre-flight: existing 27 must currently hold POST-repair values
    for eid, orig_s, orig_e, new_s_repair, new_e_repair in CORRECTIONS:
        s = snapshot[eid]
        now_s = s["starts_at"].isoformat()
        now_e = s["ends_at"].isoformat()
        if (now_s, now_e) != (new_s_repair, new_e_repair):
            raise SystemExit(
                f"Row {eid} does not hold the post-repair values.\n"
                f"  starts_at post-repair={new_s_repair}, DB now={now_s}\n"
                f"  ends_at   post-repair={new_e_repair}, DB now={now_e}\n"
                f"  Rollback refused. Investigate before reversing."
            )
        if s["recurrence_total"] != 10:
            raise SystemExit(
                f"Row {eid} has recurrence_total={s['recurrence_total']}, "
                f"expected 10 after the repair. Rollback refused."
            )
    print("Pre-flight OK — all 27 existing rows hold their post-repair values.\n")

    # --- 4. Booking guard on the 3 new rows -----------------------------
    booking_counts = db.execute(text("""
        SELECT event_id, COUNT(*) AS n
        FROM event_bookings
        WHERE event_id = ANY(:new_ids)
        GROUP BY event_id
    """), {"new_ids": list(expected_new_ids)}).all()
    with_bookings = [row for row in booking_counts if row[1] > 0]
    if with_bookings:
        blocking = ", ".join(f"{eid} ({n} bookings)" for eid, n in with_bookings)
        raise SystemExit(
            "Booking guard REFUSED rollback — one or more of the new "
            "rows has acquired bookings since the repair ran:\n"
            f"  {blocking}\n"
            "Cancel or migrate those bookings first, or run a partial "
            "restore that leaves the additions in place."
        )
    print(f"Booking guard OK — none of the 3 new rows has any bookings.\n")

    # --- 5. Restore 27 existing rows -----------------------------------
    print("Restoring 27 rows to pre-repair values:")
    for eid, orig_s, orig_e, new_s_repair, new_e_repair in CORRECTIONS:
        s = snapshot[eid]
        # booking_closes_at, if non-null, was shifted by the same delta
        # as starts_at during the repair. Reverse that shift.
        params: dict[str, Any] = {
            "id": eid,
            "orig_s": datetime.fromisoformat(orig_s),
            "orig_e": datetime.fromisoformat(orig_e),
        }
        if s["booking_closes_at"] is not None:
            delta_forward = datetime.fromisoformat(new_s_repair) - datetime.fromisoformat(orig_s)
            orig_bca = s["booking_closes_at"] - delta_forward
            db.execute(text("""
                UPDATE events
                SET starts_at = :orig_s, ends_at = :orig_e,
                    booking_closes_at = :orig_bca, recurrence_total = 9
                WHERE id = :id
            """), {**params, "orig_bca": orig_bca})
            print(f"  {eid}  restored to {orig_s} / {orig_e} / booking_closes {orig_bca.isoformat()} / total 9")
        else:
            db.execute(text("""
                UPDATE events
                SET starts_at = :orig_s, ends_at = :orig_e, recurrence_total = 9
                WHERE id = :id
            """), params)
            print(f"  {eid}  restored to {orig_s} / {orig_e} / total 9 (booking_closes: NULL)")

    # --- 6. Delete the 3 new rows --------------------------------------
    print("\nDeleting 3 new rows:")
    for nid in expected_new_ids:
        db.execute(text("DELETE FROM events WHERE id = :id"), {"id": nid})
        print(f"  deleted {nid}")

    print(f"\nRollback complete. 27 restorations + 3 deletions.")
    return {
        "restorations": 27,
        "deletions": 3,
    }


__all__ = ["run_rollback"]
