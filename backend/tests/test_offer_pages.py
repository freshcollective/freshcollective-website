"""Offer Pages — V1 backend foundation.

Covers the storage-and-endpoints half of the milestone:

  * Model defaults (drafts start as draft; slug lock derived, not
    stored).
  * Slug generation + uniqueness per Collective; auto-suffix on
    collisions.
  * Slug lock — permanent once ``published_at`` is set; unchanged by
    unpublish or archive (link stability across the shared link's
    lifetime is the whole reason the lock exists).
  * Status transitions — publishing sets published_at; unpublishing
    keeps it; republishing does not touch it.
  * Target validation — must belong to the same Collective as the
    Offer Page; unknown target kinds are rejected.
  * Public visibility — only ``published`` visible to visitors;
    owner previews draft + archived through the same URL.
  * ``user_has_target_access`` — flips based on the viewer's real
    pathway access (uses the existing ``_compute_pathway_access``
    helper, so the boolean matches every other public surface).

The Creator Studio surface + public renderer land in later commits;
those flows are exercised via the endpoints here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.creator.routes import (
    create_offer_page,
    delete_offer_page,
    get_offer_page,
    list_offer_pages,
    update_offer_page,
)
from app.creator.schemas import (
    OfferInvitationSection,
    OfferPageCreateRequest,
    OfferPageUpdateRequest,
    OfferSectionsConfig,
    OfferWhatsIncludedSection,
)
from app.models.creator_billing import CreatorPlan, CreatorSubscription
from app.models.platform import (
    Enrollment,
    OfferPage,
    Pathway,
    PathwayEntitlement,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.spaces.routes import get_public_offer_page


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pathway(
    db, space, *, title: str = "Home Practice", access_type: str = "free",
    price_cents: int | None = None, status: str = "active",
) -> Pathway:
    p = Pathway(
        id=f"pw_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        status=status,
        access_type=access_type,
        price_cents=price_cents,
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def _member_of(db, make_user, space, *, role: SpaceRole = SpaceRole.learner):
    u = make_user(role="user")
    db.add(SpaceMembership(
        id=f"sm_{uuid.uuid4().hex[:12]}",
        user_id=u.id,
        space_id=space.id,
        role=role,
        status=SpaceMembershipStatus.active,
    ))
    db.flush()
    return u


# Offer Page writes go through ``guard_offer_pages_enabled`` which
# reads ``creator_plans`` + ``creator_subscriptions`` via the shared
# ``resolve_creator_plan`` helper. Its fallback rule is "cheapest
# active plan" — so seeding *only* the Creator plan by default gives
# every creator user Creator-tier capabilities without needing an
# explicit subscription row. Gating tests that need a different tier
# (Community, Pro) create their own plan + subscription explicitly.

def _seed_plan(db, slug: str, price_cents: int) -> CreatorPlan:
    existing = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
    if existing:
        return existing
    plan = CreatorPlan(
        id=f"plan_{slug}_{uuid.uuid4().hex[:8]}",
        name=slug.capitalize(),
        slug=slug,
        monthly_price_cents=price_cents,
        currency="AUD",
        transaction_fee_basis_points=800 if slug in ("creator",) else 300 if slug == "pro" else 0,
        collective_limit=5 if slug == "pro" else 1,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


def _grant_plan(db, user, slug: str) -> CreatorSubscription:
    plan = _seed_plan(
        db, slug,
        price_cents={"community": 0, "creator": 1900, "pro": 7900}.get(slug, 1900),
    )
    sub = CreatorSubscription(
        id=f"sub_{uuid.uuid4().hex[:12]}",
        user_id=user.id,
        creator_plan_id=plan.id,
        status="active",
        source="manual_grant",
    )
    db.add(sub)
    db.flush()
    return sub


@pytest.fixture(autouse=True)
def _seed_creator_default_plan(db):
    """Autouse: seed a Creator plan so ``resolve_creator_plan``'s
    fallback ("cheapest active") returns Creator by default. Every
    creator-role user in this file therefore passes the Offer Pages
    guard without needing an explicit subscription row — matching
    the codebase's convention that a creator without an explicit
    subscription is treated as being on the cheapest active plan.
    """
    _seed_plan(db, "creator", 1900)
    yield


# ---------------------------------------------------------------------------
# Create + defaults
# ---------------------------------------------------------------------------


class TestCreate:
    def test_new_page_starts_as_draft(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        result = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Join Home Practice",
                target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        assert result["status"] == "draft"
        assert result["published_at"] is None
        assert result["slug_locked"] is False
        # Slug is auto-generated from the title.
        assert result["slug"].startswith("join-home-practice")

    def test_slug_can_be_explicitly_supplied(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        result = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Join Home Practice",
                target_kind="pathway",
                target_id=pathway.id,
                slug="winter-launch",
            ),
            db=db, current_user=creator,
        )
        assert result["slug"] == "winter-launch"

    def test_slug_auto_suffix_on_collision(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        first = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Join Home Practice",
                target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        second = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Join Home Practice",
                target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        assert first["slug"] != second["slug"]
        assert second["slug"].endswith("-2")

    def test_explicit_slug_collision_rejected(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="First", target_kind="pathway",
                target_id=pathway.id, slug="taken",
            ),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as exc:
            create_offer_page(
                slug=space.slug,
                body=OfferPageCreateRequest(
                    title="Second", target_kind="pathway",
                    target_id=pathway.id, slug="taken",
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_unknown_target_kind_rejected(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()

        with pytest.raises(ValueError):
            OfferPageCreateRequest(
                title="x", target_kind="bundle", target_id="whatever",
            )

    def test_target_from_other_space_rejected(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space_a = make_space(creator=creator)
        space_b = make_space()
        # Target pathway lives in space_b — creator has no rights.
        other_pathway = _make_pathway(db, space_b)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_offer_page(
                slug=space_a.slug,
                body=OfferPageCreateRequest(
                    title="Cross-space", target_kind="pathway",
                    target_id=other_pathway.id,
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Slug lock
# ---------------------------------------------------------------------------


class TestSlugLock:
    def _publish(self, db, offer_row):
        offer_row.status = "published"
        offer_row.published_at = datetime.utcnow()
        db.commit()

    def test_draft_slug_is_editable(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Draft", target_kind="pathway",
                target_id=pathway.id, slug="draft-one",
            ),
            db=db, current_user=creator,
        )
        result = update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(slug="draft-renamed"),
            db=db, current_user=creator,
        )
        assert result["slug"] == "draft-renamed"
        assert result["slug_locked"] is False

    def test_published_slug_is_locked(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Live", target_kind="pathway",
                target_id=pathway.id, slug="live-one",
            ),
            db=db, current_user=creator,
        )
        # Publish
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        # Now attempting to rename must fail.
        with pytest.raises(HTTPException) as exc:
            update_offer_page(
                slug=space.slug, offer_slug="live-one",
                body=OfferPageUpdateRequest(slug="renamed"),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_unpublished_slug_stays_locked_permanently(
        self, db, make_user, make_space,
    ):
        # This is the specific decision the user asked for:
        # link stability persists across the offer's whole life.
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Live", target_kind="pathway",
                target_id=pathway.id, slug="was-live",
            ),
            db=db, current_user=creator,
        )
        # Publish then unpublish (back to draft)
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug="was-live",
            body=OfferPageUpdateRequest(status="draft"),
            db=db, current_user=creator,
        )
        # Even though status is now draft, slug MUST remain locked.
        with pytest.raises(HTTPException) as exc:
            update_offer_page(
                slug=space.slug, offer_slug="was-live",
                body=OfferPageUpdateRequest(slug="renamed"),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_archived_slug_stays_locked(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Live", target_kind="pathway",
                target_id=pathway.id, slug="was-live-then-archived",
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="archived"),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as exc:
            update_offer_page(
                slug=space.slug, offer_slug=created["slug"],
                body=OfferPageUpdateRequest(slug="renamed"),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Publish transitions
# ---------------------------------------------------------------------------


class TestPublish:
    def test_publish_sets_published_at(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Publishing test", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        assert created["published_at"] is None

        result = update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        assert result["status"] == "published"
        assert result["published_at"] is not None
        assert result["slug_locked"] is True

    def test_unpublish_keeps_published_at(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Publishing test", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        result = update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="draft"),
            db=db, current_user=creator,
        )
        assert result["status"] == "draft"
        assert result["published_at"] is not None    # never cleared
        assert result["slug_locked"] is True         # still locked


# ---------------------------------------------------------------------------
# Sections config round-trip
# ---------------------------------------------------------------------------


class TestSectionsConfig:
    def test_sections_persist_as_dict(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Sectiony", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        sections = OfferSectionsConfig(
            invitation=OfferInvitationSection(
                enabled=True, body="hello",
            ),
            whats_included=OfferWhatsIncludedSection(
                enabled=True, items=["A", "B"],
            ),
        )
        result = update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(sections_config=sections),
            db=db, current_user=creator,
        )
        assert result["sections_config"]["invitation"]["enabled"] is True
        assert result["sections_config"]["invitation"]["body"] == "hello"
        assert result["sections_config"]["whats_included"]["items"] == ["A", "B"]

    def test_whats_included_items_stripped_and_deduped(
        self, db, make_user, make_space,
    ):
        # The section validator drops blanks and trims whitespace.
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="clean", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        sections = OfferSectionsConfig(
            whats_included=OfferWhatsIncludedSection(
                enabled=True, items=["  one  ", "", "two"],
            ),
        )
        result = update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(sections_config=sections),
            db=db, current_user=creator,
        )
        assert result["sections_config"]["whats_included"]["items"] == ["one", "two"]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_draft_deletable(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="disposable", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        delete_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            db=db, current_user=creator,
        )
        # Refetch must 404
        with pytest.raises(HTTPException) as exc:
            get_offer_page(
                slug=space.slug, offer_slug=created["slug"],
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 404

    def test_published_delete_forbidden_archive_instead(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="live", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as exc:
            delete_offer_page(
                slug=space.slug, offer_slug=created["slug"],
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestList:
    def test_list_includes_target_title(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space, title="Home Practice")
        db.commit()

        create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="join hp", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        rows = list_offer_pages(
            slug=space.slug, db=db, current_user=creator,
        )
        assert len(rows) == 1
        assert rows[0]["target_title"] == "Home Practice"


# ---------------------------------------------------------------------------
# Public visibility
# ---------------------------------------------------------------------------


class TestPublicVisibility:
    def _create_paid_pathway_and_offer(self, db, creator, space):
        pathway = _make_pathway(
            db, space, title="Paid Path", access_type="one_time",
            price_cents=4900,
        )
        db.commit()
        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Paid Path Offer", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        return pathway, created

    def test_draft_404s_for_visitor(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _, created = self._create_paid_pathway_and_offer(db, creator, space)
        visitor = make_user()
        db.commit()

        with pytest.raises(HTTPException) as exc:
            get_public_offer_page(
                slug=space.slug, offer_slug=created["slug"],
                db=db, current_user=visitor,
            )
        assert exc.value.status_code == 404

    def test_draft_404s_for_anonymous(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _, created = self._create_paid_pathway_and_offer(db, creator, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            get_public_offer_page(
                slug=space.slug, offer_slug=created["slug"],
                db=db, current_user=None,
            )
        assert exc.value.status_code == 404

    def test_owner_previews_draft_at_the_public_url(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        # The space fixture creates the creator as owner; grant a
        # creator-role membership so ``_viewer_owns_space`` recognises
        # them via the standard membership check.
        db.add(SpaceMembership(
            id=f"sm_{uuid.uuid4().hex[:12]}",
            user_id=creator.id, space_id=space.id,
            role=SpaceRole.creator,
            status=SpaceMembershipStatus.active,
        ))
        _, created = self._create_paid_pathway_and_offer(db, creator, space)
        db.commit()

        result = get_public_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            db=db, current_user=creator,
        )
        assert result.status == "draft"       # owner sees drafts too

    def test_published_visible_to_everyone(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _, created = self._create_paid_pathway_and_offer(db, creator, space)
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        visitor = make_user()
        db.commit()

        result = get_public_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            db=db, current_user=visitor,
        )
        assert result.status == "published"

    def test_archived_404s_for_visitor(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _, created = self._create_paid_pathway_and_offer(db, creator, space)
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="archived"),
            db=db, current_user=creator,
        )
        visitor = make_user()
        db.commit()

        with pytest.raises(HTTPException) as exc:
            get_public_offer_page(
                slug=space.slug, offer_slug=created["slug"],
                db=db, current_user=visitor,
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# user_has_target_access
# ---------------------------------------------------------------------------


class TestUserHasAccess:
    def test_false_for_signed_out_visitor(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(
            db, space, access_type="one_time", price_cents=4900,
        )
        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="paid", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        db.commit()

        result = get_public_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            db=db, current_user=None,
        )
        assert result.user_has_target_access is False
        assert result.target.checkout_path is not None

    def test_true_when_member_holds_entitlement(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(
            db, space, access_type="one_time", price_cents=4900,
        )
        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="paid", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        # Grant a member entitlement — this is what a real purchase
        # would insert. ``_compute_pathway_access`` reads exactly this.
        member = _member_of(db, make_user, space)
        db.add(PathwayEntitlement(
            id=f"pe_{uuid.uuid4().hex[:12]}",
            user_id=member.id,
            space_id=space.id,
            pathway_id=pathway.id,
            source="one_time_purchase",
            status="active",
        ))
        db.commit()

        result = get_public_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            db=db, current_user=member,
        )
        assert result.user_has_target_access is True
        # ``enter_path`` is always populated so the "Continue" CTA has
        # somewhere to go.
        assert result.target.enter_path == f"/spaces/{space.slug}/pathways/{pathway.slug}"


# ---------------------------------------------------------------------------
# Plan gating — Community must not be able to author Offer Pages
# ---------------------------------------------------------------------------


class TestPlanGating:
    """Offer Pages are a commercial surface. The guard reuses the
    existing ``paid_offers_enabled`` capability so Community-plan
    creators are refused at the write boundary — frontend hiding
    alone would let a direct API call slip through.
    """

    def test_community_plan_forbidden_on_create(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        # Explicit Community subscription overrides the autouse
        # Creator fallback for this user only.
        _grant_plan(db, creator, "community")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_offer_page(
                slug=space.slug,
                body=OfferPageCreateRequest(
                    title="Community-attempt",
                    target_kind="pathway",
                    target_id=pathway.id,
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 403
        assert "Offer Pages" in exc.value.detail

    def test_community_plan_forbidden_on_update(
        self, db, make_user, make_space,
    ):
        # Set up an Offer Page while the creator is on Creator plan,
        # then downgrade them to Community and try to update. The
        # historical row still exists (read still works), but writes
        # are blocked — the exact "downgraded creator" UX.
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        # First write happens on the default Creator plan (autouse
        # seeds it as the fallback).
        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Made on Creator", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        # Now downgrade — explicit Community subscription.
        _grant_plan(db, creator, "community")
        db.commit()

        with pytest.raises(HTTPException) as exc:
            update_offer_page(
                slug=space.slug, offer_slug=created["slug"],
                body=OfferPageUpdateRequest(title="renamed"),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 403

    def test_community_plan_forbidden_on_delete(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()
        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Delete me", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        _grant_plan(db, creator, "community")
        db.commit()

        with pytest.raises(HTTPException) as exc:
            delete_offer_page(
                slug=space.slug, offer_slug=created["slug"],
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 403

    def test_creator_plan_allowed(self, db, make_user, make_space):
        # Explicit Creator subscription (the default anyway) — just
        # asserts the happy path so the gate isn't accidentally
        # refusing Creator too.
        creator = make_user(role="creator")
        _grant_plan(db, creator, "creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        result = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="creator ok", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        assert result["status"] == "draft"

    def test_pro_plan_allowed(self, db, make_user, make_space):
        creator = make_user(role="creator")
        _grant_plan(db, creator, "pro")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        result = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="pro ok", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        assert result["status"] == "draft"

    def test_platform_admin_bypasses_the_guard(
        self, db, make_user, make_space,
    ):
        # Platform Owner (role='admin') does not belong to any
        # creator plan and therefore bypasses ``paid_offers_enabled``
        # entirely. No subscription needed.
        admin = make_user(role="admin")
        space = make_space(creator=admin)   # admin owns the space
        pathway = _make_pathway(db, space)
        db.commit()

        result = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="admin bypass", target_kind="pathway",
                target_id=pathway.id,
            ),
            db=db, current_user=admin,
        )
        assert result["status"] == "draft"
