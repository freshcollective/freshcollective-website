"""Offerings Phase B4 — creator API, pricing, quota and publication.

Route handlers are imported and called directly, matching the suite's
convention (no TestClient). One consequence worth stating: calling a
handler directly **bypasses the router-level feature-flag dependency**,
so the flag is tested two ways instead — the dependency function itself,
and a structural assertion that the router declares it. A test that only
called handlers would silently prove nothing about the gate.

Every refusal here sits beside a positive control. A permission layer
that refused everyone would satisfy half this file and fail the rest.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.creator import _offering_routes as api
from app.creator.plan_config import PLANS_BY_SLUG
from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingEntitlementSource,
    OfferingEntitlementStatus,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
    OfferingPricingKind,
    OfferingStatus,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.services import offering_files as of
from app.services import offering_readiness as readiness
from app.services import offering_validation as ov

DEFAULT_COVER = "/api/uploads/platform-artwork/offering-covers/workbook.png"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:16]}"


@pytest.fixture
def plan(db):
    """Seed creator plans and attach one to a user.

    Mirrors the seeding other commerce tests do — the plan table must
    hold a row for ``resolve_creator_plan`` to find anything.
    """
    from app.models.creator_billing import (
        CreatorPlan, CreatorSubscription, CreatorSubscriptionStatus,
    )

    def _attach(user, slug: str):
        cap = PLANS_BY_SLUG[slug]
        row = (
            db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
        )
        if row is None:
            row = CreatorPlan(
                id=_uid("plan"), slug=slug, name=cap.display_name,
                monthly_price_cents=cap.monthly_price_cents or 0,
                currency="AUD", transaction_fee_basis_points=800,
                collective_limit=cap.active_collective_limit or 1,
                pathway_limit=cap.pathways_max_per_collective,
            )
            db.add(row)
            db.flush()
        db.add(CreatorSubscription(
            id=_uid("sub"), user_id=user.id, creator_plan_id=row.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(),
        ))
        db.flush()
        return row

    return _attach


@pytest.fixture
def owner_space(db, make_space, make_user, plan):
    """A Collective, its owner, and a plan. Defaults to a paid plan."""
    def _make(plan_slug: str = "creator"):
        from app.models.user import User
        space = make_space()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        plan(owner, plan_slug)
        return space, owner
    return _make


def _offering(db, space, **kw) -> Offering:
    d = dict(
        id=_uid("off"), space_id=space.id, created_by_user_id=space.creator_id,
        slug=f"g-{uuid.uuid4().hex[:8]}", title="A Gentle Guide",
        summary="Short lines for a card.", status=OfferingStatus.draft.value,
    )
    d.update(kw)
    row = Offering(**d)
    db.add(row)
    db.flush()
    return row


def _file(db, off, *, status=FVS.passed.value, **kw) -> OfferingFile:
    name = kw.pop("name", "workbook.pdf")
    d = dict(
        id=_uid("ofl"), offering_id=off.id,
        storage_key=of.build_storage_key(offering_id=off.id, filename=name),
        original_filename=name, content_type="application/pdf",
        byte_size=2048, sort_order=0, validation_status=status,
        checks_performed=[
            {"id": c.id, "version": c.version, "outcome": "pass"}
            for c in ov.REQUIRED_CHECKS
        ],
        validation_policy_version=ov.VALIDATION_POLICY_VERSION,
    )
    d.update(kw)
    row = OfferingFile(**d)
    db.add(row)
    db.flush()
    return row


def _publishable(db, space, **kw) -> Offering:
    """An Offering that satisfies every requirement."""
    off = _offering(
        db, space, cover_image_url=DEFAULT_COVER,
        pricing_kind=OfferingPricingKind.free.value, **kw,
    )
    _file(db, off)
    db.flush()
    return off


def _member(db, user, space, role="moderator"):
    row = SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id, role=role,
        status=SpaceMembershipStatus.active, source="invited",
        joined_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _code_only(obj) -> str:
    """Source of ``obj`` with every docstring removed.

    These files explain at length *why* something is absent — no admin
    bypass, no Stripe — and a substring check over raw source therefore
    fails on the explanation rather than on a real use. Stripping
    docstrings via the AST bans the use, not the word.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            body.pop(0)
    return ast.dump(tree)


def _status(fn, *a, **kw) -> int | None:
    """Run a handler; return the HTTP status it refused with, or None."""
    try:
        fn(*a, **kw)
        return None
    except HTTPException as e:
        return e.status_code


# ---------------------------------------------------------------------------
# 1 · Authorisation — owner only
# ---------------------------------------------------------------------------


