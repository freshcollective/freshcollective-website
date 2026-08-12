"""Milestone 2 Step 1 — Offer Pages targeting Gathering Series /
Gathering + the new /api/checkout/gathering-series endpoint.

Covers:

  * Extended target validation — ``event_series`` and ``gathering``
    kinds accepted at create-time, cross-Collective targets rejected.
  * ``_build_target_snapshot`` — series target returns published
    PaymentOptions + Schedules; gathering target returns event
    metadata + ticket fields; deleted targets return an "(Unavailable)"
    snapshot without crashing.
  * PublicOfferPage exposes the real ``CreatorProfile`` on ``creator``
    with a Space-name fallback when the profile is missing or
    non-public.
  * ``EventSummary.series_offer_page_slug`` populated from a
    *published* Offer Page whose ``target_kind='event_series'``
    matches — draft/archived pages must not leak into the member API.
  * ``POST /api/checkout/gathering-series``:
      – 404 on unknown series / option / schedule
      – 400 on non-series option, wrong series-option pairing,
        non-published option, non-published schedule, zero price
      – 503 on recurring_installments schedule
      – 409 on active-pass duplicate
      – Success writes a ``member_series_pass_purchase`` transaction
        with the right metadata and no PathwayEntitlement.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe
from fastapi import HTTPException

from app.checkout.routes import create_gathering_series_checkout_session
from app.checkout.schemas import GatheringSeriesCheckoutRequest
from app.core.config import settings
from app.creator.routes import create_offer_page, update_offer_page
from app.creator.schemas import OfferPageCreateRequest, OfferPageUpdateRequest
from app.models.access_pass import (
    AccessPass,
    AccessPassStatus,
    AccessPassType,
)
from app.models.creator_billing import CreatorPlan, CreatorSubscription
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    CreatorProfile,
    Event,
    EventSeries,
    OfferPage,
    Pathway,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.spaces.routes import get_public_offer_page, list_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


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
        transaction_fee_basis_points=800 if slug == "creator" else 0,
        collective_limit=1,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


@pytest.fixture(autouse=True)
def _seed_creator_default_plan(db):
    """Autouse: seed a Creator plan so the offer-page guard's
    "cheapest active" fallback returns Creator by default."""
    _seed_plan(db, "creator", 1900)
    yield


@pytest.fixture
def stripe_configured(monkeypatch):
    """``settings.stripe_enabled`` is a computed property (secret_key
    AND webhook_secret both set) — set both so the endpoint's guard
    passes."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")


def _make_pathway(db, space, *, title: str = "Practice") -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        status="active",
        access_type="free",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def _make_series(
    db, space, *, title: str = "EMBODY Term",
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    status: str = "published",
) -> EventSeries:
    starts_at = starts_at or (datetime.utcnow() + timedelta(days=7))
    s = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title,
        starts_at=starts_at,
        ends_at=ends_at if ends_at is not None else (starts_at + timedelta(days=90)),
        status=status,
        cover_image_url="https://images.test/series-cover.jpg",
    )
    db.add(s)
    db.flush()
    return s


def _make_series_option(
    db, space, series, *, name: str,
    total_sessions: int = 12, sessions_per_week: int = 1,
    price_cents: int = 60000,
    status: PaymentOptionStatus = PaymentOptionStatus.published,
    grants_pathway_id: str | None = None,
) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        pathway_id=None,
        attaches_to_kind="event_series",
        attaches_to_id=series.id,
        grants_pathway_id=grants_pathway_id,
        name=name,
        payment_type=PaymentOptionType.term_pass,
        status=status,
        sessions_per_week=sessions_per_week,
        total_sessions=total_sessions,
        price_per_session_cents=price_cents // max(total_sessions, 1),
        calculated_total_cents=price_cents,
        currency="AUD",
        position=0,
    )
    db.add(opt)
    db.flush()
    return opt


