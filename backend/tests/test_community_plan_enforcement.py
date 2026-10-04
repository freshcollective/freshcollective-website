"""Community plan: self-serve activation + the limits the page advertises.

The public Community Collective page promises five things. Three were
already enforced before this suite existed (one Collective, five
Pathways, World Builders included); two were display copy only. These
tests cover the two that were added, the self-serve door that makes the
plan reachable without an admin, and the plan-resolution fallback the
whole design rests on.

Specifically:

* ``resolve_creator_plan`` returns Community for a creator with no
  subscription row — the reason self-serve activation does not need to
  write one (see ``app/creator/community_start.py``).
* ``guard_member_allowance`` enforces "Up to 100 members" against the
  *owning* creator's plan, counting the same active-learner predicate
  the public cards display.
* ``POST /api/creator/spaces/{slug}`` cannot be PATCHed from free to
  paid on a plan without ``paid_offers_enabled`` — the bypass that made
  "For non-commercial gatherings" unenforceable.
* ``POST /api/creator/community/start`` promotes a verified user, is
  idempotent, requires verification, and writes no subscription row.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_creator_user,
    get_current_user,
    get_verified_creator_user,
    get_verified_current_user,
)
from app.core.database import get_db
from app.creator.plan_config import get_plan_capability
from app.creator.plan_guards import (
    count_space_members,
    guard_member_allowance,
    guard_pathway_limit,
    resolve_creator_plan,
)
from app.main import app
from app.models.creator_billing import CreatorPlan, CreatorSubscription
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_members(db, space, count, *, role=SpaceRole.learner,
                 status=SpaceMembershipStatus.active, make_user=None):
    """Attach ``count`` memberships to ``space``. Each gets its own user so
    the (user_id, space_id) unique constraint is respected."""
    for _ in range(count):
        db.add(SpaceMembership(
            id=str(uuid.uuid4()),
            user_id=make_user().id,
            space_id=space.id,
            role=role,
            status=status,
            source="joined",
        ))
    db.flush()


@pytest.fixture
def plans(db):
    """Ensure the three self-service creator_plans rows exist.

    Production gets these from migration 068 (which INSERTs Community and
    renames the two paid rows), but the test database is bootstrapped from
    a schema dump taken *past* that revision, so the forward INSERT never
    ran here and the table starts empty. Seeding explicitly keeps these
    tests independent of bootstrap vintage.

    Prices matter: the Community fallback in ``resolve_creator_plan`` picks
    the *cheapest active* plan, so Community must be the cheapest.
    """
    rows = [
        ("plan-community-test", "Community", "community", 0, 1),
        ("plan-creator-test", "Creator", "creator", 1900, 3),
        ("plan-pro-test", "Pro", "pro", 7900, 10),
    ]
    created = []
    for pid, name, slug, cents, collective_limit in rows:
        existing = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
        if existing is not None:
            continue
        plan = CreatorPlan(
            id=pid,
            name=name,
            slug=slug,
            monthly_price_cents=cents,
            currency="AUD",
            transaction_fee_basis_points=0,
            collective_limit=collective_limit,
            is_active=True,
        )
        db.add(plan)
        created.append(plan)
    db.flush()
    return created


def _subscribe(db, user, slug):
    """Give ``user`` an active subscription to the plan with ``slug``."""
    plan = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
    assert plan is not None, f"no creator_plans row for slug={slug!r}"
    sub = CreatorSubscription(
        id=str(uuid.uuid4()),
        user_id=user.id,
        creator_plan_id=plan.id,
        status="active",
    )
    db.add(sub)
    db.flush()
    return sub


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear the community-start rate limiter between tests.

    ``/api/creator/community/start`` is limited to 5/minute per caller
    IP, and TestClient presents a single fixed IP, so the whole module
    shares one budget. Without this reset the tests below sit exactly on
    the limit and the next one anybody adds turns the suite flaky with a
    429 that looks like a real failure. Rate limiting itself is verified
    deliberately in ``test_rate_limit_is_enforced``.
    """
    from app.creator.community_start import limiter
    try:
        limiter.reset()
    except Exception:
        # Storage backends without reset() (or none configured) are fine
        # to skip — the tests simply run against a shared budget again.
        pass
    yield