class TestOwnerOnlyAccess:
    def test_the_owner_can_list_and_create(self, db, owner_space):
        space, owner = owner_space()
        assert api.list_offerings(space.slug, db=db, current_user=owner) == []
        from app.creator.schemas_offerings import OfferingCreateRequest
        out = api.create_offering(
            space.slug, OfferingCreateRequest(title="Morning Pages"),
            db=db, current_user=owner,
        )
        assert out["status"] == "draft"
        assert out["slug"] == "morning-pages"

    def test_a_moderator_is_refused(self, db, owner_space, make_user):
        """The stricter rule. Every other creator surface would allow
        this; Offerings must not, because a moderator should not put a
        product on sale under someone else's payout account."""
        space, _ = owner_space()
        mod = make_user(role="creator")
        _member(db, mod, space, role="moderator")
        db.flush()
        assert _status(api.list_offerings, space.slug, db=db, current_user=mod) == 404

    def test_a_space_creator_member_is_also_refused(self, db, owner_space, make_user):
        """``_get_managed_space`` accepts role='creator' memberships too.
        Owner-only means owner, not "anyone the generic helper trusts"."""
        space, _ = owner_space()
        helper = make_user(role="creator")
        _member(db, helper, space, role="creator")
        db.flush()
        assert _status(api.list_offerings, space.slug, db=db, current_user=helper) == 404

    def test_a_platform_creator_role_alone_grants_nothing(
        self, db, owner_space, make_user,
    ):
        """Being a creator somewhere is not a relationship to *this*
        Collective."""
        space, _ = owner_space()
        stranger = make_user(role="creator")
        db.flush()
        assert _status(api.list_offerings, space.slug, db=db, current_user=stranger) == 404

    def test_a_platform_admin_is_not_an_owner_here(self, db, owner_space, make_user):
        """Consistent with the rest of Creator Studio: cross-Collective
        oversight lives in the admin portal."""
        space, _ = owner_space()
        admin = make_user(role="admin")
        db.flush()
        assert _status(api.list_offerings, space.slug, db=db, current_user=admin) == 404

    def test_cross_collective_access_is_refused_as_404(self, db, owner_space):
        """404 rather than 403, so the endpoint cannot be used to learn
        that another creator's Collective exists."""
        space_a, owner_a = owner_space()
        space_b, _ = owner_space()
        assert _status(api.list_offerings, space_b.slug, db=db, current_user=owner_a) == 404

    def test_another_collectives_offering_slug_is_404(self, db, owner_space):
        space_a, owner_a = owner_space()
        space_b, _ = owner_space()
        other = _offering(db, space_b, slug="their-guide")
        db.flush()
        assert _status(
            api.get_offering, space_a.slug, "their-guide",
            db=db, current_user=owner_a,
        ) == 404

    def test_moderator_permissions_elsewhere_are_untouched(self):
        """The strict rule is local to Offerings. ``_get_managed_space``
        must still accept moderators for every other surface."""
        import inspect
        from app.creator import routes
        src = inspect.getsource(routes._get_managed_space)
        assert '"creator", "moderator"' in src or "'creator', 'moderator'" in src

    @pytest.mark.parametrize("handler,args", [
        ("get_offering", ()),
        ("update_offering", ()),
        ("get_offering_readiness", ()),
        ("publish_offering", ()),
        ("retire_offering", ()),
    ])
    def test_every_mutating_and_reading_route_enforces_ownership(
        self, db, owner_space, make_user, handler, args,
    ):
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, _ = owner_space()
        off = _offering(db, space)
        intruder = make_user(role="creator")
        db.flush()
        fn = getattr(api, handler)
        kw = dict(db=db, current_user=intruder)
        if handler == "update_offering":
            code = _status(fn, space.slug, off.slug,
                           OfferingUpdateRequest(title="x"), **kw)
        else:
            code = _status(fn, space.slug, off.slug, **kw)
        assert code == 404, handler


# ---------------------------------------------------------------------------
# 2 · Plan quota
# ---------------------------------------------------------------------------


class TestCommunityQuota:
    def test_community_may_create_five_offerings(self, db, owner_space):
        from app.creator.schemas_offerings import OfferingCreateRequest
        space, owner = owner_space("community")
        for i in range(5):
            api.create_offering(
                space.slug, OfferingCreateRequest(title=f"Guide {i}"),
                db=db, current_user=owner,
            )
        assert len(api.list_offerings(space.slug, db=db, current_user=owner)) == 5

    def test_the_sixth_is_refused(self, db, owner_space):
        from app.creator.schemas_offerings import OfferingCreateRequest
        space, owner = owner_space("community")
        for i in range(5):
            api.create_offering(
                space.slug, OfferingCreateRequest(title=f"Guide {i}"),
                db=db, current_user=owner,
            )
        code = _status(
            api.create_offering, space.slug,
            OfferingCreateRequest(title="One too many"),
            db=db, current_user=owner,
        )
        assert code == 403

    @pytest.mark.parametrize("state", ["draft", "published", "retired"])
    def test_every_lifecycle_state_counts_towards_the_allowance(
        self, db, owner_space, state,
    ):
        """All three hold rows and may hold files, so a creator cannot
        free a slot by unpublishing — the approved rule."""
        from app.creator.schemas_offerings import OfferingCreateRequest
        space, owner = owner_space("community")
        for i in range(5):
            _offering(db, space, slug=f"g{i}", status=state)
        db.flush()
        code = _status(
            api.create_offering, space.slug,
            OfferingCreateRequest(title="Six"), db=db, current_user=owner,
        )
        assert code == 403, state

    def test_a_paid_plan_is_uncapped(self, db, owner_space):
        from app.creator.schemas_offerings import OfferingCreateRequest
        space, owner = owner_space("creator")
        for i in range(7):
            api.create_offering(
                space.slug, OfferingCreateRequest(title=f"Guide {i}"),
                db=db, current_user=owner,
            )
        assert len(api.list_offerings(space.slug, db=db, current_user=owner)) == 7

    def test_the_quota_is_enforced_under_a_row_lock(self):
        """Concurrency. Two simultaneous creates could otherwise both
        count four and both insert. The lock on the Collective
        serialises them — asserted structurally because two real
        connections cannot be driven inside one savepoint-wrapped
        session."""
        import inspect
        src = inspect.getsource(api.create_offering)
        assert "FOR UPDATE" in src
        assert src.index("FOR UPDATE") < src.index("guard_offering_limit")

    def test_the_guard_counts_per_collective_and_that_matches_the_intent(self):
        """The approved rule is "five across all Collectives a Community
        creator owns". Scoping per Collective delivers it because
        Community's ``active_collective_limit`` is 1 and Offerings are
        owner-only — so such a creator can hold Offerings in at most one
        Collective. This test pins the premise, so if the collective
        allowance ever rises the equivalence breaks loudly here."""
        community = PLANS_BY_SLUG["community"]
        assert community.active_collective_limit == 1
        assert community.offerings_max_per_collective == 5

    def test_the_displayed_allowance_matches_the_enforced_one(
        self, db, owner_space,
    ):
        from app.creator.plan_guards import offering_allowance
        space, owner = owner_space("community")
        off = _offering(db, space)
        db.flush()
        out = api.get_offering_readiness(
            space.slug, off.slug, db=db, current_user=owner,
        )
        assert out["offering_limit"] == offering_allowance(owner, db) == 5