def _make_schedule(
    db, option, *, name: str = "Pay in full",
    schedule_type: str = "pay_in_full",
    total_amount_cents: int = 60000,
    installment_amount_cents: int | None = None,
    installment_count: int | None = None,
    status: str = "published",
) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"),
        payment_option_id=option.id,
        name=name,
        schedule_type=schedule_type,
        status=status,
        total_amount_cents=total_amount_cents,
        installment_amount_cents=installment_amount_cents,
        installment_count=installment_count,
        currency="AUD",
    )
    db.add(s)
    db.flush()
    return s


def _make_event(db, space, *, series=None, **overrides) -> Event:
    defaults = dict(
        id=_uid("e"),
        space_id=space.id,
        created_by_id=space.creator_id,
        title="Session",
        starts_at=datetime.utcnow() + timedelta(days=10),
        ends_at=datetime.utcnow() + timedelta(days=10, hours=1),
        location_type="zoom",
        is_published=True,
        status="active",
        requires_booking=True,
        capacity=20,
        booking_access_type="included_with_series" if series else "included_with_collective",
        gathering_type="workshop",
        attendance_format="online",
        series_id=series.id if series else None,
    )
    defaults.update(overrides)
    e = Event(**defaults)
    db.add(e)
    db.flush()
    return e


def _member_of(db, make_user, space):
    u = make_user(role="user")
    db.add(SpaceMembership(
        id=_uid("sm"),
        user_id=u.id,
        space_id=space.id,
        role=SpaceRole.learner,
        status=SpaceMembershipStatus.active,
    ))
    db.flush()
    return u


# ---------------------------------------------------------------------------
# Target validation: three kinds accepted, cross-space rejected
# ---------------------------------------------------------------------------


