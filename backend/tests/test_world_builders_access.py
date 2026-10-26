"""World Builders — auto-grant access lifecycle tests.

Covers the ``services.creator_eligibility`` reconciler + the route
guards that keep an auto-grant collective off the public join flow.

The reconciler is the beating heart of the feature; each of the
lifecycle transitions in its docstring is exercised here as a
separate test. The route guards are tested by direct FastAPI
handler calls (matching the pattern used elsewhere in this suite).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.admin.service import set_user_role
from app.models.platform import (
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import UserRole
from app.services.creator_eligibility import (
    AUTO_ROLE_SOURCE,
    apply_creator_eligibility_change,
    is_eligible_creator,
    reconcile_at_session_time,
)
from app.creator.routes import update_space
from app.creator.schemas import SpaceUpdateRequest
from app.spaces.routes import join_space, list_public_spaces


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def world_builders(db, make_user):
    """Create a World-Builders-style auto-grant space owned by an admin.
    Not necessarily slug='world-builders' — the reconciler discovers
    the space by ``auto_grant_role``, not by slug."""
    owner = make_user(role="admin")
    space = Space(
        id=f"s_{uuid.uuid4().hex[:12]}",
        slug=f"wb-{uuid.uuid4().hex[:8]}",
        name="World Builders",
        status="draft",
        is_public=False,
        creator_id=owner.id,
        auto_grant_role=UserRole.creator.value,
    )
    db.add(space)
    db.flush()
    return space


@pytest.fixture
def seeded_world_builders(db):
    """The **real** ``world-builders`` row, which the migrations seed.

    Used rather than a fresh fixture for the discovery tests, because
    the exception is keyed on that exact slug and a randomised one
    would not qualify — and because testing the actual row is what
    makes these tests evidence about production rather than about a
    stand-in. The savepoint fixture rolls back any field this sets.
    """
    space = db.query(Space).filter(Space.slug == "world-builders").one_or_none()
    if space is None:  # pragma: no cover — the migration seeds it
        pytest.skip("world-builders is seeded by migration; row missing")
    # Confirm the shape these tests reason about, so a change to the
    # seed shows up here rather than as a confusing assertion later.
    assert space.is_public is False
    assert space.auto_grant_role == UserRole.creator.value
    return space


def _get_membership(db, user_id: str, space_id: str) -> SpaceMembership | None:
    return (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.space_id == space_id,
            SpaceMembership.source == AUTO_ROLE_SOURCE,
        )
        .first()
    )


# ---------------------------------------------------------------------------
# is_eligible_creator predicate
# ---------------------------------------------------------------------------


class TestEligibilityPredicate:
    def test_active_creator_is_eligible(self, make_user):
        assert is_eligible_creator(make_user(role="creator")) is True

    def test_plain_user_is_not_eligible(self, make_user):
        assert is_eligible_creator(make_user(role="user")) is False

    def test_admin_is_not_eligible(self, make_user):
        assert is_eligible_creator(make_user(role="admin")) is False

    def test_suspended_creator_is_not_eligible(self, make_user):
        u = make_user(role="creator", creator_suspended_at=datetime.utcnow())
        assert is_eligible_creator(u) is False

    def test_cancelled_creator_is_not_eligible(self, make_user):
        u = make_user(role="creator", creator_cancelled_at=datetime.utcnow())
        assert is_eligible_creator(u) is False


# ---------------------------------------------------------------------------
# Lifecycle reconciliation
# ---------------------------------------------------------------------------


class TestReconciliationLifecycle:
    def test_eligible_creator_gets_active_membership(self, db, make_user, world_builders):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m is not None
        assert m.status == SpaceMembershipStatus.active
        assert m.role == SpaceRole.learner
        assert m.source == AUTO_ROLE_SOURCE

    def test_reconciler_is_idempotent(self, db, make_user, world_builders):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()
        apply_creator_eligibility_change(creator, db)
        db.flush()
        rows = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == creator.id,
                SpaceMembership.space_id == world_builders.id,
            )
            .all()
        )
        assert len(rows) == 1

    def test_suspension_pauses_membership(self, db, make_user, world_builders):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()

        creator.creator_suspended_at = datetime.utcnow()
        apply_creator_eligibility_change(creator, db)
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m.status == SpaceMembershipStatus.paused

    def test_lifting_suspension_reactivates_membership(self, db, make_user, world_builders):
        creator = make_user(role="creator", creator_suspended_at=datetime.utcnow())
        apply_creator_eligibility_change(creator, db)
        db.flush()

        creator.creator_suspended_at = None
        apply_creator_eligibility_change(creator, db)
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m is not None
        assert m.status == SpaceMembershipStatus.active

    def test_cancellation_removes_membership(self, db, make_user, world_builders):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()

        creator.creator_cancelled_at = datetime.utcnow()
        apply_creator_eligibility_change(creator, db)
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m.status == SpaceMembershipStatus.removed

    def test_role_change_removes_membership(self, db, make_user, world_builders):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()

        creator.role = "user"
        apply_creator_eligibility_change(creator, db)
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m.status == SpaceMembershipStatus.removed

    def test_cancellation_then_restore_reactivates_same_row(
        self, db, make_user, world_builders
    ):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()
        first = _get_membership(db, creator.id, world_builders.id)
        first_id = first.id

        creator.creator_cancelled_at = datetime.utcnow()
        apply_creator_eligibility_change(creator, db)
        db.flush()

        creator.creator_cancelled_at = None
        apply_creator_eligibility_change(creator, db)
        db.flush()
        second = _get_membership(db, creator.id, world_builders.id)
        assert second.id == first_id
        assert second.status == SpaceMembershipStatus.active

    def test_non_auto_role_membership_is_never_touched(
        self, db, make_user, world_builders
    ):
        """A pre-existing 'joined' or 'invited' membership must survive
        every reconciler pass, including role-change removals."""
        creator = make_user(role="creator")
        explicit = SpaceMembership(
            id=f"m_{uuid.uuid4().hex[:12]}",
            user_id=creator.id,
            space_id=world_builders.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            source="joined",
        )
        db.add(explicit)
        db.flush()

        # Role change to 'user' should NOT sweep the explicit membership.
        creator.role = "user"
        apply_creator_eligibility_change(creator, db)
        db.flush()
        db.refresh(explicit)
        assert explicit.status == SpaceMembershipStatus.active
        assert explicit.source == "joined"


# ---------------------------------------------------------------------------
# Route guards
# ---------------------------------------------------------------------------


class TestJoinIsRefused:
    def test_join_returns_403_on_auto_grant_space(
        self, db, make_user, world_builders
    ):
        # The endpoint filters by status=='active'; the auto-grant space
        # starts as 'draft' so we flip it to active for this test only.
        world_builders.status = "active"
        db.flush()
        stranger = make_user(role="user")
        with pytest.raises(HTTPException) as e:
            join_space(slug=world_builders.slug, db=db, current_user=stranger)
        assert e.value.status_code == 403
        assert "automatically" in e.value.detail.lower()


class TestPublicCardVisibilityIsSeparateFromAccess:
    """The distinction this release introduces.

    This class used to hold one test —
    ``test_auto_grant_space_hidden_from_public_list`` — asserting that
    an auto-grant Collective never appears on a public surface. That
    was the right rule when the only auto-grant Collective was meant
    to be invisible, and it is now deliberately inverted **for World
    Builders only**: it has a public case to make and nothing to hide
    at card level.

    What replaces it is the harder statement, and the one worth
    pinning: a **card** is not **access**. World Builders is listed;
    its Collective payload, its join endpoint and its member areas are
    exactly as closed as they were. Every other auto-grant Collective
    is still hidden outright.
    """

    def test_world_builders_appears_on_the_public_list(
        self, db, seeded_world_builders,
    ):
        from app.spaces.routes import PUBLICLY_DISCOVERABLE_MANAGED_SLUGS

        # A named exception, not a rule — the slug is the key.
        assert "world-builders" in PUBLICLY_DISCOVERABLE_MANAGED_SLUGS
        db.flush()

        rows = list_public_spaces(db=db)
        card = next(
            (r for r in rows if r.id == seeded_world_builders.id), None,
        )
        assert card is not None, "World Builders should be discoverable"
        assert card.creator_only is True
        # Listed *as itself* — its own name, not a special-case
        # placeholder.
        assert card.name == seeded_world_builders.name

    def test_the_exception_does_not_change_what_a_card_contains(
        self, db, seeded_world_builders,
    ):
        """Only the restricted card shape is exposed. The guidance
        bodies and About copy live on ``SpaceResponse``, which this
        endpoint does not return and ``get_space`` still refuses to an
        anonymous caller."""
        seeded_world_builders.about_content = "<p>members only</p>"
        seeded_world_builders.guidance_start_body = "MEMBERS-ONLY GUIDANCE"
        seeded_world_builders.welcome_message = "Welcome Creator."
        db.flush()

        card = next(
            r for r in list_public_spaces(db=db) if r.slug == "world-builders"
        )
        fields = card.model_dump()
        for leaked in (
            "about_content", "guidance_start_body", "guidance_focus_body",
            "guidance_links_body", "welcome_message", "home_tiles",
            "pathways", "area_access", "auto_grant_role",
        ):
            assert leaked not in fields, f"{leaked} must not reach a public card"

    def test_every_other_auto_grant_collective_stays_hidden(
        self, db, world_builders, make_space,
    ):
        """The reason the exception is a list of one rather than a
        predicate on the flag. Automatically managed membership and
        public discoverability are separate concepts, and a future
        operational Collective must not become listed as a side effect
        of a decision about who belongs in it."""
        normal = make_space(is_public=True, status="active")
        world_builders.status = "active"
        world_builders.is_public = True  # even public, auto_grant hides it
        db.flush()

        ids = {r.id for r in list_public_spaces(db=db)}
        assert normal.id in ids
        assert world_builders.id not in ids

    def test_ordinary_collective_discovery_is_unchanged(
        self, db, make_space,
    ):
        listed = make_space(is_public=True, status="active")
        private = make_space(is_public=False, status="active")
        draft = make_space(is_public=True, status="draft")
        db.flush()

        ids = {r.id for r in list_public_spaces(db=db)}
        assert listed.id in ids
        assert private.id not in ids
        assert draft.id not in ids
        # An ordinary card never claims to be creator-only.
        card = next(r for r in list_public_spaces(db=db) if r.id == listed.id)
        assert card.creator_only is False

    def test_the_single_slug_route_matches_the_list(
        self, db, seeded_world_builders, make_space,
    ):
        """``get_public_space`` shares ``_public_space_query`` so the two
        can never disagree — an unlisted Collective must not be
        addressable by slug, and a listed one must be."""
        from app.spaces.routes import get_public_space

        hidden = make_space(is_public=False, status="active")
        db.flush()

        assert get_public_space("world-builders", db=db).slug == "world-builders"
        with pytest.raises(HTTPException) as exc:
            get_public_space(hidden.slug, db=db)
        assert exc.value.status_code == 404

    def test_discover_places_keeps_its_own_stricter_rule(self):
        """Discover Places has a separate copy of the old predicate
        (``places.routes._collective_is_publicly_listable``) and is
        deliberately left alone: it answers "which Collectives are *at
        this place*", and World Builders is online-only with no
        physical Place. Pinned so the exception cannot leak there by
        someone later consolidating the two.
        """
        import inspect

        from app.places import routes as places_routes

        src = inspect.getsource(places_routes._collective_is_publicly_listable)
        assert "auto_grant_role" in src
        assert "is_public" in src
        assert "PUBLICLY_DISCOVERABLE" not in src


# ---------------------------------------------------------------------------
# Admin role change wires into the reconciler
# ---------------------------------------------------------------------------


class TestAdminRoleChangeReconciles:
    def test_setting_creator_to_user_removes_auto_role_membership(
        self, db, make_user, world_builders
    ):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()
        assert _get_membership(db, creator.id, world_builders.id).status \
            == SpaceMembershipStatus.active

        set_user_role(db, creator.id, "user")
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m.status == SpaceMembershipStatus.removed


# ---------------------------------------------------------------------------
# Session-time reconciler short-circuit
# ---------------------------------------------------------------------------


class TestUpdateSpaceGuards:
    def test_editable_field_change_is_allowed_on_auto_managed(
        self, db, make_user, world_builders
    ):
        """Editing tagline / description / timezone on an auto-managed
        collective is allowed; the creator still owns the collective."""
        owner = db.query(type(make_user())).filter_by(id=world_builders.creator_id).one()
        body = SpaceUpdateRequest(tagline="A refreshed tagline")
        # _get_managed_space checks the caller is the space owner or
        # an admin; the owner from the fixture is an admin, so this passes.
        update_space(
            slug=world_builders.slug,
            body=body,
            db=db,
            current_user=owner,
        )
        db.refresh(world_builders)
        assert world_builders.tagline == "A refreshed tagline"

    def test_toggling_is_public_is_refused_on_auto_managed(
        self, db, make_user, world_builders
    ):
        owner = db.query(type(make_user())).filter_by(id=world_builders.creator_id).one()
        body = SpaceUpdateRequest(is_public=True)  # attempting to unlock
        with pytest.raises(HTTPException) as e:
            update_space(
                slug=world_builders.slug,
                body=body,
                db=db,
                current_user=owner,
            )
        assert e.value.status_code == 403
        assert "is_public" in e.value.detail

    def test_pricing_change_is_refused_on_auto_managed(
        self, db, make_user, world_builders
    ):
        owner = db.query(type(make_user())).filter_by(id=world_builders.creator_id).one()
        body = SpaceUpdateRequest(pricing_type="paid_monthly")
        with pytest.raises(HTTPException) as e:
            update_space(
                slug=world_builders.slug,
                body=body,
                db=db,
                current_user=owner,
            )
        assert e.value.status_code == 403
        assert "pricing_type" in e.value.detail


class TestSessionTimeReconciler:
    def test_short_circuits_when_nothing_relevant(self, db, make_user):
        """No auto-grant space + no auto_role rows → zero writes."""
        u = make_user(role="user")
        # No world_builders fixture — no auto-grant space exists at all.
        reconcile_at_session_time(u, db)
        # Should not error, no rows created.
        assert (
            db.query(SpaceMembership).filter(SpaceMembership.user_id == u.id).count()
            == 0
        )

    def test_grants_membership_when_reconciler_runs(
        self, db, make_user, world_builders
    ):
        creator = make_user(role="creator")
        reconcile_at_session_time(creator, db)
        m = _get_membership(db, creator.id, world_builders.id)
        assert m is not None
        assert m.status == SpaceMembershipStatus.active


# ---------------------------------------------------------------------------
# A card is not access
# ---------------------------------------------------------------------------


class TestDiscoverabilityDoesNotOpenTheCollective:
    """Everything the public card deliberately does not unlock.

    One of these was a real leak before this release, found while
    investigating the card change and verified against production: the
    Collective page answered 401 to an anonymous caller and its
    Pathways catalogue answered **200 with the full listing** — titles,
    descriptions, cover images, step counts. ``POLICY_PUBLIC`` means
    "anyone, signed in or not", which is the right reading for a
    Collective anybody can find and the wrong one for a Collective
    that is ``is_public=False``.

    Closed in ``area_access.resolve_area_access``, where every surface
    already asks the question, rather than by a per-route patch or a
    stored policy on one row.
    """

    def _wb(self, db, make_user, **over):
        owner = make_user(role="admin")
        space = Space(
            id=f"s_{uuid.uuid4().hex[:12]}",
            slug=f"wb-{uuid.uuid4().hex[:8]}",
            name="World Builders",
            status="active",
            is_public=False,
            creator_id=owner.id,
            auto_grant_role=UserRole.creator.value,
            **over,
        )
        db.add(space)
        db.flush()
        return space, owner

    def _pathway(self, db, space, *, status="active"):
        from app.models.platform import Pathway, PathwayType

        p = Pathway(
            id=f"pw_{uuid.uuid4().hex[:10]}",
            space_id=space.id,
            slug=f"p-{uuid.uuid4().hex[:8]}",
            title="World Builders - Start Here",
            description="Start here to discover what Fresh Collective is about.",
            status=status,
            access_type="included",
            pathway_type=PathwayType.guided_experience,
            currency="AUD",
        )
        db.add(p)
        db.flush()
        return p

    def _member(self, db, space, user):
        m = SpaceMembership(
            id=f"sm_{uuid.uuid4().hex[:10]}",
            space_id=space.id,
            user_id=user.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            source=AUTO_ROLE_SOURCE,
        )
        db.add(m)
        db.flush()
        return m

    # ── the gap, closed ──────────────────────────────────────────────

    def test_an_anonymous_visitor_cannot_list_its_pathways(
        self, db, make_user,
    ):
        from app.spaces.routes import list_pathways

        space, _owner = self._wb(db, make_user)
        self._pathway(db, space)
        db.flush()

        with pytest.raises(HTTPException) as exc:
            list_pathways(space.slug, db=db, current_user=None)
        # 404, not 403 — a refusal must not confirm the area exists.
        assert exc.value.status_code == 404

    def test_an_anonymous_visitor_cannot_list_its_offerings(
        self, db, make_user, offerings_enabled,
    ):
        from app.spaces._offering_member_routes import list_member_offerings

        space, _owner = self._wb(db, make_user)
        db.flush()

        with pytest.raises(HTTPException) as exc:
            list_member_offerings(space.slug, db=db, current_user=None)
        assert exc.value.status_code == 404

    def test_its_gatherings_and_members_were_already_closed(
        self, db, make_user,
    ):
        """The audit's other half. Gatherings and Members default to
        ``POLICY_MEMBERS``, so they refused an anonymous caller before
        this change and still do — the fix adds nothing here, and
        these are pinned so a later policy default change cannot open
        them quietly."""
        from app.members.routes import list_members
        from app.spaces.routes import list_events

        space, _owner = self._wb(db, make_user)
        db.flush()

        for call in (
            lambda: list_events(space.slug, db=db, current_user=None),
            lambda: list_members(space.slug, db=db, current_user=None),
        ):
            with pytest.raises(HTTPException) as exc:
                call()
            assert exc.value.status_code == 404

    def test_a_member_keeps_the_pathways_catalogue(self, db, make_user):
        """The half that matters most: closing the anonymous door must
        not close the members' one."""
        from app.spaces.routes import list_pathways

        space, _owner = self._wb(db, make_user)
        self._pathway(db, space)
        creator = make_user(role="creator")
        self._member(db, space, creator)
        db.flush()

        rows = list_pathways(space.slug, db=db, current_user=creator)
        assert [r.title for r in rows] == ["World Builders - Start Here"]

    def test_the_owner_keeps_it_too(self, db, make_user):
        from app.spaces.routes import list_pathways

        space, owner = self._wb(db, make_user)
        self._pathway(db, space, status="draft")
        db.flush()

        rows = list_pathways(space.slug, db=db, current_user=owner)
        # A caretaker sees drafts as well, unchanged.
        assert len(rows) == 1

    def test_an_ordinary_public_collective_is_unaffected(
        self, db, make_space,
    ):
        """The area fix is scoped to ``is_public=False``. A public
        Collective's Pathways catalogue stays anonymously readable,
        which is what Explore and every public About page rely on."""
        from app.spaces.routes import list_pathways

        space = make_space(is_public=True, status="active")
        self._pathway(db, space)
        db.flush()

        rows = list_pathways(space.slug, db=db, current_user=None)
        assert len(rows) == 1

    # ── the payload, and content ─────────────────────────────────────

    def test_the_full_collective_payload_stays_closed(self, db, make_user):
        """``get_space`` — guidance bodies, About copy, home tiles,
        member counts. Unchanged by the card exception."""
        from app.spaces.routes import get_space

        space, _owner = self._wb(
            db, make_user, guidance_start_body="MEMBERS-ONLY GUIDANCE",
        )
        db.flush()

        with pytest.raises(HTTPException) as exc:
            get_space(space.slug, db=db, current_user=None)
        assert exc.value.status_code == 401

    def test_pathway_content_stays_closed_to_a_non_member(
        self, db, make_user,
    ):
        """Discovery never reached content even before the fix —
        ``_check_pathway_access`` requires membership for an
        ``included`` Pathway. Pinned because the card makes the
        Collective findable, and "findable" must not drift into
        "readable"."""
        from app.spaces.routes import _check_pathway_access

        space, _owner = self._wb(db, make_user)
        pathway = self._pathway(db, space)
        stranger = make_user()
        db.flush()

        with pytest.raises(HTTPException) as exc:
            _check_pathway_access(stranger, pathway, space, db)
        assert exc.value.status_code == 403

    def test_a_member_can_open_the_pathway(self, db, make_user):
        from app.spaces.routes import _check_pathway_access

        space, _owner = self._wb(db, make_user)
        pathway = self._pathway(db, space)
        creator = make_user(role="creator")
        self._member(db, space, creator)
        db.flush()

        _check_pathway_access(creator, pathway, space, db)  # does not raise

    def test_a_suspended_creator_cannot_enter(self, db, make_user):
        """Suspension pauses the membership, and a paused membership is
        not an active one — so every area gate refuses. The card still
        shows (it is public), which is why the client sends them to
        their own account rather than into the Collective."""
        from app.spaces.routes import _check_pathway_access, list_pathways

        space, _owner = self._wb(db, make_user)
        pathway = self._pathway(db, space)
        creator = make_user(role="creator")
        membership = self._member(db, space, creator)
        db.flush()

        creator.creator_suspended_at = datetime.utcnow()
        apply_creator_eligibility_change(creator, db)
        db.flush()
        assert membership.status == SpaceMembershipStatus.paused

        # The guarantee: no content. A paused membership is not an
        # active one, so ``resolve_space_viewer`` stops qualifying them
        # and every members-only gate refuses.
        with pytest.raises(HTTPException) as exc:
            _check_pathway_access(creator, pathway, space, db)
        assert exc.value.status_code == 403

        # They DO still see the catalogue listing, because they are a
        # signed-in non-member and ``AREA_PATHWAYS`` is public-policy —
        # the same ``visibility='link'`` behaviour documented in
        # ``test_a_signed_in_non_member_still_reaches_the_catalogue``
        # below. Asserted rather than left ambiguous: this is the state
        # the client's "Check your creator status" CTA exists for.
        assert len(list_pathways(space.slug, db=db, current_user=creator)) == 1

    def test_a_signed_in_non_member_still_reaches_the_catalogue(
        self, db, make_user,
    ):
        """Documented, not fixed — and deliberately so.

        ``get_space`` has always admitted a signed-in non-member to a
        non-public Collective; that is the ``visibility='link'`` model,
        "anyone with the link, who has an account". Narrowing it is a
        product decision about the visibility model rather than a bug
        fix, so this release reports it instead of taking it.

        Pinned here so the decision is visible in the suite rather than
        only in a report. If the model changes, this test is the one to
        invert.
        """
        from app.spaces.routes import get_space, list_pathways

        space, _owner = self._wb(
            db, make_user, guidance_start_body="MEMBERS-ONLY GUIDANCE",
        )
        self._pathway(db, space)
        stranger = make_user()
        db.flush()

        assert len(list_pathways(space.slug, db=db, current_user=stranger)) == 1
        payload = get_space(space.slug, db=db, current_user=stranger)
        assert payload.guidance_start_body == "MEMBERS-ONLY GUIDANCE"