class TestPlanDowngrade:
    def test_existing_offerings_survive_a_downgrade(self, db, owner_space, plan):
        """Nothing is deleted and nothing is converted. A creator over
        their allowance keeps everything and is simply refused the
        next one."""
        from app.creator.schemas_offerings import OfferingCreateRequest
        from app.models.creator_billing import CreatorSubscription
        space, owner = owner_space("creator")
        for i in range(7):
            api.create_offering(
                space.slug, OfferingCreateRequest(title=f"Guide {i}"),
                db=db, current_user=owner,
            )
        # Downgrade: end the paid subscription, attach Community.
        db.query(CreatorSubscription).filter(
            CreatorSubscription.user_id == owner.id,
        ).delete()
        plan(owner, "community")
        db.flush()

        kept = api.list_offerings(space.slug, db=db, current_user=owner)
        assert len(kept) == 7, "nothing deleted"
        assert _status(
            api.create_offering, space.slug,
            OfferingCreateRequest(title="Another"),
            db=db, current_user=owner,
        ) == 403, "but no new ones"

    def test_a_paid_offering_is_not_converted_to_free_on_downgrade(
        self, db, owner_space, plan,
    ):
        from app.models.creator_billing import CreatorSubscription
        space, owner = owner_space("creator")
        off = _offering(
            db, space, pricing_kind=OfferingPricingKind.one_time.value,
            price_cents=2500,
        )
        db.flush()
        db.query(CreatorSubscription).filter(
            CreatorSubscription.user_id == owner.id,
        ).delete()
        plan(owner, "community")
        db.flush()
        db.refresh(off)
        assert off.pricing_kind == "one_time"
        assert off.price_cents == 2500


# ---------------------------------------------------------------------------
# 3 · Pricing
# ---------------------------------------------------------------------------


