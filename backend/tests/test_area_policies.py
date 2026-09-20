"""Who may reach each area of a Collective.

The doorway, not the lock behind it. These tests care about whether an
area answers at all; whether a particular Pathway opens or a particular
Gathering can be booked is covered by the entitlement tests beside
them and is deliberately untouched here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.access_pass import (
    AccessPass, AccessPassSource, AccessPassStatus, AccessPassType,
)
from app.models.platform import (
    EntitlementSource, EntitlementStatus, PathwayEntitlement, SpaceMembership,
)
from app.spaces import area_policies as ap
from app.spaces.area_access import resolve_area_access


def join(db, user, space, role="learner", status="active"):
    db.add(SpaceMembership(
        id=str(uuid.uuid4()), user_id=user.id, space_id=space.id,
        role=role, status=status,
    ))
    db.flush()


def give_pass(db, user, space, *, status=AccessPassStatus.active, valid_until=None):
    db.add(AccessPass(
        id=f"ap_{uuid.uuid4().hex[:16]}", user_id=user.id, space_id=space.id,
        pass_type=AccessPassType.term_pass, status=status,
        source=AccessPassSource.one_time_purchase,
        valid_from=datetime.utcnow() - timedelta(days=1), valid_until=valid_until,
    ))
    db.flush()


def give_entitlement(db, user, space, pathway_id, *,
                     status=EntitlementStatus.active, ends_at=None,
                     source=EntitlementSource.one_time_purchase):
    db.add(PathwayEntitlement(
        id=str(uuid.uuid4()), user_id=user.id, space_id=space.id,
        pathway_id=pathway_id, source=source, status=status,
        starts_at=datetime.utcnow() - timedelta(days=1), ends_at=ends_at,
    ))
    db.flush()


@pytest.fixture
def pathway(db, make_space):
    from app.models.platform import Pathway
    def _make(space):
        p = Pathway(id=str(uuid.uuid4()), space_id=space.id,
                    slug=f"p-{uuid.uuid4().hex[:6]}", title="A Pathway",
                    status="active")
        db.add(p); db.flush()
        return p
    return _make


# ---------------------------------------------------------------------------
# Vocabulary and storage
# ---------------------------------------------------------------------------


class TestVocabulary:
    def test_three_policies_and_no_more(self):
        assert ap.POLICY_ORDER == ("public", "members", "active_access")

    def test_fixed_areas_offer_exactly_one_choice(self):
        """About, Home and Messages are not creator decisions."""
        assert ap.AREA_ALLOWED[ap.AREA_ABOUT] == (ap.POLICY_PUBLIC,)
        assert ap.AREA_ALLOWED[ap.AREA_HOME] == (ap.POLICY_MEMBERS,)
        assert ap.AREA_ALLOWED[ap.AREA_MESSAGES] == (ap.POLICY_MEMBERS,)
        for fixed in (ap.AREA_ABOUT, ap.AREA_HOME, ap.AREA_MESSAGES):
            assert fixed not in ap.CONFIGURABLE_AREAS

    def test_conversations_and_members_are_never_public(self):
        for area in (ap.AREA_CONVERSATIONS, ap.AREA_MEMBERS):
            assert ap.POLICY_PUBLIC not in ap.AREA_ALLOWED[area]

    def test_defaults_are_todays_behaviour(self):
        """Pathways stay public. Quietly privatising every Collective's
        Pathway list would be a worse regression than the
        inconsistency it tidies."""
        assert ap.AREA_DEFAULTS == {
            "about": "public", "home": "members", "gatherings": "members",
            "pathways": "public", "conversations": "members",
            "members": "members", "messages": "members",
        }


class TestStorage:
    def test_null_gives_the_platform_defaults(self):
        assert ap.resolve_policies(None) == ap.AREA_DEFAULTS

    def test_a_missing_area_takes_its_default(self):
        got = ap.resolve_policies({"areas": {"gatherings": "public"}})
        assert got["gatherings"] == "public"
        assert got["pathways"] == "public"
        assert got["conversations"] == "members"

    def test_an_unknown_area_is_ignored_not_fatal(self):
        cfg = ap.validate({"areas": {"gatherings": "public", "teleporter": "public"}})
        assert cfg == {"areas": {"gatherings": "public"}}

    @pytest.mark.parametrize("bad", [
        {"areas": {"gatherings": "everyone"}},
        {"areas": {"conversations": "public"}},
        {"areas": {"about": "members"}},
        {"areas": {"messages": "active_access"}},
        {"areas": {"gatherings": 3}},
        {"areas": "nope"},
        "nope",
    ])
    def test_an_invalid_policy_is_refused_on_write(self, bad):
        with pytest.raises(ap.AreaPolicyError):
            ap.validate(bad)

    def test_nothing_usable_stores_nothing(self):
        assert ap.validate({"areas": {}}) is None
        assert ap.validate({"areas": {"teleporter": "public"}}) is None
        assert ap.validate(None) is None

    def test_an_invalid_stored_value_fails_closed(self):
        """Not to the default — to the strictest the area allows. A
        corrupt byte must shut a door, never open one."""
        got = ap.resolve_policies({"areas": {"pathways": "everyone"}})
        assert got["pathways"] == "active_access"
        got = ap.resolve_policies({"areas": {"gatherings": None}})
        assert got["gatherings"] == "active_access"

    def test_the_access_query_is_skipped_when_nothing_needs_it(self):
        assert ap.requires_active_access(None) is False
        assert ap.requires_active_access({"areas": {"gatherings": "members"}}) is False
        assert ap.requires_active_access({"areas": {"pathways": "active_access"}}) is True


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------


ALL_ACTIVE = {"areas": {
    "gatherings": "active_access", "pathways": "active_access",
    "conversations": "active_access", "members": "active_access",
}}


class TestResolverByViewer:
    def test_a_visitor_reaches_only_public_areas(self, db, make_space):
        space = make_space(is_public=True, show_member_directory=True)
        db.flush()
        access = resolve_area_access(db, space, None)
        assert access.can_reach("about")
        assert access.can_reach("pathways")      # default public
        for closed in ("home", "gatherings", "conversations", "members", "messages"):
            assert not access.can_reach(closed), closed

    def test_a_signed_in_non_member_is_still_a_visitor(
        self, db, make_space, make_user,
    ):
        space = make_space(is_public=True, show_member_directory=True)
        stranger = make_user(role="user")
        db.flush()
        access = resolve_area_access(db, space, stranger)
        assert not access.can_reach("conversations")
        assert not access.can_reach("home")

    def test_an_ordinary_member_reaches_the_members_areas(
        self, db, make_space, make_user,
    ):
        space = make_space(is_public=True, show_member_directory=True)
        member = make_user(role="user")
        join(db, member, space)
        access = resolve_area_access(db, space, member)
        for area in ("about", "home", "gatherings", "pathways",
                     "conversations", "members", "messages"):
            assert access.can_reach(area), area

    def test_a_member_without_access_misses_the_entitled_areas(
        self, db, make_space, make_user,
    ):
        space = make_space(is_public=True, show_member_directory=True,
                           area_policies=ALL_ACTIVE)
        member = make_user(role="user")
        join(db, member, space)
        access = resolve_area_access(db, space, member)
        assert access.can_reach("home"), "a lapsed member must still land somewhere"
        assert access.can_reach("about")
        assert access.can_reach("messages"), "and still be able to ask for help"
        for gated in ("gatherings", "pathways", "conversations", "members"):
            assert not access.can_reach(gated), gated

    def test_an_active_pass_opens_them(self, db, make_space, make_user):
        space = make_space(is_public=True, show_member_directory=True,
                           area_policies=ALL_ACTIVE)
        member = make_user(role="user")
        join(db, member, space)
        give_pass(db, member, space)
        access = resolve_area_access(db, space, member)
        assert access.has_active_access
        for area in ("gatherings", "pathways", "conversations", "members"):
            assert access.can_reach(area), area

    def test_an_active_entitlement_opens_them_too(
        self, db, make_space, make_user, pathway,
    ):
        space = make_space(is_public=True, show_member_directory=True,
                           area_policies=ALL_ACTIVE)
        member = make_user(role="user")
        join(db, member, space)
        give_entitlement(db, member, space, pathway(space).id)
        assert resolve_area_access(db, space, member).has_active_access

    @pytest.mark.parametrize("source", [
        EntitlementSource.manual_grant, EntitlementSource.admin,
        EntitlementSource.free, EntitlementSource.included,
    ])
    def test_a_granted_entitlement_counts_exactly_like_a_bought_one(
        self, db, make_space, make_user, pathway, source,
    ):
        """Access is a row's state, never a payment history. A
        complimentary place is a real place."""
        space = make_space(is_public=True, area_policies=ALL_ACTIVE)
        member = make_user(role="user")
        join(db, member, space)
        give_entitlement(db, member, space, pathway(space).id, source=source)
        assert resolve_area_access(db, space, member).has_active_access

    @pytest.mark.parametrize("status", [
        AccessPassStatus.expired, AccessPassStatus.cancelled,
        AccessPassStatus.suspended, AccessPassStatus.pending,
    ])
    def test_a_pass_that_is_not_active_does_not_count(
        self, db, make_space, make_user, status,
    ):
        space = make_space(is_public=True, area_policies=ALL_ACTIVE)
        member = make_user(role="user")
        join(db, member, space)
        give_pass(db, member, space, status=status)
        assert not resolve_area_access(db, space, member).has_active_access

    def test_an_expired_pass_does_not_count(self, db, make_space, make_user):
        space = make_space(is_public=True, area_policies=ALL_ACTIVE)
        member = make_user(role="user")
        join(db, member, space)
        give_pass(db, member, space,
                  valid_until=datetime.utcnow() - timedelta(days=1))
        assert not resolve_area_access(db, space, member).has_active_access

    def test_a_pass_for_a_future_term_does_count(self, db, make_space, make_user):
        """Bought next term in September; they hold it now."""
        space = make_space(is_public=True, area_policies=ALL_ACTIVE)
        member = make_user(role="user")
        join(db, member, space)
        give_pass(db, member, space,
                  valid_until=datetime.utcnow() + timedelta(days=90))
        assert resolve_area_access(db, space, member).has_active_access

    @pytest.mark.parametrize("status", [
        EntitlementStatus.revoked, EntitlementStatus.expired,
        EntitlementStatus.cancelled, EntitlementStatus.pending,
    ])
    def test_a_revoked_entitlement_does_not_count(
        self, db, make_space, make_user, pathway, status,
    ):
        space = make_space(is_public=True, area_policies=ALL_ACTIVE)
        member = make_user(role="user")
        join(db, member, space)
        give_entitlement(db, member, space, pathway(space).id, status=status)
        assert not resolve_area_access(db, space, member).has_active_access

    def test_membership_alone_is_not_access(self, db, make_space, make_user):
        space = make_space(is_public=True, area_policies=ALL_ACTIVE)
        member = make_user(role="user")
        join(db, member, space)
        assert not resolve_area_access(db, space, member).has_active_access

    def test_access_does_not_bleed_between_collectives(
        self, db, make_space, make_user,
    ):
        mine = make_space(is_public=True, area_policies=ALL_ACTIVE)
        theirs = make_space(is_public=True)
        member = make_user(role="user")
        join(db, member, mine)
        give_pass(db, member, theirs)   # access somewhere else entirely
        assert not resolve_area_access(db, mine, member).has_active_access


class TestLeadersAndAdmins:
    def test_the_owner_reaches_everything_without_a_pass(
        self, db, make_space, make_user,
    ):
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner,
                           show_member_directory=True, area_policies=ALL_ACTIVE)
        db.flush()
        access = resolve_area_access(db, space, owner)
        for area in ("gatherings", "pathways", "conversations", "members"):
            assert access.can_reach(area), area

    def test_a_moderator_does_too(self, db, make_space, make_user):
        space = make_space(is_public=True, show_member_directory=True,
                           area_policies=ALL_ACTIVE)
        mod = make_user(role="user")
        join(db, mod, space, role="moderator")
        assert resolve_area_access(db, space, mod).can_reach("pathways")

    def test_a_platform_admin_does_too(self, db, make_space, make_user):
        space = make_space(is_public=True, show_member_directory=True,
                           area_policies=ALL_ACTIVE)
        admin = make_user(role="admin")
        db.flush()
        assert resolve_area_access(db, space, admin).can_reach("conversations")

    def test_leaders_are_not_asked_the_access_question_at_all(
        self, db, make_space, make_user,
    ):
        """Cost, and meaning: administering a Collective is not access."""
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner, area_policies=ALL_ACTIVE)
        db.flush()
        access = resolve_area_access(db, space, owner)
        assert access.active_access_evaluated is False


class TestQueryCost:
    def test_no_access_query_when_no_area_needs_one(
        self, db, make_space, make_user,
    ):
        """Every Collective today. The resolver must not cost them a
        query for a feature they do not use."""
        space = make_space(is_public=True)
        member = make_user(role="user")
        join(db, member, space)
        access = resolve_area_access(db, space, member)
        assert access.active_access_evaluated is False

    def test_the_query_runs_when_an_area_needs_it(
        self, db, make_space, make_user,
    ):
        space = make_space(is_public=True,
                           area_policies={"areas": {"pathways": "active_access"}})
        member = make_user(role="user")
        join(db, member, space)
        assert resolve_area_access(db, space, member).active_access_evaluated is True

    def test_a_visitor_is_never_asked(self, db, make_space):
        space = make_space(is_public=True, area_policies=ALL_ACTIVE)
        db.flush()
        assert resolve_area_access(db, space, None).active_access_evaluated is False


class TestDirectoryPrivacyComposes:
    def test_an_area_policy_cannot_open_a_closed_directory(
        self, db, make_space, make_user,
    ):
        """The tile and the tab still disappear — that rule lives in
        home_config.resolve and SpaceNav, both of which take
        show_member_directory. Policy never overrides it."""
        from app.spaces import home_config
        space = make_space(is_public=True, show_member_directory=False,
                           area_policies={"areas": {"members": "members"}})
        member = make_user(role="user")
        join(db, member, space)
        access = resolve_area_access(db, space, member)
        tiles = home_config.resolve(
            None, show_member_directory=space.show_member_directory,
            reachable_areas=access.reachable,
        )
        assert "members" not in [t["key"] for t in tiles]

    def test_but_a_member_can_still_find_the_leaders(
        self, db, make_space, make_user,
    ):
        """A closed directory hides learners from each other; it is not
        a wall around the people running the Collective."""
        space = make_space(is_public=True, show_member_directory=False)
        member = make_user(role="user")
        join(db, member, space)
        assert resolve_area_access(db, space, member).can_reach("members")
