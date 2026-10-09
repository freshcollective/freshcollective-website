"""Two requests, one place, one allowance.

Every other booking test in this repository runs inside the shared
``db`` fixture, which is a single connection wrapped in a savepoint.
That is the right default — nothing escapes a test — but it cannot
express the question this file exists to ask. A row lock is invisible
to the only transaction that holds it. To find out whether capacity and
pass allowances actually hold, two transactions have to want the same
thing at the same time.

So these tests commit their fixtures on their own connection, run the
real booking paths in parallel threads on separate connections, and
assert on what the database ends up holding. They clean up after
themselves.

Two distinct resources are contended, and they need different locks:

* **A place** is a property of the occurrence. Two members racing for
  the last seat contend on the ``events`` row.
* **An allowance** is a property of the *pass*. One member booking two
  different Mondays contends on nothing at all unless the pass row is
  locked — two different occurrences, two different locks, both
  decisions seeing an empty weekly count. That one is not theoretical:
  it is what a double-click on two schedule cards does.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_booking_concurrency.py
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

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
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services import regular_sessions as rs

# The full model registry. Opening a second set of sessions outside the
# shared ``db`` fixture means SQLAlchemy has to resolve every foreign
# key it can see, and ``access_passes.payment_transaction_id`` points
# at a table no other import in this module pulls in.
import app.models.payment  # noqa: F401
import app.models.purchase_plan  # noqa: F401
import app.models.payment_option  # noqa: F401

#: A thread that has not finished in this long is a lock we got wrong,
#: not a slow machine. Failing beats hanging the suite.
JOIN_TIMEOUT_SECONDS = 30


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Fixture:
    """Ids of committed rows, plus the engine to open sessions on."""

    def __init__(self, engine, **ids):
        self.engine = engine
        self.__dict__.update(ids)

    def session(self):
        return sessionmaker(bind=self.engine, future=True, expire_on_commit=False)()


def _build(
    engine, *, starts, capacity, per_week=None, total=None, members=1,
    passes=True,
):
    """Commit a Collective, a Series, occurrences and passes.

    Committed deliberately: another connection has to be able to see
    them, which is the whole point of this file.
    """
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = Session()
    creator = User(
        id=_uid("u"), email=f"c-{uuid.uuid4().hex[:8]}@example.test",
        name="Creator", role="creator",
        password_hash="$2b$12$0" + "0" * 52,
        email_verified_at=datetime.utcnow(),
    )
    s.add(creator)
    s.flush()
    space = Space(
        id=_uid("s"), slug=f"conc-{uuid.uuid4().hex[:8]}", name="Concurrency",
        status="active", creator_id=creator.id, timezone="Australia/Melbourne",
    )
    s.add(space)
    s.flush()
    # A real Collective's creator holds an active creator membership.
    # Without it this fixture builds a Space that
    # ``test_space_creator_consistency`` is right to call broken — and
    # if a teardown ever misses, that is the test that pays for it.
    s.add(SpaceMembership(
        id=_uid("sm"), user_id=creator.id, space_id=space.id,
        role=SpaceRole.creator, status=SpaceMembershipStatus.active,
    ))
    s.flush()
    series = EventSeries(
        id=_uid("es"), space_id=space.id, slug=f"es-{uuid.uuid4().hex[:8]}",
        title="Circle", starts_at=datetime.utcnow() - timedelta(days=1),
        ends_at=datetime.utcnow() + timedelta(days=200), status="published",
    )
    s.add(series)
    # Flushed in stages. There is no mapper relationship from
    # ``access_passes`` to ``event_series``, so the unit of work has no
    # reason to insert the Series first and will happily violate the
    # foreign key.
    s.flush()

    users = []
    for n in range(members):
        u = User(
            id=_uid("u"), email=f"m{n}-{uuid.uuid4().hex[:8]}@example.test",
            name=f"Member {n}", role="user",
            password_hash="$2b$12$0" + "0" * 52,
            email_verified_at=datetime.utcnow(),
        )
        s.add(u)
        s.flush()
        s.add(SpaceMembership(
            id=_uid("sm"), user_id=u.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        ))
        s.flush()
        if passes:
            s.add(AccessPass(
                id=_uid("ap"), user_id=u.id, space_id=space.id,
                eligible_series_id=series.id,
                pass_type=AccessPassType.term_pass,
                status=AccessPassStatus.active,
                source=AccessPassSource.one_time_purchase,
                valid_from=datetime.utcnow() - timedelta(days=2),
                valid_until=datetime.utcnow() + timedelta(days=200),
                credits_per_week=per_week, total_credits=total, used_credits=0,
            ))
        users.append(u)
        s.flush()

    events = []
    for when in starts:
        e = Event(
            id=_uid("e"), space_id=space.id, created_by_id=creator.id,
            title="Session", starts_at=when, ends_at=when + timedelta(hours=1),
            is_published=True, status="active", requires_booking=True,
            capacity=capacity, gathering_type="circle",
            attendance_format="online",
            booking_access_type="included_with_series", series_id=series.id,
        )
        s.add(e)
        events.append(e)

    s.commit()
    fixture = Fixture(
        engine,
        space_id=space.id, space_slug=space.slug, series_id=series.id,
        creator_id=creator.id,
        user_ids=[u.id for u in users],
        event_ids=[e.id for e in events],
    )
    s.close()
    return fixture


def _teardown(engine, fixture):
    """Remove everything the fixture committed.

    Each statement runs in its own transaction. A booking confirmation
    emits communication rows, and which of those tables exist — and
    which reference what — is not this file's business; one failed
    DELETE must not abort the transaction that still has a Space to
    remove.
    """
    def run(sql: str, params: dict) -> None:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql), params)
        except Exception:
            # Best effort, like the emit that created the rows.
            pass

    run(
        "DELETE FROM event_bookings WHERE event_id = ANY(:ids)",
        {"ids": fixture.event_ids},
    )
    # A reservation emits one summary confirmation, and several tests
    # elsewhere count communication events across the whole database
    # ("no events, no rows"). Leaving these behind surfaced as five
    # unrelated failures in two other files, which is a far worse
    # failure mode than an untidy test.
    #
    # ``actor_user_id`` is the only user column on
    # ``communication_events``; the subject is the untyped
    # ``subject_id``. Both are matched.
    # Deliveries hang off intents, intents off events — deleted in that
    # order, with the real column names (``intent_id`` and ``event_id``,
    # not ``communication_event_id``; checked rather than guessed, after
    # the first version silently deleted nothing).
    run(
        "DELETE FROM communication_deliveries WHERE intent_id IN "
        "(SELECT i.id FROM communication_intents i "
        " JOIN communication_events e ON i.event_id = e.id "
        " WHERE e.actor_user_id = ANY(:ids) OR e.subject_id = ANY(:ids))",
        {"ids": fixture.user_ids},
    )
    run(
        "DELETE FROM communication_intents WHERE event_id IN "
        "(SELECT id FROM communication_events "
        " WHERE actor_user_id = ANY(:ids) OR subject_id = ANY(:ids))",
        {"ids": fixture.user_ids},
    )
    run(
        "DELETE FROM communication_events "
        "WHERE actor_user_id = ANY(:ids) OR subject_id = ANY(:ids)",
        {"ids": fixture.user_ids},
    )
    run("DELETE FROM spaces WHERE id = :sid", {"sid": fixture.space_id})
    run(
        "DELETE FROM users WHERE id = ANY(:ids)",
        {"ids": [*fixture.user_ids, fixture.creator_id]},
    )


@pytest.fixture
def committed(engine):
    """Factory for committed fixtures, torn down after the test.

    Takes the suite's session-scoped engine — the one whose schema the
    conftest has already migrated — rather than building a second one.
    Each thread opens its own session on it, which is its own
    connection, which is what makes the locks real.
    """
    built: list[Fixture] = []

    def _factory(**kwargs):
        f = _build(engine, **kwargs)
        built.append(f)
        return f

    try:
        yield _factory
    finally:
        for f in built:
            _teardown(engine, f)
        # Verified, not assumed. These fixtures commit, so a teardown
        # that quietly fails leaves rows in a database the whole suite
        # shares — which is exactly what happened while this file was
        # being written, and it surfaced as seven unrelated failures in
        # ``test_space_creator_consistency`` two files later.
        with engine.begin() as conn:
            for f in built:
                remaining = conn.execute(
                    text("SELECT count(*) FROM spaces WHERE id = :sid"),
                    {"sid": f.space_id},
                ).scalar_one()
                assert remaining == 0, (
                    f"teardown left Space {f.space_id} behind — it will "
                    f"break other tests in this suite"
                )
                comms = conn.execute(
                    text(
                        "SELECT count(*) FROM communication_events "
                        "WHERE actor_user_id = ANY(:ids) "
                        "OR subject_id = ANY(:ids)"
                    ),
                    {"ids": f.user_ids},
                ).scalar_one()
                assert comms == 0, (
                    f"teardown left {comms} communication events behind — "
                    f"tests that count them globally will fail"
                )


@pytest.fixture
def widen_the_race(monkeypatch):
    """Hold both requests inside the critical section at once.

    Without this the tests in this file pass whether the locks exist or
    not, which was measured rather than assumed: removing the pass lock
    from the single-booking endpoint left every assertion green. A
    barrier aligns the *start* of two requests, but each then runs
    several queries before it reads a count, and in practice one
    finishes before the other arrives. The window is real in production
    — a slow query, a loaded database, two members on the same page —
    and far too narrow to hit on demand.

    So the two reads that a lock is supposed to serialise are slowed
    down. Nothing about the code under test changes: the same functions
    run in the same order, and the only difference is that both
    requests are provably inside the window together. With the locks in
    place the second request waits and reads a fresh number; without
    them both read a stale one and both commit.

    Patched by module attribute in each place the name is bound —
    ``routes`` and ``regular_sessions`` import these directly, so
    patching only the defining module would miss them.
    """
    import time

    from app.services import gathering_booking_rules as rules
    from app.services import regular_sessions as rs_module
    from app.spaces import routes as routes_module

    real_weekly = rules.weekly_usage_on_pass
    real_confirmed = rules.confirmed_booking_count

    def slow_weekly(*args, **kwargs):
        value = real_weekly(*args, **kwargs)
        time.sleep(0.5)
        return value

    def slow_confirmed(*args, **kwargs):
        value = real_confirmed(*args, **kwargs)
        time.sleep(0.5)
        return value

    monkeypatch.setattr(rules, "weekly_usage_on_pass", slow_weekly)
    monkeypatch.setattr(rules, "confirmed_booking_count", slow_confirmed)
    monkeypatch.setattr(rs_module, "confirmed_booking_count", slow_confirmed)
    monkeypatch.setattr(
        routes_module, "_confirmed_booking_count", slow_confirmed,
    )


def _run_together(*callables):
    """Run each callable in its own thread, started at the same moment.

    The barrier is what makes the overlap real rather than hopeful:
    without it one request routinely finishes before the other begins
    and the test passes whether the locks exist or not.
    """
    barrier = threading.Barrier(len(callables))
    results: list[object] = [None] * len(callables)

    def wrap(index, fn):
        def runner():
            barrier.wait()
            try:
                results[index] = fn()
            except BaseException as exc:  # noqa: BLE001 — reported, not swallowed
                results[index] = exc
        return runner

    threads = [
        threading.Thread(target=wrap(i, fn), daemon=True)
        for i, fn in enumerate(callables)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=JOIN_TIMEOUT_SECONDS)
        assert not t.is_alive(), "a booking request never finished — lock order?"
    return results


def _confirmed_count(engine, event_id: str) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM event_bookings "
                "WHERE event_id = :eid AND status = 'confirmed'"
            ),
            {"eid": event_id},
        ).scalar_one()


def _pass_usage(engine, user_id: str) -> tuple[int, int]:
    """``(used_credits, bookings charged to the pass)``."""
    with engine.begin() as conn:
        used = conn.execute(
            text("SELECT used_credits FROM access_passes WHERE user_id = :uid"),
            {"uid": user_id},
        ).scalar_one()
        charged = conn.execute(
            text(
                "SELECT count(*) FROM event_bookings b "
                "JOIN access_passes p ON b.access_pass_id = p.id "
                "WHERE p.user_id = :uid AND b.status = 'confirmed'"
            ),
            {"uid": user_id},
        ).scalar_one()
    return used, charged


def _bulk(fixture, user_id: str, pattern_key: str):
    """Call the bulk reserve path on its own connection."""
    def run():
        session = fixture.session()
        try:
            user = session.get(User, user_id)
            space = session.get(Space, fixture.space_id)
            series = session.get(EventSeries, fixture.series_id)
            return rs.commit_reservations(
                session, user=user, space=space, series=series,
                pattern_keys=[pattern_key], now=datetime.utcnow(),
            )
        finally:
            session.close()
    return run


def _single(fixture, user_id: str, event_id: str):
    """Call the single-booking endpoint on its own connection."""
    def run():
        from app.spaces.routes import book_event

        session = fixture.session()
        try:
            user = session.get(User, user_id)
            return book_event(
                slug=fixture.space_slug,
                event_id=event_id,
                background_tasks=BackgroundTasks(),
                db=session,
                current_user=user,
            )
        finally:
            session.close()
    return run


def _pattern_key(fixture, event_id: str) -> str:
    session = fixture.session()
    try:
        event = session.get(Event, event_id)
        tz = rs.ZoneInfo("Australia/Melbourne")
        return rs.pattern_key_for(
            rs.to_local(event.starts_at, tz),
            rs.to_local(event.ends_at, tz) if event.ends_at else None,
        )
    finally:
        session.close()


def _monday_and_thursday_same_week() -> list[datetime]:
    """Two sessions in one calendar week, far enough ahead to be bookable."""
    base = datetime.utcnow() + timedelta(days=30)
    monday = (base - timedelta(days=base.weekday())).replace(
        hour=7, minute=0, second=0, microsecond=0,
    )
    return [monday, monday + timedelta(days=3)]


# ---------------------------------------------------------------------------
# Allowance: the pass is the contended resource
# ---------------------------------------------------------------------------


class TestWeeklyAllowanceUnderConcurrency:
    def test_two_bulk_requests_for_different_days_cannot_exceed_one_per_week(
        self, committed, widen_the_race,
    ):
        # The case event-row locks cannot catch. Monday and Thursday are
        # different rows, so without a lock on the pass both requests
        # count the week as empty and both spend its only credit.
        monday, thursday = _monday_and_thursday_same_week()
        f = committed(starts=[monday, thursday], capacity=None, per_week=1)
        user = f.user_ids[0]

        results = _run_together(
            _bulk(f, user, _pattern_key(f, f.event_ids[0])),
            _bulk(f, user, _pattern_key(f, f.event_ids[1])),
        )
        for r in results:
            assert not isinstance(r, BaseException), r

        reserved = sum(getattr(r, "reserved_count", 0) for r in results)
        used, charged = _pass_usage(f.engine, user)
        assert reserved == 1, f"the pass paid for {reserved} sessions"
        assert used == 1
        assert charged == 1

    def test_two_single_bookings_for_different_days_cannot_either(
        self, committed, widen_the_race,
    ):
        # The same race through the older, one-at-a-time endpoint.
        monday, thursday = _monday_and_thursday_same_week()
        f = committed(starts=[monday, thursday], capacity=None, per_week=1)
        user = f.user_ids[0]

        results = _run_together(
            _single(f, user, f.event_ids[0]),
            _single(f, user, f.event_ids[1]),
        )
        refusals = [r for r in results if isinstance(r, HTTPException)]
        other_errors = [
            r for r in results
            if isinstance(r, BaseException) and not isinstance(r, HTTPException)
        ]
        assert other_errors == [], other_errors
        assert len(refusals) == 1, results
        assert refusals[0].status_code == 409

        used, charged = _pass_usage(f.engine, user)
        assert used == 1
        assert charged == 1

    def test_a_total_allowance_holds_across_concurrent_requests(
        self, committed, widen_the_race,
    ):
        # Two different weeks, so the weekly cap is not what is being
        # tested — the total is.
        base = datetime.utcnow() + timedelta(days=30)
        f = committed(
            starts=[base, base + timedelta(days=7)], capacity=None, total=1,
        )
        user = f.user_ids[0]

        results = _run_together(
            _single(f, user, f.event_ids[0]),
            _single(f, user, f.event_ids[1]),
        )
        other_errors = [
            r for r in results
            if isinstance(r, BaseException) and not isinstance(r, HTTPException)
        ]
        assert other_errors == [], other_errors
        used, charged = _pass_usage(f.engine, user)
        assert used == 1, f"a 1-session pass was charged {used} times"
        assert charged == 1


# ---------------------------------------------------------------------------
# Capacity: the occurrence is the contended resource
# ---------------------------------------------------------------------------


class TestLastPlaceUnderConcurrency:
    def test_bulk_and_individual_cannot_both_take_the_last_place(
        self, committed, widen_the_race,
    ):
        # The two paths meet on one seat. Both lock the occurrence row,
        # and they take their locks in the same order — occurrence,
        # then pass — so neither deadlocks and only one wins.
        when = datetime.utcnow() + timedelta(days=30)
        f = committed(starts=[when], capacity=1, members=2)
        bulk_user, single_user = f.user_ids
        event_id = f.event_ids[0]

        results = _run_together(
            _bulk(f, bulk_user, _pattern_key(f, event_id)),
            _single(f, single_user, event_id),
        )
        other_errors = [
            r for r in results
            if isinstance(r, BaseException) and not isinstance(r, HTTPException)
        ]
        assert other_errors == [], other_errors
        assert _confirmed_count(f.engine, event_id) == 1

        bulk_result, single_result = results
        bulk_won = getattr(bulk_result, "reserved_count", 0) == 1
        single_won = not isinstance(single_result, BaseException)
        assert bulk_won != single_won, (
            f"exactly one must win: bulk={bulk_result} single={single_result}"
        )
        if not bulk_won:
            # The loser is told, not silently given nothing.
            assert [u.reason for u in bulk_result.unavailable] == ["full"]
        else:
            assert isinstance(single_result, HTTPException)
            assert single_result.status_code == 400

    def test_two_bulk_requests_cannot_both_take_the_last_place(
        self, committed, widen_the_race,
    ):
        when = datetime.utcnow() + timedelta(days=30)
        f = committed(starts=[when], capacity=1, members=2)
        key = _pattern_key(f, f.event_ids[0])

        results = _run_together(
            _bulk(f, f.user_ids[0], key),
            _bulk(f, f.user_ids[1], key),
        )
        for r in results:
            assert not isinstance(r, BaseException), r
        assert _confirmed_count(f.engine, f.event_ids[0]) == 1
        assert sum(r.reserved_count for r in results) == 1
        loser = next(r for r in results if r.reserved_count == 0)
        assert [u.reason for u in loser.unavailable] == ["full"]

    def test_two_single_bookings_cannot_both_take_the_last_place(
        self, committed, widen_the_race,
    ):
        # The pre-existing endpoint, now locking the row it counts.
        when = datetime.utcnow() + timedelta(days=30)
        f = committed(starts=[when], capacity=1, members=2)
        event_id = f.event_ids[0]

        results = _run_together(
            _single(f, f.user_ids[0], event_id),
            _single(f, f.user_ids[1], event_id),
        )
        other_errors = [
            r for r in results
            if isinstance(r, BaseException) and not isinstance(r, HTTPException)
        ]
        assert other_errors == [], other_errors
        assert _confirmed_count(f.engine, event_id) == 1
        assert len([r for r in results if isinstance(r, HTTPException)]) == 1

    def test_two_members_reserving_the_same_term_both_succeed(
        self, committed, widen_the_race,
    ):
        # The other half of a lock: it has to serialise without
        # starving. The bulk path locks every remaining occurrence in
        # the Series, so two members reserving the same term queue
        # behind each other — and must both come out whole when there
        # is room for both. This is also what makes the pass lock in
        # that path redundant rather than load-bearing: same-Series
        # concurrency never reaches the allowance check in parallel.
        base = datetime.utcnow() + timedelta(days=30)
        f = committed(
            starts=[base, base + timedelta(days=7)],
            capacity=10, members=2,
        )
        key = _pattern_key(f, f.event_ids[0])

        results = _run_together(
            _bulk(f, f.user_ids[0], key),
            _bulk(f, f.user_ids[1], key),
        )
        for r in results:
            assert not isinstance(r, BaseException), r
        # Both weeks fall on the same weekday, so one pattern covers
        # both occurrences for each member.
        assert [r.reserved_count for r in results] == [2, 2]
        for user_id in f.user_ids:
            used, charged = _pass_usage(f.engine, user_id)
            assert used == 2 and charged == 2

    def test_the_same_member_clicking_twice_books_once(
        self, committed, widen_the_race,
    ):
        # Not a capacity question — an idempotency one, under a real
        # race rather than two sequential calls.
        when = datetime.utcnow() + timedelta(days=30)
        f = committed(starts=[when], capacity=10)
        user = f.user_ids[0]
        key = _pattern_key(f, f.event_ids[0])

        results = _run_together(_bulk(f, user, key), _bulk(f, user, key))
        for r in results:
            assert not isinstance(r, BaseException), r
        assert _confirmed_count(f.engine, f.event_ids[0]) == 1
        assert sum(r.reserved_count for r in results) == 1
        used, _ = _pass_usage(f.engine, user)
        assert used == 1