class TestExtendedTargetValidation:
    def test_series_target_accepted(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        series = _make_series(db, space, title="EMBODY Term 4")
        db.commit()

        result = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="EMBODY Term 4 pass",
                target_kind="event_series",
                target_id=series.id,
            ),
            db=db, current_user=creator,
        )
        assert result["target_kind"] == "event_series"
        assert result["target_id"] == series.id

    def test_gathering_target_accepted(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        e = _make_event(db, space)
        db.commit()

        result = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Single-session ticket",
                target_kind="gathering",
                target_id=e.id,
            ),
            db=db, current_user=creator,
        )
        assert result["target_kind"] == "gathering"
        assert result["target_id"] == e.id

    def test_cross_space_series_rejected(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space_a = make_space(creator=creator)
        space_b = make_space()
        other_series = _make_series(db, space_b, title="Their term")
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_offer_page(
                slug=space_a.slug,
                body=OfferPageCreateRequest(
                    title="Cross-space",
                    target_kind="event_series",
                    target_id=other_series.id,
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_cross_space_gathering_rejected(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space_a = make_space(creator=creator)
        space_b = make_space()
        other_event = _make_event(db, space_b)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_offer_page(
                slug=space_a.slug,
                body=OfferPageCreateRequest(
                    title="Cross-space",
                    target_kind="gathering",
                    target_id=other_event.id,
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_unknown_kind_still_rejected(self):
        with pytest.raises(ValueError):
            OfferPageCreateRequest(
                title="x", target_kind="bundle", target_id="whatever",
            )


# ---------------------------------------------------------------------------
# Public snapshot: series target
# ---------------------------------------------------------------------------


class TestSeriesTargetSnapshot:
    def _publish_series_offer(
        self, db, creator, space, series,
    ) -> str:
        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Series pass",
                target_kind="event_series",
                target_id=series.id,
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        return created["slug"]

    def test_snapshot_includes_published_options_and_schedules(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        series = _make_series(db, space, title="EMBODY Term 4")

        awaken = _make_series_option(
            db, space, series, name="Awaken", total_sessions=8,
            sessions_per_week=1, price_cents=40000,
        )
        _make_schedule(db, awaken, total_amount_cents=40000)
        _make_schedule(
            db, awaken, name="Weekly instalments",
            schedule_type="recurring_installments",
            total_amount_cents=40000,
            installment_amount_cents=5000, installment_count=8,
        )

        # A draft option must NOT surface publicly.
        _make_series_option(
            db, space, series, name="Hidden draft",
            status=PaymentOptionStatus.draft,
        )

        offer_slug = self._publish_series_offer(db, creator, space, series)
        db.commit()

        page = get_public_offer_page(
            slug=space.slug, offer_slug=offer_slug,
            db=db, current_user=None,
        )
        assert page.target.kind == "event_series"
        assert page.target.title == "EMBODY Term 4"
        assert page.target.starts_at == series.starts_at
        assert page.target.ends_at == series.ends_at
        # No single-price on the target for series — pricing is on options.
        assert page.target.price_cents is None
        assert page.target.access_type is None

        opts = page.target.payment_options
        assert len(opts) == 1                       # draft filtered out
        assert opts[0].name == "Awaken"
        assert opts[0].effective_price_cents == 40000
        assert opts[0].total_sessions == 8
        # Both schedules published → both surfaced.
        assert len(opts[0].schedules) == 2
        types = {s.schedule_type for s in opts[0].schedules}
        assert types == {"pay_in_full", "recurring_installments"}

    def test_series_snapshot_omits_unpublished_schedules(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        series = _make_series(db, space)
        opt = _make_series_option(db, space, series, name="Awaken")
        _make_schedule(db, opt, name="Live", status="published")
        _make_schedule(db, opt, name="Draft", status="draft")

        offer_slug = self._publish_series_offer(db, creator, space, series)
        db.commit()

        page = get_public_offer_page(
            slug=space.slug, offer_slug=offer_slug,
            db=db, current_user=None,
        )
        [only] = page.target.payment_options
        assert [s.name for s in only.schedules] == ["Live"]

    def test_series_snapshot_has_access_when_viewer_holds_pass(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        # A Series that has already started so the viewer's pass
        # falls inside its window (valid_from <= now).
        started = datetime.utcnow() - timedelta(days=1)
        series = _make_series(
            db, space, starts_at=started, ends_at=started + timedelta(days=60),
        )
        offer_slug = self._publish_series_offer(db, creator, space, series)

        member = _member_of(db, make_user, space)
        db.add(AccessPass(
            id=_uid("ap"),
            user_id=member.id,
            space_id=space.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            valid_from=started,
            valid_until=series.ends_at,
            eligible_series_id=series.id,
        ))
        db.commit()

        page = get_public_offer_page(
            slug=space.slug, offer_slug=offer_slug,
            db=db, current_user=member,
        )
        assert page.user_has_target_access is True

    def test_deleted_series_target_returns_unavailable(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        series = _make_series(db, space)
        offer_slug = self._publish_series_offer(db, creator, space, series)
        # Delete the series — the offer row should keep serving the
        # "(Unavailable)" placeholder rather than crash.
        db.delete(series)
        db.commit()

        page = get_public_offer_page(
            slug=space.slug, offer_slug=offer_slug,
            db=db, current_user=None,
        )
        assert page.target.title == "(Unavailable)"
        assert page.target.payment_options == []
        assert page.user_has_target_access is False


# ---------------------------------------------------------------------------
# Public snapshot: gathering target
# ---------------------------------------------------------------------------


class TestGatheringTargetSnapshot:
    def test_snapshot_carries_ticket_fields(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        e = _make_event(
            db, space,
            booking_access_type="paid_separately",
            ticket_price_cents=2500, ticket_currency="AUD",
        )
        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Come along",
                target_kind="gathering",
                target_id=e.id,
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        db.commit()

        page = get_public_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            db=db, current_user=None,
        )
        assert page.target.kind == "gathering"
        assert page.target.title == "Session"
        assert page.target.ticket_price_cents == 2500
        assert page.target.ticket_currency == "AUD"
        assert page.target.access_type == "paid_separately"


# ---------------------------------------------------------------------------
# Creator profile exposed on public page
# ---------------------------------------------------------------------------


class TestCreatorProfileExposure:
    def test_creator_profile_populated_when_public(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator", name="Lindsey Doe")
        space = make_space(creator=creator)
        db.add(CreatorProfile(
            user_id=creator.id,
            display_name="Lindsey Doe",
            profile_tagline="Somatic practitioner",
            bio="Twenty years holding space.",
            avatar_url="https://images.test/av.jpg",
            website_url="https://lindsey.example",
            is_public=True,
        ))
        pathway = _make_pathway(db, space)
        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Join", target_kind="pathway", target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        db.commit()

        page = get_public_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            db=db, current_user=None,
        )
        assert page.creator.display_name == "Lindsey Doe"
        assert page.creator.tagline == "Somatic practitioner"
        assert page.creator.bio == "Twenty years holding space."
        assert page.creator.avatar_url == "https://images.test/av.jpg"

    def test_creator_falls_back_to_user_name_when_profile_private(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator", name="Lindsey Doe")
        space = make_space(creator=creator, name="Fresh Collective")
        db.add(CreatorProfile(
            user_id=creator.id,
            display_name="Lindsey Doe",
            is_public=False,           # opted out
        ))
        pathway = _make_pathway(db, space)
        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Join", target_kind="pathway", target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        db.commit()

        page = get_public_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            db=db, current_user=None,
        )
        # Falls back to the User.name — not the private CreatorProfile.
        assert page.creator.display_name == "Lindsey Doe"
        assert page.creator.bio is None
        assert page.creator.avatar_url is None

    def test_creator_falls_back_to_user_name_when_no_profile(
        self, db, make_user, make_space,
    ):
        # No CreatorProfile row at all — the User's real name is the
        # only personal identity we have, so use it.
        creator = make_user(role="creator", name="Lindsey Doe")
        space = make_space(creator=creator, name="EMBODY")
        pathway = _make_pathway(db, space)
        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Join", target_kind="pathway", target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        db.commit()

        page = get_public_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            db=db, current_user=None,
        )
        assert page.creator is not None
        assert page.creator.display_name == "Lindsey Doe"

    def test_creator_is_null_when_nothing_personal_available(
        self, db, make_user, make_space,
    ):
        # No CreatorProfile row AND no usable User.name — the "Meet
        # your guide" section should be omitted entirely rather than
        # fall back to the Collective's identity.
        creator = make_user(role="creator", name="")
        space = make_space(creator=creator, name="EMBODY")
        pathway = _make_pathway(db, space)
        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Join", target_kind="pathway", target_id=pathway.id,
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        db.commit()

        page = get_public_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            db=db, current_user=None,
        )
        assert page.creator is None

    def test_embody_regression_collective_name_never_leaks_as_creator(
        self, db, make_user, make_space,
    ):
        """Regression: an Offer Page hosted by the EMBODY Collective
        must never report ``creator.display_name == 'EMBODY'`` just
        because the CreatorProfile is missing. Covers three states —
        no profile, private profile, and public profile with a blank
        display name — none of which may leak the Collective name."""
        # State 1: no CreatorProfile at all — user name is the real
        # Creator identity.
        creator_1 = make_user(role="creator", name="Lindsey Doe")
        space_1 = make_space(creator=creator_1, name="EMBODY")
        pw1 = _make_pathway(db, space_1)
        o1 = create_offer_page(
            slug=space_1.slug,
            body=OfferPageCreateRequest(
                title="Join", target_kind="pathway", target_id=pw1.id,
            ),
            db=db, current_user=creator_1,
        )
        update_offer_page(
            slug=space_1.slug, offer_slug=o1["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator_1,
        )

        # State 2: private CreatorProfile — falls back to User.name.
        creator_2 = make_user(role="creator", name="Lindsey Doe")
        space_2 = make_space(creator=creator_2, name="EMBODY")
        db.add(CreatorProfile(user_id=creator_2.id, is_public=False))
        pw2 = _make_pathway(db, space_2)
        o2 = create_offer_page(
            slug=space_2.slug,
            body=OfferPageCreateRequest(
                title="Join", target_kind="pathway", target_id=pw2.id,
            ),
            db=db, current_user=creator_2,
        )
        update_offer_page(
            slug=space_2.slug, offer_slug=o2["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator_2,
        )

        # State 3: public CreatorProfile but no display_name — falls
        # back to User.name, NOT the Collective name.
        creator_3 = make_user(role="creator", name="Lindsey Doe")
        space_3 = make_space(creator=creator_3, name="EMBODY")
        db.add(CreatorProfile(
            user_id=creator_3.id, display_name=None, is_public=True,
        ))
        pw3 = _make_pathway(db, space_3)
        o3 = create_offer_page(
            slug=space_3.slug,
            body=OfferPageCreateRequest(
                title="Join", target_kind="pathway", target_id=pw3.id,
            ),
            db=db, current_user=creator_3,
        )
        update_offer_page(
            slug=space_3.slug, offer_slug=o3["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator_3,
        )
        db.commit()

        for slug, offer_slug in (
            (space_1.slug, o1["slug"]),
            (space_2.slug, o2["slug"]),
            (space_3.slug, o3["slug"]),
        ):
            page = get_public_offer_page(
                slug=slug, offer_slug=offer_slug, db=db, current_user=None,
            )
            # The Collective's name must never surface as the Creator.
            if page.creator is not None:
                assert page.creator.display_name != "EMBODY"
                assert page.creator.tagline != "EMBODY"
                assert page.creator.bio != "EMBODY"


# ---------------------------------------------------------------------------
# Event list: series_offer_page_slug bulk population
# ---------------------------------------------------------------------------


class TestSeriesOfferPageSlugOnEvents:
    def test_populated_when_published_offer_targets_series(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        series = _make_series(db, space)
        e = _make_event(db, space, series=series)

        created = create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Term pass", target_kind="event_series",
                target_id=series.id,
            ),
            db=db, current_user=creator,
        )
        update_offer_page(
            slug=space.slug, offer_slug=created["slug"],
            body=OfferPageUpdateRequest(status="published"),
            db=db, current_user=creator,
        )
        member = _member_of(db, make_user, space)
        db.commit()

        events = list_events(slug=space.slug, db=db, current_user=member)
        [event] = [ev for ev in events if ev.id == e.id]
        assert event.series_offer_page_slug == created["slug"]

    def test_omitted_when_offer_is_draft(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        series = _make_series(db, space)
        e = _make_event(db, space, series=series)

        # Draft page must not leak into the member API.
        create_offer_page(
            slug=space.slug,
            body=OfferPageCreateRequest(
                title="Term pass", target_kind="event_series",
                target_id=series.id,
            ),
            db=db, current_user=creator,
        )
        member = _member_of(db, make_user, space)
        db.commit()

        events = list_events(slug=space.slug, db=db, current_user=member)
        [event] = [ev for ev in events if ev.id == e.id]
        assert event.series_offer_page_slug is None


# ---------------------------------------------------------------------------
# /api/checkout/gathering-series endpoint
# ---------------------------------------------------------------------------


def _series_with_option(db, space):
    series = _make_series(db, space, title="EMBODY Term 4")
    opt = _make_series_option(db, space, series, name="Awaken")
    schedule = _make_schedule(db, opt)
    return series, opt, schedule


class TestGatheringSeriesCheckout:
    def test_503_when_stripe_disabled(
        self, db, make_user, make_space, monkeypatch,
    ):
        # ``settings.stripe_enabled`` is a computed property that
        # reads from the underlying secret + webhook secret; unset
        # them both so the endpoint's guard trips.
        monkeypatch.setattr(settings, "stripe_secret_key", None)
        monkeypatch.setattr(settings, "stripe_webhook_secret", None)
        space = make_space()
        series, opt, schedule = _series_with_option(db, space)
        buyer = _member_of(db, make_user, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_gathering_series_checkout_session(
                GatheringSeriesCheckoutRequest(
                    series_id=series.id,
                    payment_option_id=opt.id,
                    payment_option_schedule_id=schedule.id,
                    success_url="https://app.test/ok",
                    cancel_url="https://app.test/cancel",
                ),
                current_user=buyer, db=db,
            )
        assert exc.value.status_code == 503

    def test_404_unknown_series(
        self, db, make_user, stripe_configured,
    ):
        buyer = make_user()
        with pytest.raises(HTTPException) as exc:
            create_gathering_series_checkout_session(
                GatheringSeriesCheckoutRequest(
                    series_id="es_missing",
                    payment_option_id="po_x",
                    payment_option_schedule_id="pos_x",
                    success_url="https://app.test/ok",
                    cancel_url="https://app.test/cancel",
                ),
                current_user=buyer, db=db,
            )
        assert exc.value.status_code == 404

    def test_400_unpublished_series(
        self, db, make_user, make_space, stripe_configured,
    ):
        space = make_space()
        series = _make_series(db, space, status="draft")
        opt = _make_series_option(db, space, series, name="Awaken")
        schedule = _make_schedule(db, opt)
        buyer = _member_of(db, make_user, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_gathering_series_checkout_session(
                GatheringSeriesCheckoutRequest(
                    series_id=series.id,
                    payment_option_id=opt.id,
                    payment_option_schedule_id=schedule.id,
                    success_url="https://app.test/ok",
                    cancel_url="https://app.test/cancel",
                ),
                current_user=buyer, db=db,
            )
        assert exc.value.status_code == 400

    def test_404_option_not_attached_to_series(
        self, db, make_user, make_space, stripe_configured,
    ):
        space = make_space()
        series_a = _make_series(db, space, title="A")
        series_b = _make_series(db, space, title="B")
        # Option attached to series_b, but request targets series_a.
        opt_b = _make_series_option(db, space, series_b, name="Awaken")
        schedule = _make_schedule(db, opt_b)
        buyer = _member_of(db, make_user, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_gathering_series_checkout_session(
                GatheringSeriesCheckoutRequest(
                    series_id=series_a.id,
                    payment_option_id=opt_b.id,
                    payment_option_schedule_id=schedule.id,
                    success_url="https://app.test/ok",
                    cancel_url="https://app.test/cancel",
                ),
                current_user=buyer, db=db,
            )
        assert exc.value.status_code == 404

    def test_404_pathway_attached_option_rejected(
        self, db, make_user, make_space, stripe_configured,
    ):
        space = make_space()
        pathway = _make_pathway(db, space)
        series = _make_series(db, space)
        # A pathway-attached option must not be usable through the
        # series checkout even if the request tries to lie about the
        # series.
        pathway_opt = PaymentOption(
            id=_uid("po"),
            space_id=space.id,
            pathway_id=pathway.id,
            attaches_to_kind="pathway",
            attaches_to_id=pathway.id,
            name="Pathway one-time",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=20000,
            currency="AUD",
        )
        db.add(pathway_opt)
        db.flush()
        schedule = _make_schedule(db, pathway_opt, total_amount_cents=20000)
        buyer = _member_of(db, make_user, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_gathering_series_checkout_session(
                GatheringSeriesCheckoutRequest(
                    series_id=series.id,
                    payment_option_id=pathway_opt.id,
                    payment_option_schedule_id=schedule.id,
                    success_url="https://app.test/ok",
                    cancel_url="https://app.test/cancel",
                ),
                current_user=buyer, db=db,
            )
        assert exc.value.status_code == 404

    def test_503_recurring_installments_not_yet_purchasable(
        self, db, make_user, make_space, stripe_configured,
    ):
        space = make_space()
        series = _make_series(db, space)
        opt = _make_series_option(db, space, series, name="Awaken")
        recurring = _make_schedule(
            db, opt,
            schedule_type="recurring_installments",
            total_amount_cents=60000,
            installment_amount_cents=7500, installment_count=8,
        )
        buyer = _member_of(db, make_user, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_gathering_series_checkout_session(
                GatheringSeriesCheckoutRequest(
                    series_id=series.id,
                    payment_option_id=opt.id,
                    payment_option_schedule_id=recurring.id,
                    success_url="https://app.test/ok",
                    cancel_url="https://app.test/cancel",
                ),
                current_user=buyer, db=db,
            )
        assert exc.value.status_code == 503

    def test_409_when_active_pass_already_held(
        self, db, make_user, make_space, stripe_configured,
    ):
        space = make_space()
        # A series that has already started so the existing pass is
        # inside the valid_from window.
        started = datetime.utcnow() - timedelta(days=1)
        series = _make_series(
            db, space, starts_at=started, ends_at=started + timedelta(days=60),
        )
        opt = _make_series_option(db, space, series, name="Awaken")
        schedule = _make_schedule(db, opt)
        buyer = _member_of(db, make_user, space)
        db.add(AccessPass(
            id=_uid("ap"),
            user_id=buyer.id,
            space_id=space.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            valid_from=started,
            valid_until=series.ends_at,
            eligible_series_id=series.id,
        ))
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_gathering_series_checkout_session(
                GatheringSeriesCheckoutRequest(
                    series_id=series.id,
                    payment_option_id=opt.id,
                    payment_option_schedule_id=schedule.id,
                    success_url="https://app.test/ok",
                    cancel_url="https://app.test/cancel",
                ),
                current_user=buyer, db=db,
            )
        assert exc.value.status_code == 409

    def test_success_writes_series_pass_txn_with_correct_metadata(
        self, db, make_user, make_space, stripe_configured,
    ):
        space = make_space()
        series, opt, schedule = _series_with_option(db, space)
        buyer = _member_of(db, make_user, space)
        db.commit()

        with patch("stripe.checkout.Session.create") as mock_create:
            mock_create.return_value = SimpleNamespace(
                id="cs_series_ok", url="https://checkout.stripe.test/x",
            )
            res = create_gathering_series_checkout_session(
                GatheringSeriesCheckoutRequest(
                    series_id=series.id,
                    payment_option_id=opt.id,
                    payment_option_schedule_id=schedule.id,
                    success_url="https://app.test/ok",
                    cancel_url="https://app.test/cancel",
                ),
                current_user=buyer, db=db,
            )
        assert res.checkout_url == "https://checkout.stripe.test/x"

        # The Stripe call carries the metadata the webhook expects.
        kwargs = mock_create.call_args.kwargs
        meta = kwargs["metadata"]
        assert meta["series_id"] == series.id
        assert meta["space_id"] == space.id
        assert meta["payer_user_id"] == buyer.id
        assert meta["payment_option_id"] == opt.id
        assert meta["payment_option_schedule_id"] == schedule.id
        # No pathway_id — the webhook derives that from the option.
        assert "pathway_id" not in meta

        [txn] = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_checkout_session_id == "cs_series_ok")
            .all()
        )
        assert txn.transaction_type == PaymentTransactionType.member_series_pass_purchase
        assert txn.status == PaymentTransactionStatus.pending
        assert txn.space_id == space.id
        assert txn.payer_user_id == buyer.id
        assert txn.payment_option_id == opt.id
        assert txn.payment_option_schedule_id == schedule.id
        assert txn.gross_amount_cents == 60000
        # No grants_pathway_id on this option → no pathway_id on the row.
        assert txn.pathway_id is None
