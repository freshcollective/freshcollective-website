"""Participation: people, acts, and the difference between them.

The whole section rests on one distinction, and every test here
defends it from a different side. ``participation_acts`` counts what
happened; the ``*_attendees`` / ``*_contributors`` / ``*_participants``
family counts who. One member at three Gatherings is three acts and
one person, and a dashboard that reported the first as the second
would describe a community three times more active than it is.

Two further rules carry their own tests. **A booking is not an
attendance** — attendance is recorded, and a Gathering whose register
was never marked contributes nothing rather than being assumed
attended. And **nothing here reads what anybody wrote**: the metrics
count posts, comments and reactions, never their contents.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

import app.models.community_care  # noqa: F401
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    EventBooking,
    Pathway,
    PathwayStep,
    PostComment,
    PostReaction,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    StepProgress,
)
from app.reporting.classification import PRODUCTION, TEST
from app.reporting.population import Population, PopulationView
from app.reporting.registry import REGISTRY, Window
from app.reporting.scope import Audience, ReportScope, ScopeDenied, platform_scope

WINDOW = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
WHEN = datetime(2026, 10, 10)
PRODUCTION_POP = Population(PopulationView.production)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def val(db, key, window=WINDOW, scope=None, population=None):
    return REGISTRY.get(key).evaluate(
        db, scope or platform_scope(), window,
        population or Population(PopulationView.all),
    )


def _join(db, user, space):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        joined_at=datetime(2026, 1, 1),
    ))
    db.flush()


def _channel(db, space):
    c = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="General",
        slug=f"g-{uuid.uuid4().hex[:6]}", channel_type="standard",
    )
    db.add(c)
    db.flush()
    return c


def _post(db, space, author, when=WHEN, channel=None):
    p = CommunityPost(
        id=_uid("cp"), space_id=space.id, author_id=author.id,
        channel_id=(channel or _channel(db, space)).id,
        body="hello", created_at=when,
    )
    db.add(p)
    db.flush()
    return p


def _attend(db, event, user, *, attended=True, when=WHEN):
    db.add(EventBooking(
        id=_uid("bk"), event_id=event.id, user_id=user.id,
        status="confirmed", booked_at=when,
        attendance_status="attended" if attended else None,
    ))
    db.flush()


def _step(db, space, user, when=WHEN):
    pw = Pathway(
        id=_uid("pw"), space_id=space.id, title="A Pathway",
        slug=f"pw-{uuid.uuid4().hex[:6]}",
    )
    db.add(pw)
    db.flush()
    st = PathwayStep(
        id=_uid("st"), pathway_id=pw.id, title="Step",
        slug=f"s-{uuid.uuid4().hex[:6]}", position=1,
    )
    db.add(st)
    db.flush()
    db.add(StepProgress(
        id=_uid("sp"), user_id=user.id, step_id=st.id, completed_at=when,
    ))
    db.flush()


# ---------------------------------------------------------------------------

class TestPeopleAreNotActs:
    def test_one_person_at_three_gatherings_is_one_person(
        self, db, make_space, make_user, make_event,
    ):
        space = make_space(reporting_class=PRODUCTION)
        member = make_user()
        _join(db, member, space)
        for _ in range(3):
            event = make_event(space=space, starts_at=WHEN,
                               ends_at=WHEN + timedelta(hours=1))
            _attend(db, event, member)

        assert val(db, "gathering_attendance").value == 3, "three attendances"
        assert val(db, "gathering_attendees").value == 1, "one person"

    def test_one_person_posting_three_times_is_one_contributor(
        self, db, make_space, make_user,
    ):
        space = make_space(reporting_class=PRODUCTION)
        member = make_user()
        _join(db, member, space)
        channel = _channel(db, space)
        for _ in range(3):
            _post(db, space, member, channel=channel)

        acts = val(db, "participation_acts")
        assert acts.qualifiers["by_kind"]["conversation_post"] == 3
        assert val(db, "conversation_contributors").value == 1

    def test_three_people_once_each_is_three_contributors(
        self, db, make_space, make_user,
    ):
        space = make_space(reporting_class=PRODUCTION)
        channel = _channel(db, space)
        for _ in range(3):
            member = make_user()
            _join(db, member, space)
            _post(db, space, member, channel=channel)
        assert val(db, "conversation_contributors").value == 3

    def test_steps_completed_and_people_progressing_are_different(
        self, db, make_space, make_user,
    ):
        space = make_space(reporting_class=PRODUCTION)
        member = make_user()
        _join(db, member, space)
        _step(db, space, member)
        _step(db, space, member)

        assert val(db, "pathway_steps_completed").value == 2
        assert val(db, "pathway_participants").value == 1

    def test_the_people_metrics_are_never_stored_as_daily_rows(self):
        """Thirty daily unique counts do not make a monthly one."""
        from app.reporting.aggregates import store_eligible

        for key in (
            "gathering_attendees", "pathway_participants",
            "conversation_contributors", "repeat_gathering_attendees",
        ):
            metric = REGISTRY.get(key)
            assert metric.aggregation.value == "distinct_count", key
            assert not store_eligible(metric), key

    def test_membership_alone_is_not_participation(
        self, db, make_space, make_user,
    ):
        space = make_space(reporting_class=PRODUCTION)
        for _ in range(5):
            _join(db, make_user(), space)
        assert val(db, "active_members").value == 0, (
            "joining is not participating"
        )
        assert val(db, "participation_acts").value == 0


class TestABookingIsNotAnAttendance:
    def test_bookings_and_attendance_are_counted_separately(
        self, db, make_space, make_user, make_event,
    ):
        space = make_space(reporting_class=PRODUCTION)
        event = make_event(space=space, starts_at=WHEN,
                           ends_at=WHEN + timedelta(hours=1))
        for attended in (True, True, False, False, False):
            member = make_user()
            _join(db, member, space)
            _attend(db, event, member, attended=attended)

        assert val(db, "gathering_bookings").value == 5
        assert val(db, "gathering_attendance").value == 2

    def test_an_unmarked_register_is_not_an_attendance(
        self, db, make_space, make_user, make_event,
    ):
        """The rule: never assume a booking was attended."""
        space = make_space(reporting_class=PRODUCTION)
        event = make_event(space=space, starts_at=WHEN,
                           ends_at=WHEN + timedelta(hours=1))
        for _ in range(4):
            member = make_user()
            _join(db, member, space)
            _attend(db, event, member, attended=False)

        assert val(db, "gathering_bookings").value == 4
        assert val(db, "gathering_attendance").value == 0
        assert val(db, "gathering_attendees").value == 0

    def test_the_attendance_rate_comes_from_recorded_attendance(
        self, db, make_space, make_user, make_event,
    ):
        space = make_space(reporting_class=PRODUCTION)
        event = make_event(space=space, starts_at=WHEN,
                           ends_at=WHEN + timedelta(hours=1))
        for attended in (True, False, False, False):
            member = make_user()
            _join(db, member, space)
            _attend(db, event, member, attended=attended)
        v = val(db, "gathering_attendance")
        assert v.qualifiers["booked"] == 4
        assert v.qualifiers["attendance_rate"] == 0.25

    def test_the_limitation_is_stated_on_the_metric(self):
        assert "never assume a booking was attended" in (
            REGISTRY.get("gathering_bookings").limitations or ""
        )

    def test_repeat_attendance_needs_two_different_gatherings(
        self, db, make_space, make_user, make_event,
    ):
        space = make_space(reporting_class=PRODUCTION)
        once, twice = make_user(), make_user()
        _join(db, once, space)
        _join(db, twice, space)
        a = make_event(space=space, starts_at=WHEN,
                       ends_at=WHEN + timedelta(hours=1))
        b = make_event(space=space, starts_at=WHEN + timedelta(days=1),
                       ends_at=WHEN + timedelta(days=1, hours=1))
        _attend(db, a, once)
        _attend(db, a, twice)
        _attend(db, b, twice)

        v = val(db, "repeat_gathering_attendees")
        assert v.value == 1
        assert v.qualifiers["attended_at_all"] == 2

    def test_repeat_attendance_ignores_unattended_bookings(
        self, db, make_space, make_user, make_event,
    ):
        space = make_space(reporting_class=PRODUCTION)
        member = make_user()
        _join(db, member, space)
        a = make_event(space=space, starts_at=WHEN,
                       ends_at=WHEN + timedelta(hours=1))
        b = make_event(space=space, starts_at=WHEN + timedelta(days=1),
                       ends_at=WHEN + timedelta(days=1, hours=1))
        _attend(db, a, member, attended=True)
        _attend(db, b, member, attended=False)
        assert val(db, "repeat_gathering_attendees").value == 0, (
            "a second booking is not a second attendance"
        )


class TestBookingsAndAttendanceShareADate:
    def test_both_are_dated_by_the_gathering_not_the_booking(
        self, db, make_space, make_user, make_event,
    ):
        """A booking made in September for an October Gathering belongs
        to October in both figures, or the pair cannot be compared."""
        space = make_space(reporting_class=PRODUCTION)
        member = make_user()
        _join(db, member, space)
        event = make_event(space=space, starts_at=WHEN,
                           ends_at=WHEN + timedelta(hours=1))
        _attend(db, event, member, when=datetime(2026, 9, 1))

        september = Window(datetime(2026, 9, 1), datetime(2026, 10, 1), "sep")
        assert val(db, "gathering_bookings", september).value == 0
        assert val(db, "gathering_attendance", september).value == 0
        assert val(db, "gathering_bookings", WINDOW).value == 1
        assert val(db, "gathering_attendance", WINDOW).value == 1


class TestReturningParticipationIsExplicit:
    def test_returning_means_active_in_two_adjacent_periods(
        self, db, make_space, make_user,
    ):
        space = make_space(reporting_class=PRODUCTION)
        channel = _channel(db, space)
        stayed, left = make_user(), make_user()
        _join(db, stayed, space)
        _join(db, left, space)
        _post(db, space, stayed, when=datetime(2026, 9, 10), channel=channel)
        _post(db, space, left, when=datetime(2026, 9, 10), channel=channel)
        _post(db, space, stayed, when=WHEN, channel=channel)

        v = val(db, "returning_participants")
        assert v.value == 1
        assert v.qualifiers["active_previous_period"] == 2
        assert v.qualifiers["return_rate"] == 0.5

    def test_it_is_undefined_over_all_time(self, db):
        v = val(db, "returning_participants", Window())
        assert v.value is None
        assert "two adjacent periods" in v.unavailable_reason


class TestParticipationRateDenominator:
    def test_the_denominator_is_people_not_memberships(
        self, db, make_space, make_user,
    ):
        """A person in three Collectives must not make the platform look
        three times less engaged."""
        a = make_space(reporting_class=PRODUCTION)
        b = make_space(reporting_class=PRODUCTION)
        member = make_user()
        _join(db, member, a)
        _join(db, member, b)
        _post(db, space=a, author=member)

        v = val(db, "participation_rate")
        assert v.qualifiers["unique_members"] == 1
        assert v.qualifiers["active_members"] == 1
        assert v.value == 1.0

    def test_no_members_gives_no_rate_rather_than_zero(self, db):
        v = val(db, "participation_rate")
        assert v.value is None
        assert "no rate to report" in v.unavailable_reason


class TestClassificationAndAuthorisation:
    def test_a_test_account_does_not_count_as_a_participant(
        self, db, make_space, make_user,
    ):
        space = make_space(reporting_class=PRODUCTION)
        real, fixture = make_user(), make_user(reporting_class=TEST)
        _join(db, real, space)
        _join(db, fixture, space)
        channel = _channel(db, space)
        _post(db, space, real, channel=channel)
        _post(db, space, fixture, channel=channel)

        assert val(db, "conversation_contributors").value == 2
        assert val(
            db, "conversation_contributors", population=PRODUCTION_POP,
        ).value == 1

    def test_a_test_collective_is_out_of_the_production_view(
        self, db, make_space, make_user,
    ):
        fixture_space = make_space(reporting_class=TEST)
        member = make_user()
        _join(db, member, fixture_space)
        _post(db, space=fixture_space, author=member)
        assert val(db, "participation_acts").value == 1
        assert val(
            db, "participation_acts", population=PRODUCTION_POP,
        ).value == 0

    def test_a_creator_sees_only_their_own_collectives(
        self, db, make_space, make_user,
    ):
        mine = make_space(reporting_class=PRODUCTION)
        theirs = make_space(reporting_class=PRODUCTION)
        for space in (mine, theirs):
            member = make_user()
            _join(db, member, space)
            _post(db, space=space, author=member)

        creator_scope = ReportScope(
            audience=Audience.creator, user_id="u", space_ids=(mine.id,),
        )
        assert val(db, "participation_acts").value == 2
        assert val(db, "participation_acts", scope=creator_scope).value == 1

    def test_a_creator_is_refused_a_platform_only_participation_metric(
        self, db,
    ):
        creator_scope = ReportScope(
            audience=Audience.creator, user_id="u", space_ids=("s1",),
        )
        with pytest.raises(ScopeDenied):
            REGISTRY.get("retention_cohorts").evaluate(
                db, creator_scope, WINDOW,
            )

    def test_a_creator_managing_nothing_sees_nothing(self, db, make_space, make_user):
        space = make_space(reporting_class=PRODUCTION)
        member = make_user()
        _join(db, member, space)
        _post(db, space=space, author=member)
        nobody = ReportScope(audience=Audience.creator, user_id="u", space_ids=())
        assert val(db, "participation_acts", scope=nobody).value == 0


class TestPrivacyBoundaries:
    def test_no_participation_metric_reads_what_anybody_wrote(self):
        """Counts and dates only — never a body, a title or a reflection."""
        forbidden = (
            "community_posts.body", "post_comments.body", "reflection_text",
            "exercise_responses", "direct_messages", "message_body",
        )
        for key in (
            "participation_acts", "active_members", "gathering_attendees",
            "pathway_participants", "conversation_contributors",
            "gathering_bookings", "repeat_gathering_attendees",
            "returning_participants", "participation_rate",
        ):
            source = REGISTRY.get(key).source_of_truth.lower()
            for column in forbidden:
                assert column not in source, f"{key} names {column}"

    def test_the_participation_union_selects_no_content_column(self):
        """The union is (user, space, when, kind). Nothing else."""
        from app.reporting.engagement import participation_events

        columns = {c.name for c in participation_events().columns}
        assert columns == {"user_id", "space_id", "occurred_at", "kind"}

    def test_metrics_about_people_are_marked_as_personal_data(self):
        for key in (
            "gathering_attendees", "pathway_participants",
            "conversation_contributors", "repeat_gathering_attendees",
        ):
            assert REGISTRY.get(key).personal_data, key


class TestWhatCannotBeReportedIsNotInvented:
    def test_there_is_no_pathway_completion_metric(self):
        """``ActivityType.pathway_completed`` exists in the model and no
        production code emits it, and a Pathway has no stored step count
        with history — so neither a completion nor a completion rate can
        be computed for any past date without inventing one."""
        for key in REGISTRY.all():
            assert "completion" not in key.key, (
                f"{key.key} claims a completion the records cannot support"
            )

    def test_missing_activity_is_never_reported_as_zero_participation(
        self, db, make_space, make_user,
    ):
        """A period before instrumentation is not a quiet period.

        The metrics declare ``from_instrumentation`` so the chart draws
        a gap rather than a floor of zeroes.
        """
        for key in (
            "gathering_attendees", "pathway_participants",
            "conversation_contributors",
        ):
            assert REGISTRY.get(key).availability.value == "from_instrumentation"


class TestARatioDeclaresHowItReads:
    """A fraction formatted as a count is a wrong number on screen.

    ``Unit`` exists separately from ``Aggregation`` because the two
    answer different questions, and the registry already carries the
    scar: 1.83 memberships per person once appeared as 183% because the
    dashboard inferred "ratio means percentage".

    The same hole in the other direction put ``participation_rate`` on
    the Participation dashboard as "0.75". It declared no unit, so the
    resolver fell back to the key-suffix rule — money if the key ends
    ``_cents``, a count otherwise — and three quarters of the
    membership was rendered as a bare number.

    Inference is right for almost every metric and wrong for exactly
    the ones whose value is not a whole thing, so a ratio must say.
    """

    def test_participation_rate_is_a_proportion(self):
        assert REGISTRY.get("participation_rate").resolved_unit.value == (
            "proportion"
        )

    def test_every_ratio_metric_declares_its_unit_explicitly(self):
        """Never left to the key-suffix inference."""
        undeclared = [
            m.key for m in REGISTRY.all()
            if m.aggregation.value == "ratio" and m.unit is None
        ]
        assert not undeclared, (
            f"these would be formatted by guesswork: {undeclared}"
        )

    def test_a_proportion_is_between_zero_and_one(
        self, db, make_space, make_user,
    ):
        """So the frontend multiplying by 100 is correct."""
        space = make_space(reporting_class=PRODUCTION)
        for _ in range(4):
            _join(db, make_user(), space)
        active = make_user()
        _join(db, active, space)
        _post(db, space=space, author=active)

        v = val(db, "participation_rate")
        assert 0 <= v.value <= 1
        assert v.value == 0.2, "one of five members took part"

    def test_the_denominator_follows_the_population(
        self, db, make_space, make_user,
    ):
        """A production rate must not be divided by every member."""
        production = make_space(reporting_class=PRODUCTION)
        fixture = make_space(reporting_class=TEST)
        real = make_user()
        _join(db, real, production)
        _post(db, space=production, author=real)
        for _ in range(9):
            _join(db, make_user(), fixture)

        everything = val(db, "participation_rate")
        narrowed = val(db, "participation_rate", population=PRODUCTION_POP)
        assert everything.qualifiers["unique_members"] == 10
        assert narrowed.qualifiers["unique_members"] == 1, (
            "the denominator must be narrowed with the numerator, or a "
            "production rate is divided by the whole platform"
        )
        assert narrowed.value == 1.0

    def test_the_denominator_is_members_not_memberships(
        self, db, make_space, make_user,
    ):
        a = make_space(reporting_class=PRODUCTION)
        b = make_space(reporting_class=PRODUCTION)
        member = make_user()
        _join(db, member, a)
        _join(db, member, b)
        assert val(db, "participation_rate").qualifiers["unique_members"] == 1


class TestReturningParticipationIsEstablishedNotAssumed:
    """Checked rather than changed.

    The hazard named in review is a real one in general — reporting
    "nobody returned" when the earlier period simply has no records —
    but it does not arise here, and the reason is worth writing down.
    The participation union reads the application's own tables (posts,
    comments, reactions, bookings, step progress, payments), not
    ``business_events``. Those rows go back as far as the feature does,
    so a past period is as complete as it ever was and BI-1 is not a
    floor for this family.

    What *is* a floor is having a preceding period at all, and that is
    reported as unavailable rather than as zero.
    """

    def test_all_time_is_unavailable_rather_than_zero(self, db):
        v = val(db, "returning_participants", Window())
        assert v.value is None, "no preceding period exists for all time"
        assert "two adjacent periods" in v.unavailable_reason

    def test_the_first_period_of_a_range_still_looks_behind_it(
        self, db, make_space, make_user,
    ):
        """A chart's earliest bucket is not blind.

        The preceding window is computed from the window itself, not
        from the range on screen, so somebody active in September
        counts as returning in the first October bucket even though
        September is not drawn.
        """
        space = make_space(reporting_class=PRODUCTION)
        member = make_user()
        _join(db, member, space)
        channel = _channel(db, space)
        _post(db, space, member, when=datetime(2026, 9, 20), channel=channel)
        _post(db, space, member, when=WHEN, channel=channel)

        v = val(db, "returning_participants", WINDOW)
        assert v.value == 1
        assert v.qualifiers["active_previous_period"] == 1

    def test_nobody_active_before_means_nobody_could_return(
        self, db, make_space, make_user,
    ):
        """Zero here is established, not assumed — and the qualifiers
        say which, so "0 of 0" cannot be read as "0 of 40"."""
        space = make_space(reporting_class=PRODUCTION)
        member = make_user()
        _join(db, member, space)
        _post(db, space=space, author=member, when=WHEN)

        v = val(db, "returning_participants", WINDOW)
        assert v.value == 0
        assert v.qualifiers["active_previous_period"] == 0
        assert v.qualifiers["return_rate"] is None, (
            "a rate out of nobody is undefined, not zero"
        )

    def test_returning_is_narrowed_by_population_on_both_periods(
        self, db, make_space, make_user,
    ):
        """Filtering only the current period would count a test account
        as having returned."""
        space = make_space(reporting_class=PRODUCTION)
        fixture = make_user(reporting_class=TEST)
        _join(db, fixture, space)
        channel = _channel(db, space)
        _post(db, space, fixture, when=datetime(2026, 9, 20), channel=channel)
        _post(db, space, fixture, when=WHEN, channel=channel)

        assert val(db, "returning_participants").value == 1
        v = val(db, "returning_participants", population=PRODUCTION_POP)
        assert v.value == 0
        assert v.qualifiers["active_previous_period"] == 0

    def test_the_participation_union_does_not_depend_on_business_events(self):
        """Why BI-1 is not a floor for this family."""
        import inspect

        from app.reporting.engagement import participation_events

        source = inspect.getsource(participation_events)
        assert "BusinessEvent" not in source
        assert "business_events" not in source

    def test_the_denominator_is_the_membership_of_the_period_not_of_today(
        self, db, make_space, make_user,
    ):
        """The defect that made every past period look disengaged.

        The denominator was evaluated over all time, which for a
        snapshot means *now*. On a historical chart that divided each
        past period's participants by today's membership, so every
        earlier period was depressed by every member who joined after
        it — the line sloped downwards however engaged the platform
        had been.
        """
        space = make_space(reporting_class=PRODUCTION)
        early = make_user()
        _join(db, early, space)
        db.query(SpaceMembership).filter(
            SpaceMembership.user_id == early.id
        ).update({"joined_at": datetime(2026, 1, 1)})
        _post(db, space=space, author=early, when=WHEN)

        # Nine more join *after* the period being measured.
        for _ in range(9):
            later = make_user()
            _join(db, later, space)
            db.query(SpaceMembership).filter(
                SpaceMembership.user_id == later.id
            ).update({"joined_at": datetime(2026, 12, 1)})
        db.flush()

        v = val(db, "participation_rate", WINDOW)
        assert v.qualifiers["unique_members"] == 1, (
            "members who joined in December are not October's denominator"
        )
        assert v.value == 1.0

    def test_the_basis_travels_with_the_figure(self, db, make_space, make_user):
        space = make_space(reporting_class=PRODUCTION)
        member = make_user()
        _join(db, member, space)
        _post(db, space=space, author=member)
        v = val(db, "participation_rate")
        assert "members as at the end of it" in v.qualifiers["basis"]
