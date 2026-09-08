"""Regression tests for the timezone-aware recurring gathering generator.

Covers the two defects fixed together:

1. **Weekday convention mismatch.** The frontend's picker sent JS-shaped
   values (Sun=0..Sat=6) while ``routes.bulk_create_events`` compared
   them against Python's ``datetime.weekday()`` (Mon=0..Sun=6). Every
   recurring occurrence landed on the day AFTER the intended weekday.
   The rewritten generator now consumes ``days_of_week`` in Python's
   Mon=0..Sun=6 convention (as the schema documents) and the frontend
   ``WEEKDAYS`` array is corrected to match.

2. **Timezone-naive enumeration.** The old generator did
   ``body.starts_at.date()`` on a UTC-aware anchor and treated the
   result as if it were the creator's local calendar day. This broke:
     * Morning sessions in Australia (Sat 9 am AEDT = Fri 22:00 UTC —
       the UTC weekday is Fri, not Sat).
     * Recurrences spanning DST transitions — the wall-clock time
       drifted by an hour after the transition.
   The generator now runs entirely in the space's local timezone,
   converting each occurrence back to UTC only at storage time.

The tests below drive the actual ``POST /spaces/{slug}/events/bulk``
endpoint end-to-end so any regression in either layer is caught.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Cross-file model registration for the SAVEPOINT test session.
import app.models.community_care  # noqa: F401

from app.auth.dependencies import get_verified_creator_user
from app.core.database import get_db
from app.main import app
from app.models.platform import Event


AEDT_ANCHOR_MON_6PM = datetime(2026, 10, 5, 7, 0, 0, tzinfo=timezone.utc)
"""Mon 5 Oct 2026 6 pm Australia/Melbourne (AEDT +11 in DST) = 07:00 UTC."""

AEDT_ANCHOR_SAT_9AM = datetime(2026, 10, 3, 22, 0, 0, tzinfo=timezone.utc)
"""Sat 3 Oct 2026 9 am Australia/Melbourne (AEDT +11) = 22:00 UTC on Fri 2 Oct."""

MELBOURNE = ZoneInfo("Australia/Melbourne")


@pytest.fixture
def client_as(db: Session):
    """TestClient with dependency overrides that authenticate as the
    passed-in user and pin the DB session to the SAVEPOINT-scoped one."""
    def _install(user):
        app.dependency_overrides[get_verified_creator_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app, follow_redirects=False)

    yield _install

    app.dependency_overrides.pop(get_verified_creator_user, None)
    app.dependency_overrides.pop(get_db, None)


def _bulk_request(
    *, starts_at_utc: datetime, ends_at_utc: datetime | None,
    days_of_week: list[int], count: int, title: str = "Recurring",
) -> dict:
    payload = {
        "title": title,
        "starts_at": starts_at_utc.isoformat(),
        "ends_at": ends_at_utc.isoformat() if ends_at_utc else None,
        "location_type": "zoom",
        "requires_booking": False,
        "attendance_format": "online",
        "gathering_type": "workshop",
        "booking_access_type": "included_with_collective",
        "recurrence": {
            "pattern": "weekly",
            "days_of_week": days_of_week,
            "end_after_n": count,
        },
    }
    return payload


def _local_wall_clock(utc_naive: datetime) -> datetime:
    """Read a naive-UTC DB value back as a Melbourne wall-clock time."""
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(MELBOURNE)


# ---------------------------------------------------------------------------
# 1. Weekday convention — Mon, Thu, Sat land on the correct wall-clock day
# ---------------------------------------------------------------------------


class TestWeekdayConvention:
    """The three cases the creator reported: Mondays 6 pm, Thursdays 6 pm,
    Saturdays 9 am — must generate occurrences on the requested weekday
    in the collective's timezone. Under the buggy generator, each landed
    one day later."""

    def test_mondays_6pm_stay_on_mondays(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        end_utc = AEDT_ANCHOR_MON_6PM.replace(hour=8)  # Mon 7 pm AEDT = 08:00 UTC
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json=_bulk_request(
                starts_at_utc=AEDT_ANCHOR_MON_6PM,
                ends_at_utc=end_utc,
                days_of_week=[0],  # Python: Monday
                count=4,
                title="Mondays",
            ),
        )
        assert r.status_code == 201, r.text
        rows = db.query(Event).filter(Event.space_id == space.id).order_by(Event.starts_at).all()
        assert len(rows) == 4
        for row in rows:
            local = _local_wall_clock(row.starts_at)
            assert local.weekday() == 0, f"expected Monday, got {local.strftime('%A')} for {local.isoformat()}"
            assert (local.hour, local.minute) == (18, 0)
            local_end = _local_wall_clock(row.ends_at)
            assert (local_end.hour, local_end.minute) == (19, 0)

    def test_thursdays_6pm_stay_on_thursdays(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        anchor = datetime(2026, 10, 8, 7, 0, 0, tzinfo=timezone.utc)  # Thu 8 Oct 6pm AEDT
        end_utc = anchor.replace(hour=8)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json=_bulk_request(
                starts_at_utc=anchor, ends_at_utc=end_utc,
                days_of_week=[3],  # Python: Thursday
                count=3,
                title="Thursdays",
            ),
        )
        assert r.status_code == 201
        rows = db.query(Event).filter(Event.space_id == space.id).order_by(Event.starts_at).all()
        for row in rows:
            local = _local_wall_clock(row.starts_at)
            assert local.weekday() == 3
            assert (local.hour, local.minute) == (18, 0)

    def test_saturday_morning_stays_on_saturdays(
        self, client_as, make_user, make_space, db,
    ):
        """The critical morning-session case. Sat 9 am AEDT is Fri 22:00
        UTC — the UTC weekday is Friday, not Saturday. The old generator
        used ``.date().weekday()`` on the UTC anchor and got Friday
        instead of Saturday, then mismapped the JS weekday index on top.
        The new generator enumerates in local, so this stays Saturday."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        # Sat 3 Oct 2026 9 am AEDT = Fri 2 Oct 22:00 UTC
        end_utc = AEDT_ANCHOR_SAT_9AM.replace(hour=23)  # Sat 10 am AEDT = 23:00 UTC same UTC day
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json=_bulk_request(
                starts_at_utc=AEDT_ANCHOR_SAT_9AM,
                ends_at_utc=end_utc,
                days_of_week=[5],  # Python: Saturday
                count=4,
                title="Saturdays",
            ),
        )
        assert r.status_code == 201, r.text
        rows = db.query(Event).filter(Event.space_id == space.id).order_by(Event.starts_at).all()
        assert len(rows) == 4
        for row in rows:
            local_start = _local_wall_clock(row.starts_at)
            assert local_start.weekday() == 5, (
                f"expected Saturday, got {local_start.strftime('%A')} for {local_start.isoformat()}"
            )
            assert (local_start.hour, local_start.minute) == (9, 0)
            local_end = _local_wall_clock(row.ends_at)
            assert (local_end.hour, local_end.minute) == (10, 0)


