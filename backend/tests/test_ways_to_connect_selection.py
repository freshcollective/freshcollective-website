"""Which few people Ways to Connect introduces, and who is eligible at all.

Pure-function tests. Recognition objects are built by hand rather than
through the database — selection has no opinion about *whether*
evidence is real, only about how much of it there is and what kind, so
building the substrate would test the service again.

Three properties worth protecting: one shared thing never earns a
card, what actually happened outranks what is merely planned, and the
page does not reshuffle when a member refreshes it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.recognition_service import (
    Recognition,
    SharedCollective,
    SharedGathering,
    SharedGatheringBasis,
    SharedPathway,
)
from app.ways_to_connect.selection import (
    CAT_ATTENDED_AND_PATHWAY,
    CAT_ATTENDED_AND_UPCOMING,
    CAT_PATHWAY_AND_UPCOMING,
    CAT_REPEATED_ATTENDANCE,
    CAT_REPEATED_PATHWAYS,
    MAX_PEOPLE,
    MIN_SIGNALS,
    day_index,
    read_evidence,
    select_people,
)

NOW = datetime(2026, 6, 1, 12, 0, 0)
COLLECTIVE = SharedCollective(
    collective_id="s1", slug="embody", name="EMBODY",
    timezone="Australia/Melbourne",
)


def _g(days: int, basis: SharedGatheringBasis) -> SharedGathering:
    return SharedGathering(
        gathering_id=f"ev{days}", title=f"G{days}",
        starts_at=NOW + timedelta(days=days),
        collective_id="s1", basis=basis,
    )


def _p(days_ago: int | None, n: int = 1) -> SharedPathway:
    return SharedPathway(
        pathway_id=f"pw{n}", slug=f"p{n}", title=f"P{n}", collective_id="s1",
        crossing_at=None if days_ago is None else NOW - timedelta(days=days_ago),
    )


def person(
    uid: str, *, attended: list[int] = [], upcoming: list[int] = [],
    pathways: list[int | None] = [],
) -> Recognition:
    """``attended``/``upcoming`` are day offsets; ``pathways`` are
    crossing dates in days ago (or None)."""
    return Recognition(
        other_user_id=uid,
        collectives=(COLLECTIVE,),
        gatherings=tuple(
            [_g(-d, SharedGatheringBasis.ATTENDED) for d in attended]
            + [_g(d, SharedGatheringBasis.UPCOMING) for d in upcoming]
        ),
        pathways=tuple(_p(d, i) for i, d in enumerate(pathways)),
    )


def ids(result) -> list[str]:
    return [r.other_user_id for r in result]


# ---------------------------------------------------------------------------
# Eligibility — one shared thing is a coincidence
# ---------------------------------------------------------------------------

class TestTwoSignalThreshold:
    def test_two_is_the_threshold(self):
        assert MIN_SIGNALS == 2

    def test_one_attended_gathering_alone_does_not_qualify(self):
        assert select_people([person("a", attended=[10])], now=NOW) == []

    def test_one_pathway_alone_does_not_qualify(self):
        assert select_people([person("a", pathways=[5])], now=NOW) == []

    def test_one_upcoming_gathering_alone_does_not_qualify(self):
        assert select_people([person("a", upcoming=[3])], now=NOW) == []

    def test_two_attended_gatherings_qualify(self):
        assert ids(select_people([person("a", attended=[10, 40])], now=NOW)) == ["a"]

    def test_a_pathway_and_an_attended_gathering_qualify(self):
        assert ids(
            select_people([person("a", attended=[10], pathways=[5])], now=NOW)
        ) == ["a"]

    def test_two_pathways_qualify(self):
        assert ids(select_people([person("a", pathways=[5, 30])], now=NOW)) == ["a"]

    def test_an_attended_gathering_plus_an_upcoming_one_qualifies(self):
        assert ids(
            select_people([person("a", attended=[10], upcoming=[3])], now=NOW)
        ) == ["a"]

    def test_a_pathway_plus_an_upcoming_gathering_qualifies(self):
        assert ids(
            select_people([person("a", pathways=[5], upcoming=[3])], now=NOW)
        ) == ["a"]

    def test_two_upcoming_gatherings_alone_do_not_qualify(self):
        """Two signals, and nothing has happened between these two
        people yet. A plan is not a shared experience — it says when an
        existing overlap will continue, and there is no overlap here to
        continue."""
        assert select_people([person("a", upcoming=[3, 10])], now=NOW) == []

    def test_six_upcoming_gatherings_alone_still_do_not_qualify(self):
        """Not a threshold that more plans can climb."""
        assert select_people(
            [person("a", upcoming=[1, 2, 3, 4, 5, 6])], now=NOW
        ) == []

    def test_a_card_needs_one_realised_signal(self):
        """The whole rule in three lines: plans support, they never
        establish."""
        assert select_people([person("plans", upcoming=[3, 10])], now=NOW) == []
        assert ids(
            select_people([person("room", attended=[10], upcoming=[3])], now=NOW)
        ) == ["room"]
        assert ids(
            select_people([person("path", pathways=[10], upcoming=[3])], now=NOW)
        ) == ["path"]

    def test_collective_membership_is_never_a_signal(self):
        """A Recognition carrying only collectives is what the service
        returns for co-members, and it must never become a card."""
        co_member = Recognition(other_user_id="a", collectives=(COLLECTIVE,))
        assert select_people([co_member], now=NOW) == []

    def test_the_threshold_never_drops_to_fill_the_page(self):
        """Three people with one signal each is still an empty page."""
        pool = [person(f"u{i}", attended=[i + 1]) for i in range(3)]
        assert select_people(pool, now=NOW) == []

    def test_an_expired_upcoming_gathering_stops_counting(self):
        """Read from a later clock, a booking for something that has
        since happened is no longer an upcoming signal — and without it
        this pair drops below the threshold."""
        p = person("a", pathways=[5], upcoming=[3])
        assert ids(select_people([p], now=NOW)) == ["a"]
        assert select_people([p], now=NOW + timedelta(days=4)) == []


# ---------------------------------------------------------------------------
# The evidence hierarchy — what happened beats what is planned
# ---------------------------------------------------------------------------

class TestCategories:
    def test_every_eligible_shape_lands_in_exactly_one_category(self):
        cases = [
            (person("a", attended=[5, 40]),               CAT_REPEATED_ATTENDANCE),
            (person("b", attended=[5], pathways=[9]),     CAT_ATTENDED_AND_PATHWAY),
            (person("c", attended=[5], upcoming=[9]),     CAT_ATTENDED_AND_UPCOMING),
            (person("d", pathways=[5, 40]),               CAT_REPEATED_PATHWAYS),
            (person("e", pathways=[5], upcoming=[9]),     CAT_PATHWAY_AND_UPCOMING),
        ]
        for p, expected in cases:
            assert read_evidence(p, NOW).category == expected

    def test_ineligible_shapes_have_no_category(self):
        for p in (
            person("only_plans", upcoming=[3, 10]),
            person("one_room", attended=[5]),
            person("one_path", pathways=[5]),
            person("one_plan", upcoming=[5]),
        ):
            assert read_evidence(p, NOW).category is None

    def test_extra_plans_never_change_a_category(self):
        """A pair with real history stays where their history put them,
        however full their diary is."""
        e = read_evidence(person("a", attended=[5, 40], upcoming=[1, 2, 3]), NOW)
        assert e.category == CAT_REPEATED_ATTENDANCE

    def test_the_full_preference_order(self):
        pool = [
            person("cat5", pathways=[1], upcoming=[1]),
            person("cat3", attended=[1], upcoming=[1]),
            person("cat1", attended=[1, 30]),
        ]
        assert ids(select_people(pool, now=NOW)) == ["cat1", "cat3", "cat5"]

    def test_repeated_attendance_beats_one_attendance_plus_a_plan(self):
        """The refinement asked for: two real rooms outrank one room and
        a booking, however imminent the booking."""
        pool = [
            person("once_plus_plan", attended=[1], upcoming=[1]),
            person("twice", attended=[200, 240]),
        ]
        assert ids(select_people(pool, now=NOW)) == ["twice", "once_plus_plan"]

    def test_attendance_plus_pathway_beats_attendance_plus_plan(self):
        pool = [
            person("plan", attended=[1], upcoming=[1]),
            person("path", attended=[200], pathways=[300]),
        ]
        assert ids(select_people(pool, now=NOW)) == ["path", "plan"]

    def test_one_attendance_plus_a_plan_beats_two_pathways(self):
        """Category 3 above category 4: a room that happened outranks
        paths, even two of them."""
        pool = [
            person("paths", pathways=[1, 2]),
            person("room_plus_plan", attended=[300], upcoming=[300]),
        ]
        assert ids(select_people(pool, now=NOW)) == ["room_plus_plan", "paths"]

    def test_two_pathways_beat_a_pathway_plus_a_plan(self):
        pool = [
            person("path_plan", pathways=[1], upcoming=[1]),
            person("two_paths", pathways=[200, 260]),
        ]
        assert ids(select_people(pool, now=NOW)) == ["two_paths", "path_plan"]

    def test_imminence_never_moves_anyone_up_the_list(self):
        pool = [
            person("tomorrow", pathways=[400], upcoming=[1]),
            person("last_year", attended=[300, 340]),
        ]
        assert ids(select_people(pool, now=NOW)) == ["last_year", "tomorrow"]


# ---------------------------------------------------------------------------
# Recency, inside a category only
# ---------------------------------------------------------------------------

class TestRecencyWithinCategory:
    def test_more_recent_attendance_comes_first(self):
        pool = [person("older", attended=[100, 140]), person("newer", attended=[5, 40])]
        assert ids(select_people(pool, now=NOW)) == ["newer", "older"]

    def test_more_recent_pathway_crossing_comes_first(self):
        pool = [person("stalled", pathways=[200, 250]), person("moving", pathways=[2, 9])]
        assert ids(select_people(pool, now=NOW)) == ["moving", "stalled"]

    def test_sooner_upcoming_breaks_ties_in_the_pathway_plan_category(self):
        pool = [
            person("later", pathways=[10], upcoming=[30]),
            person("sooner", pathways=[10], upcoming=[2]),
        ]
        assert ids(select_people(pool, now=NOW)) == ["sooner", "later"]

    def test_imminence_breaks_ties_between_comparable_people(self):
        """Same most-recent attendance; one of them also has something
        coming up. That is the tiebreak, not a promotion."""
        pool = [
            person("no_plans", attended=[10, 60]),
            person("has_plans", attended=[10, 90], upcoming=[2]),
        ]
        assert ids(select_people(pool, now=NOW))[0] == "has_plans"

    def test_a_pathway_with_no_crossing_date_sorts_last_not_out(self):
        pool = [person("dated", pathways=[10, 20]), person("undated", pathways=[None, None])]
        result = ids(select_people(pool, now=NOW))
        assert result == ["dated", "undated"]


# ---------------------------------------------------------------------------
# Slot arithmetic
# ---------------------------------------------------------------------------

class TestSlotArithmetic:
    def test_at_most_three(self):
        pool = [person(f"u{i}", attended=[i + 1, i + 50]) for i in range(8)]
        assert len(select_people(pool, now=NOW)) == MAX_PEOPLE

    def test_two_eligible_people_yield_two(self):
        pool = [person("a", attended=[1, 5]), person("b", attended=[2, 6])]
        assert len(select_people(pool, now=NOW)) == 2

    def test_one_eligible_person_yields_one(self):
        assert len(select_people([person("a", attended=[1, 5])], now=NOW)) == 1

    def test_nobody_yields_nobody(self):
        assert select_people([], now=NOW) == []

    def test_ineligible_people_do_not_occupy_slots(self):
        pool = [person("good", attended=[1, 5])] + [
            person(f"thin{i}", upcoming=[i + 1]) for i in range(5)
        ] + [person("plans_only", upcoming=[3, 12])]
        assert ids(select_people(pool, now=NOW)) == ["good"]

    def test_a_lower_category_fills_slots_a_higher_one_left_open(self):
        pool = [
            person("hist", attended=[1, 5]),
            person("weaker", pathways=[9], upcoming=[2]),
        ]
        assert ids(select_people(pool, now=NOW)) == ["hist", "weaker"]


# ---------------------------------------------------------------------------
# Rotation — within a tier, by the day
# ---------------------------------------------------------------------------

class TestRotation:
    def _band(self, n=5):
        """``n`` comparable people, all in the repeated-attendance
        category."""
        return [person(f"u{i}", attended=[i * 10 + 1, i * 10 + 40]) for i in range(n)]

    def test_the_same_day_always_gives_the_same_people(self):
        pool = self._band()
        assert ids(select_people(pool, now=NOW)) == ids(
            select_people(pool, now=NOW + timedelta(hours=6))
        )

    def test_a_different_day_gives_different_people(self):
        pool = self._band()
        assert set(ids(select_people(pool, now=NOW))) != set(
            ids(select_people(pool, now=NOW + timedelta(days=1)))
        )

    def test_everyone_in_the_band_gets_a_turn(self):
        pool = self._band(5)
        seen: set[str] = set()
        for d in range(14):
            seen.update(ids(select_people(pool, now=NOW + timedelta(days=d))))
        assert seen == {f"u{i}" for i in range(5)}

    def test_rotation_never_reaches_across_a_category(self):
        """Four people with repeated attendance and one with a path plus
        a plan: the weaker pair never displaces anybody, on any day.

        The plan is far enough out to stay upcoming for the whole
        window — otherwise the test would pass for the wrong reason,
        that pair having simply dropped below the threshold."""
        pool = self._band(4) + [person("weaker", pathways=[5], upcoming=[100])]
        for d in range(20):
            assert "weaker" not in ids(select_people(pool, now=NOW + timedelta(days=d)))

    def test_a_lower_category_is_reached_only_when_slots_remain(self):
        pool = self._band(2) + [person("weaker", pathways=[5], upcoming=[100])]
        for d in range(10):
            assert "weaker" in ids(select_people(pool, now=NOW + timedelta(days=d)))

    def test_the_days_pick_is_presented_in_category_order(self):
        """Rotation decides *who*, not the order they appear in."""
        pool = self._band(5)
        for d in range(7):
            picked = select_people(pool, now=NOW + timedelta(days=d))
            stamps = [
                max(g.starts_at for g in r.gatherings) for r in picked
            ]
            assert stamps == sorted(stamps, reverse=True), "most recent first"

    def test_day_index_advances_once_per_day(self):
        assert day_index(NOW) == day_index(NOW + timedelta(hours=11))
        assert day_index(NOW + timedelta(days=1)) == day_index(NOW) + 1


# ---------------------------------------------------------------------------
# What selection must never become
# ---------------------------------------------------------------------------

class TestNotAScore:
    def test_more_shared_things_does_not_promote_within_a_tier(self):
        """Four old attendances against two recent ones. Volume loses;
        recency decides. Anything else would be a score."""
        pool = [
            person("many", attended=[100, 140, 180, 220]),
            person("recent", attended=[5, 40]),
        ]
        assert ids(select_people(pool, now=NOW))[0] == "recent"

    def test_evidence_counts_are_not_summed_into_a_rating(self):
        """Six upcoming Gatherings is six signals and no card at all: a
        pile of plans cannot add up to one real shared room."""
        pool = [
            person("busy_planner", upcoming=[1, 2, 3, 4, 5, 6]),
            person("was_there", attended=[300], upcoming=[40]),
        ]
        assert ids(select_people(pool, now=NOW)) == ["was_there"]

    def test_ties_break_deterministically_rather_than_arbitrarily(self):
        pool = [person("zed", attended=[5, 50]), person("abe", attended=[5, 50])]
        assert ids(select_people(pool, now=NOW)) == ids(
            select_people(list(reversed(pool)), now=NOW)
        )

    def test_the_cap_is_three(self):
        assert MAX_PEOPLE == 3
