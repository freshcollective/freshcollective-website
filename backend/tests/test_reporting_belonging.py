"""Belonging: staying, coming back, and belonging in more than one place.

Three behaviours that get conflated. The tests here mostly defend the
boundaries between them, and the boundary between what the records can
establish and what they cannot.

The two that matter most:

**Membership retention is not person retention.** Somebody who leaves
one Collective and stays in another has not left Fresh Collective, and
a figure that counted it as churn would describe exploration as loss.

**An unreached milestone is not a failed one.** A cohort that joined
last month has no three-month retention, and reporting that as zero is
the single easiest way to make a growing platform look like a leaking
one.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

import app.models.community_care  # noqa: F401
from app.models.business_event import BusinessEvent
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.reporting.classification import PRODUCTION, TEST
from app.reporting.population import Population, PopulationView
from app.reporting.registry import REGISTRY, Window
from app.reporting.scope import Audience, ReportScope, ScopeDenied, platform_scope

PRODUCTION_POP = Population(PopulationView.production)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def val(db, key, window=None, scope=None, population=None):
    return REGISTRY.get(key).evaluate(
        db, scope or platform_scope(), window or Window(),
        population or Population(PopulationView.all),
    )


def _join(db, user, space, joined_at, removed_at=None, undated_removal=False):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=SpaceRole.learner,
        status=(
            SpaceMembershipStatus.removed
            if (removed_at or undated_removal)
            else SpaceMembershipStatus.active
        ),
        joined_at=joined_at,
        removed_at=removed_at,
    ))
    db.flush()


def _post(db, space, author, when):
    channel = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="General",
        slug=f"g-{uuid.uuid4().hex[:6]}", channel_type="standard",
    )
    db.add(channel)
    db.flush()
    db.add(CommunityPost(
        id=_uid("cp"), space_id=space.id, channel_id=channel.id,
        author_id=author.id, body="hello", created_at=when,
    ))
    db.flush()


def _cohort(result, label):
    return next(
        c for c in result.qualifiers["cohorts"] if c["cohort"] == label
    )


def _offset(cohort, months_after):
    return next(o for o in cohort["offsets"] if o["months_after"] == months_after)


# ---------------------------------------------------------------------------

class TestLeavingACollectiveIsNotLeavingFreshCollective:
    def test_a_membership_ending_is_counted_at_membership_level(
        self, db, make_space, make_user,
    ):
        a, b = (make_space(reporting_class=PRODUCTION) for _ in range(2))
        person = make_user()
        _join(db, person, a, datetime(2026, 1, 1),
              removed_at=datetime(2026, 10, 10))
        _join(db, person, b, datetime(2026, 1, 1),
              removed_at=datetime(2026, 10, 12))
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        assert val(db, "memberships_ended", window).value == 2

    def test_somebody_who_moved_has_not_left(self, db, make_space, make_user):
        """The distinction the whole section rests on."""
        a, b = (make_space(reporting_class=PRODUCTION) for _ in range(2))
        mover = make_user()
        _join(db, mover, a, datetime(2026, 1, 1),
              removed_at=datetime(2026, 10, 10))
        _join(db, mover, b, datetime(2026, 1, 1))

        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        assert val(db, "memberships_ended", window).value == 1
        assert val(db, "members_leaving_entirely", window).value == 0, (
            "they are still a member of something"
        )

    def test_somebody_who_left_everything_is_counted(
        self, db, make_space, make_user,
    ):
        space = make_space(reporting_class=PRODUCTION)
        leaver = make_user()
        _join(db, leaver, space, datetime(2026, 1, 1),
              removed_at=datetime(2026, 10, 10))
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        v = val(db, "members_leaving_entirely", window)
        assert v.value == 1
        assert v.qualifiers["members_at_start"] == 1
        assert v.qualifiers["members_at_end"] == 0

    def test_leaving_is_undefined_over_all_time(self, db):
        v = val(db, "members_leaving_entirely", Window())
        assert v.value is None
        assert "two moments" in v.unavailable_reason

    def test_a_departure_nobody_dated_is_disclosed_not_guessed(
        self, db, make_space, make_user,
    ):
        """It is a real departure that cannot be placed in a period."""
        space = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), space, datetime(2026, 1, 1), undated_removal=True)
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        v = val(db, "memberships_ended", window)
        assert v.value == 0, "it belongs to no period"
        assert v.qualifiers["departures_without_a_date"] == 1
        assert "lower bound" in v.qualifiers["undated_note"]

    def test_an_undated_departure_is_not_counted_as_a_current_member(
        self, db, make_space, make_user,
    ):
        space = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), space, datetime(2026, 1, 1), undated_removal=True)
        assert REGISTRY.get("unique_members").evaluate(
            db, platform_scope(), Window(),
        ).value == 0


class TestRejoiningIsOnlyKnownFromTheEvent:
    def _event(self, db, space, user, when):
        """A core insert, as the producer does.

        ``sequence_number`` is NOT NULL with a database sequence behind
        it and no default in the mapping, so ``db.add`` sends an
        explicit NULL and the row is rejected.
        """
        db.execute(BusinessEvent.__table__.insert().values(
            id=_uid("be"), event_type="membership_reactivated",
            occurred_at=when, recorded_at=when,
            subject_type="membership", subject_id=_uid("sm"),
            user_id=user.id, space_id=space.id,
            payload={}, dedupe_key=_uid("dk"),
        ))
        db.flush()

    def test_a_recorded_rejoin_is_counted(self, db, make_space, make_user):
        space = make_space(reporting_class=PRODUCTION)
        user = make_user()
        self._event(db, space, user, datetime(2026, 10, 10))
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        assert val(db, "memberships_rejoined", window).value == 1

    def test_a_period_before_recording_is_unavailable_not_zero(
        self, db, make_space, make_user,
    ):
        """Nobody wrote it down. That is not evidence nobody rejoined."""
        space = make_space(reporting_class=PRODUCTION)
        self._event(db, space, make_user(), datetime(2026, 10, 10))
        earlier = Window(datetime(2025, 1, 1), datetime(2025, 2, 1), "jan 25")
        v = val(db, "memberships_rejoined", earlier)
        assert v.value is None
        assert "cannot be established" in v.unavailable_reason
        assert "not the same as nobody" in v.unavailable_reason

    def test_with_no_recording_at_all_it_is_unavailable(self, db):
        # Cleared inside this transaction rather than assumed empty.
        # ``rebuild_range`` commits per day, so tests that exercise it
        # leave business_events behind in fc_test and a later test that
        # depends on the table being empty fails for reasons nothing to
        # do with it.
        db.execute(BusinessEvent.__table__.delete())
        db.flush()
        v = val(db, "memberships_rejoined",
                Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct"))
        assert v.value is None
        assert "has not begun" in v.unavailable_reason

    def test_a_period_straddling_the_floor_says_so(
        self, db, make_space, make_user,
    ):
        space = make_space(reporting_class=PRODUCTION)
        self._event(db, space, make_user(), datetime(2026, 10, 20))
        straddling = Window(datetime(2026, 1, 1), datetime(2026, 11, 1), "2026")
        v = val(db, "memberships_rejoined", straddling)
        assert v.value == 1
        assert "predates business-event recording" in (
            v.qualifiers["partial_period_note"]
        )


class TestCohortsDoNotPunishTheRecentlyJoined:
    def _joined(self, db, space, when, n=1):
        from app.models.user import User

        people = []
        for _ in range(n):
            u = User(
                id=_uid("u"), email=f"{uuid.uuid4().hex[:8]}@t.test",
                name="M", role="user", password_hash="x",
                created_at=when, email_verified_at=when,
            )
            db.add(u)
            db.flush()
            _join(db, u, space, when)
            people.append(u)
        return people

    def test_an_unreached_milestone_is_blank_not_zero(
        self, db, make_space,
    ):
        """The single easiest way to make growth look like leakage."""
        space = make_space(reporting_class=PRODUCTION)
        last_month = datetime.utcnow().replace(day=1) - timedelta(days=5)
        self._joined(db, space, last_month, n=3)

        v = val(db, "membership_retention_cohorts")
        cohort = v.qualifiers["cohorts"][-1]
        far = _offset(cohort, 6)
        assert far["reached"] is False
        assert far["retained_in_collective"] is None, "blank, never zero"
        assert far["retained_anywhere"] is None

    def test_a_reached_milestone_reports_a_number(self, db, make_space):
        space = make_space(reporting_class=PRODUCTION)
        self._joined(db, space, datetime(2026, 1, 10), n=4)
        v = val(db, "membership_retention_cohorts")
        cohort = _cohort(v, "2026-01")
        first = _offset(cohort, 1)
        assert first["reached"] is True
        assert first["retained_in_collective"] == 4

    def test_the_denominator_is_who_joined_in_that_month(
        self, db, make_space,
    ):
        space = make_space(reporting_class=PRODUCTION)
        self._joined(db, space, datetime(2026, 1, 10), n=3)
        self._joined(db, space, datetime(2026, 2, 10), n=5)
        v = val(db, "membership_retention_cohorts")
        assert _cohort(v, "2026-01")["people_joined"] == 3
        assert _cohort(v, "2026-02")["people_joined"] == 5

    def test_somebody_who_left_is_not_retained(self, db, make_space, make_user):
        space = make_space(reporting_class=PRODUCTION)
        stayer, leaver = make_user(), make_user()
        _join(db, stayer, space, datetime(2026, 1, 10))
        _join(db, leaver, space, datetime(2026, 1, 10),
              removed_at=datetime(2026, 2, 5))
        v = val(db, "membership_retention_cohorts")
        cohort = _cohort(v, "2026-01")
        assert cohort["people_joined"] == 2
        assert _offset(cohort, 1)["retained_in_collective"] == 1

    def test_retained_anywhere_is_never_smaller_than_in_collective(
        self, db, make_space, make_user,
    ):
        a, b = (make_space(reporting_class=PRODUCTION) for _ in range(2))
        mover = make_user()
        _join(db, mover, a, datetime(2026, 1, 10),
              removed_at=datetime(2026, 2, 5))
        _join(db, mover, b, datetime(2026, 1, 10))

        v = val(db, "membership_retention_cohorts")
        cohort = _cohort(v, "2026-01")
        for o in cohort["offsets"]:
            if not o["reached"]:
                continue
            assert o["retained_anywhere"] >= o["retained_in_collective"], (
                "a person retained somewhere cannot be fewer than a "
                "membership retained"
            )

    def test_moving_shows_as_a_gap_between_the_two_retentions(
        self, db, make_space, make_user,
    ):
        a, b = (make_space(reporting_class=PRODUCTION) for _ in range(2))
        mover = make_user()
        _join(db, mover, a, datetime(2026, 1, 10),
              removed_at=datetime(2026, 2, 5))
        _join(db, mover, b, datetime(2026, 1, 10))
        v = val(db, "membership_retention_cohorts")
        first = _offset(_cohort(v, "2026-01"), 1)
        assert first["retained_in_collective"] == 1, "the b membership"
        assert first["retained_anywhere"] == 1, "the person"

    def test_cohort_months_are_australian(self, db, make_space, make_user):
        """A join just before local midnight on 1 February is February.

        Sydney is ahead of UTC, so 31 January 14:00 UTC is already
        1 February locally — a UTC month boundary would file it under
        the wrong cohort.
        """
        space = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), space, datetime(2026, 1, 31, 14, 0))
        v = val(db, "membership_retention_cohorts")
        labels = [c["cohort"] for c in v.qualifiers["cohorts"]]
        assert "2026-02" in labels
        assert "2026-01" not in labels

    def test_the_limitation_about_rejoining_is_stated(self, db, make_space, make_user):
        space = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), space, datetime(2026, 1, 10))
        v = val(db, "membership_retention_cohorts")
        assert "overstates retention" in v.qualifiers["limitation"]

    def test_undated_departures_are_disclosed_on_the_grid(
        self, db, make_space, make_user,
    ):
        space = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), space, datetime(2026, 1, 10))
        _join(db, make_user(), space, datetime(2026, 1, 10), undated_removal=True)
        v = val(db, "membership_retention_cohorts")
        assert v.qualifiers["undated_departures"] == 1
        assert "nobody recorded" in v.qualifiers["limitation"]

    def test_no_memberships_means_no_cohorts_rather_than_an_empty_grid(self, db):
        v = val(db, "membership_retention_cohorts")
        assert v.value is None
        assert "no cohorts" in v.unavailable_reason


class TestBelongingInMoreThanOnePlace:
    def test_overlap_and_participation_are_different_questions(
        self, db, make_space, make_user,
    ):
        """Belonging to three is not participating in three."""
        a, b, c = (make_space(reporting_class=PRODUCTION) for _ in range(3))
        person = make_user()
        for space in (a, b, c):
            _join(db, person, space, datetime(2026, 1, 1))
        _post(db, a, person, datetime(2026, 10, 10))

        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        assert REGISTRY.get("members_in_three_plus_collectives").evaluate(
            db, platform_scope(), window,
        ).value == 1, "they belong to three"
        assert val(db, "multi_collective_participants", window).value == 0, (
            "but they acted in one"
        )

    def test_participating_in_two_is_counted(self, db, make_space, make_user):
        a, b = (make_space(reporting_class=PRODUCTION) for _ in range(2))
        person = make_user()
        for space in (a, b):
            _join(db, person, space, datetime(2026, 1, 1))
            _post(db, space, person, datetime(2026, 10, 10))
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        v = val(db, "multi_collective_participants", window)
        assert v.value == 1
        assert v.qualifiers["participated_anywhere"] == 1

    def test_the_basis_says_it_counts_acts_not_belonging(self, db):
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        v = val(db, "multi_collective_participants", window)
        assert "not where they belong" in v.qualifiers["basis"]


class TestClassificationAndAuthorisation:
    def test_a_test_account_does_not_inflate_retention(
        self, db, make_space, make_user,
    ):
        space = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), space, datetime(2026, 1, 10))
        _join(db, make_user(reporting_class=TEST), space, datetime(2026, 1, 10))

        everything = val(db, "membership_retention_cohorts")
        narrowed = val(db, "membership_retention_cohorts",
                       population=PRODUCTION_POP)
        assert _cohort(everything, "2026-01")["people_joined"] == 2
        assert _cohort(narrowed, "2026-01")["people_joined"] == 1

    def test_a_test_collective_is_out_of_the_production_cohorts(
        self, db, make_space, make_user,
    ):
        fixture = make_space(reporting_class=TEST)
        _join(db, make_user(), fixture, datetime(2026, 1, 10))
        v = val(db, "membership_retention_cohorts", population=PRODUCTION_POP)
        assert v.value is None, "no production memberships at all"

    def test_endings_are_narrowed_too(self, db, make_space, make_user):
        fixture = make_space(reporting_class=TEST)
        _join(db, make_user(), fixture, datetime(2026, 1, 1),
              removed_at=datetime(2026, 10, 10))
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        assert val(db, "memberships_ended", window).value == 1
        assert val(
            db, "memberships_ended", window, population=PRODUCTION_POP,
        ).value == 0

    def test_a_creator_sees_only_their_own_cohorts(
        self, db, make_space, make_user,
    ):
        mine = make_space(reporting_class=PRODUCTION)
        theirs = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), mine, datetime(2026, 1, 10))
        for _ in range(4):
            _join(db, make_user(), theirs, datetime(2026, 1, 10))

        creator = ReportScope(
            audience=Audience.creator, user_id="u", space_ids=(mine.id,),
        )
        assert _cohort(val(db, "membership_retention_cohorts"),
                       "2026-01")["people_joined"] == 5
        assert _cohort(
            val(db, "membership_retention_cohorts", scope=creator), "2026-01",
        )["people_joined"] == 1

    def test_platform_only_belonging_metrics_refuse_a_creator(self, db):
        creator = ReportScope(
            audience=Audience.creator, user_id="u", space_ids=("s1",),
        )
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        for key in ("members_leaving_entirely", "multi_collective_participants"):
            with pytest.raises(ScopeDenied):
                REGISTRY.get(key).evaluate(db, creator, window)

    def test_a_creator_managing_nothing_sees_nothing(self, db, make_space, make_user):
        space = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), space, datetime(2026, 1, 10))
        nobody = ReportScope(audience=Audience.creator, user_id="u", space_ids=())
        assert val(db, "membership_retention_cohorts", scope=nobody).value is None


class TestPrivacyAndInterpretation:
    def test_no_belonging_metric_reads_member_authored_content(self):
        forbidden = (
            "community_posts.body", "post_comments.body", "reflection_text",
            "direct_messages", "message_body", "exercise_responses",
        )
        for key in (
            "memberships_ended", "members_leaving_entirely",
            "memberships_rejoined", "membership_retention_cohorts",
            "multi_collective_participants",
        ):
            source = REGISTRY.get(key).source_of_truth.lower()
            for column in forbidden:
                assert column not in source, f"{key} names {column}"

    def test_metrics_about_people_are_marked_as_personal_data(self):
        for key in (
            "members_leaving_entirely", "membership_retention_cohorts",
            "multi_collective_participants",
        ):
            assert REGISTRY.get(key).personal_data, key

    def test_no_metric_claims_to_measure_belonging_itself(self):
        """Belonging is a feeling; these are behaviours beside it."""
        for m in REGISTRY.all():
            assert "belonging" not in m.key, (
                f"{m.key} names itself after something it cannot measure"
            )