@pytest.fixture
def client(db):
    def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app, follow_redirects=False)
    for dep in (get_db, get_creator_user, get_verified_creator_user,
                get_current_user, get_verified_current_user):
        app.dependency_overrides.pop(dep, None)


# ---------------------------------------------------------------------------
# The fallback the whole free-plan design rests on
# ---------------------------------------------------------------------------


class TestPlanResolutionFallback:
    def test_creator_without_subscription_resolves_to_community(self, plans, db, make_user):
        """No subscription row → cheapest active plan → Community ($0).

        This is why ``/api/creator/community/start`` does not write a
        CreatorSubscription: the guards already treat a bare creator as
        a Community creator.
        """
        creator = make_user(role="creator")
        plan = resolve_creator_plan(creator, db)
        assert plan is not None
        assert plan.slug == "community"
        assert plan.monthly_price_cents == 0

    def test_community_capability_matches_the_advertised_limits(self):
        """The page's bullets and the capability record must not drift."""
        cap = get_plan_capability("community")
        assert cap is not None
        assert cap.active_collective_limit == 1          # "One Collective"
        assert cap.member_allowance_per_collective == 100  # "Up to 100 members"
        assert cap.pathways_max_per_collective == 5      # "Up to 5 Pathways"
        assert cap.paid_offers_enabled is False          # "non-commercial"
        assert cap.commercial_use is False

    def test_platform_owner_has_no_plan(self, db, make_user):
        owner = make_user(role="admin")
        assert resolve_creator_plan(owner, db) is None


# ---------------------------------------------------------------------------
# "Up to 100 members"
# ---------------------------------------------------------------------------


