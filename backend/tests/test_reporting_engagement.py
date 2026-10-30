"""Participation, and the distinctions that make it meaningful.

The point of this family is that membership counts do not tell you
whether anybody is actually taking part. So the properties worth
protecting are the ones that separate participation from presence:

* a booking is not an attendance,
* a page view is not anything (none are recorded, by design),
* one person participating ten times is ten acts and one active member,
* and a person in three Collectives is still one active member.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

import app.models.community_care  # noqa: F401
import app.reporting  # noqa: F401 — registers the metric catalogue
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    Event,
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
from app.reporting.registry import REGISTRY, Aggregation, Window
from app.reporting.scope import creator_scope, platform_scope

ALL_TIME = Window()


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def val(db, key, scope=None, window=ALL_TIME):
    return REGISTRY.get(key).evaluate(db, scope or platform_scope(), window)


def _join(db, user, space, role=SpaceRole.learner):
    m = SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id, role=role,
        status=SpaceMembershipStatus.active, joined_at=datetime.utcnow(),
    )
    db.add(m); db.flush()
    return m


def _channel(db, space):
    c = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="General",
        slug=f"general-{uuid.uuid4().hex[:6]}", channel_type="standard",
    )
    db.add(c); db.flush()
    return c


def _post(db, space, author, *, when=None, channel=None):
    p = CommunityPost(
        id=_uid("cp"), space_id=space.id, author_id=author.id,
        body="hello", created_at=when or datetime.utcnow(),
        channel_id=(channel or _channel(db, space)).id,
    )
    db.add(p); db.flush()
    return p


def _gathering(db, space, *, starts_at=None):
    e = Event(
        id=_uid("ev"), space_id=space.id, title="A Gathering",
        starts_at=starts_at or datetime.utcnow(),
        ends_at=(starts_at or datetime.utcnow()) + timedelta(hours=1),
        is_published=True, status="active",
    )
    db.add(e); db.flush()
    return e


def _booking(db, event, user, *, attended: bool):
    b = EventBooking(
        id=_uid("bk"), event_id=event.id, user_id=user.id,
        status="confirmed", booked_at=datetime.utcnow(),
        attendance_status="attended" if attended else None,
    )
    db.add(b); db.flush()
    return b


def _step_completion(db, space, user, *, when=None):
    pw = Pathway(
        id=_uid("pw"), space_id=space.id, title="A Pathway",
        slug=f"pw-{uuid.uuid4().hex[:6]}",
    )
    db.add(pw); db.flush()
    st = PathwayStep(
        id=_uid("st"), pathway_id=pw.id, title="Step",
        slug=f"step-{uuid.uuid4().hex[:6]}", position=1,
    )
    db.add(st); db.flush()
    sp = StepProgress(
        id=_uid("sp"), user_id=user.id, step_id=st.id,
        completed_at=when or datetime.utcnow(),
    )
    db.add(sp); db.flush()
    return sp


# ---------------------------------------------------------------------------
# The core distinction
# ---------------------------------------------------------------------------

class TestParticipationIsNotPresence:
    def test_a_member_who_did_nothing_is_not_active(
        self, db, make_user, make_space,
    ):
        space = make_space(creator=make_user(role="creator"))
        _join(db, make_user(), space)
        db.flush()
        assert val(db, "unique_members").value == 1
        assert val(db, "active_members").value == 0

    def test_a_booking_without_attendance_is_not_participation(
        self, db, make_user, make_space,
    ):
        """Intent, not participation — and reported separately."""
        space = make_space(creator=make_user(role="creator"))
        member = make_user()
        _join(db, member, space)
        ev = _gathering(db, space)
        _booking(db, ev, member, attended=False)
        db.flush()
        assert val(db, "active_members").value == 0
        att = val(db, "gathering_attendance")
        assert att.value == 0
        assert att.qualifiers["booked"] == 1

    def test_attending_is_participation(self, db, make_user, make_space):
        space = make_space(creator=make_user(role="creator"))
        member = make_user()
        _join(db, member, space)
        _booking(db, _gathering(db, space), member, attended=True)
        db.flush()
        assert val(db, "active_members").value == 1
        att = val(db, "gathering_attendance")
        assert att.value == 1
        assert att.qualifiers["attendance_rate"] == 1.0

    @pytest.mark.parametrize("act", ["post", "comment", "reaction", "step", "purchase"])
    def test_each_kind_of_act_makes_someone_active(
        self, db, make_user, make_space, act,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        member = make_user()
        _join(db, member, space)
        if act == "post":
            _post(db, space, member)
        elif act == "comment":
            post = _post(db, space, creator)
            db.add(PostComment(
                id=_uid("pc"), post_id=post.id, author_id=member.id,
                body="hi", created_at=datetime.utcnow(),
            ))
        elif act == "reaction":
            post = _post(db, space, creator)
            db.add(PostReaction(
                id=_uid("pr"), post_id=post.id, user_id=member.id,
                emoji="❤️", created_at=datetime.utcnow(),
            ))
        elif act == "step":
            _step_completion(db, space, member)
        elif act == "purchase":
            db.add(PaymentTransaction(
                id=_uid("txn"),
                transaction_type=PaymentTransactionType.member_pathway_purchase,
                status=PaymentTransactionStatus.succeeded,
                payer_user_id=member.id, creator_user_id=creator.id,
                space_id=space.id, currency="AUD", gross_amount_cents=1000,
                platform_fee_basis_points=1000, platform_fee_cents=100,
                net_creator_amount_cents=900, stripe_mode="test",
                settled_at=datetime.utcnow(), settled_at_source="observed",
            ))
        db.flush()
        # The comment and reaction cases need a post to attach to, and that
        # post's author is themselves participating — so assert the member
        # specifically became active rather than asserting a total.
        from app.reporting.engagement import participation_events
        from sqlalchemy import select as _select
        part = participation_events()
        active = {
            r[0] for r in db.execute(_select(part.c.user_id).select_from(part))
        }
        assert member.id in active, f"{act} did not register"

    def test_ten_acts_by_one_person_is_one_active_member(
        self, db, make_user, make_space,
    ):
        space = make_space(creator=make_user(role="creator"))
        member = make_user()
        _join(db, member, space)
        ch = _channel(db, space)
        for _ in range(10):
            _post(db, space, member, channel=ch)
        db.flush()
        assert val(db, "active_members").value == 1
        assert val(db, "participation_acts").value == 10

    def test_one_person_active_in_three_collectives_is_one_active_member(
        self, db, make_user, make_space,
    ):
        """The multi-Collective guarantee, on the engagement side."""
        person = make_user()
        for _ in range(3):
            sp = make_space(creator=make_user(role="creator"))
            _join(db, person, sp)
            _post(db, sp, person)
        db.flush()
        assert val(db, "active_members").value == 1
        assert val(db, "participation_acts").value == 3


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

class TestPeriodBoundaries:
    def test_activity_outside_the_window_does_not_count(
        self, db, make_user, make_space,
    ):
        space = make_space(creator=make_user(role="creator"))
        member = make_user()
        _join(db, member, space)
        _post(db, space, member, when=datetime(2026, 1, 15))
        db.flush()
        jan = Window(datetime(2026, 1, 1), datetime(2026, 2, 1), "Jan")
        feb = Window(datetime(2026, 2, 1), datetime(2026, 3, 1), "Feb")
        assert val(db, "active_members", window=jan).value == 1
        assert val(db, "active_members", window=feb).value == 0

    def test_the_window_is_half_open(self, db, make_user, make_space):
        """``ends_at`` is exclusive, so a boundary act lands in one period."""
        space = make_space(creator=make_user(role="creator"))
        member = make_user()
        _join(db, member, space)
        _post(db, space, member, when=datetime(2026, 2, 1))
        db.flush()
        jan = Window(datetime(2026, 1, 1), datetime(2026, 2, 1), "Jan")
        feb = Window(datetime(2026, 2, 1), datetime(2026, 3, 1), "Feb")
        assert val(db, "active_members", window=jan).value == 0
        assert val(db, "active_members", window=feb).value == 1

    def test_attendance_is_dated_by_the_gathering_not_the_register(
        self, db, make_user, make_space,
    ):
        """Avoids the timezone-aware ``attendance_marked_at`` column, and
        is the more meaningful date anyway."""
        space = make_space(creator=make_user(role="creator"))
        member = make_user()
        _join(db, member, space)
        ev = _gathering(db, space, starts_at=datetime(2026, 1, 20))
        b = _booking(db, ev, member, attended=True)
        b.attendance_marked_at = datetime(2026, 3, 5)  # marked much later
        db.flush()
        jan = Window(datetime(2026, 1, 1), datetime(2026, 2, 1), "Jan")
        mar = Window(datetime(2026, 3, 1), datetime(2026, 4, 1), "Mar")
        assert val(db, "active_members", window=jan).value == 1
        assert val(db, "active_members", window=mar).value == 0


# ---------------------------------------------------------------------------
# Returning participation
# ---------------------------------------------------------------------------

class TestReturningParticipation:
    def test_someone_active_in_both_periods_is_returning(
        self, db, make_user, make_space,
    ):
        space = make_space(creator=make_user(role="creator"))
        member = make_user()
        _join(db, member, space)
        ch = _channel(db, space)
        _post(db, space, member, when=datetime(2026, 1, 10), channel=ch)
        _post(db, space, member, when=datetime(2026, 2, 10), channel=ch)
        db.flush()
        feb = Window(datetime(2026, 2, 1), datetime(2026, 3, 1), "Feb")
        v = val(db, "returning_participants", window=feb)
        assert v.value == 1
        assert v.qualifiers["return_rate"] == 1.0

    def test_someone_active_only_now_is_not_returning(
        self, db, make_user, make_space,
    ):
        space = make_space(creator=make_user(role="creator"))
        member = make_user()
        _join(db, member, space)
        _post(db, space, member, when=datetime(2026, 2, 10))
        db.flush()
        feb = Window(datetime(2026, 2, 1), datetime(2026, 3, 1), "Feb")
        assert val(db, "returning_participants", window=feb).value == 0

    def test_it_is_unavailable_for_all_time_rather_than_zero(self, db):
        v = val(db, "returning_participants")
        assert v.value is None
        assert v.available is False
        assert "all time" in v.unavailable_reason.lower()


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------

class TestRates:
    def test_participation_rate_uses_people_not_memberships(
        self, db, make_user, make_space,
    ):
        """A person in three Collectives must not depress the rate."""
        person = make_user()
        for _ in range(3):
            sp = make_space(creator=make_user(role="creator"))
            _join(db, person, sp)
        _post(db, make_space(creator=make_user(role="creator")), person)
        db.flush()
        v = val(db, "participation_rate")
        assert v.qualifiers["unique_members"] == 1
        assert v.value == 1.0

    def test_the_rate_is_unavailable_with_no_members(self, db):
        v = val(db, "participation_rate")
        assert v.value is None
        assert v.available is False

    def test_overlap_versus_engagement_buckets_by_membership_count(
        self, db, make_user, make_space,
    ):
        a = make_space(creator=make_user(role="creator"))
        b = make_space(creator=make_user(role="creator"))
        single, both = make_user(), make_user()
        _join(db, single, a)
        _join(db, both, a); _join(db, both, b)
        _post(db, a, both)
        db.flush()
        v = val(db, "overlap_vs_engagement")
        buckets = v.qualifiers["by_membership_count"]
        assert buckets["1"]["members"] == 1 and buckets["1"]["active"] == 0
        assert buckets["2"]["members"] == 1 and buckets["2"]["active"] == 1

    def test_engagement_by_theme_warns_that_buckets_overlap(
        self, db, make_user, make_space,
    ):
        space = make_space(
            creator=make_user(role="creator"), themes=["Wellbeing", "Movement"],
        )
        member = make_user()
        _join(db, member, space)
        _post(db, space, member)
        db.flush()
        v = val(db, "engagement_by_theme")
        by_theme = v.qualifiers["active_members_by_theme"]
        assert by_theme["Wellbeing"] == 1
        assert by_theme["Movement"] == 1
        # One person, two buckets — hence the warning.
        assert v.value == 2
        assert "sum to more than" in v.qualifiers["note"]


# ---------------------------------------------------------------------------
# Cohorts
# ---------------------------------------------------------------------------

class TestRetentionCohorts:
    def test_a_cohort_is_reported_with_its_rate(self, db, make_user, make_space):
        space = make_space(creator=make_user(role="creator"))
        member = make_user()
        m = _join(db, member, space)
        m.joined_at = datetime(2026, 1, 15)
        _post(db, space, member, when=datetime(2026, 2, 10))
        db.flush()
        feb = Window(datetime(2026, 2, 1), datetime(2026, 3, 1), "Feb")
        v = val(db, "retention_cohorts", window=feb)
        jan = [c for c in v.qualifiers["cohorts"] if c["cohort"] == "2026-01"]
        assert jan and jan[0]["joined"] == 1 and jan[0]["active_in_period"] == 1
        assert jan[0]["rate"] == 1.0

    def test_it_states_its_own_historical_limitation(self, db, make_user, make_space):
        space = make_space(creator=make_user(role="creator"))
        _join(db, make_user(), space)
        db.flush()
        v = val(db, "retention_cohorts")
        assert "understate churn" in v.qualifiers["limitation"]

    def test_with_no_memberships_it_is_unavailable_not_zero(self, db):
        v = val(db, "retention_cohorts")
        assert v.value is None
        assert v.available is False


# ---------------------------------------------------------------------------
# Scoping and privacy
# ---------------------------------------------------------------------------

class TestEngagementScoping:
    def test_a_creator_sees_only_their_own_collectives_activity(
        self, db, make_user, make_space,
    ):
        a_creator, b_creator = make_user(role="creator"), make_user(role="creator")
        a, b = make_space(creator=a_creator), make_space(creator=b_creator)
        _join(db, a_creator, a, role=SpaceRole.creator)
        _join(db, b_creator, b, role=SpaceRole.creator)
        _post(db, a, make_user())
        _post(db, b, make_user())
        _post(db, b, make_user())
        db.commit()
        scope = creator_scope(db, a_creator.id)
        assert REGISTRY.get("participation_acts").evaluate(
            db, scope, ALL_TIME).value == 1
        assert val(db, "participation_acts").value == 3

    def test_platform_only_engagement_metrics_are_refused_to_a_creator(
        self, db, make_user,
    ):
        from app.reporting.scope import ScopeDenied

        scope = creator_scope(db, make_user(role="creator").id)
        for key in ("active_creators", "overlap_vs_engagement",
                    "engagement_by_theme", "retention_cohorts"):
            with pytest.raises(ScopeDenied):
                REGISTRY.get(key).evaluate(db, scope, ALL_TIME)

    def test_the_participation_union_reads_no_content_column(self):
        """Identifiers and timestamps only — never what anybody wrote."""
        import inspect

        from app.reporting import engagement

        src = inspect.getsource(engagement.participation_events)
        for forbidden in (
            ".body", "reflection_text", "exercise_response", "note",
            "message", "title",
        ):
            assert forbidden not in src, f"participation union selects {forbidden}"

    def test_every_engagement_metric_declares_its_aggregation(self):
        engagement_keys = {
            "active_members", "active_creators", "returning_participants",
            "participation_acts", "gathering_attendance",
            "pathway_steps_completed", "participation_rate",
            "overlap_vs_engagement", "engagement_by_theme", "retention_cohorts",
        }
        for key in engagement_keys:
            m = REGISTRY.get(key)
            assert isinstance(m.aggregation, Aggregation)
            if m.aggregation is Aggregation.distinct_count:
                assert m.limitations, f"{key} is a distinct count with no caveat"
