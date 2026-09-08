"""Repair the embody / term-4-2026 series.

Single transactional operation:
  * SELECT ... FOR UPDATE lock on the 27 existing rows.
  * Pre-flight equality assertion (rows haven't moved since the
    report was built).
  * Correct 27 starts_at / ends_at values, shifting booking_closes_at
    by the same delta where non-null.
  * Bump recurrence_total 9 → 10 on all 27.
  * Duplicate-check the 3 new dates against existing occurrences on
    the same Melbourne local date within the same track.
  * Insert 3 new rows, inheriting all sibling config, applying the
    sibling's booking_closes_at OFFSET (captured before the
    correction touches the sibling row) to the new starts_at.
  * Print a step-by-step log and return a summary dict.

Used both by ``tests/test_term4_repair.py`` (validation) and by the
one-liner the operator pastes into the Render fc-api Shell.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session


# ---- 27 corrections ---------------------------------------------------------
# (event.id, current_starts_at, current_ends_at, new_starts_at, new_ends_at)
CORRECTIONS: list[tuple[str, str, str, str, str]] = [
    # Mondays 1..9 (Δ starts_at -1 day; duration 1h unchanged)
    ("8eba347c-56c6-402d-977a-c8f1d779291a", "2026-10-06T07:00:00", "2026-10-06T08:00:00", "2026-10-05T07:00:00", "2026-10-05T08:00:00"),
    ("e9708582-4572-483a-a24b-12055a8566ee", "2026-10-13T07:00:00", "2026-10-13T08:00:00", "2026-10-12T07:00:00", "2026-10-12T08:00:00"),
    ("eb887bd4-e686-45a1-ab88-977bd225d564", "2026-10-20T07:00:00", "2026-10-20T08:00:00", "2026-10-19T07:00:00", "2026-10-19T08:00:00"),
    ("1dd9e450-9661-4372-ae18-b366bf4c6f64", "2026-10-27T07:00:00", "2026-10-27T08:00:00", "2026-10-26T07:00:00", "2026-10-26T08:00:00"),
    ("e70a94ff-3b82-47db-887a-c11d8b457bcd", "2026-11-03T07:00:00", "2026-11-03T08:00:00", "2026-11-02T07:00:00", "2026-11-02T08:00:00"),
    ("ac476c33-4d6f-48d7-9109-e41d4bfbf4e4", "2026-11-10T07:00:00", "2026-11-10T08:00:00", "2026-11-09T07:00:00", "2026-11-09T08:00:00"),
    ("738407ec-a1b2-407a-8717-a2793a507887", "2026-11-17T07:00:00", "2026-11-17T08:00:00", "2026-11-16T07:00:00", "2026-11-16T08:00:00"),
    ("b6b20ff7-bd0c-4a35-b1a2-5694af9d700e", "2026-11-24T07:00:00", "2026-11-24T08:00:00", "2026-11-23T07:00:00", "2026-11-23T08:00:00"),
    ("10c5c51c-d748-4995-8869-629af611f054", "2026-12-01T07:00:00", "2026-12-01T08:00:00", "2026-11-30T07:00:00", "2026-11-30T08:00:00"),
    # Thursdays 1..9 (Δ -1 day; duration unchanged)
    ("de98e593-c315-46dc-870b-e0a800de078d", "2026-10-09T07:00:00", "2026-10-09T08:00:00", "2026-10-08T07:00:00", "2026-10-08T08:00:00"),
    ("a74b5198-d90b-4bea-a31d-dcce0a7cfc2a", "2026-10-16T07:00:00", "2026-10-16T08:00:00", "2026-10-15T07:00:00", "2026-10-15T08:00:00"),
    ("ea973072-6b28-464f-a43e-51a193769b7f", "2026-10-23T07:00:00", "2026-10-23T08:00:00", "2026-10-22T07:00:00", "2026-10-22T08:00:00"),
    ("257b8cef-cefc-4b13-ad2b-6d130f7768bd", "2026-10-30T07:00:00", "2026-10-30T08:00:00", "2026-10-29T07:00:00", "2026-10-29T08:00:00"),
    ("091f6d2a-7690-4557-a8d8-a901440b4ff0", "2026-11-06T07:00:00", "2026-11-06T08:00:00", "2026-11-05T07:00:00", "2026-11-05T08:00:00"),
    ("3d487302-ddd7-4bf3-8f8e-ea1d45e28eb5", "2026-11-13T07:00:00", "2026-11-13T08:00:00", "2026-11-12T07:00:00", "2026-11-12T08:00:00"),
    ("c901a8d6-431f-497d-9819-f6473b6708ef", "2026-11-20T07:00:00", "2026-11-20T08:00:00", "2026-11-19T07:00:00", "2026-11-19T08:00:00"),
    ("58d4bcc8-6baa-4993-afd3-7661b32ad6de", "2026-11-27T07:00:00", "2026-11-27T08:00:00", "2026-11-26T07:00:00", "2026-11-26T08:00:00"),
    ("0a2decd1-8046-4278-8ab4-0328969bb3e3", "2026-12-04T07:00:00", "2026-12-04T08:00:00", "2026-12-03T07:00:00", "2026-12-03T08:00:00"),
    # Saturdays 1..9 (Δ -2 days AND duration 13h → 1h)
    ("7724743d-b6f4-45d8-bd01-7f6429d31e3e", "2026-10-11T22:00:00", "2026-10-12T11:00:00", "2026-10-09T22:00:00", "2026-10-09T23:00:00"),
    ("11175f28-b065-455d-83a8-3c3cdd4b7f35", "2026-10-18T22:00:00", "2026-10-19T11:00:00", "2026-10-16T22:00:00", "2026-10-16T23:00:00"),
    ("f58cc3cc-74af-43ae-9661-38bccfdf367c", "2026-10-25T22:00:00", "2026-10-26T11:00:00", "2026-10-23T22:00:00", "2026-10-23T23:00:00"),
    ("6107ff6c-789c-4a30-8111-850f2cd5b952", "2026-11-01T22:00:00", "2026-11-02T11:00:00", "2026-10-30T22:00:00", "2026-10-30T23:00:00"),
    ("d5f2403e-357b-4d2e-9bb1-a40f2e42eaa2", "2026-11-08T22:00:00", "2026-11-09T11:00:00", "2026-11-06T22:00:00", "2026-11-06T23:00:00"),
    ("9182d858-f15d-4bb4-8310-589dcb5bc3c4", "2026-11-15T22:00:00", "2026-11-16T11:00:00", "2026-11-13T22:00:00", "2026-11-13T23:00:00"),
    ("eb6aa11d-c0f5-4e1f-a60a-0e99580fae10", "2026-11-22T22:00:00", "2026-11-23T11:00:00", "2026-11-20T22:00:00", "2026-11-20T23:00:00"),
    ("753d4446-1181-4eab-95c7-2f646b1b36bd", "2026-11-29T22:00:00", "2026-11-30T11:00:00", "2026-11-27T22:00:00", "2026-11-27T23:00:00"),
    ("b7a1683b-27fa-4a11-8b5c-95bfc6d70692", "2026-12-06T22:00:00", "2026-12-07T11:00:00", "2026-12-04T22:00:00", "2026-12-04T23:00:00"),
]

# ---- 3 additions ------------------------------------------------------------
# (track_label, sibling_id_ninth, new_starts_at, new_ends_at)
NEW_ROWS: list[tuple[str, str, str, str]] = [
    ("EMBODY - Term 4 - Mondays",   "10c5c51c-d748-4995-8869-629af611f054", "2026-12-07T07:00:00", "2026-12-07T08:00:00"),
    ("EMBODY - Term 4 - Thursdays", "0a2decd1-8046-4278-8ab4-0328969bb3e3", "2026-12-10T07:00:00", "2026-12-10T08:00:00"),
    ("EMBODY - Term 4 - Saturdays", "b7a1683b-27fa-4a11-8b5c-95bfc6d70692", "2026-12-11T22:00:00", "2026-12-11T23:00:00"),
]

# Columns copied verbatim from sibling to new row.
INHERITED_COLUMNS = [
    "space_id", "created_by_id", "title", "description",
    "location_type", "location_url", "recording_url",
    "is_published", "is_public", "requires_booking", "capacity",
    "booking_note", "thumbnail_url", "gathering_type", "attendance_format",
    "venue_name", "venue_address", "venue_locality", "access_instructions",
    "booking_access_type", "booking_required_pathway_id",
    "ticket_price_cents", "ticket_currency",
    "recurrence_series_id", "recurrence_label", "series_id",
]

MEL = ZoneInfo("Australia/Melbourne")


def run_repair(db: Session) -> dict[str, Any]:
    """Execute the repair. Raises ``SystemExit`` on any pre-flight or
    duplicate-check failure — no partial writes leak because the
    caller is responsible for committing (the pytest fixture rolls
    back; the Render shell wrapper commits at the end).

    Returns a summary dict with counts and the 3 new UUIDs.
    """
    expected_ids = {row[0] for row in CORRECTIONS}

    # --- 1. Scope sanity check --------------------------------------------
    scoped = {r[0] for r in db.execute(text("""
        SELECT e.id
        FROM events e
        JOIN spaces s ON s.id = e.space_id
        JOIN event_series es ON es.id = e.series_id
        WHERE s.slug = 'embody' AND es.slug = 'term-4-2026'
    """)).all()}
    if scoped != expected_ids:
        raise SystemExit(
            "Scope check FAILED.\n"
            f"  In DB but not in table: {sorted(scoped - expected_ids)}\n"
            f"  In table but not in DB: {sorted(expected_ids - scoped)}"
        )
    print(f"Scope check OK — 27 rows matched by primary key.\n")

    # --- 2. Row-lock the 27 rows (SELECT ... FOR UPDATE) ------------------
    #     Captures ALL fields we need for later logic BEFORE any write:
    #     current starts_at, ends_at, booking_closes_at.
    locked = db.execute(text("""
        SELECT id, starts_at, ends_at, booking_closes_at
        FROM events
        WHERE id = ANY(:ids)
        FOR UPDATE
    """), {"ids": list(expected_ids)}).all()
    snapshot = {r[0]: {"starts_at": r[1], "ends_at": r[2], "booking_closes_at": r[3]} for r in locked}
    print(f"Row-locks acquired on {len(snapshot)} rows.\n")

    # --- 3. Pre-flight equality (guards against concurrent edits) --------
    for eid, cur_s, cur_e, _, _ in CORRECTIONS:
        s = snapshot[eid]
        now_s, now_e = s["starts_at"].isoformat(), s["ends_at"].isoformat()
        if (now_s, now_e) != (cur_s, cur_e):
            raise SystemExit(
                f"Row {eid} moved since the report was built:\n"
                f"  starts_at report={cur_s}, DB={now_s}\n"
                f"  ends_at   report={cur_e}, DB={now_e}"
            )
    print("Pre-flight OK — all 27 rows match the report's values.\n")

    # --- 4. Capture sibling booking_closes_at offsets BEFORE we touch the
    #     sibling's starts_at. Used later when inheriting into the new
    #     rows.
    sibling_offsets: dict[str, Any] = {}
    for _label, sibling_id, _ns, _ne in NEW_ROWS:
        s = snapshot[sibling_id]
        if s["booking_closes_at"] is not None:
            sibling_offsets[sibling_id] = s["booking_closes_at"] - s["starts_at"]
        else:
            sibling_offsets[sibling_id] = None

    # --- 5. Duplicate check for the 3 new rows ---------------------------
    for label, sibling_id, new_s, _ in NEW_ROWS:
        local_date = datetime.fromisoformat(new_s).replace(tzinfo=timezone.utc).astimezone(MEL).date()
        existing = db.execute(text("""
            SELECT id, starts_at FROM events
            WHERE recurrence_series_id = (SELECT recurrence_series_id FROM events WHERE id = :sibling_id)
              AND recurrence_label = :label
        """), {"sibling_id": sibling_id, "label": label}).all()
        for existing_id, existing_start in existing:
            existing_local = existing_start.replace(tzinfo=timezone.utc).astimezone(MEL).date()
            if existing_local == local_date:
                raise SystemExit(
                    f"Duplicate check FAILED for {label}: existing event {existing_id} "
                    f"already sits on Melbourne date {local_date}. Refusing to insert."
                )
    print("Duplicate check OK — no existing occurrence on any of the three target dates.\n")

    # --- 6. Apply the 27 timestamp corrections ---------------------------
    print("Applying 27 timestamp corrections:")
    for eid, cur_s, cur_e, new_s, new_e in CORRECTIONS:
        params: dict[str, Any] = {
            "id": eid,
            "new_s": datetime.fromisoformat(new_s),
            "new_e": datetime.fromisoformat(new_e),
        }
        # Also shift booking_closes_at by the same delta where non-null.
        s = snapshot[eid]
        if s["booking_closes_at"] is not None:
            delta = datetime.fromisoformat(new_s) - s["starts_at"]
            new_bca = s["booking_closes_at"] + delta
            db.execute(text("""
                UPDATE events
                SET starts_at = :new_s, ends_at = :new_e, booking_closes_at = :new_bca
                WHERE id = :id
            """), {**params, "new_bca": new_bca})
            print(f"  {eid}  starts {cur_s} → {new_s}   ends {cur_e} → {new_e}   booking_closes {s['booking_closes_at'].isoformat()} → {new_bca.isoformat()}")
        else:
            db.execute(text("""
                UPDATE events
                SET starts_at = :new_s, ends_at = :new_e
                WHERE id = :id
            """), params)
            print(f"  {eid}  starts {cur_s} → {new_s}   ends {cur_e} → {new_e}   (booking_closes: NULL)")

    # --- 7. Bump recurrence_total 9 → 10 on all 27 -----------------------
    db.execute(text("""
        UPDATE events SET recurrence_total = 10 WHERE id = ANY(:ids)
    """), {"ids": list(expected_ids)})
    print(f"\nrecurrence_total updated: 9 → 10 on {len(expected_ids)} rows.\n")

    # --- 8. Insert the 3 new rows ----------------------------------------
    print("Inserting 3 new rows:")
    new_ids: list[dict[str, Any]] = []
    for label, sibling_id, new_s, new_e in NEW_ROWS:
        sib = db.execute(text(
            f"SELECT {', '.join(INHERITED_COLUMNS)} FROM events WHERE id = :id"
        ), {"id": sibling_id}).mappings().one()

        new_bca = None
        offset = sibling_offsets[sibling_id]
        if offset is not None:
            new_bca = datetime.fromisoformat(new_s) + offset

        new_id = str(uuid.uuid4())
        params = dict(sib)
        params["id"] = new_id
        params["starts_at"] = datetime.fromisoformat(new_s)
        params["ends_at"] = datetime.fromisoformat(new_e)
        params["booking_closes_at"] = new_bca
        params["recurrence_index"] = 10
        params["recurrence_total"] = 10
        params["status"] = "active"
        params["attendance_completed_at"] = None
        params["attendance_completed_by"] = None

        cols = list(params.keys())
        db.execute(text(
            f"INSERT INTO events ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
        ), params)
        print(f"  inserted {new_id}  {label}  {new_s}–{new_e}  booking_closes={new_bca.isoformat() if new_bca else 'NULL'}  (inherited from {sibling_id})")
        new_ids.append({"id": new_id, "label": label, "starts_at": new_s})

    print(f"\nRepair complete. 27 corrections + 27 recurrence_total bumps + 3 insertions.")
    return {
        "corrections_applied": 27,
        "recurrence_total_bumped": 27,
        "insertions": 3,
        "new_ids": new_ids,
    }


__all__ = ["CORRECTIONS", "NEW_ROWS", "INHERITED_COLUMNS", "run_repair"]
