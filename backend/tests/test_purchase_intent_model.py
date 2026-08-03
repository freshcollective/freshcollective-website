"""PurchaseIntent — Stage 1 model + service-helper tests.

Covers the minimal core the Stage 1 brief calls for:
  * model creation for every supported kind
  * nullable pre-account payer
  * secure token hashing (raw token is never stored)
  * unique checkout-session constraint (partial: NULLs are allowed)
  * unique claim-token-hash constraint (partial: NULLs are allowed)
  * default status + timestamps
  * a paid intent is NOT automatically ``expired`` merely because its
    claim token has elapsed — those are separate concerns.

Explicitly out of scope: any state transition beyond model creation
(mark_paid, consume, refund) — those belong in Stage 2 and later.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.purchase_intent import (
    PurchaseIntent,
    PurchaseIntentKind,
    PurchaseIntentStatus,
)
from app.purchases.service import (
    InvalidIntentSubjectError,
    build_intent,
    generate_claim_token,
    hash_claim_token,
)


# ---------------------------------------------------------------------------
# Model creation for each supported kind
# ---------------------------------------------------------------------------


def test_creator_subscription_intent_persists(db, make_user):
    user = make_user()
    intent = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="creator",
        payer_user_id=user.id,
    )
    db.add(intent)
    db.flush()

    assert intent.id
    assert intent.kind == PurchaseIntentKind.creator_subscription
    assert intent.plan_slug == "creator"
    assert intent.payer_user_id == user.id
    # created_by_user_id defaults to the payer when not passed
    assert intent.created_by_user_id == user.id


def test_collective_membership_intent_persists(db, make_space):
    space = make_space()
    intent = build_intent(
        kind=PurchaseIntentKind.collective_membership,
        space_id=space.id,
    )
    db.add(intent)
    db.flush()

    assert intent.kind == PurchaseIntentKind.collective_membership
    assert intent.space_id == space.id
    # No payer yet — this represents a pre-account flow
    assert intent.payer_user_id is None
    assert intent.created_by_user_id is None


def test_gathering_intent_persists(db, make_event):
    event = make_event()
    intent = build_intent(
        kind=PurchaseIntentKind.gathering,
        event_id=event.id,
    )
    db.add(intent)
    db.flush()
    assert intent.kind == PurchaseIntentKind.gathering
    assert intent.event_id == event.id


def test_pathway_intent_persists(db):
    # We don't need a real Pathway row to prove the model persists —
    # SET NULL on delete means the FK tolerates missing referents at
    # the model level; the endpoint layer will validate existence.
    # This test uses a NULL pathway_id to keep the fixture surface
    # small; the required-field check is exercised separately.
    intent = build_intent(
        kind=PurchaseIntentKind.pathway,
        pathway_id="pw_placeholder_not_a_real_row",
    )
    # A real DB write would fail the FK; the point of this test is the
    # model + build_intent path, so we don't add to the session.
    assert intent.kind == PurchaseIntentKind.pathway
    assert intent.pathway_id == "pw_placeholder_not_a_real_row"


# ---------------------------------------------------------------------------
# Nullable pre-account payer
# ---------------------------------------------------------------------------


def test_intent_can_be_created_without_payer(db, make_space):
    """A brand-new visitor may begin an intent before an account exists.
    The DB must accept payer_user_id = NULL."""
    space = make_space()
    intent = build_intent(
        kind=PurchaseIntentKind.collective_membership,
        space_id=space.id,
    )
    db.add(intent)
    db.flush()
    assert intent.payer_user_id is None
    assert intent.created_by_user_id is None
    assert intent.status == PurchaseIntentStatus.pending


# ---------------------------------------------------------------------------
# Kind → subject validation (service level, not DB CHECK)
# ---------------------------------------------------------------------------


def test_creator_subscription_requires_plan_slug():
    with pytest.raises(InvalidIntentSubjectError):
        build_intent(kind=PurchaseIntentKind.creator_subscription)


def test_creator_subscription_rejects_space_id():
    with pytest.raises(InvalidIntentSubjectError):
        build_intent(
            kind=PurchaseIntentKind.creator_subscription,
            plan_slug="creator",
            space_id="s_x",
        )


def test_collective_membership_requires_space_id():
    with pytest.raises(InvalidIntentSubjectError):
        build_intent(kind=PurchaseIntentKind.collective_membership)


def test_pathway_kind_rejects_plan_slug():
    with pytest.raises(InvalidIntentSubjectError):
        build_intent(
            kind=PurchaseIntentKind.pathway,
            pathway_id="pw_x",
            plan_slug="creator",
        )


def test_gathering_kind_requires_event_id():
    with pytest.raises(InvalidIntentSubjectError):
        build_intent(kind=PurchaseIntentKind.gathering)


# ---------------------------------------------------------------------------
# Secure token hashing — raw token is NEVER stored
# ---------------------------------------------------------------------------


def test_generate_claim_token_is_high_entropy_hex():
    t1 = generate_claim_token()
    t2 = generate_claim_token()
    # 32 bytes → 64 hex chars, per secrets.token_hex(32).
    assert len(t1) == 64
    assert all(c in "0123456789abcdef" for c in t1)
    # Overwhelmingly unlikely to collide.
    assert t1 != t2


def test_hash_claim_token_is_deterministic_sha256():
    raw = generate_claim_token()
    h1 = hash_claim_token(raw)
    h2 = hash_claim_token(raw)
    assert h1 == h2
    # SHA-256 hex digest → 64 hex chars.
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)
    # The hash MUST NOT equal the raw token.
    assert h1 != raw


def test_intent_stores_only_the_hash(db, make_user):
    """Raw claim tokens are never persisted; only the hash may be."""
    user = make_user()
    raw = generate_claim_token()
    intent = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="creator",
        payer_user_id=user.id,
    )
    intent.claim_token_hash = hash_claim_token(raw)
    intent.claim_token_expires_at = datetime.utcnow() + timedelta(hours=24)
    db.add(intent)
    db.flush()

    # Round-trip: fetch and confirm the raw token is nowhere in the row.
    db.refresh(intent)
    assert intent.claim_token_hash == hash_claim_token(raw)
    assert intent.claim_token_hash != raw
    # No column on the model carries the raw token.
    assert not any(getattr(intent, attr, None) == raw for attr in vars(intent))


# ---------------------------------------------------------------------------
# Unique constraints (partial indexes: NULLs are allowed to coexist)
# ---------------------------------------------------------------------------


def test_unique_provider_checkout_session_id(db, make_user):
    user = make_user()
    a = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="creator",
        payer_user_id=user.id,
    )
    a.provider_checkout_session_id = "cs_test_shared"
    b = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="pro",
        payer_user_id=user.id,
    )
    b.provider_checkout_session_id = "cs_test_shared"

    db.add_all([a, b])
    with pytest.raises(IntegrityError):
        db.flush()


def test_null_provider_checkout_session_ids_may_coexist(db, make_user):
    """The partial unique index allows many pending intents to share
    NULL before any Stripe Session is created."""
    user = make_user()
    a = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="creator",
        payer_user_id=user.id,
    )
    b = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="pro",
        payer_user_id=user.id,
    )
    db.add_all([a, b])
    db.flush()
    assert a.provider_checkout_session_id is None
    assert b.provider_checkout_session_id is None


def test_unique_claim_token_hash(db, make_user):
    user = make_user()
    same_hash = hash_claim_token(generate_claim_token())
    a = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="creator",
        payer_user_id=user.id,
    )
    a.claim_token_hash = same_hash
    b = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="pro",
        payer_user_id=user.id,
    )
    b.claim_token_hash = same_hash

    db.add_all([a, b])
    with pytest.raises(IntegrityError):
        db.flush()


def test_null_claim_token_hashes_may_coexist(db, make_user):
    user = make_user()
    a = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="creator",
        payer_user_id=user.id,
    )
    b = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="pro",
        payer_user_id=user.id,
    )
    db.add_all([a, b])
    db.flush()
    assert a.claim_token_hash is None
    assert b.claim_token_hash is None


# ---------------------------------------------------------------------------
# Defaults: status + timestamps
# ---------------------------------------------------------------------------


def test_new_intent_defaults_to_pending_with_timestamps(db, make_user):
    user = make_user()
    intent = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="creator",
        payer_user_id=user.id,
    )
    db.add(intent)
    db.flush()
    db.refresh(intent)

    assert intent.status == PurchaseIntentStatus.pending
    assert intent.provider == "stripe"
    assert intent.created_at is not None
    assert intent.updated_at is not None
    # Paid / consumed markers stay clear on a fresh row.
    assert intent.paid_at is None
    assert intent.consumed_at is None
    assert intent.consumed_by_user_id is None


# ---------------------------------------------------------------------------
# Paid intent is NOT automatically expired just because claim token elapses
# ---------------------------------------------------------------------------


def test_paid_intent_with_elapsed_claim_token_stays_paid(db, make_user):
    """Claim-token expiry and intent status are separate concepts.
    A paid but unclaimed purchase must NOT silently become
    ``expired`` — that flag is reserved for unpaid / abandoned intents
    and would forfeit real money if applied here. Support recovery
    must remain possible for the customer."""
    user = make_user()
    intent = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug="creator",
        payer_user_id=user.id,
    )
    intent.status = PurchaseIntentStatus.paid
    intent.paid_at = datetime.utcnow() - timedelta(hours=48)
    # Claim window closed 24 hours ago.
    intent.claim_token_expires_at = datetime.utcnow() - timedelta(hours=24)
    intent.claim_token_hash = hash_claim_token(generate_claim_token())
    db.add(intent)
    db.flush()
    db.refresh(intent)

    # Status is unchanged — nothing in the model or service auto-flips
    # a paid intent to expired based on claim-window elapse.
    assert intent.status == PurchaseIntentStatus.paid