class TestPricing:
    def test_a_paid_plan_may_set_a_price(self, db, owner_space):
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space("creator")
        off = _offering(db, space)
        db.flush()
        out = api.update_offering(
            space.slug, off.slug,
            OfferingUpdateRequest(pricing_kind="one_time", price_cents=2500),
            db=db, current_user=owner,
        )
        assert out["pricing_kind"] == "one_time"
        assert out["price_cents"] == 2500

    def test_community_cannot_set_a_paid_price(self, db, owner_space):
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space("community")
        off = _offering(db, space)
        db.flush()
        code = _status(
            api.update_offering, space.slug, off.slug,
            OfferingUpdateRequest(pricing_kind="one_time", price_cents=2500),
            db=db, current_user=owner,
        )
        assert code == 403

    def test_community_may_set_free(self, db, owner_space):
        """The positive control — Community sells free Offerings."""
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space("community")
        off = _offering(db, space)
        db.flush()
        out = api.update_offering(
            space.slug, off.slug, OfferingUpdateRequest(pricing_kind="free"),
            db=db, current_user=owner,
        )
        assert out["pricing_kind"] == "free"
        assert out["price_cents"] is None

    def test_free_clears_any_previous_price(self, db, owner_space):
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space("creator")
        off = _offering(
            db, space, pricing_kind="one_time", price_cents=1000,
        )
        db.flush()
        out = api.update_offering(
            space.slug, off.slug, OfferingUpdateRequest(pricing_kind="free"),
            db=db, current_user=owner,
        )
        assert out["price_cents"] is None

    @pytest.mark.parametrize("price", [0, None])
    def test_a_paid_offering_needs_a_positive_price(self, db, owner_space, price):
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space("creator")
        off = _offering(db, space)
        db.flush()
        code = _status(
            api.update_offering, space.slug, off.slug,
            OfferingUpdateRequest(pricing_kind="one_time", price_cents=price),
            db=db, current_user=owner,
        )
        assert code == 422

    def test_an_unknown_pricing_kind_is_refused(self, db, owner_space):
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space("creator")
        off = _offering(db, space)
        db.flush()
        assert _status(
            api.update_offering, space.slug, off.slug,
            OfferingUpdateRequest(pricing_kind="subscription", price_cents=500),
            db=db, current_user=owner,
        ) == 422

    def test_a_price_without_a_kind_is_refused_not_guessed(self, db, owner_space):
        """Inventing ``one_time`` would be the server making a pricing
        decision on the creator's behalf."""
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space("creator")
        off = _offering(db, space)
        db.flush()
        assert _status(
            api.update_offering, space.slug, off.slug,
            OfferingUpdateRequest(price_cents=1500),
            db=db, current_user=owner,
        ) == 422

    def test_the_database_refuses_an_inconsistent_pair(self, db, make_space):
        """Belt and braces: the CHECK holds even if a future code path
        forgets. A free Offering cannot carry a price."""
        from sqlalchemy.exc import IntegrityError
        space = make_space()
        with pytest.raises(IntegrityError):
            _offering(db, space, pricing_kind="free", price_cents=500)
            db.flush()
        db.rollback()

    def test_the_database_refuses_a_paid_offering_with_no_price(
        self, db, make_space,
    ):
        from sqlalchemy.exc import IntegrityError
        space = make_space()
        with pytest.raises(IntegrityError):
            _offering(db, space, pricing_kind="one_time", price_cents=None)
            db.flush()
        db.rollback()

    def test_setting_pricing_creates_no_payment_option(self, db, owner_space):
        """Phase D's job. A Payment Option now would be a commerce row
        nothing can fulfil."""
        from app.creator.schemas_offerings import OfferingUpdateRequest
        from app.models.payment_option import PaymentOption
        space, owner = owner_space("creator")
        off = _offering(db, space)
        db.flush()
        before = db.query(PaymentOption).count()
        api.update_offering(
            space.slug, off.slug,
            OfferingUpdateRequest(pricing_kind="one_time", price_cents=3000),
            db=db, current_user=owner,
        )
        assert db.query(PaymentOption).count() == before


# ---------------------------------------------------------------------------
# 4 · Cover images
# ---------------------------------------------------------------------------


class TestCoverImages:
    def test_a_platform_default_is_accepted(self, db, owner_space):
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space()
        off = _offering(db, space)
        db.flush()
        out = api.update_offering(
            space.slug, off.slug,
            OfferingUpdateRequest(cover_image_url=DEFAULT_COVER),
            db=db, current_user=owner,
        )
        assert out["cover_image_url"] == DEFAULT_COVER

    def test_a_creator_uploaded_cover_is_accepted(self, db, owner_space):
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space()
        off = _offering(db, space)
        db.flush()
        url = f"/api/uploads/offering-covers/{off.id}/{uuid.uuid4().hex}_c.png"
        out = api.update_offering(
            space.slug, off.slug, OfferingUpdateRequest(cover_image_url=url),
            db=db, current_user=owner,
        )
        assert out["cover_image_url"] == url

    @pytest.mark.parametrize("url", [
        "https://evil.example.com/tracker.png",
        "http://example.com/x.png",
        "/api/uploads/avatars/someone.png",
        "/api/uploads/platform-artwork/brand/logo.png",
        "javascript:alert(1)",
    ])
    def test_anything_else_is_refused(self, db, owner_space, url):
        """An allow-list of two shapes, not a URL validator — an
        arbitrary host would mean an off-platform request on every
        member page view."""
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space()
        off = _offering(db, space)
        db.flush()
        assert _status(
            api.update_offering, space.slug, off.slug,
            OfferingUpdateRequest(cover_image_url=url),
            db=db, current_user=owner,
        ) == 422, url

    def test_a_default_cover_routes_to_the_public_bucket_and_route(
        self, monkeypatch,
    ):
        """Verified against the real serving architecture, not asserted.

        A curated default is platform-owned imagery shown to anyone who
        can see the Offering, so it belongs on the same public path
        brand assets already use — which means supporting it changes no
        shared media-security rule.
        """
        from fastapi.routing import APIRoute
        from app.core import storage
        from app.core.config import settings
        from app.main import app
        monkeypatch.setattr(settings, "r2_bucket_public", "fc-public")
        monkeypatch.setattr(settings, "r2_bucket_private", "fc-private")

        key = "platform-artwork/offering-covers/workbook.png"
        assert storage._bucket_for_key(key) == "fc-public"

        scope = {
            "type": "http", "method": "GET", "path": f"/api/uploads/{key}",
            "headers": [], "query_string": b"", "root_path": "",
        }
        matched = next(
            r for r in app.routes
            if isinstance(r, APIRoute)
            and str(r.matches(scope)[0]) == "Match.FULL"
        )
        assert matched.endpoint.__name__ == "serve_public_upload"

    def test_a_creator_cover_routes_to_the_private_gated_path(
        self, monkeypatch,
    ):
        """The counterpart. A creator's own cover stays private and goes
        through ``_authorise_offering_cover`` — so the two kinds coexist
        without the public one widening access to the other."""
        from fastapi.routing import APIRoute
        from app.core import storage
        from app.core.config import settings
        from app.main import app
        monkeypatch.setattr(settings, "r2_bucket_public", "fc-public")
        monkeypatch.setattr(settings, "r2_bucket_private", "fc-private")

        key = "offering-covers/off_123/abcdef_mycover.png"
        assert storage._bucket_for_key(key) == "fc-private"

        scope = {
            "type": "http", "method": "GET", "path": f"/api/uploads/{key}",
            "headers": [], "query_string": b"", "root_path": "",
        }
        matched = next(
            r for r in app.routes
            if isinstance(r, APIRoute)
            and str(r.matches(scope)[0]) == "Match.FULL"
        )
        assert matched.endpoint.__name__ == "serve_upload"
        from app.uploads import authorization
        assert "offering-covers" in authorization._DISPATCH

    @pytest.mark.parametrize("url", [
        "/api/uploads/platform-artwork/offering-covers/../brand/logo.png",
        "/api/uploads/platform-artwork/offering-covers/sub/dir/x.png",
        "/api/uploads/platform-artwork/offering-covers/script.svg",
        "/api/uploads/offering-covers/../../avatars/x.png",
    ])
    def test_neither_namespace_accepts_an_arbitrary_deep_path(self, url):
        """Shapes are matched precisely, not by prefix alone, so a
        creator cannot reach another namespace through either one."""
        assert readiness.is_acceptable_cover(url) is False

    def test_a_default_cover_is_referenced_not_copied(self, db, owner_space):
        """No duplication: selecting a default stores a URL, so N
        Offerings choosing the same cover share one stored object."""
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space()
        a, b = _offering(db, space, slug="a"), _offering(db, space, slug="b")
        db.flush()
        for off in (a, b):
            api.update_offering(
                space.slug, off.slug,
                OfferingUpdateRequest(cover_image_url=DEFAULT_COVER),
                db=db, current_user=owner,
            )
        db.refresh(a); db.refresh(b)
        assert a.cover_image_url == b.cover_image_url == DEFAULT_COVER

    def test_the_default_prefix_is_the_existing_public_namespace(self):
        """Default covers need no change to media-security rules: the
        ``platform-artwork/`` prefix already has a public read route for
        exactly this class of curated, platform-owned image."""
        assert readiness._DEFAULT_COVER_PREFIX.startswith(
            "/api/uploads/platform-artwork/"
        )
        from app.core import storage
        assert storage._bucket_for_key.__doc__ is not None
        import inspect
        assert "platform-artwork/" in inspect.getsource(storage._bucket_for_key)


