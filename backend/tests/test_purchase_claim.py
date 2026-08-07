"""Stage 3 — PurchaseIntent claim orchestrator + HTTP endpoints.

Covers:
  * ``claim_intent`` happy path and every error branch.
  * ``GET /api/purchases/by-token`` response shape + 404.
  * ``POST /api/purchases/claim`` — email match, wrong user, expired
    token, replay is a no-op.
  * ``POST /api/purchases/claim-with-signup`` — creates account,
    activates, sets session cookie; refuses when logged in / email
    already registered / token expired.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.creator.plan_activation import ActivationSource, activate_creator_plan
from app.models.creator_billing import CreatorPlan
from app.models.platform import Space
from app.models.purchase_intent import (
    PurchaseIntent,
    PurchaseIntentKind,
    PurchaseIntentStatus,
)
from app.models.user import UserRole
from app.purchases.claim import (
    IntentAlreadyConsumedByOtherUserError,
    IntentEmailMismatchError,
    IntentNotPaidError,
    InvalidClaimTokenError,
    claim_intent,
    fetch_intent_by_raw_token,
    is_claim_token_expired,
)
from app.purchases.routes import (
    ClaimTokenBody,
    ClaimWithSignupBody,
    claim_purchase,
    claim_with_signup,
    get_purchase_by_token,
)
from app.purchases.service import (
    build_intent,
    generate_claim_token,
    hash_claim_token,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _plans(db):
    for slug, price, fee_bps, cap in (
        ("creator", 1900, 800, 1),
        ("pro", 7900, 300, 5),
    ):
        if db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first() is None:
            db.add(CreatorPlan(
                id=f"cp_{slug}",
                name=slug.title(),
                slug=slug,
                monthly_price_cents=price,
                transaction_fee_basis_points=fee_bps,
                collective_limit=cap,
                is_active=True,
            ))
    db.flush()


@pytest.fixture
def world_builders(db, make_user):
    owner = make_user(role="admin")
    space = Space(
        id=f"s_wb_{uuid.uuid4().hex[:8]}",
        slug=f"wb-{uuid.uuid4().hex[:8]}",
        name="World Builders",
        status="active",
        is_public=False,
        creator_id=owner.id,
        auto_grant_role=UserRole.creator.value,
    )
    db.add(space)
    db.flush()
    return space


def _make_paid_intent(
    db, *, plan_slug="creator", claim_email=None, payer_user_id=None,
    with_token=True,
) -> tuple[PurchaseIntent, str | None]:
    intent = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug=plan_slug,
        payer_user_id=payer_user_id,
    )
    intent.status = PurchaseIntentStatus.paid
    intent.paid_at = datetime.utcnow()
    intent.provider_checkout_session_id = f"cs_test_{uuid.uuid4().hex[:8]}"
    intent.provider_subscription_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    intent.provider_customer_id = f"cus_test_{uuid.uuid4().hex[:8]}"
    if claim_email:
        intent.claim_email = claim_email.lower()

    raw_token: str | None = None
    if with_token:
        raw_token = generate_claim_token()
        intent.claim_token_hash = hash_claim_token(raw_token)
        intent.claim_token_expires_at = datetime.utcnow() + timedelta(hours=24)

    db.add(intent)
    db.flush()
    return intent, raw_token


# ---------------------------------------------------------------------------
# claim_intent — orchestrator unit tests
# ---------------------------------------------------------------------------


class TestClaimIntent:
    def test_happy_path_activates_creator_plan_and_marks_consumed(
        self, db, make_user, _plans, world_builders,
    ):
        user = make_user(role="user", email="paid@example.test")
        intent, _ = _make_paid_intent(
            db, plan_slug="creator", claim_email=user.email,
        )
        claim_intent(db, intent, user)
        db.flush()

        assert intent.status == PurchaseIntentStatus.consumed
        assert intent.consumed_by_user_id == user.id
        assert intent.consumed_at is not None
        assert user.role == "creator"

    def test_repeat_claim_by_same_user_is_noop(
        self, db, make_user, _plans, world_builders,
    ):
        user = make_user(role="user", email="repeat@example.test")
        intent, _ = _make_paid_intent(
            db, plan_slug="creator", claim_email=user.email,
        )
        claim_intent(db, intent, user)
        db.flush()
        first_consumed_at = intent.consumed_at
        # Repeat
        claim_intent(db, intent, user)
        db.flush()
        assert intent.consumed_at == first_consumed_at
        assert intent.status == PurchaseIntentStatus.consumed

    def test_claim_by_different_user_raises(
        self, db, make_user, _plans, world_builders,
    ):
        buyer = make_user(role="user", email="buyer@example.test")
        thief = make_user(role="user", email="thief@example.test")
        # Set claim_email to thief's so the email check would pass;
        # what fails is the consumed-by-other check.
        intent, _ = _make_paid_intent(
            db, plan_slug="creator", claim_email=buyer.email,
        )
        claim_intent(db, intent, buyer)
        db.flush()
        # Change claim_email so email match wouldn't refuse thief here.
        intent.claim_email = thief.email.lower()
        db.flush()

        with pytest.raises(IntentAlreadyConsumedByOtherUserError):
            claim_intent(db, intent, thief)

    def test_email_mismatch_refuses(self, db, make_user, _plans, world_builders):
        user = make_user(role="user", email="me@example.test")
        intent, _ = _make_paid_intent(
            db, plan_slug="creator", claim_email="someone-else@example.test",
        )
        with pytest.raises(IntentEmailMismatchError):
            claim_intent(db, intent, user)

    def test_pending_intent_refuses(self, db, make_user, _plans):
        user = make_user(role="user", email="me@example.test")
        intent, _ = _make_paid_intent(db, claim_email=user.email)
        intent.status = PurchaseIntentStatus.pending
        db.flush()
        with pytest.raises(IntentNotPaidError):
            claim_intent(db, intent, user)


# ---------------------------------------------------------------------------
# fetch_intent_by_raw_token + is_claim_token_expired
# ---------------------------------------------------------------------------


class TestTokenLookup:
    def test_valid_token_returns_intent(self, db, _plans):
        intent, raw = _make_paid_intent(db)
        found = fetch_intent_by_raw_token(db, raw)
        assert found.id == intent.id

    def test_unknown_token_raises(self, db):
        with pytest.raises(InvalidClaimTokenError):
            fetch_intent_by_raw_token(db, generate_claim_token())

    def test_empty_token_raises(self, db):
        with pytest.raises(InvalidClaimTokenError):
            fetch_intent_by_raw_token(db, "")

    def test_expired_detected(self, db, _plans):
        intent, raw = _make_paid_intent(db)
        intent.claim_token_expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.flush()
        assert is_claim_token_expired(intent) is True

    def test_no_expiry_never_expired(self, db, _plans):
        intent, raw = _make_paid_intent(db, with_token=False)
        assert is_claim_token_expired(intent) is False


# ---------------------------------------------------------------------------
# GET /api/purchases/by-token
# ---------------------------------------------------------------------------


class TestByTokenEndpoint:
    def test_unknown_token_returns_404(self, db):
        with pytest.raises(HTTPException) as exc:
            get_purchase_by_token(generate_claim_token(), db=db, current_user=None)
        assert exc.value.status_code == 404

    def test_paid_intent_returns_safe_summary(self, db, make_user, _plans):
        intent, raw = _make_paid_intent(
            db, plan_slug="pro", claim_email="paid@example.test",
        )
        summary = get_purchase_by_token(raw, db=db, current_user=None)
        assert summary.status == "paid"
        assert summary.kind == "creator_subscription"
        assert summary.plan_slug == "pro"
        assert summary.plan_display_name == "Pro"
        assert summary.claim_email == "paid@example.test"
        assert summary.claim_email_has_account is False
        assert summary.payer_bound is False
        assert summary.claim_token_expired is False
        assert summary.consumed_by_current_user is False

    def test_claim_email_has_account_when_user_exists(
        self, db, make_user, _plans,
    ):
        existing = make_user(email="known@example.test")
        intent, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email=existing.email,
        )
        summary = get_purchase_by_token(raw, db=db, current_user=None)
        assert summary.claim_email_has_account is True

    def test_consumed_by_current_user_true_when_matches(
        self, db, make_user, _plans, world_builders,
    ):
        user = make_user(email="me@example.test")
        intent, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email=user.email,
        )
        claim_intent(db, intent, user)
        db.flush()
        summary = get_purchase_by_token(raw, db=db, current_user=user)
        assert summary.status == "consumed"
        assert summary.consumed_by_current_user is True


# ---------------------------------------------------------------------------
# POST /api/purchases/claim
# ---------------------------------------------------------------------------


class TestClaimEndpoint:
    def test_logged_in_user_activates(self, db, make_user, _plans, world_builders):
        user = make_user(role="user", email="me@example.test")
        _, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email=user.email,
        )
        result = claim_purchase(
            ClaimTokenBody(token=raw), db=db, current_user=user,
        )
        assert result.status == "consumed"
        assert result.next_url == "/creator-onboarding"
        assert user.role == "creator"

    def test_wrong_email_returns_403(self, db, make_user, _plans, world_builders):
        user = make_user(role="user", email="me@example.test")
        _, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email="different@example.test",
        )
        with pytest.raises(HTTPException) as exc:
            claim_purchase(
                ClaimTokenBody(token=raw), db=db, current_user=user,
            )
        assert exc.value.status_code == 403

    def test_expired_token_returns_410(
        self, db, make_user, _plans, world_builders,
    ):
        user = make_user(role="user", email="me@example.test")
        intent, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email=user.email,
        )
        intent.claim_token_expires_at = datetime.utcnow() - timedelta(hours=1)
        db.flush()
        with pytest.raises(HTTPException) as exc:
            claim_purchase(
                ClaimTokenBody(token=raw), db=db, current_user=user,
            )
        assert exc.value.status_code == 410

    def test_next_url_skips_onboarding_when_already_onboarded(
        self, db, make_user, _plans, world_builders,
    ):
        """An existing Creator who has already completed the Creator
        welcome (backfilled by migration 096 or completed later) is
        sent straight to Creator Studio — never re-runs onboarding."""
        from datetime import datetime as _dt
        user = make_user(role="user", email="onboarded@example.test")
        user.creator_onboarded_at = _dt.utcnow()
        db.flush()
        _, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email=user.email,
        )
        result = claim_purchase(
            ClaimTokenBody(token=raw), db=db, current_user=user,
        )
        assert result.next_url == "/creator-studio"

    def test_replay_after_activation_returns_success(
        self, db, make_user, _plans, world_builders,
    ):
        user = make_user(role="user", email="me@example.test")
        intent, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email=user.email,
        )
        first = claim_purchase(
            ClaimTokenBody(token=raw), db=db, current_user=user,
        )
        assert first.status == "consumed"
        # Second call should be a no-op success (same user, same intent).
        second = claim_purchase(
            ClaimTokenBody(token=raw), db=db, current_user=user,
        )
        assert second.status == "consumed"
        assert second.purchase_intent_id == first.purchase_intent_id

    def test_unknown_token_returns_404(self, db, make_user):
        user = make_user()
        with pytest.raises(HTTPException) as exc:
            claim_purchase(
                ClaimTokenBody(token=generate_claim_token()),
                db=db, current_user=user,
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/purchases/claim-with-signup
# ---------------------------------------------------------------------------


class TestClaimWithSignupEndpoint:
    def _fake_response(self):
        """Minimal Response stand-in — set_session_cookie only calls
        .set_cookie(...) on it. FastAPI would inject a real one."""
        from starlette.responses import Response
        return Response()

    def test_creates_account_activates_and_sets_cookie(
        self, db, _plans, world_builders,
    ):
        _, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email="new@example.test",
        )
        response = self._fake_response()
        result = claim_with_signup(
            ClaimWithSignupBody(
                token=raw, name="New Creator", password="hunter22ok",
            ),
            response=response, db=db, current_user=None,
        )
        assert result.status == "consumed"
        assert result.next_url == "/creator-onboarding"

        # Session cookie set (Starlette records this via raw_headers).
        set_cookie_headers = [
            v for k, v in response.raw_headers if k.lower() == b"set-cookie"
        ]
        assert any(b"fc_session=" in h for h in set_cookie_headers)

        # User row exists and is promoted to creator.
        from app.models.user import User
        user = db.query(User).filter(User.email == "new@example.test").one()
        assert user.role == "creator"

    def test_refuses_when_already_logged_in(self, db, make_user, _plans):
        signed_in = make_user()
        _, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email="new@example.test",
        )
        with pytest.raises(HTTPException) as exc:
            claim_with_signup(
                ClaimWithSignupBody(
                    token=raw, name="Someone", password="hunter22ok",
                ),
                response=self._fake_response(), db=db, current_user=signed_in,
            )
        assert exc.value.status_code == 409

    def test_refuses_when_account_already_exists_for_claim_email(
        self, db, make_user, _plans,
    ):
        make_user(email="existing@example.test")
        _, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email="existing@example.test",
        )
        with pytest.raises(HTTPException) as exc:
            claim_with_signup(
                ClaimWithSignupBody(
                    token=raw, name="Someone", password="hunter22ok",
                ),
                response=self._fake_response(), db=db, current_user=None,
            )
        assert exc.value.status_code == 409

    def test_refuses_when_token_expired(self, db, _plans):
        intent, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email="new@example.test",
        )
        intent.claim_token_expires_at = datetime.utcnow() - timedelta(hours=1)
        db.flush()
        with pytest.raises(HTTPException) as exc:
            claim_with_signup(
                ClaimWithSignupBody(
                    token=raw, name="Someone", password="hunter22ok",
                ),
                response=self._fake_response(), db=db, current_user=None,
            )
        assert exc.value.status_code == 410

    def test_refuses_when_intent_still_pending(self, db, _plans):
        intent, raw = _make_paid_intent(
            db, plan_slug="creator", claim_email="new@example.test",
        )
        intent.status = PurchaseIntentStatus.pending
        db.flush()
        with pytest.raises(HTTPException) as exc:
            claim_with_signup(
                ClaimWithSignupBody(
                    token=raw, name="Someone", password="hunter22ok",
                ),
                response=self._fake_response(), db=db, current_user=None,
            )
        assert exc.value.status_code == 409
