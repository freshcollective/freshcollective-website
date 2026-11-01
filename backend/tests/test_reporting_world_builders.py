"""World Builders reporting: reach, participation and development.

What these guard
----------------
The dashboard's value rests on three claims that are each easy to
break and hard to notice broken.

**It must stay out of Production.** World Builders is classified
``internal_operations`` so its activity never inflates the figures for
public Collectives. A dashboard built by relaxing that classification
would look right and quietly corrupt the other six.

**Eligible is not joined.** Membership is auto-granted, so a funnel
presenting "joined" as a stage would describe a decision nobody made.
The gap runs both ways and both directions are real.

**Taking part is not completing.** No reliable Pathway completion event
is emitted, so no figure here may imply one.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

import app.models.community_care  # noqa: F401
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.reporting.classification import INTERNAL_OPERATIONS, PRODUCTION
from app.reporting.population import Population, PopulationView
from app.reporting.registry import REGISTRY, Window
from app.reporting.scope import platform_scope
from app.services.creator_eligibility import AUTO_ROLE_SOURCE


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def world_builders(make_space):
    """A learning Collective, identified the way the product does.

    By ``auto_grant_role``, never by slug — the same structural lookup
    ``creator_eligibility`` and ``build_your_collective`` use.
    """
    return make_space(
        name="World Builders",
        auto_grant_role="creator",
        reporting_class=INTERNAL_OPERATIONS,
    )


def _auto_join(db, user, space):
    """The membership the auto-grant reconciler would write."""
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        source=AUTO_ROLE_SOURCE, joined_at=datetime(2026, 1, 1),
    ))
    db.flush()


def _post(db, user, space, when=datetime(2026, 6, 1)):
    channel = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="General",
        slug=f"general-{uuid.uuid4().hex[:6]}", channel_type="standard",
    )
    db.add(channel)
    db.flush()
    db.add(CommunityPost(
        id=_uid("cp"), space_id=space.id, author_id=user.id,
        body="x", channel_id=channel.id, created_at=when,
    ))
    db.flush()


def delta(db, key, before, window=None, population=None):
    """The change this test caused.

    ``fc_test`` is migration-seeded and already contains a learning
    Collective and at least one creator, so an absolute count here
    would be asserting on fixture data as much as on the code. Every
    count below is a delta against a baseline taken in the same test.
    """
    return ev(db, key, window, population).value - before


def _member_ids(db, view):
    """User ids holding an active membership inside a population."""
    from sqlalchemy import select

    from app.models.platform import Space

    pop = Population(view)
    q = select(SpaceMembership.user_id).where(
        SpaceMembership.status == SpaceMembershipStatus.active,
    )
    spaces = pop.space_id_select()
    if spaces is not None:
        q = q.where(SpaceMembership.space_id.in_(spaces))
    assert Space is not None
    return {r[0] for r in db.execute(q)}


def ev(db, key, window=None, population=None):
    return REGISTRY.get(key).evaluate(
        db, platform_scope(), window or Window(),
        population or Population(PopulationView.all),
    )


# ---------------------------------------------------------------------------


class TestItStaysOutOfProduction:
    """The classification is preserved, not worked around."""

    def test_world_builders_activity_is_absent_from_production(
        self, db, make_user, make_space, world_builders,
    ):
        learner = make_user(role="creator")
        _auto_join(db, learner, world_builders)

        public = make_space(reporting_class=PRODUCTION)
        _join = SpaceMembership(
            id=_uid("sm"), user_id=make_user().id, space_id=public.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime(2026, 1, 1),
        )
        db.add(_join)
        db.flush()

        production = ev(
            db, "unique_members",
            population=Population(PopulationView.production),
        )
        everything = ev(db, "unique_members")
        # The learner is in the ledger and not in Production.
        assert learner.id not in _member_ids(db, PopulationView.production)
        assert production.value < everything.value

    def test_the_learning_collective_keeps_its_classification(
        self, db, world_builders,
    ):
        """Nothing in reporting reclassifies it to make it visible."""
        db.refresh(world_builders)
        assert world_builders.reporting_class == INTERNAL_OPERATIONS

    def test_it_is_found_by_flag_rather_than_by_name(
        self, db, make_space, world_builders,
    ):
        from app.reporting.world_builders import learning_space_ids

        decoy = make_space(name="World Builders", reporting_class=PRODUCTION)
        found = {r[0] for r in db.execute(learning_space_ids())}
        assert world_builders.id in found
        # Same name, no auto-grant rule, so not a learning Collective.
        assert decoy.id not in found


class TestEligibilityIsNotMembership:
    def test_an_eligible_creator_is_counted_whether_or_not_joined(
        self, db, make_user, world_builders,
    ):
        before = ev(db, "wb_eligible_creators")
        make_user(role="creator")  # eligible, no membership row yet
        after = ev(db, "wb_eligible_creators")
        assert after.value - before.value == 1
        assert (
            after.qualifiers["eligible_without_membership"]
            - before.qualifiers["eligible_without_membership"]
        ) == 1

    def test_a_suspended_creator_is_not_eligible(self, db, make_user):
        before = ev(db, "wb_eligible_creators").value
        make_user(role="creator", creator_suspended_at=datetime(2026, 5, 1))
        assert delta(db, "wb_eligible_creators", before) == 0

    def test_a_cancelled_creator_is_not_eligible(self, db, make_user):
        before = ev(db, "wb_eligible_creators").value
        make_user(role="creator", creator_cancelled_at=datetime(2026, 5, 1))
        assert delta(db, "wb_eligible_creators", before) == 0

    def test_a_member_who_is_not_eligible_is_reported_not_hidden(
        self, db, make_user, world_builders,
    ):
        """The founder holds the admin role and still takes part."""
        before = ev(db, "wb_eligible_creators")
        founder = make_user(role="admin")
        _auto_join(db, founder, world_builders)
        after = ev(db, "wb_eligible_creators")
        assert after.value == before.value, "an admin is not auto-granted"
        assert (
            after.qualifiers["members_not_eligible"]
            - before.qualifiers["members_not_eligible"]
        ) == 1

    def test_eligibility_is_narrower_than_creator_accounts(
        self, db, make_user, make_space,
    ):
        """The two populations differ, and differ on purpose.

        The Creators dashboard widens to anybody operating a
        Collective so the founder stays visible; the auto-grant rule
        does not. Reporting one as the other would describe nothing.
        """
        eligible_before = ev(db, "wb_eligible_creators").value
        accounts_before = ev(db, "creator_accounts").value

        founder = make_user(role="admin")
        # make_space mints its own creator unless given one, which would
        # move both figures; this one is the founder's.
        make_space(creator=founder, reporting_class=PRODUCTION)

        # The founder is a creator account and is not auto-grant
        # eligible. That difference is the whole point of the metric.
        assert delta(db, "wb_eligible_creators", eligible_before) == 0
        assert delta(db, "creator_accounts", accounts_before) == 1


class TestParticipation:
    def test_distinct_people_not_acts(
        self, db, make_user, world_builders,
    ):
        before = ev(db, "wb_creator_participation").value
        busy = make_user(role="creator")
        for _ in range(4):
            _post(db, busy, world_builders)
        assert delta(db, "wb_creator_participation", before) == 1

    def test_membership_alone_is_not_participation(
        self, db, make_user, world_builders,
    ):
        """Auto-granted access is not evidence anybody used it."""
        before = ev(db, "wb_creator_participation").value
        _auto_join(db, make_user(role="creator"), world_builders)
        assert delta(db, "wb_creator_participation", before) == 0

    def test_activity_elsewhere_does_not_count(
        self, db, make_user, make_space, world_builders,
    ):
        before = ev(db, "wb_creator_participation").value
        elsewhere = make_space(reporting_class=PRODUCTION)
        _post(db, make_user(role="creator"), elsewhere)
        assert delta(db, "wb_creator_participation", before) == 0

    def test_founder_operated_and_independent_are_split(
        self, db, make_user, make_space, world_builders,
    ):
        before = ev(db, "wb_creator_participation")

        founder = make_user(role="admin")
        make_space(creator=founder, reporting_class=PRODUCTION)
        _post(db, founder, world_builders)

        independent = make_user(role="creator")
        make_space(creator=independent, reporting_class=PRODUCTION)
        _post(db, independent, world_builders)

        after = ev(db, "wb_creator_participation")
        assert after.value - before.value == 2
        assert (
            after.qualifiers["founder_operated"]
            - before.qualifiers["founder_operated"]
        ) == 1
        assert (
            after.qualifiers["independent"]
            - before.qualifiers["independent"]
        ) == 1

    def test_a_window_narrows_participation(
        self, db, make_user, world_builders,
    ):
        window = Window(
            starts_at=datetime(2026, 6, 1), ends_at=datetime(2026, 7, 1),
        )
        before = ev(db, "wb_creator_participation", window=window).value
        person = make_user(role="creator")
        _post(db, person, world_builders, when=datetime(2026, 1, 15))
        assert delta(db, "wb_creator_participation", before, window=window) == 0

    def test_the_shape_of_participation_is_reported(
        self, db, make_user, world_builders,
    ):
        before = ev(db, "wb_creator_participation").qualifiers[
            "distinct_people_by_kind"
        ]
        _post(db, make_user(role="creator"), world_builders)
        after = ev(db, "wb_creator_participation").qualifiers[
            "distinct_people_by_kind"
        ]
        assert after.get("conversation_post", 0) - before.get(
            "conversation_post", 0
        ) == 1


class TestNoCompletionClaim:
    def test_no_metric_counts_a_finished_pathway(self):
        """``ActivityType.pathway_completed`` is declared, never emitted.

        Asserted structurally rather than by scanning prose for the
        word "completed": the participation metric legitimately says
        "completed a Pathway **step**", and a blunt substring check
        would either fail on that correct sentence or be weakened
        until it caught nothing.
        """
        import app.reporting  # noqa: F401 — the full catalogue

        finished = [
            m.key
            for m in REGISTRY._metrics.values()
            if "pathway" in m.key and "complet" in m.key
        ]
        # Steps are real and counted; a finished Pathway is not.
        assert finished == ["pathway_steps_completed"]

    def test_participation_says_so_in_its_limitations(self):
        m = REGISTRY.get("wb_creator_participation")
        assert m.limitations is not None
        assert "completing" in m.limitations.lower()


class TestCreatorDevelopment:
    def test_it_describes_two_groups_without_claiming_cause(
        self, db, make_user, make_space, world_builders,
    ):
        before = ev(db, "wb_creator_development")

        took_part = make_user(role="creator")
        make_space(creator=took_part, reporting_class=PRODUCTION)
        _post(db, took_part, world_builders)

        after = ev(db, "wb_creator_development")
        assert after.value - before.value == 1
        assert (
            after.qualifiers["participated"]["has_collective"]
            - before.qualifiers["participated"]["has_collective"]
        ) == 1
        assert "not evidence" in after.qualifiers["comparison_note"]

    def test_milestones_without_dates_are_named_as_absent(self):
        v = REGISTRY.get("wb_creator_development")
        assert v.limitations is not None
        assert "publication date" in v.limitations

    def test_it_is_observation_only(self):
        """No milestone trend is drawn from records that cannot carry one."""
        assert REGISTRY.get("wb_creator_development").observation_only is True
        assert REGISTRY.get("wb_eligible_creators").observation_only is True


class TestPrivacyAndAuthorisation:
    def test_every_world_builders_metric_is_platform_only(self):
        from app.reporting.scope import Access

        for key in (
            "wb_eligible_creators",
            "wb_creator_participation",
            "wb_creator_development",
        ):
            assert REGISTRY.get(key).access is Access.platform_only

    def test_a_creator_scope_is_refused(self, db, make_user):
        from app.reporting.scope import Audience, ReportScope, ScopeDenied

        creator = ReportScope(audience=Audience.creator, user_id="u", space_ids=())
        for key in (
            "wb_eligible_creators",
            "wb_creator_participation",
            "wb_creator_development",
        ):
            with pytest.raises(ScopeDenied):
                REGISTRY.get(key).evaluate(
                    db, creator, Window(), Population(PopulationView.all),
                )

    def test_no_conversation_text_is_read(self):
        """Participation is counted from the act, never from its content."""
        src = open("app/reporting/world_builders.py").read()
        assert "CommunityPost.body" not in src
        assert ".body" not in src


class TestTheCollectiveFilterOnQuery:
    """``/query`` gained the Collective filter ``/history`` already had.

    A general capability rather than a World Builders one, tested here
    because this is the dashboard that needed it: without it the cards
    under a Collective's charts were computed across every Collective
    while the charts above them were not.
    """

    @pytest.fixture
    def client(self, db, make_user):
        from fastapi.testclient import TestClient

        from app.auth.dependencies import get_admin_user, get_current_user
        from app.core.database import get_db
        from app.main import app

        admin = make_user(role="admin")
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_admin_user] = lambda: admin
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_it_narrows_to_the_collective_asked_for(
        self, client, db, make_user, make_space, world_builders,
    ):
        _auto_join(db, make_user(role="creator"), world_builders)
        elsewhere = make_space(reporting_class=PRODUCTION)
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=make_user().id, space_id=elsewhere.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime(2026, 1, 1),
        ))
        db.flush()

        r = client.get(
            "/api/admin/reporting/query",
            params={
                "keys": "unique_members",
                "period": "all_time",
                "collectives": world_builders.id,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["metrics"][0]["value"] == 1

    def test_a_platform_only_metric_is_refused_with_a_reason(
        self, client, world_builders,
    ):
        """Never the platform total under one Collective's name."""
        r = client.get(
            "/api/admin/reporting/query",
            params={
                "keys": "registered_users",
                "period": "all_time",
                "collectives": world_builders.id,
            },
        )
        assert r.status_code == 200, r.text
        m = r.json()["metrics"][0]
        assert m["available"] is False
        assert m["value"] is None
        assert "whole platform" in m["unavailable_reason"]

    def test_an_unknown_collective_is_a_404_not_a_page_of_zeros(self, client):
        r = client.get(
            "/api/admin/reporting/query",
            params={"keys": "unique_members", "collectives": "s_nope"},
        )
        assert r.status_code == 404

    def test_omitting_it_still_answers_platform_wide(
        self, client, db, make_user, make_space, world_builders,
    ):
        _auto_join(db, make_user(role="creator"), world_builders)
        r = client.get(
            "/api/admin/reporting/query",
            params={"keys": "unique_members", "period": "all_time"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["metrics"][0]["value"] >= 1


class TestTheLearningEnvironmentIsDiscoverable:
    """The dashboard finds World Builders by its rule, not its name."""

    @pytest.fixture
    def client(self, db, make_user):
        from fastapi.testclient import TestClient

        from app.auth.dependencies import get_admin_user, get_current_user
        from app.core.database import get_db
        from app.main import app

        admin = make_user(role="admin")
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_admin_user] = lambda: admin
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_the_listing_marks_it(self, client, make_space, world_builders):
        decoy = make_space(name="World Builders", reporting_class=PRODUCTION)
        rows = {r["id"]: r for r in client.get(
            "/api/admin/reporting/collectives", params={"population": "all"},
        ).json()}
        assert rows[world_builders.id]["learning_environment"] is True
        # Same name, no auto-grant rule.
        assert rows[decoy.id]["learning_environment"] is False