# ---------------------------------------------------------------------------
# 5 · Readiness and publication
# ---------------------------------------------------------------------------


class TestReadiness:
    def test_a_complete_offering_is_ready(self, db, owner_space):
        space, owner = owner_space()
        off = _publishable(db, space)
        out = api.get_offering_readiness(
            space.slug, off.slug, db=db, current_user=owner,
        )
        assert out["ready"] is True, [r for r in out["requirements"] if not r["met"]]

    @pytest.mark.parametrize("field,value,unmet", [
        ("title", "", "title"),
        ("summary", None, "summary"),
        ("cover_image_url", None, "cover_image"),
    ])
    def test_each_missing_detail_is_reported(
        self, db, owner_space, field, value, unmet,
    ):
        space, owner = owner_space()
        off = _publishable(db, space)
        setattr(off, field, value)
        db.flush()
        out = api.get_offering_readiness(
            space.slug, off.slug, db=db, current_user=owner,
        )
        assert out["ready"] is False
        assert unmet in [r["id"] for r in out["requirements"] if not r["met"]]

    def test_no_files_is_reported(self, db, owner_space):
        space, owner = owner_space()
        off = _offering(
            db, space, cover_image_url=DEFAULT_COVER, pricing_kind="free",
        )
        db.flush()
        out = api.get_offering_readiness(
            space.slug, off.slug, db=db, current_user=owner,
        )
        unmet = [r["id"] for r in out["requirements"] if not r["met"]]
        assert "has_files" in unmet

    @pytest.mark.parametrize("state", ["pending", "rejected", "error", "quarantined"])
    def test_an_unvalidated_file_blocks_readiness(self, db, owner_space, state):
        space, owner = owner_space()
        off = _offering(
            db, space, cover_image_url=DEFAULT_COVER, pricing_kind="free",
        )
        _file(db, off, status=state)
        db.flush()
        out = api.get_offering_readiness(
            space.slug, off.slug, db=db, current_user=owner,
        )
        assert out["ready"] is False
        assert "files_validated" in [
            r["id"] for r in out["requirements"] if not r["met"]
        ]

    def test_a_superseded_file_does_not_block(self, db, owner_space):
        """Only the current bundle is judged — the same predicate member
        download authorisation uses."""
        space, owner = owner_space()
        off = _publishable(db, space)
        _file(db, off, name="old.pdf", status="rejected",
              superseded_at=datetime.utcnow())
        db.flush()
        out = api.get_offering_readiness(
            space.slug, off.slug, db=db, current_user=owner,
        )
        assert out["ready"] is True

    def test_missing_pricing_is_reported(self, db, owner_space):
        space, owner = owner_space()
        off = _offering(db, space, cover_image_url=DEFAULT_COVER)
        _file(db, off)
        db.flush()
        out = api.get_offering_readiness(
            space.slug, off.slug, db=db, current_user=owner,
        )
        assert "pricing" in [r["id"] for r in out["requirements"] if not r["met"]]

    def test_rich_content_is_never_a_requirement(self, db, owner_space):
        """Optional by product decision, so it must not appear in the
        checklist at all — not even as a passing row, which would imply
        it had been assessed."""
        space, owner = owner_space()
        off = _publishable(db, space)
        out = api.get_offering_readiness(
            space.slug, off.slug, db=db, current_user=owner,
        )
        ids = [r["id"] for r in out["requirements"]]
        assert not any("about" in i or "rich" in i or "block" in i for i in ids)
        assert out["ready"] is True, "publishable with no rich content"

    def test_every_requirement_is_returned_not_just_the_first_failure(
        self, db, owner_space,
    ):
        space, owner = owner_space()
        off = _offering(db, space, title="T")   # nothing else set
        db.flush()
        out = api.get_offering_readiness(
            space.slug, off.slug, db=db, current_user=owner,
        )
        unmet = [r["id"] for r in out["requirements"] if not r["met"]]
        assert len(unmet) >= 3, unmet
        assert all(r["message"] for r in out["requirements"] if not r["met"])

    def test_no_message_implies_a_malware_scan(self, db, owner_space):
        space, owner = owner_space()
        off = _offering(db, space, cover_image_url=DEFAULT_COVER,
                        pricing_kind="free")
        _file(db, off, status="pending")
        db.flush()
        out = api.get_offering_readiness(
            space.slug, off.slug, db=db, current_user=owner,
        )
        blob = " ".join(r["message"] for r in out["requirements"]).lower()
        for banned in ("virus", "malware", "scanned", "safe", "clean"):
            assert banned not in blob, banned