# ---------------------------------------------------------------------------
# 2. DST transitions — the wall-clock time doesn't drift across a boundary
# ---------------------------------------------------------------------------


class TestDaylightSavingTransitions:
    """Australia/Melbourne's DST rules for 2026:
      * Spring-forward: Sunday 4 October 2026 at 02:00 → 03:00 AEDT (+11).
      * Fall-back:      Sunday 5 April 2026 at 03:00 → 02:00 AEST (+10).
    A weekly recurrence that starts BEFORE the boundary must land on the
    same wall-clock time AFTER the boundary. Under a UTC-arithmetic
    generator the wall-clock time drifts by an hour after each transition.
    """

    def test_recurrence_crosses_spring_forward(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        # Anchor: Mon 28 Sep 2026 6 pm Melbourne. Melbourne is AEST +10
        # on that day (DST starts the following Sunday). So 6 pm local =
        # 08:00 UTC.
        anchor = datetime(2026, 9, 28, 8, 0, 0, tzinfo=timezone.utc)
        end_utc = datetime(2026, 9, 28, 9, 0, 0, tzinfo=timezone.utc)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json=_bulk_request(
                starts_at_utc=anchor, ends_at_utc=end_utc,
                days_of_week=[0],  # Monday
                count=4,  # 28 Sep, 5 Oct, 12 Oct, 19 Oct — brackets DST start (4 Oct)
                title="Mondays across DST",
            ),
        )
        assert r.status_code == 201
        rows = db.query(Event).filter(Event.space_id == space.id).order_by(Event.starts_at).all()
        for row in rows:
            local = _local_wall_clock(row.starts_at)
            assert local.weekday() == 0
            # Every occurrence stays at 6 pm Melbourne wall-clock time,
            # even though the underlying UTC hour shifts (08:00 before
            # DST, 07:00 after DST).
            assert local.hour == 18, f"{local.isoformat()} not at 6pm local"
            assert local.minute == 0

    def test_recurrence_crosses_fall_back(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        # Anchor: Mon 30 Mar 2026 6 pm Melbourne. Still AEDT +11 (DST
        # ends Sun 5 Apr). So 6 pm local = 07:00 UTC.
        anchor = datetime(2026, 3, 30, 7, 0, 0, tzinfo=timezone.utc)
        end_utc = datetime(2026, 3, 30, 8, 0, 0, tzinfo=timezone.utc)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json=_bulk_request(
                starts_at_utc=anchor, ends_at_utc=end_utc,
                days_of_week=[0],  # Monday
                count=4,  # 30 Mar, 6 Apr, 13 Apr, 20 Apr — brackets DST end
                title="Mondays across DST end",
            ),
        )
        assert r.status_code == 201
        rows = db.query(Event).filter(Event.space_id == space.id).order_by(Event.starts_at).all()
        for row in rows:
            local = _local_wall_clock(row.starts_at)
            assert local.weekday() == 0
            assert local.hour == 18, f"{local.isoformat()} not at 6pm local"