class TestMemberAllowance:
    def test_under_the_cap_is_allowed(self, plans, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _add_members(db, space, 99, make_user=make_user)
        guard_member_allowance(space, db)   # does not raise

    def test_at_the_cap_is_refused(self, plans, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _add_members(db, space, 100, make_user=make_user)
        with pytest.raises(HTTPException) as exc:
            guard_member_allowance(space, db)
        assert exc.value.status_code == 403

    def test_visitor_message_does_not_leak_the_owners_plan(self, plans, db, make_user, make_space):
        """A stranger joining must not be able to read the creator's tier."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _add_members(db, space, 100, make_user=make_user)
        with pytest.raises(HTTPException) as exc:
            guard_member_allowance(space, db, for_creator=False)
        assert "Community" not in str(exc.value.detail)
        assert "plan" not in str(exc.value.detail).lower()

    def test_creator_message_names_the_plan_and_limit(self, plans, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _add_members(db, space, 100, make_user=make_user)
        with pytest.raises(HTTPException) as exc:
            guard_member_allowance(space, db, for_creator=True)
        detail = str(exc.value.detail)
        assert "Community" in detail
        assert "100" in detail

    def test_caretakers_do_not_count_as_members(self, plans, db, make_user, make_space):
        """Moderators and co-creators are not members for allowance purposes —
        they are counted by caretaker_limit_per_collective instead."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _add_members(db, space, 99, make_user=make_user)
        _add_members(db, space, 5, role=SpaceRole.moderator, make_user=make_user)
        _add_members(db, space, 5, role=SpaceRole.creator, make_user=make_user)
        assert count_space_members(space, db) == 99
        guard_member_allowance(space, db)   # still under the cap

    def test_paused_and_removed_members_do_not_count(self, plans, db, make_user, make_space):
        """Freeing a seat by removing someone must actually free it."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _add_members(db, space, 99, make_user=make_user)
        _add_members(db, space, 10, status=SpaceMembershipStatus.removed,
                     make_user=make_user)
        _add_members(db, space, 10, status=SpaceMembershipStatus.paused,
                     make_user=make_user)
        assert count_space_members(space, db) == 99
        guard_member_allowance(space, db)

    def test_auto_managed_collective_bypasses(self, plans, db, make_user, make_space):
        """World Builders membership is computed from eligibility, not
        admitted, so the cap must not apply to it."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, auto_grant_role="creator")
        _add_members(db, space, 150, make_user=make_user)
        guard_member_allowance(space, db)   # does not raise

    def test_platform_owner_collective_is_uncapped(self, plans, db, make_user, make_space):
        owner = make_user(role="admin")
        space = make_space(creator=owner)
        _add_members(db, space, 150, make_user=make_user)
        guard_member_allowance(space, db)   # no plan applies to an owner

    def test_paid_plan_has_a_higher_cap(self, plans, db, make_user, make_space):
        """A Creator-plan Collective is not blocked at Community's 100."""
        creator = make_user(role="creator")
        _subscribe(db, creator, "creator")
        space = make_space(creator=creator)
        _add_members(db, space, 100, make_user=make_user)
        guard_member_allowance(space, db)   # Creator allows 500

    def test_the_cap_is_the_owners_plan_not_the_joiners(self, plans, db, make_user, make_space):
        """A Pro-plan visitor joining a Community Collective is still bound
        by the Community owner's allowance."""
        community_owner = make_user(role="creator")
        space = make_space(creator=community_owner)
        _add_members(db, space, 100, make_user=make_user)
        pro_joiner = make_user(role="creator")
        _subscribe(db, pro_joiner, "pro")
        with pytest.raises(HTTPException) as exc:
            guard_member_allowance(space, db)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# "For non-commercial gatherings" — the update-path bypass
# ---------------------------------------------------------------------------


class TestNonCommercialEnforcement:
    def test_community_creator_cannot_patch_a_collective_to_paid(
        self, plans, db, client, make_user, make_space,
    ):
        """The bypass: create free (allowed), then PATCH to paid.

        Before the guard was added on the update path this returned 200
        and the Collective became commercial on a non-commercial plan.
        """
        creator = make_user(role="creator")
        space = make_space(creator=creator, pricing_type="free")
        app.dependency_overrides[get_verified_creator_user] = lambda: creator
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.patch(
            f"/api/creator/spaces/{space.slug}",
            json={"pricing_type": "paid_monthly"},
        )
        assert res.status_code == 403, res.text
        db.refresh(space)
        assert space.pricing_type == "free"

    def test_community_creator_can_still_patch_other_fields(
        self, plans, db, client, make_user, make_space,
    ):
        """The guard must only fire on pricing_type, not block ordinary edits."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, pricing_type="free")
        app.dependency_overrides[get_verified_creator_user] = lambda: creator
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.patch(
            f"/api/creator/spaces/{space.slug}",
            json={"name": "Renamed Collective"},
        )
        assert res.status_code == 200, res.text

    def test_community_creator_can_set_pricing_type_free(
        self, plans, db, client, make_user, make_space,
    ):
        """Re-asserting 'free' is not a commercial action."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, pricing_type="free")
        app.dependency_overrides[get_verified_creator_user] = lambda: creator
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.patch(
            f"/api/creator/spaces/{space.slug}",
            json={"pricing_type": "free"},
        )
        assert res.status_code == 200, res.text

    def test_paid_plan_creator_may_patch_to_paid(
        self, plans, db, client, make_user, make_space,
    ):
        """The guard must not catch creators whose plan does allow selling."""
        creator = make_user(role="creator")
        _subscribe(db, creator, "creator")
        space = make_space(creator=creator, pricing_type="free")
        app.dependency_overrides[get_verified_creator_user] = lambda: creator
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.patch(
            f"/api/creator/spaces/{space.slug}",
            json={"pricing_type": "paid_monthly"},
        )
        assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# Self-serve activation
# ---------------------------------------------------------------------------


class TestCommunityStart:
    def test_verified_user_becomes_a_creator(self, plans, db, client, make_user):
        user = make_user(role="user")
        app.dependency_overrides[get_verified_current_user] = lambda: user

        res = client.post("/api/creator/community/start")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["started"] is True
        assert body["already_creator"] is False
        assert body["plan_slug"] == "community"
        assert body["next"] == "/creator-onboarding"
        db.refresh(user)
        assert user.role == "creator"

    def test_writes_no_subscription_row(self, plans, db, client, make_user):
        """Deliberate: a Community row would make the later paid upgrade
        raise ActivationConflictError after the card had been charged."""
        user = make_user(role="user")
        app.dependency_overrides[get_verified_current_user] = lambda: user

        client.post("/api/creator/community/start")
        subs = (
            db.query(CreatorSubscription)
            .filter(CreatorSubscription.user_id == user.id)
            .all()
        )
        assert subs == []

    def test_is_idempotent(self, plans, db, client, make_user):
        user = make_user(role="user")
        app.dependency_overrides[get_verified_current_user] = lambda: user

        first = client.post("/api/creator/community/start")
        second = client.post("/api/creator/community/start")
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["already_creator"] is False
        assert second.json()["already_creator"] is True
        db.refresh(user)
        assert user.role == "creator"

    def test_does_not_downgrade_a_platform_owner(self, plans, db, client, make_user):
        """Regression guard for the 2026-09-15 incident: an admin calling
        this must keep admin, not be rewritten to 'creator'."""
        owner = make_user(role="admin")
        app.dependency_overrides[get_verified_current_user] = lambda: owner

        res = client.post("/api/creator/community/start")
        assert res.status_code == 200, res.text
        db.refresh(owner)
        assert owner.role == "admin"
        # An owner belongs to no creator plan.
        assert res.json()["plan_slug"] is None

    def test_unverified_user_is_refused(self, plans, db, client, make_user):
        """SEC-009 — activation is a trust action. Granting the role to an
        unverified account would dead-end at the first Collective write."""
        user = make_user(role="user", email_verified_at=None)
        # No override: exercise the real get_verified_current_user chain by
        # overriding only the authentication step beneath it.
        app.dependency_overrides[get_current_user] = lambda: user

        res = client.post("/api/creator/community/start")
        assert res.status_code == 403, res.text

    def test_requires_authentication(self, client):
        res = client.post("/api/creator/community/start")
        assert res.status_code in (401, 403), res.text

    def test_rate_limit_is_enforced(self, plans, db, client, make_user):
        """Repeated self-serve activation is rate-limited per caller IP.

        Part of the abuse surface: without this, the endpoint is a cheap
        way to churn accounts into Creator capability. Promotion itself is
        idempotent, so the limit is about request volume, not state.
        """
        user = make_user(role="user")
        app.dependency_overrides[get_verified_current_user] = lambda: user

        codes = [
            client.post("/api/creator/community/start").status_code
            for _ in range(8)
        ]
        assert 429 in codes, f"expected a 429 within 8 rapid calls, got {codes}"


# ---------------------------------------------------------------------------
# The guard must be WIRED, not merely correct
# ---------------------------------------------------------------------------


class TestMemberAllowanceIsWiredIntoRoutes:
    """Unit-testing the guard proves it works; these prove it is called.

    The four paths that admit a new active learner are the public join,
    invitation acceptance, creator approval of an access request, and the
    creator adding someone directly. A guard wired into only some of them
    is a guard with a door left open.
    """

    def test_public_join_is_refused_at_the_cap(
        self, plans, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, is_public=True, join_policy="open")
        _add_members(db, space, 100, make_user=make_user)
        joiner = make_user()
        app.dependency_overrides[get_verified_current_user] = lambda: joiner

        res = client.post(f"/api/spaces/{space.slug}/join")
        assert res.status_code == 403, res.text
        # Neutral message — a stranger must not learn the owner's tier.
        assert "Community" not in res.text

    def test_public_join_succeeds_under_the_cap(
        self, plans, db, client, make_user, make_space,
    ):
        """The guard must not break ordinary joining."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, is_public=True, join_policy="open")
        _add_members(db, space, 99, make_user=make_user)
        joiner = make_user()
        app.dependency_overrides[get_verified_current_user] = lambda: joiner

        res = client.post(f"/api/spaces/{space.slug}/join")
        assert res.status_code == 201, res.text
        assert count_space_members(space, db) == 100

    def test_existing_member_is_never_locked_out(
        self, plans, db, client, make_user, make_space,
    ):
        """Re-joining at capacity must return already_member, not 403 —
        the guard sits after the existing-membership check for this reason."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, is_public=True, join_policy="open")
        _add_members(db, space, 99, make_user=make_user)
        member = make_user()
        db.add(SpaceMembership(
            id=str(uuid.uuid4()),
            user_id=member.id,
            space_id=space.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            source="joined",
        ))
        db.flush()
        assert count_space_members(space, db) == 100   # at the cap
        app.dependency_overrides[get_verified_current_user] = lambda: member

        res = client.post(f"/api/spaces/{space.slug}/join")
        assert res.status_code == 201, res.text
        assert res.json()["already_member"] is True

    def test_creator_adding_a_member_is_refused_at_the_cap(
        self, plans, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _add_members(db, space, 100, make_user=make_user)
        invitee = make_user()
        app.dependency_overrides[get_verified_creator_user] = lambda: creator
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.post(
            f"/api/creator/spaces/{space.slug}/members/add",
            json={"email": invitee.email, "role": "learner"},
        )
        assert res.status_code == 403, res.text
        # The creator IS the audience here, so the limit is named.
        assert "100" in res.text

    def test_creator_may_still_add_a_moderator_at_the_cap(
        self, plans, db, client, make_user, make_space,
    ):
        """Caretakers are not members for allowance purposes, so a full
        Collective can still gain a moderator."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _add_members(db, space, 100, make_user=make_user)
        helper = make_user()
        app.dependency_overrides[get_verified_creator_user] = lambda: creator
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.post(
            f"/api/creator/spaces/{space.slug}/members/add",
            json={"email": helper.email, "role": "moderator"},
        )
        assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# "Up to 5 Pathways"
# ---------------------------------------------------------------------------


class TestPathwayLimit:
    """``guard_pathway_limit`` existed with a live call site but had no
    behavioural coverage — only config invariants. "Up to 5 Pathways" is
    one of the five promises the public page makes, so it gets tested
    here alongside the others rather than being taken on trust.
    """

    @staticmethod
    def _add_pathways(db, space, count):
        from app.models.platform import Pathway
        for i in range(count):
            db.add(Pathway(
                id=str(uuid.uuid4()),
                space_id=space.id,
                slug=f"p-{uuid.uuid4().hex[:8]}",
                title=f"Pathway {i}",
            ))
        db.flush()

    def test_under_the_cap_is_allowed(self, plans, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        self._add_pathways(db, space, 4)
        guard_pathway_limit(creator, space, db)   # does not raise

    def test_at_the_cap_is_refused(self, plans, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        self._add_pathways(db, space, 5)
        with pytest.raises(HTTPException) as exc:
            guard_pathway_limit(creator, space, db)
        assert exc.value.status_code == 403
        assert "5 Pathways" in str(exc.value.detail)

    def test_paid_plan_is_uncapped(self, plans, db, make_user, make_space):
        creator = make_user(role="creator")
        _subscribe(db, creator, "creator")
        space = make_space(creator=creator)
        self._add_pathways(db, space, 12)
        guard_pathway_limit(creator, space, db)   # Creator has no cap

    def test_platform_owner_is_uncapped(self, plans, db, make_user, make_space):
        owner = make_user(role="admin")
        space = make_space(creator=owner)
        self._add_pathways(db, space, 12)
        guard_pathway_limit(owner, space, db)