class TestPublish:
    def test_a_ready_offering_publishes(self, db, owner_space):
        space, owner = owner_space()
        off = _publishable(db, space)
        out = api.publish_offering(
            space.slug, off.slug, db=db, current_user=owner,
        )
        assert out["status"] == "published"
        assert out["published_at"] is not None

    @pytest.mark.parametrize("state", ["pending", "rejected", "error", "quarantined"])
    def test_publishing_is_refused_while_a_file_is_unvalidated(
        self, db, owner_space, state,
    ):
        space, owner = owner_space()
        off = _offering(db, space, cover_image_url=DEFAULT_COVER,
                        pricing_kind="free")
        _file(db, off, status=state)
        db.flush()
        assert _status(
            api.publish_offering, space.slug, off.slug,
            db=db, current_user=owner,
        ) == 409, state

    def test_publishing_revalidates_rather_than_trusting_readiness(
        self, db, owner_space,
    ):
        """A file can be removed or quarantined between the creator
        seeing a green checklist and clicking publish."""
        space, owner = owner_space()
        off = _publishable(db, space)
        assert api.get_offering_readiness(
            space.slug, off.slug, db=db, current_user=owner,
        )["ready"] is True

        f = db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).one()
        f.validation_status = FVS.quarantined.value
        f.quarantined_at = datetime.utcnow()
        db.flush()

        assert _status(
            api.publish_offering, space.slug, off.slug,
            db=db, current_user=owner,
        ) == 409

    def test_a_community_creator_cannot_publish_a_paid_offering(
        self, db, owner_space,
    ):
        """Pricing was set under a paid plan and the creator downgraded.
        Readiness catches it at publish time."""
        space, owner = owner_space("community")
        off = _publishable(db, space)
        off.pricing_kind = OfferingPricingKind.one_time.value
        off.price_cents = 2500
        db.flush()
        assert _status(
            api.publish_offering, space.slug, off.slug,
            db=db, current_user=owner,
        ) == 409

    def test_a_published_offering_keeps_its_first_published_at(
        self, db, owner_space,
    ):
        space, owner = owner_space()
        off = _publishable(db, space)
        first = api.publish_offering(
            space.slug, off.slug, db=db, current_user=owner,
        )["published_at"]
        again = api.publish_offering(
            space.slug, off.slug, db=db, current_user=owner,
        )["published_at"]
        assert first == again

    def test_a_draft_is_not_listed_to_anyone_else(self, db, owner_space):
        """Draft privacy. There is no member route yet, so the guarantee
        here is that no other creator can reach it."""
        space, owner = owner_space()
        space_b, owner_b = owner_space()
        _offering(db, space, slug="secret-draft")
        db.flush()
        assert _status(
            api.get_offering, space_b.slug, "secret-draft",
            db=db, current_user=owner_b,
        ) == 404