# ---------------------------------------------------------------------------
# 3. Non-Melbourne collective — timezone comes from Space.timezone
# ---------------------------------------------------------------------------


class TestSpaceTimezone:
    def test_uses_space_timezone_not_a_hardcode(
        self, client_as, make_user, make_space, db,
    ):
        """A collective whose ``space.timezone`` is Pacific/Auckland
        must generate occurrences using NZ wall-clock time, not
        Melbourne."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Pacific/Auckland")
        client = client_as(creator)
        # Mon 5 Oct 2026 6 pm NZDT (+13) = 05:00 UTC
        anchor = datetime(2026, 10, 5, 5, 0, 0, tzinfo=timezone.utc)
        end_utc = datetime(2026, 10, 5, 6, 0, 0, tzinfo=timezone.utc)
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json=_bulk_request(
                starts_at_utc=anchor, ends_at_utc=end_utc,
                days_of_week=[0], count=3, title="NZ Mondays",
            ),
        )
        assert r.status_code == 201
        akl = ZoneInfo("Pacific/Auckland")
        rows = db.query(Event).filter(Event.space_id == space.id).order_by(Event.starts_at).all()
        for row in rows:
            local = row.starts_at.replace(tzinfo=timezone.utc).astimezone(akl)
            assert local.weekday() == 0
            assert local.hour == 18


# ---------------------------------------------------------------------------
# 4. Naive anchor tolerance — the app-wide "naive means UTC" convention
# ---------------------------------------------------------------------------


class TestNaiveAnchorTolerance:
    def test_naive_anchor_is_treated_as_utc(
        self, client_as, make_user, make_space, db,
    ):
        """The frontend always sends an ISO with a Z suffix (from
        ``.toISOString()``), so ``body.starts_at`` is UTC-aware in
        production. Under Pydantic v2 a naive datetime would ALSO
        parse OK; the app's convention is that naive = UTC. This
        test defends the convention explicitly."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, timezone="Australia/Melbourne")
        client = client_as(creator)
        # Naive datetime — no tzinfo. Semantically UTC.
        anchor_naive = "2026-10-05T07:00:00"  # Mon 6 pm AEDT
        end_naive = "2026-10-05T08:00:00"
        r = client.post(
            f"/api/creator/spaces/{space.slug}/events/bulk",
            json={
                "title": "Naive-anchor test",
                "starts_at": anchor_naive,
                "ends_at": end_naive,
                "location_type": "zoom",
                "requires_booking": False,
                "attendance_format": "online",
                "gathering_type": "workshop",
                "booking_access_type": "included_with_collective",
                "recurrence": {
                    "pattern": "weekly",
                    "days_of_week": [0],
                    "end_after_n": 2,
                },
            },
        )
        assert r.status_code == 201
        rows = db.query(Event).filter(Event.space_id == space.id).order_by(Event.starts_at).all()
        for row in rows:
            local = _local_wall_clock(row.starts_at)
            assert local.weekday() == 0
            assert local.hour == 18