# ---------------------------------------------------------------------------
# visibility='private' — enforced, and the public introduction beside it
# ---------------------------------------------------------------------------


class TestPrivateVisibilityIsEnforced:
    """``Space.visibility`` carried three levels since migration 063 and
    exactly one module ever read it — ``services.member_visibility``,
    deciding whether a Creator's profile may name a Collective, where
    ``link`` and ``private`` already behaved identically. Every access
    decision ran off ``is_public``.

    So before this release, setting World Builders to ``private``
    would have changed nothing: a signed-in stranger could read its
    full payload, guidance bodies included, and list its Pathways.
    Verified directly before implementing, which is why the level is
    now enforced rather than merely set.

    ``public`` and ``link`` are untouched — the point is to make the
    strictest level mean something without disturbing the two that
    ordinary creators use.
    """

    @pytest.fixture
    def wb(self, db, seeded_world_builders, make_user):
        """The real row, set private, with one Pathway and the guidance
        a member is supposed to be the only one reading."""
        from app.models.platform import Pathway, PathwayType

        space = seeded_world_builders
        space.visibility = "private"
        space.guidance_start_body = "MEMBERS-ONLY GUIDANCE"
        space.about_content = "<h2>Our Story</h2><p>Every collective has one.</p>"
        if space.creator_id is None:
            space.creator_id = make_user(role="admin").id
        db.add(Pathway(
            id=f"pw_{uuid.uuid4().hex[:10]}",
            space_id=space.id,
            slug=f"p-{uuid.uuid4().hex[:8]}",
            title="World Builders - Start Here",
            status="active",
            access_type="included",
            pathway_type=PathwayType.guided_experience,
            currency="AUD",
        ))
        db.flush()
        return space

    def _member(self, db, space, user, status=SpaceMembershipStatus.active):
        m = SpaceMembership(
            id=f"sm_{uuid.uuid4().hex[:10]}",
            space_id=space.id, user_id=user.id,
            role=SpaceRole.learner, status=status,
            source=AUTO_ROLE_SOURCE,
        )
        db.add(m)
        db.flush()
        return m

    # ── refused ──────────────────────────────────────────────────────

    @pytest.mark.parametrize("who", ["anonymous", "signed_in_non_member"])
    def test_the_full_payload_is_refused(self, db, wb, make_user, who):
        from app.spaces.routes import get_space

        user = None if who == "anonymous" else make_user()
        db.flush()

        with pytest.raises(HTTPException) as exc:
            get_space(wb.slug, db=db, current_user=user)
        # 401 for anonymous (pre-existing), 404 for a signed-in
        # outsider — a refusal must not confirm the Collective exists.
        assert exc.value.status_code in (401, 404)

    @pytest.mark.parametrize("who", ["anonymous", "signed_in_non_member"])
    def test_the_pathways_catalogue_is_refused(self, db, wb, make_user, who):
        from app.spaces.routes import list_pathways

        user = None if who == "anonymous" else make_user()
        db.flush()

        with pytest.raises(HTTPException) as exc:
            list_pathways(wb.slug, db=db, current_user=user)
        assert exc.value.status_code == 404

    @pytest.mark.parametrize("who", ["anonymous", "signed_in_non_member"])
    def test_the_offerings_catalogue_is_refused(
        self, db, wb, make_user, offerings_enabled, who,
    ):
        from app.spaces._offering_member_routes import list_member_offerings

        user = None if who == "anonymous" else make_user()
        db.flush()

        with pytest.raises(HTTPException) as exc:
            list_member_offerings(wb.slug, db=db, current_user=user)
        assert exc.value.status_code == 404

    def test_the_other_member_areas_stay_refused(self, db, wb, make_user):
        from app.members.routes import list_members
        from app.spaces.routes import list_events

        stranger = make_user()
        db.flush()

        for user in (None, stranger):
            for call in (
                lambda: list_events(wb.slug, db=db, current_user=user),
                lambda: list_members(wb.slug, db=db, current_user=user),
            ):
                with pytest.raises(HTTPException) as exc:
                    call()
                assert exc.value.status_code == 404

    @pytest.mark.parametrize(
        "lapse", ["creator_suspended_at", "creator_cancelled_at"],
    )
    def test_a_lapsed_creator_loses_everything(
        self, db, wb, make_user, lapse,
    ):
        """Suspension pauses the membership and cancellation removes
        it. Neither state qualifies, so the ``private`` gate refuses
        them with nothing lapse-specific written anywhere — which is
        why one predicate covers both."""
        from app.spaces.routes import get_space, list_pathways

        creator = make_user(role="creator")
        self._member(db, wb, creator)
        db.flush()

        setattr(creator, lapse, datetime.utcnow())
        apply_creator_eligibility_change(creator, db)
        db.flush()

        for call in (
            lambda: get_space(wb.slug, db=db, current_user=creator),
            lambda: list_pathways(wb.slug, db=db, current_user=creator),
        ):
            with pytest.raises(HTTPException) as exc:
                call()
            assert exc.value.status_code == 404

    def test_a_direct_url_cannot_bypass_any_of_it(self, db, wb, make_user):
        """Every slug-addressable door, asked by a signed-in outsider in
        one test, because "try the URL directly" is one attempt and
        should meet one answer."""
        from app.members.routes import list_members
        from app.spaces._offering_member_routes import list_member_offerings
        from app.spaces.routes import (
            get_space, list_events, list_pathways, request_access,
        )

        stranger = make_user()
        db.flush()

        doors = [
            lambda: get_space(wb.slug, db=db, current_user=stranger),
            lambda: list_pathways(wb.slug, db=db, current_user=stranger),
            lambda: list_events(wb.slug, db=db, current_user=stranger),
            lambda: list_members(wb.slug, db=db, current_user=stranger),
        ]
        for call in doors:
            with pytest.raises(HTTPException) as exc:
                call()
            assert exc.value.status_code in (401, 403, 404)

    # ── permitted ────────────────────────────────────────────────────

    def test_an_eligible_creator_member_keeps_everything(
        self, db, wb, make_user,
    ):
        from app.spaces.routes import get_space, list_pathways

        creator = make_user(role="creator")
        self._member(db, wb, creator)
        db.flush()

        payload = get_space(wb.slug, db=db, current_user=creator)
        assert payload.guidance_start_body == "MEMBERS-ONLY GUIDANCE"
        assert len(list_pathways(wb.slug, db=db, current_user=creator)) == 1

    def test_the_owner_keeps_everything(self, db, wb, make_user):
        from app.models.user import User
        from app.spaces.routes import get_space, list_pathways

        owner = db.query(User).filter(User.id == wb.creator_id).one()
        db.flush()

        assert get_space(wb.slug, db=db, current_user=owner).slug == wb.slug
        assert len(list_pathways(wb.slug, db=db, current_user=owner)) == 1

    def test_a_platform_admin_keeps_everything(self, db, wb, make_user):
        from app.spaces.routes import get_space, list_pathways

        admin = make_user(role="admin")
        db.flush()

        assert get_space(wb.slug, db=db, current_user=admin).slug == wb.slug
        assert len(list_pathways(wb.slug, db=db, current_user=admin)) == 1

    def test_automatic_membership_still_reconciles(self, db, wb, make_user):
        """The grant path is untouched: nothing about ``private``
        changes who the platform decides belongs here."""
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()

        row = _get_membership(db, creator.id, wb.id)
        assert row is not None
        assert row.status == SpaceMembershipStatus.active

    def test_manual_joining_is_still_refused(self, db, wb, make_user):
        from app.spaces.routes import join_space

        for user in (make_user(), make_user(role="creator")):
            with pytest.raises(HTTPException) as exc:
                join_space(
                    wb.slug, background_tasks=None, db=db, current_user=user,
                )
            assert exc.value.status_code == 403

    def test_requesting_access_is_refused_too(self, db, wb, make_user):
        """Found while auditing the doors for this release.

        ``join_space`` has always refused an auto-grant Collective; this
        endpoint did not, so a signed-in non-creator could lodge a
        pending access request. Approving one writes a
        ``source='joined'`` membership, and the eligibility reconciler
        only ever touches ``source='auto_role'`` rows — so it would be
        permanent and invisible to the rule that decides who belongs
        there.
        """
        from app.models.platform import SpaceAccessRequest
        from app.spaces.routes import request_access

        stranger = make_user()
        db.flush()

        with pytest.raises(HTTPException) as exc:
            request_access(wb.slug, db=db, current_user=stranger)
        assert exc.value.status_code == 403
        assert db.query(SpaceAccessRequest).filter(
            SpaceAccessRequest.space_id == wb.id,
        ).count() == 0

    # ── and the card is still public ─────────────────────────────────

    def test_the_public_card_is_unaffected(self, db, wb):
        db.flush()
        card = next(
            (r for r in list_public_spaces(db=db) if r.slug == wb.slug), None,
        )
        assert card is not None
        assert card.creator_only is True

    # ── ordinary Collectives keep their behaviour ────────────────────

    @pytest.mark.parametrize(
        "visibility,is_public", [("public", True), ("link", False)],
    )
    def test_public_and_link_collectives_are_unchanged(
        self, db, make_space, make_user, visibility, is_public,
    ):
        """The blast radius, pinned. A ``link`` Collective's signed-in
        reader keeps the access the level has always meant — "anyone
        with the link, who has an account"."""
        from app.spaces.routes import get_space, list_pathways
        from app.models.platform import Pathway, PathwayType

        space = make_space(
            is_public=is_public, status="active", visibility=visibility,
        )
        db.add(Pathway(
            id=f"pw_{uuid.uuid4().hex[:10]}", space_id=space.id,
            slug=f"p-{uuid.uuid4().hex[:8]}", title="A Pathway",
            status="active", access_type="included",
            pathway_type=PathwayType.guided_experience, currency="AUD",
        ))
        stranger = make_user()
        db.flush()

        assert get_space(space.slug, db=db, current_user=stranger).slug == space.slug
        assert len(list_pathways(space.slug, db=db, current_user=stranger)) == 1