class TestRetire:
    def test_retiring_sets_the_state_and_timestamp(self, db, owner_space):
        space, owner = owner_space()
        off = _publishable(db, space)
        api.publish_offering(space.slug, off.slug, db=db, current_user=owner)
        out = api.retire_offering(
            space.slug, off.slug, db=db, current_user=owner,
        )
        assert out["status"] == "retired"
        assert out["retired_at"] is not None

    def test_retiring_preserves_entitlements_and_files(
        self, db, owner_space, make_user,
    ):
        space, owner = owner_space()
        off = _publishable(db, space)
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id,
            source=OfferingEntitlementSource.one_time_purchase.value,
            status=OfferingEntitlementStatus.active.value,
        ))
        db.flush()
        api.retire_offering(space.slug, off.slug, db=db, current_user=owner)

        ent = db.query(OfferingEntitlement).filter(
            OfferingEntitlement.offering_id == off.id,
        ).one()
        assert ent.status == "active"
        assert db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).count() == 1

    def test_a_retired_purchaser_can_still_download(
        self, db, owner_space, make_user,
    ):
        """The architectural guarantee, re-asserted at this layer:
        download authorisation never consults an Offering's status."""
        from app.uploads.authorization import authorize_upload
        space, owner = owner_space()
        off = _publishable(db, space)
        f = db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).one()
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id, source="one_time_purchase", status="active",
        ))
        db.flush()
        api.retire_offering(space.slug, off.slug, db=db, current_user=owner)
        authorize_upload(f.storage_key, buyer, db)   # no exception

    def test_retiring_is_idempotent(self, db, owner_space):
        space, owner = owner_space()
        off = _publishable(db, space)
        a = api.retire_offering(space.slug, off.slug, db=db, current_user=owner)
        b = api.retire_offering(space.slug, off.slug, db=db, current_user=owner)
        assert a["retired_at"] == b["retired_at"]

    def test_a_retired_offering_cannot_be_republished(self, db, owner_space):
        space, owner = owner_space()
        off = _publishable(db, space)
        api.retire_offering(space.slug, off.slug, db=db, current_user=owner)
        assert _status(
            api.publish_offering, space.slug, off.slug,
            db=db, current_user=owner,
        ) == 409

    def test_retired_offerings_stay_in_the_creator_list(self, db, owner_space):
        space, owner = owner_space()
        off = _publishable(db, space)
        api.retire_offering(space.slug, off.slug, db=db, current_user=owner)
        rows = api.list_offerings(space.slug, db=db, current_user=owner)
        assert [r["status"] for r in rows] == ["retired"]

    def test_nothing_is_physically_deleted_in_this_phase(self):
        """No endpoint deletes an Offering. A retired product still has
        purchasers."""
        import inspect
        src = inspect.getsource(api)
        assert "db.delete(" not in src
        assert not any(
            r.path.endswith("/offerings/{offering_slug}")
            and "DELETE" in (getattr(r, "methods", None) or set())
            for r in __import__("app.main", fromlist=["app"]).app.routes
        )


# ---------------------------------------------------------------------------
# 6 · Feature flag
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    def test_it_is_disabled_by_default(self):
        from app.core.config import Settings
        assert Settings().offerings_enabled is False

    def test_the_dependency_refuses_while_disabled(self):
        from app.core.config import settings
        assert settings.offerings_enabled is False
        with pytest.raises(HTTPException) as exc:
            api.require_offerings_enabled()
        assert exc.value.status_code == 404

    def test_the_refusal_stays_outside_sentrys_captured_range(self):
        """The regression this fix exists for.

        Sentry's ``StarletteIntegration`` keeps its
        ``failed_request_status_codes`` default of 500–599, so a 5xx
        refusal from a *deliberately* disabled feature becomes a
        captured event — which is what produced FC-API-9: 36 events of
        the application working as designed.

        Asserted against the SDK's actual default rather than the
        number 500, so this keeps meaning what it says if the default
        ever moves.
        """
        from sentry_sdk.integrations.starlette import (
            StarletteIntegration,
        )
        import inspect

        sig = inspect.signature(StarletteIntegration.__init__)
        captured = sig.parameters["failed_request_status_codes"].default

        with pytest.raises(HTTPException) as exc:
            api.require_offerings_enabled()
        code = exc.value.status_code

        # ``captured`` is a range-like set of status codes in current
        # SDKs; fall back to the documented 500-599 if the shape differs.
        try:
            is_captured = code in captured
        except TypeError:          # pragma: no cover - SDK shape change
            is_captured = 500 <= code <= 599
        assert not is_captured, (
            f"status {code} falls inside Sentry's captured range — a "
            "disabled feature must not report itself as an error"
        )

    def test_the_refusal_does_not_name_the_feature(self):
        """A refusal should not confirm the existence of something the
        caller is not entitled to see — the same reasoning
        ``_get_owned_space`` uses for its 404."""
        with pytest.raises(HTTPException) as exc:
            api.require_offerings_enabled()
        assert "offering" not in str(exc.value.detail).lower()

    def test_global_exception_handling_is_untouched(self):
        """The fix changes one status code, not how errors are
        reported. Genuine 5xx must still reach Sentry, so the captured
        range and the ignore list stay exactly as they were."""
        import inspect
        from app.core import observability
        src = inspect.getsource(observability)
        assert "failed_request_status_codes=" not in src, (
            "the captured range must not be narrowed to fix this"
        )
        assert "default_integrations=True" in src
        # And no new logger suppression was added for Offerings.
        assert not any(
            "offering" in p.lower()
            for p in observability.NEVER_REPORTED_LOGGERS
        )

    def test_the_dependency_allows_when_enabled(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "offerings_enabled", True)
        api.require_offerings_enabled()   # no exception

    def test_the_router_declares_the_dependency_once(self):
        """Attached at the router, not remembered per handler — so a new
        endpoint added to this module cannot forget it.

        This is the assertion that matters, because the handler tests in
        this file call functions directly and therefore bypass the
        dependency entirely.
        """
        deps = api.router.dependencies
        assert len(deps) >= 1
        names = [getattr(d.dependency, "__name__", "") for d in deps]
        assert "require_offerings_enabled" in names

    def test_every_offering_route_inherits_the_gate(self):
        from app.main import app
        from fastapi.routing import APIRoute
        gated = 0
        for r in app.routes:
            if isinstance(r, APIRoute) and "offerings" in r.path:
                names = [
                    getattr(d.call, "__name__", "")
                    for d in r.dependant.dependencies
                ]
                assert "require_offerings_enabled" in names, r.path
                gated += 1

        # The loop above is the assertion; these two stop it passing
        # vacuously. Counting against the routers themselves rather than
        # against a hard-coded number means adding an endpoint cannot
        # make this test stale — it either inherits the gate and is
        # counted, or the loop fails on it.
        from app.creator import _offering_file_routes, _offering_routes
        declared = sum(
            1
            for mod in (_offering_routes, _offering_file_routes)
            for route in mod.router.routes
            if isinstance(route, APIRoute)
        )
        assert gated == declared, (gated, declared)
        # A floor, so deleting every route does not make this pass.
        # Phase B4 shipped 7; Phase B5 adds 6 file endpoints.
        assert gated >= 13, gated

    def test_there_is_no_admin_or_owner_bypass(self):
        """A bypass is how unfinished functionality reaches production.
        Turning the flag on is the only way in.

        Checked against the statements, not the source text — the
        function's docstring explains the absence and names the thing
        being excluded while doing so.
        """
        code = _code_only(api.require_offerings_enabled)
        for bypass in ("is_platform_owner", "superuser", "is_admin"):
            assert bypass not in code, bypass
        # And the only thing it reads is the flag.
        assert "offerings_enabled" in code

    def test_download_entitlements_are_independent_of_the_flag(
        self, db, owner_space, make_user,
    ):
        """The approved separation: the flag governs new activity, never
        access to what a member already owns."""
        from app.core.config import settings
        from app.uploads.authorization import authorize_upload
        assert settings.offerings_enabled is False
        space, _ = owner_space()
        off = _publishable(db, space)
        f = db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).one()
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id, source="one_time_purchase", status="active",
        ))
        db.flush()
        authorize_upload(f.storage_key, buyer, db)   # no exception


