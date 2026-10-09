"""Reserve your regular sessions.

A member with a term pass picks the slots that are theirs — "Mondays at
6", "Thursdays at 6" — and every remaining matching occurrence is
reserved in one action.

Most of this file is about the two ways that could go wrong quietly.

The first is reserving something the member was not entitled to. Bulk
selection must not become an access path: every occurrence goes through
the same gate and allowance rules as booking one session by hand, and
an occurrence the member could not have booked individually has to come
back as unavailable rather than reserved.

The second is the opposite — telling the member "12 sessions reserved"
and quietly dropping three that were full. Nothing here is allowed to
skip silently. Every occurrence the selection matches is accounted for
as reserved, already booked, or unavailable with a reason.

And one thing that is easy to get wrong and invisible when you do:
grouping by weekday has to use the Collective's local clock, or a
weekly 6pm slot splits into two patterns the moment daylight saving
starts and the member is quietly offered half their term.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_regular_sessions.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user, get_verified_current_user
from app.core.database import get_db
from app.main import app
from app.models.access_pass import (
    AccessPass,
    AccessPassSource,
    AccessPassStatus,
    AccessPassType,
)
from app.models.platform import (
    BookingStatus,
    Event,
    EventBooking,
    EventSeries,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import regular_sessions as rs

MELBOURNE = ZoneInfo("Australia/Melbourne")
UTC = ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# Substrate
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_current_user] = lambda: user


def _join(db, user, space, *, role: SpaceRole = SpaceRole.learner):
    db.add(
        SpaceMembership(
            id=_uid("sm"), user_id=user.id, space_id=space.id,
            role=role, status=SpaceMembershipStatus.active,
        )
    )
    db.flush()


def _series(db, space, *, starts_at=None, ends_at=None) -> EventSeries:
    starts = starts_at or datetime.utcnow() - timedelta(days=1)
    s = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title="Tuesday Circle",
        starts_at=starts,
        ends_at=ends_at or starts + timedelta(days=120),
        status="published",
    )
    db.add(s)
    db.flush()
    return s


def local_to_naive_utc(
    year: int, month: int, day: int, hour: int, minute: int = 0,
) -> datetime:
    """A Melbourne wall-clock reading, as the naive UTC the column holds.

    Every ``starts_at`` in this file is built through here. Writing the
    UTC value by hand is how a daylight-saving bug gets baked into the
    test as well as the code.
    """
    local = datetime(year, month, day, hour, minute, tzinfo=MELBOURNE)
    return local.astimezone(UTC).replace(tzinfo=None)


def _occurrence(
    db, space, series, *, starts_at: datetime,
    capacity: int | None = 20,
    duration_hours: int = 1,
    status: str = "active",
    is_published: bool = True,
    requires_booking: bool = True,
    access: str = "included_with_series",
) -> Event:
    e = Event(
        id=_uid("e"),
        space_id=space.id,
        created_by_id=space.creator_id,
        title="Session",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=duration_hours),
        is_published=is_published,
        status=status,
        requires_booking=requires_booking,
        capacity=capacity,
        gathering_type="circle",
        attendance_format="online",
        booking_access_type=access,
        series_id=series.id,
    )
    db.add(e)
    db.flush()
    return e


def _term_pass(
    db, user, space, series, *,
    per_week: int | None = None,
    total: int | None = None,
    used: int = 0,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> AccessPass:
    ap = AccessPass(
        id=_uid("ap"),
        user_id=user.id,
        space_id=space.id,
        eligible_series_id=series.id,
        pass_type=AccessPassType.term_pass,
        status=AccessPassStatus.active,
        source=AccessPassSource.one_time_purchase,
        valid_from=valid_from or datetime.utcnow() - timedelta(days=2),
        valid_until=valid_until or datetime.utcnow() + timedelta(days=200),
        credits_per_week=per_week,
        total_credits=total,
        used_credits=used,
    )
    db.add(ap)
    db.flush()
    return ap


def _confirmed(db, event, user) -> EventBooking:
    b = EventBooking(
        id=_uid("eb"), event_id=event.id, user_id=user.id,
        status=BookingStatus.confirmed, booked_at=datetime.utcnow(),
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def world(db, make_user, make_space):
    """A published Series in a Melbourne Collective, with a member."""
    space = make_space(timezone="Australia/Melbourne")
    member = make_user()
    _join(db, member, space)
    series = _series(db, space)
    return {"space": space, "member": member, "series": series}


def base_url(space, series) -> str:
    return (
        f"/api/spaces/{space.slug}/gathering-series/{series.slug}"
        f"/regular-sessions"
    )


# ---------------------------------------------------------------------------
# Grouping: the Collective's clock, and daylight saving
# ---------------------------------------------------------------------------


class TestScheduleGrouping:
    def test_weekly_slot_is_one_pattern_across_a_dst_change(self, db, world):
        # Melbourne moves to UTC+11 on the first Sunday of October
        # 2026 (4 October). A 6pm Monday circle is 07:00Z before the
        # change and 07:00… no: 08:00Z before, 07:00Z after. The
        # member thinks "Mondays at 6" either way, and that is what
        # has to come back.
        space, series = world["space"], world["series"]
        before = local_to_naive_utc(2026, 9, 28, 18)   # Mon, AEST
        after = local_to_naive_utc(2026, 10, 5, 18)    # Mon, AEDT
        assert before.hour != after.hour, "no DST shift in the fixture dates"

        for starts in (before, after):
            _occurrence(db, space, series, starts_at=starts)

        patterns, _ = rs.build_patterns(
            rs.remaining_occurrences(
                db, series, space, datetime(2026, 9, 1),
            ),
            "Australia/Melbourne",
        )
        assert len(patterns) == 1, [p.label for p in patterns]
        assert patterns[0].label == "Mondays — 6:00–7:00 pm"
        assert len(patterns[0].occurrences) == 2

    def test_grouping_on_stored_utc_would_have_split_it(self, db, world):
        # The counter-test, so the one above cannot pass for the wrong
        # reason. Grouped by the raw stored value these are two slots;
        # grouped by local clock they are one.
        space, series = world["space"], world["series"]
        before = local_to_naive_utc(2026, 9, 28, 18)
        after = local_to_naive_utc(2026, 10, 5, 18)
        naive_keys = {
            (d.weekday(), d.strftime("%H:%M")) for d in (before, after)
        }
        assert len(naive_keys) == 2

    def test_two_times_on_one_day_are_two_distinguishable_patterns(self, db, world):
        space, series = world["space"], world["series"]
        _occurrence(db, space, series, starts_at=local_to_naive_utc(2026, 11, 2, 10))
        _occurrence(db, space, series, starts_at=local_to_naive_utc(2026, 11, 2, 18))

        patterns, _ = rs.build_patterns(
            rs.remaining_occurrences(db, series, space, datetime(2026, 10, 1)),
            "Australia/Melbourne",
        )
        assert len(patterns) == 2
        assert [p.label for p in patterns] == [
            "Mondays — 10:00–11:00 am",
            "Mondays — 6:00–7:00 pm",
        ]
        assert all(p.shares_weekday for p in patterns)

    def test_a_single_slot_on_a_day_does_not_claim_to_share_it(self, db, world):
        space, series = world["space"], world["series"]
        _occurrence(db, space, series, starts_at=local_to_naive_utc(2026, 11, 2, 18))
        patterns, _ = rs.build_patterns(
            rs.remaining_occurrences(db, series, space, datetime(2026, 10, 1)),
            "Australia/Melbourne",
        )
        assert patterns[0].shares_weekday is False

    def test_a_range_crossing_midday_names_both_halves(self):
        start = datetime(2026, 11, 2, 11, 30, tzinfo=MELBOURNE)
        end = datetime(2026, 11, 2, 13, 0, tzinfo=MELBOURNE)
        assert rs.format_time_range(start, end) == "11:30 am–1:00 pm"

    def test_an_occurrence_with_no_end_time_still_groups(self, db, world):
        space, series = world["space"], world["series"]
        event = _occurrence(
            db, space, series, starts_at=local_to_naive_utc(2026, 11, 2, 18),
        )
        event.ends_at = None
        db.flush()
        patterns, _ = rs.build_patterns([event], "Australia/Melbourne")
        assert patterns[0].label == "Mondays — 6:00 pm"

    def test_an_unknown_timezone_falls_back_rather_than_raising(self, db, make_space):
        space = make_space(timezone="Mars/Olympus_Mons")
        assert rs.series_timezone(space) == rs.FALLBACK_TIMEZONE


# ---------------------------------------------------------------------------
# Which occurrences are even offered
# ---------------------------------------------------------------------------


class TestRemainingOccurrencesOnly:
    @pytest.fixture
    def seeded(self, db, world):
        space, series = world["space"], world["series"]
        now = datetime.utcnow()
        kept = _occurrence(db, space, series, starts_at=now + timedelta(days=7))
        excluded = {
            "past": _occurrence(db, space, series, starts_at=now - timedelta(days=7)),
            "cancelled": _occurrence(
                db, space, series, starts_at=now + timedelta(days=8),
                status="cancelled",
            ),
            "archived": _occurrence(
                db, space, series, starts_at=now + timedelta(days=9),
                status="archived",
            ),
            "unpublished": _occurrence(
                db, space, series, starts_at=now + timedelta(days=10),
                is_published=False,
            ),
            "no_booking_needed": _occurrence(
                db, space, series, starts_at=now + timedelta(days=11),
                requires_booking=False,
            ),
        }
        return {"kept": kept, "excluded": excluded, **world}

    def test_only_the_remaining_bookable_occurrence_is_offered(self, db, seeded):
        found = rs.remaining_occurrences(
            db, seeded["series"], seeded["space"], datetime.utcnow(),
        )
        assert [e.id for e in found] == [seeded["kept"].id]

    @pytest.mark.parametrize(
        "which", ["past", "cancelled", "archived", "unpublished", "no_booking_needed"],
    )
    def test_each_exclusion_holds(self, db, seeded, which):
        found = {
            e.id
            for e in rs.remaining_occurrences(
                db, seeded["series"], seeded["space"], datetime.utcnow(),
            )
        }
        assert seeded["excluded"][which].id not in found

    def test_another_series_in_the_same_collective_is_not_included(self, db, world):
        space = world["space"]
        other = _series(db, space)
        _occurrence(
            db, space, other, starts_at=datetime.utcnow() + timedelta(days=3),
        )
        found = rs.remaining_occurrences(
            db, world["series"], space, datetime.utcnow(),
        )
        assert found == []


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


class TestAccess:
    def test_a_member_without_a_pass_reserves_nothing(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _occurrence(db, space, series, starts_at=local_to_naive_utc(2027, 3, 1, 18))
        as_user(member)

        patterns = client.get(base_url(space, series)).json()["patterns"]
        key = patterns[0]["key"]

        preview = client.post(
            f"{base_url(space, series)}/preview",
            json={"pattern_keys": [key]},
        ).json()
        assert preview["new_reservation_count"] == 0
        assert len(preview["unavailable"]) == 1
        assert preview["unavailable"][0]["reason"] == "series_pass_required"

        result = client.post(
            f"{base_url(space, series)}/reserve",
            json={"pattern_keys": [key]},
        ).json()
        assert result["reserved_count"] == 0
        assert (
            db.query(EventBooking).filter(EventBooking.user_id == member.id).count()
            == 0
        )

    def test_a_pass_holder_reserves_every_remaining_match(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        for week in range(4):
            _occurrence(
                db, space, series,
                starts_at=local_to_naive_utc(2027, 3, 1 + 7 * week, 18),
            )
        as_user(member)

        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        result = client.post(
            f"{base_url(space, series)}/reserve",
            json={"pattern_keys": [key]},
        ).json()

        assert result["reserved_count"] == 4
        assert result["unavailable"] == []
        confirmed = (
            db.query(EventBooking)
            .filter(
                EventBooking.user_id == member.id,
                EventBooking.status == BookingStatus.confirmed,
            )
            .count()
        )
        assert confirmed == 4

    def test_reserving_charges_the_pass_and_grants_nothing_extra(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        term_pass = _term_pass(db, member, space, series, total=10)
        for week in range(3):
            _occurrence(
                db, space, series,
                starts_at=local_to_naive_utc(2027, 3, 1 + 7 * week, 18),
            )
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        client.post(
            f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]},
        )
        db.refresh(term_pass)
        # Exactly the sessions reserved, and no new entitlement.
        assert term_pass.used_credits == 3
        assert term_pass.total_credits == 10
        assert (
            db.query(AccessPass).filter(AccessPass.user_id == member.id).count() == 1
        )

    def test_a_pass_window_that_does_not_cover_a_date_blocks_that_date(
        self, db, client, world,
    ):
        space, series, member = world["space"], world["series"], world["member"]
        inside = local_to_naive_utc(2027, 3, 1, 18)
        outside = local_to_naive_utc(2027, 6, 7, 18)
        _term_pass(db, member, space, series, valid_until=inside + timedelta(days=1))
        _occurrence(db, space, series, starts_at=inside)
        _occurrence(db, space, series, starts_at=outside)
        as_user(member)

        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        preview = client.post(
            f"{base_url(space, series)}/preview", json={"pattern_keys": [key]},
        ).json()
        assert preview["new_reservation_count"] == 1
        assert [u["reason"] for u in preview["unavailable"]] == [
            "series_pass_required"
        ]

    def test_a_session_before_the_pass_window_opens_is_blocked(
        self, db, client, world,
    ):
        # The mirror of the case above, and a real one: a member who
        # buys next term in advance holds a pass whose window starts
        # later. Sessions in this Series that fall before it opens are
        # not theirs to reserve, even though the pass is active today.
        space, series, member = world["space"], world["series"], world["member"]
        early = local_to_naive_utc(2027, 3, 1, 18)
        covered = local_to_naive_utc(2027, 5, 3, 18)
        _term_pass(
            db, member, space, series,
            valid_from=covered - timedelta(days=1),
            valid_until=covered + timedelta(days=60),
        )
        _occurrence(db, space, series, starts_at=early)
        _occurrence(db, space, series, starts_at=covered)
        as_user(member)

        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        preview = client.post(
            f"{base_url(space, series)}/preview", json={"pattern_keys": [key]},
        ).json()

        assert preview["new_reservation_count"] == 1
        assert [o["event_id"] for o in preview["will_reserve"]] != []
        assert [u["reason"] for u in preview["unavailable"]] == [
            "series_pass_required"
        ]
        # And specifically the early one, not whichever came first.
        assert preview["unavailable"][0]["starts_at"].startswith("2027-03")

    def test_a_free_series_session_needs_no_pass(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _occurrence(
            db, space, series,
            starts_at=local_to_naive_utc(2027, 3, 1, 18),
            access="included_with_collective",
        )
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        result = client.post(
            f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]},
        ).json()
        assert result["reserved_count"] == 1

    def test_a_non_member_is_refused_per_occurrence(self, db, client, world, make_user):
        space, series = world["space"], world["series"]
        outsider = make_user()
        _term_pass(db, outsider, space, series)
        _occurrence(db, space, series, starts_at=local_to_naive_utc(2027, 3, 1, 18))
        as_user(outsider)

        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        result = client.post(
            f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]},
        ).json()
        assert result["reserved_count"] == 0
        assert result["unavailable"][0]["reason"] == "membership_required"

    def test_an_unknown_series_is_a_404(self, client, world):
        as_user(world["member"])
        res = client.get(
            f"/api/spaces/{world['space'].slug}/gathering-series/nope/regular-sessions"
        )
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# Mixed availability — nothing is skipped silently
# ---------------------------------------------------------------------------


class TestMixedAvailability:
    def test_a_full_date_is_reported_and_the_rest_reserved(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        full = _occurrence(
            db, space, series,
            starts_at=local_to_naive_utc(2027, 3, 1, 18), capacity=1,
        )
        _occurrence(db, space, series, starts_at=local_to_naive_utc(2027, 3, 8, 18))
        _occurrence(db, space, series, starts_at=local_to_naive_utc(2027, 3, 15, 18))

        someone_else = db.query(type(member)).filter(
            type(member).id != member.id,
        ).first()
        _confirmed(db, full, someone_else)

        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]

        preview = client.post(
            f"{base_url(space, series)}/preview", json={"pattern_keys": [key]},
        ).json()
        assert preview["new_reservation_count"] == 2
        assert len(preview["unavailable"]) == 1
        assert preview["unavailable"][0]["reason"] == "full"
        assert preview["unavailable"][0]["event_id"] == full.id

        result = client.post(
            f"{base_url(space, series)}/reserve",
            json={
                "pattern_keys": [key],
                "expected_event_ids": [
                    o["event_id"] for o in preview["will_reserve"]
                ],
            },
        ).json()
        assert result["reserved_count"] == 2
        assert [u["reason"] for u in result["unavailable"]] == ["full"]
        assert result["changed_since_preview"] == []

    def test_every_matched_occurrence_is_accounted_for(self, db, client, world):
        # The anti-silent-skip invariant: reserved + already booked +
        # unavailable must equal everything the selection matched.
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        dates = [local_to_naive_utc(2027, 3, 1 + 7 * w, 18) for w in range(5)]
        events = [_occurrence(db, space, series, starts_at=d) for d in dates]
        events[0].capacity = 1
        db.flush()
        someone_else = db.query(type(member)).filter(
            type(member).id != member.id,
        ).first()
        _confirmed(db, events[0], someone_else)
        _confirmed(db, events[1], member)

        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        preview = client.post(
            f"{base_url(space, series)}/preview", json={"pattern_keys": [key]},
        ).json()

        accounted = (
            len(preview["will_reserve"])
            + len(preview["already_booked"])
            + len(preview["unavailable"])
        )
        assert accounted == len(events)
        assert len(preview["already_booked"]) == 1
        assert len(preview["unavailable"]) == 1
        assert preview["new_reservation_count"] == 3

    def test_an_unavailable_date_carries_a_human_message(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        event = _occurrence(
            db, space, series,
            starts_at=local_to_naive_utc(2027, 3, 1, 18), capacity=1,
        )
        someone_else = db.query(type(member)).filter(
            type(member).id != member.id,
        ).first()
        _confirmed(db, event, someone_else)
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        preview = client.post(
            f"{base_url(space, series)}/preview", json={"pattern_keys": [key]},
        ).json()
        assert preview["unavailable"][0]["message"]
        assert preview["unavailable"][0]["starts_at"]


# ---------------------------------------------------------------------------
# Allowance, including in-flight consumption
# ---------------------------------------------------------------------------


class TestAllowance:
    def test_two_slots_in_one_week_respect_a_one_per_week_pass(self, db, client, world):
        # The case the single-booking path never had to think about:
        # both decisions happen before either is committed, so the
        # second has to see the first.
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series, per_week=1)
        monday = local_to_naive_utc(2027, 3, 1, 18)
        thursday = local_to_naive_utc(2027, 3, 4, 18)
        _occurrence(db, space, series, starts_at=monday)
        _occurrence(db, space, series, starts_at=thursday)
        as_user(member)

        keys = [p["key"] for p in client.get(base_url(space, series)).json()["patterns"]]
        assert len(keys) == 2
        preview = client.post(
            f"{base_url(space, series)}/preview", json={"pattern_keys": keys},
        ).json()

        assert preview["new_reservation_count"] == 1
        assert [u["reason"] for u in preview["unavailable"]] == [
            "weekly_limit_reached"
        ]

    def test_the_same_weekday_across_weeks_is_not_a_weekly_breach(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series, per_week=1)
        for week in range(4):
            _occurrence(
                db, space, series,
                starts_at=local_to_naive_utc(2027, 3, 1 + 7 * week, 18),
            )
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        result = client.post(
            f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]},
        ).json()
        assert result["reserved_count"] == 4

    def test_a_total_allowance_stops_the_overflow_and_names_it(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series, total=2)
        for week in range(4):
            _occurrence(
                db, space, series,
                starts_at=local_to_naive_utc(2027, 3, 1 + 7 * week, 18),
            )
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        result = client.post(
            f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]},
        ).json()

        assert result["reserved_count"] == 2
        assert [u["reason"] for u in result["unavailable"]] == [
            "no_remaining_sessions", "no_remaining_sessions",
        ]

    def test_credits_already_spent_elsewhere_are_counted(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series, total=3, used=2)
        for week in range(3):
            _occurrence(
                db, space, series,
                starts_at=local_to_naive_utc(2027, 3, 1 + 7 * week, 18),
            )
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        result = client.post(
            f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]},
        ).json()
        assert result["reserved_count"] == 1


# ---------------------------------------------------------------------------
# Duplicates, repeats and retries
# ---------------------------------------------------------------------------


class TestNoDuplicates:
    def test_reserving_twice_changes_nothing_the_second_time(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        for week in range(3):
            _occurrence(
                db, space, series,
                starts_at=local_to_naive_utc(2027, 3, 1 + 7 * week, 18),
            )
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]

        first = client.post(
            f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]},
        ).json()
        second = client.post(
            f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]},
        ).json()

        assert first["reserved_count"] == 3
        assert second["reserved_count"] == 0
        assert len(second["already_booked"]) == 3
        assert db.query(EventBooking).filter(
            EventBooking.user_id == member.id,
        ).count() == 3

    def test_a_repeat_does_not_charge_the_pass_again(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        term_pass = _term_pass(db, member, space, series, total=10)
        _occurrence(db, space, series, starts_at=local_to_naive_utc(2027, 3, 1, 18))
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        client.post(f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]})
        client.post(f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]})
        db.refresh(term_pass)
        assert term_pass.used_credits == 1

    def test_an_already_booked_session_is_reported_not_duplicated(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        event = _occurrence(
            db, space, series, starts_at=local_to_naive_utc(2027, 3, 1, 18),
        )
        _confirmed(db, event, member)
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        result = client.post(
            f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]},
        ).json()
        assert result["reserved_count"] == 0
        assert len(result["already_booked"]) == 1
        assert db.query(EventBooking).filter(
            EventBooking.event_id == event.id,
        ).count() == 1

    def test_a_cancelled_booking_is_reactivated_rather_than_duplicated(
        self, db, client, world,
    ):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        event = _occurrence(
            db, space, series, starts_at=local_to_naive_utc(2027, 3, 1, 18),
        )
        booking = _confirmed(db, event, member)
        booking.status = BookingStatus.cancelled
        booking.cancelled_at = datetime.utcnow()
        db.flush()

        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        result = client.post(
            f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]},
        ).json()

        assert result["reserved_count"] == 1
        rows = db.query(EventBooking).filter(EventBooking.event_id == event.id).all()
        assert len(rows) == 1
        assert rows[0].status == BookingStatus.confirmed
        assert rows[0].cancelled_at is None

    def test_an_empty_selection_is_refused(self, client, world):
        as_user(world["member"])
        res = client.post(
            f"{base_url(world['space'], world['series'])}/reserve",
            json={"pattern_keys": []},
        )
        assert res.status_code == 400

    def test_an_unknown_pattern_key_reserves_nothing(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        _occurrence(db, space, series, starts_at=local_to_naive_utc(2027, 3, 1, 18))
        as_user(member)
        result = client.post(
            f"{base_url(space, series)}/reserve",
            json={"pattern_keys": ["6-23:59-"]},
        ).json()
        assert result["reserved_count"] == 0
        assert db.query(EventBooking).count() == 0


# ---------------------------------------------------------------------------
# The world changing between preview and confirmation
# ---------------------------------------------------------------------------


class TestChangedSincePreview:
    def test_a_session_cancelled_after_the_preview_is_named(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        keep = _occurrence(
            db, space, series, starts_at=local_to_naive_utc(2027, 3, 1, 18),
        )
        doomed = _occurrence(
            db, space, series, starts_at=local_to_naive_utc(2027, 3, 8, 18),
        )
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        preview = client.post(
            f"{base_url(space, series)}/preview", json={"pattern_keys": [key]},
        ).json()
        expected = [o["event_id"] for o in preview["will_reserve"]]
        assert set(expected) == {keep.id, doomed.id}

        # The Creator cancels it while the member is reading.
        doomed.status = "cancelled"
        db.flush()

        result = client.post(
            f"{base_url(space, series)}/reserve",
            json={"pattern_keys": [key], "expected_event_ids": expected},
        ).json()

        assert result["reserved_count"] == 1
        assert [o["event_id"] for o in result["reserved"]] == [keep.id]
        assert len(result["changed_since_preview"]) == 1
        assert result["changed_since_preview"][0]["event_id"] == doomed.id

    def test_a_seat_taken_after_the_preview_is_named(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        contested = _occurrence(
            db, space, series,
            starts_at=local_to_naive_utc(2027, 3, 1, 18), capacity=1,
        )
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        preview = client.post(
            f"{base_url(space, series)}/preview", json={"pattern_keys": [key]},
        ).json()
        assert preview["new_reservation_count"] == 1

        someone_else = db.query(type(member)).filter(
            type(member).id != member.id,
        ).first()
        _confirmed(db, contested, someone_else)

        result = client.post(
            f"{base_url(space, series)}/reserve",
            json={
                "pattern_keys": [key],
                "expected_event_ids": [contested.id],
            },
        ).json()
        assert result["reserved_count"] == 0
        assert result["changed_since_preview"][0]["reason"] == "full"


# ---------------------------------------------------------------------------
# Capacity under concurrency
# ---------------------------------------------------------------------------


class TestConcurrentCapacity:
    def test_the_last_seat_is_taken_under_a_row_lock(self, db, world, make_user):
        # Two members, one seat, two sessions evaluated in the same
        # transaction order. The lock is what makes the second see the
        # first — asserted here through the service rather than through
        # two live connections, which the per-test SAVEPOINT harness
        # cannot give us.
        space, series = world["space"], world["series"]
        first, second = world["member"], make_user()
        _join(db, second, space)
        _term_pass(db, first, space, series)
        _term_pass(db, second, space, series)
        event = _occurrence(
            db, space, series,
            starts_at=local_to_naive_utc(2027, 3, 1, 18), capacity=1,
        )
        key = rs.pattern_key_for(
            rs.to_local(event.starts_at, MELBOURNE),
            rs.to_local(event.ends_at, MELBOURNE),
        )

        one = rs.commit_reservations(
            db, user=first, space=space, series=series,
            pattern_keys=[key], now=datetime.utcnow(),
        )
        two = rs.commit_reservations(
            db, user=second, space=space, series=series,
            pattern_keys=[key], now=datetime.utcnow(),
        )

        assert one.reserved_count == 1
        assert two.reserved_count == 0
        assert [u.reason for u in two.unavailable] == ["full"]
        assert db.query(EventBooking).filter(
            EventBooking.event_id == event.id,
            EventBooking.status == BookingStatus.confirmed,
        ).count() == 1

    def test_the_confirmation_locks_the_rows_and_the_preview_does_not(
        self, db, world,
    ):
        # Asserted against the SQL actually executed, not against the
        # outcome. Two sequential calls in one transaction reach the
        # right answer with or without a lock — only a second
        # connection would feel the difference, and the per-test
        # SAVEPOINT harness cannot give us one. So the mechanism is
        # checked directly: without ``FOR UPDATE`` two live requests
        # would both count the same confirmed total and both insert.
        #
        # And the preview must NOT lock: it runs while a member reads a
        # page, and holding row locks for that long is its own bug.
        from sqlalchemy import event as sa_event

        space, series = world["space"], world["series"]
        _occurrence(db, space, series, starts_at=local_to_naive_utc(2027, 3, 1, 18))

        seen: list[str] = []

        def record(conn, cursor, statement, params, context, executemany):
            seen.append(statement)

        engine = db.get_bind()
        sa_event.listen(engine, "before_cursor_execute", record)
        try:
            seen.clear()
            rs.remaining_occurrences(
                db, series, space, datetime.utcnow(), lock=True,
            )
            locking = [q for q in seen if "FOR UPDATE" in q.upper()]
            assert locking, f"the confirmation did not lock: {seen}"
            assert any("events" in q.lower() for q in locking)

            seen.clear()
            rs.remaining_occurrences(db, series, space, datetime.utcnow())
            assert not [
                q for q in seen if "FOR UPDATE" in q.upper()
            ], "the preview took a row lock"
        finally:
            sa_event.remove(engine, "before_cursor_execute", record)


# ---------------------------------------------------------------------------
# Cancelling one reservation
# ---------------------------------------------------------------------------


class TestIndividualCancellation:
    def test_cancelling_one_session_leaves_the_others(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        events = [
            _occurrence(
                db, space, series,
                starts_at=local_to_naive_utc(2027, 3, 1 + 7 * w, 18),
            )
            for w in range(3)
        ]
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        client.post(f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]})

        res = client.post(
            f"/api/spaces/{space.slug}/events/{events[1].id}/cancel-booking"
        )
        assert res.status_code == 200

        statuses = {
            b.event_id: b.status
            for b in db.query(EventBooking).filter(
                EventBooking.user_id == member.id,
            ).all()
        }
        assert statuses[events[0].id] == BookingStatus.confirmed
        assert statuses[events[1].id] == BookingStatus.cancelled
        assert statuses[events[2].id] == BookingStatus.confirmed

    def test_cancelling_a_reservation_returns_exactly_one_credit(
        self, db, client, world,
    ):
        # The pass is charged once per reserved session, so cancelling
        # one has to give back one — not none, and not the lot. The
        # cancel endpoint reads ``booking.credits_used`` to know how
        # much to restore, so a bulk reservation that sets the pass
        # link but leaves that field at zero takes the credit
        # permanently. Nothing about the reservation looks wrong when
        # that happens: the member simply runs out of sessions early.
        space, series, member = world["space"], world["series"], world["member"]
        term = _term_pass(db, member, space, series)
        events = [
            _occurrence(
                db, space, series,
                starts_at=local_to_naive_utc(2027, 3, 1 + 7 * w, 18),
            )
            for w in range(3)
        ]
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        client.post(f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]})
        db.refresh(term)
        assert term.used_credits == 3

        res = client.post(
            f"/api/spaces/{space.slug}/events/{events[1].id}/cancel-booking"
        )
        assert res.status_code == 200

        db.refresh(term)
        assert term.used_credits == 2

        # And the sessions either side keep their own charge intact —
        # cancelling one reservation must not disturb the accounting of
        # the others it was created alongside.
        survivors = (
            db.query(EventBooking)
            .filter(
                EventBooking.user_id == member.id,
                EventBooking.status == BookingStatus.confirmed,
            )
            .all()
        )
        assert len(survivors) == 2
        assert all(b.access_pass_id == term.id for b in survivors)
        assert all(b.credits_used == 1 for b in survivors)

    def test_cancelling_inside_the_24_hour_window_returns_nothing(
        self, db, client, world,
    ):
        # The restoration cut-off that already governs a single booking.
        # Bulk-reserved sessions are ordinary bookings, so it has to
        # reach them unchanged rather than becoming a way to cancel late
        # without cost.
        space, series, member = world["space"], world["series"], world["member"]
        term = _term_pass(db, member, space, series)
        soon = _occurrence(
            db, space, series,
            starts_at=datetime.utcnow() + timedelta(hours=12),
        )
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        client.post(f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]})
        db.refresh(term)
        assert term.used_credits == 1

        res = client.post(
            f"/api/spaces/{space.slug}/events/{soon.id}/cancel-booking"
        )
        assert res.status_code == 200

        db.refresh(term)
        assert term.used_credits == 1

    def test_the_reservations_are_ordinary_bookings(self, db, client, world):
        # Nothing marks them as special, which is the point: attendance,
        # capacity counting and booking management all keep working
        # because there is nothing new for them to know about.
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        event = _occurrence(
            db, space, series, starts_at=local_to_naive_utc(2027, 3, 1, 18),
        )
        as_user(member)
        key = client.get(base_url(space, series)).json()["patterns"][0]["key"]
        client.post(f"{base_url(space, series)}/reserve", json={"pattern_keys": [key]})

        booking = db.query(EventBooking).filter(
            EventBooking.event_id == event.id,
        ).one()
        assert booking.status == BookingStatus.confirmed
        assert booking.attendance_status is None
        assert booking.hold_expires_at is None
        assert booking.payment_transaction_id is None


# ---------------------------------------------------------------------------
# The listing endpoint
# ---------------------------------------------------------------------------


class TestPatternListing:
    def test_it_reports_counts_and_the_collective_timezone(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _term_pass(db, member, space, series)
        events = [
            _occurrence(
                db, space, series,
                starts_at=local_to_naive_utc(2027, 3, 1 + 7 * w, 18),
            )
            for w in range(3)
        ]
        _confirmed(db, events[0], member)
        as_user(member)

        body = client.get(base_url(space, series)).json()
        assert body["timezone"] == "Australia/Melbourne"
        assert body["remaining_occurrence_count"] == 3
        pattern = body["patterns"][0]
        assert pattern["occurrence_count"] == 3
        assert pattern["already_booked_count"] == 1
        assert pattern["label"] == "Mondays — 6:00–7:00 pm"
        assert pattern["first_starts_at"] < pattern["last_starts_at"]

    def test_a_series_with_nothing_ahead_offers_no_patterns(self, db, client, world):
        space, series, member = world["space"], world["series"], world["member"]
        _occurrence(
            db, space, series,
            starts_at=datetime.utcnow() - timedelta(days=3),
        )
        as_user(member)
        body = client.get(base_url(space, series)).json()
        assert body["patterns"] == []
        assert body["remaining_occurrence_count"] == 0