class TestThePublicAboutPayload:
    """The public introduction, and what it refuses to carry.

    An allowlist rather than a filtered ``SpaceResponse``: a field
    added to the private payload later is invisible here unless
    somebody writes it in, which is the direction the mistake should
    run.
    """

    @pytest.fixture
    def wb(self, db, seeded_world_builders, make_user):
        space = seeded_world_builders
        space.visibility = "private"
        space.about_content = "<h2>Our Story</h2>"
        space.guidance_start_body = "MEMBERS-ONLY GUIDANCE"
        space.guidance_focus_body = "MEMBERS-ONLY FOCUS"
        space.guidance_links_body = "MEMBERS-ONLY LINKS"
        space.welcome_message = "Welcome Creator."
        space.identity_statement = "A place for creators."
        if space.creator_id is None:
            space.creator_id = make_user(role="admin").id
        db.flush()
        return space

    def test_it_answers_without_a_session(self, db, wb):
        from app.spaces.routes import get_public_collective_about

        out = get_public_collective_about(wb.slug, db=db)
        assert out.slug == wb.slug
        assert out.name == wb.name
        assert out.creator_only is True

    def test_it_carries_the_public_story_and_imagery(self, db, wb):
        from app.spaces.routes import get_public_collective_about

        out = get_public_collective_about(wb.slug, db=db)
        assert out.about_content == "<h2>Our Story</h2>"
        # Reviewed for public suitability before shipping — see the
        # release report. The field is the creator's own public story.
        assert "MEMBERS-ONLY" not in (out.about_content or "")

    def test_private_only_fields_cannot_appear_in_it(self):
        """The regression test the release asked for, asserted against
        the **model** rather than one response — so it holds for every
        Collective and every future caller, not just the row this suite
        happens to build."""
        from app.spaces.schemas import PublicCollectiveAbout

        forbidden = {
            "guidance_start_title", "guidance_start_body",
            "guidance_focus_title", "guidance_focus_body",
            "guidance_links_title", "guidance_links_body",
            "welcome_message", "identity_statement",
            "home_tiles", "area_access", "joining_options",
            "pathways", "learner_count", "leader_count",
            "upcoming_gathering_count", "next_gathering_starts_at",
            "published_offering_count", "show_member_directory",
            "auto_grant_role", "about_content_private",
            "colour_palette", "atmosphere_keys", "status", "id",
        }
        present = set(PublicCollectiveAbout.model_fields)
        leaked = present & forbidden
        assert leaked == set(), f"public About must not expose: {leaked}"

    def test_a_response_carries_nothing_beyond_the_allowlist(self, db, wb):
        from app.spaces.routes import get_public_collective_about
        from app.spaces.schemas import PublicCollectiveAbout

        out = get_public_collective_about(wb.slug, db=db).model_dump()
        assert set(out) == set(PublicCollectiveAbout.model_fields)
        # And no value smuggles member-only text through.
        blob = " ".join(str(v) for v in out.values())
        assert "MEMBERS-ONLY" not in blob
        assert "Welcome Creator" not in blob

    def test_it_refuses_every_other_private_collective(
        self, db, make_space,
    ):
        """Scoped to the named discoverable slugs. A Collective that is
        private and not deliberately on a public surface has no public
        introduction to give, and this endpoint must not become a way
        to read one — including by confirming it exists."""
        from app.spaces.routes import get_public_collective_about

        other = make_space(
            is_public=False, status="active", visibility="private",
        )
        db.flush()

        with pytest.raises(HTTPException) as exc:
            get_public_collective_about(other.slug, db=db)
        assert exc.value.status_code == 404

    def test_an_unknown_slug_is_the_same_answer(self, db):
        from app.spaces.routes import get_public_collective_about

        with pytest.raises(HTTPException) as exc:
            get_public_collective_about("no-such-collective", db=db)
        assert exc.value.status_code == 404

    def test_a_draft_collective_is_refused(self, db, seeded_world_builders):
        from app.spaces.routes import get_public_collective_about

        seeded_world_builders.status = "draft"
        db.flush()

        with pytest.raises(HTTPException) as exc:
            get_public_collective_about("world-builders", db=db)
        assert exc.value.status_code == 404

    def test_the_response_is_identical_for_every_caller(self, db, wb):
        """No per-viewer anything, which is what makes it cacheable and
        safe to index — the reason this page can be public at all."""
        from app.spaces.routes import get_public_collective_about

        first = get_public_collective_about(wb.slug, db=db).model_dump()
        second = get_public_collective_about(wb.slug, db=db).model_dump()
        assert first == second