# ---------------------------------------------------------------------------
# 7 · Nothing else moved
# ---------------------------------------------------------------------------


class TestExistingBehaviourUnchanged:
    def test_no_stripe_or_checkout_code_is_reachable_from_here(self):
        """Phase B4 stores pricing intent and nothing more.

        Over the module's statements rather than its text: the docstrings
        say "no checkout" and "deferred to Phase D", which a raw search
        would read as a use.
        """
        code = _code_only(api)
        for forbidden in ("stripe", "PaymentOption", "DiscountCode",
                          "create_unified_checkout_session"):
            assert forbidden not in code, forbidden

    def test_the_module_imports_nothing_from_commerce(self):
        """The structural half of the same claim."""
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(api)))
        mods = []
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                mods.append(n.module)
            elif isinstance(n, ast.Import):
                mods += [a.name for a in n.names]
        for m in mods:
            assert "checkout" not in m, m
            assert "stripe" not in m, m
            assert "payment" not in m or m.endswith("plan_guards"), m

    def test_the_pathway_quota_guard_is_unchanged(self):
        from app.creator.plan_guards import guard_pathway_limit
        import inspect
        src = inspect.getsource(guard_pathway_limit)
        assert "pathways_max_per_collective" in src
        assert "Pathway.space_id == space.id" in src

    def test_existing_plan_capabilities_are_unchanged(self):
        c = PLANS_BY_SLUG["community"]
        assert c.pathways_max_per_collective == 5
        assert c.member_allowance_per_collective == 100
        assert c.paid_offers_enabled is False
        assert PLANS_BY_SLUG["creator"].paid_offers_enabled is True

    def test_the_gathering_capacity_rule_is_unchanged(self):
        from app.services.gathering_tickets import CAPACITY_USED_SQL
        sql = str(CAPACITY_USED_SQL)
        assert "pending_payment" in sql and "hold_expires_at" not in sql

    def test_payment_option_grant_kinds_are_still_unchanged(self):
        from app.models import payment_option_grant as pog
        assert not hasattr(pog, "GRANT_KIND_OFFERING")

    def test_the_offer_pages_schema_is_untouched(self):
        from app.db.base import Base
        assert "offer_pages" in Base.metadata.tables
        import pathlib
        versions = pathlib.Path(__file__).parent.parent / "alembic" / "versions"
        assert (versions / "104_offer_pages.py").exists()

    def test_only_the_three_offering_tables_carry_offering_columns(self):
        from app.db.base import Base
        allowed = {"offerings", "offering_files", "offering_entitlements"}
        for name, table in Base.metadata.tables.items():
            if name in allowed:
                continue
            bad = [c.name for c in table.columns if "offering" in c.name]
            assert bad == [], f"{name}: {bad}"
