"""``POST /api/checkout/gathering-series`` — pay-in-full Series passes.

Covers:

  * 404 on unknown series / option / schedule
  * 400 on non-series option, wrong series-option pairing,
    non-published option, non-published schedule, zero price
  * 503 on recurring_installments schedule
  * 409 on active-pass duplicate
  * Success writes a ``member_series_pass_purchase`` transaction with
    the right metadata and no PathwayEntitlement.

Provenance: this file was ``test_offer_pages_series_and_series_checkout.py``,
which paired this endpoint's coverage with the Offer Pages targeting,
public-snapshot and ``series_offer_page_slug`` tests. Offer Pages was
retired — production held zero rows — so those sections and their
helpers were removed and the file renamed to what it actually covers.
Every checkout assertion here is unchanged.
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
    Event,
    EventSeries,
    Pathway,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


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
    """Autouse: seed a Creator plan so plan resolution's "cheapest
    active" fallback returns Creator by default."""
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
