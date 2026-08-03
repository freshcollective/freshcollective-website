"""
PurchaseIntent — Stage 1 service scaffolding.

Deliberately small. This module only contains:

  * A secure claim-token generator + hasher, modelled on the
    ``PasswordReset`` pattern in ``app/auth/service.py``.
  * A safe intent-construction helper that validates the
    ``kind → subject field`` mapping in Python before insertion.

Explicitly out of scope for this stage (see Stage 1 brief):

  * ``mark_paid`` / ``consume`` transitions
  * Stripe Checkout Session creation
  * Webhook handling
  * Signup-with-token integration
  * Access grants / role changes / World Builders enrolment
  * Any HTTP route

Those belong in later stages and must not be smuggled in here.
"""

from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.purchase_intent import (
    PurchaseIntent,
    PurchaseIntentKind,
    PurchaseIntentStatus,
)


# ---------------------------------------------------------------------------
# Claim-token helpers
# ---------------------------------------------------------------------------


def generate_claim_token() -> str:
    """Return a fresh, high-entropy raw claim token.

    32 bytes → 64 hex characters. This is the *raw* token: it must be
    embedded in the Stripe Checkout success URL exactly once at Session
    creation time and never persisted server-side. Only the hash (see
    ``hash_claim_token``) is stored on the PurchaseIntent row.

    The token is opaque to Stripe — it lives in the return URL and in
    the operator's optional fallback claim email, and is verified on
    the way back by hashing and comparing to the stored hash.
    """
    return secrets.token_hex(32)


def hash_claim_token(raw_token: str) -> str:
    """SHA-256 hex-digest a raw claim token for storage / comparison.

    Mirrors ``app/auth/service.py::create_password_reset_token`` exactly
    so both token families can be reasoned about identically:
    ``hashlib.sha256(raw.encode()).hexdigest()``.
    """
    return hashlib.sha256(raw_token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Intent-kind → subject field validation
# ---------------------------------------------------------------------------


# Kind → (required subject fields, disallowed subject fields).
# Kept in Python (not a database CHECK) so future kinds can be added
# without a fragile migration. Service-level validation is enough at
# Stage 1; DB-level guarantees can follow if we ever need them.
_KIND_SUBJECT_RULES: dict[PurchaseIntentKind, tuple[set[str], set[str]]] = {
    PurchaseIntentKind.creator_subscription: (
        {"plan_slug"},
        {"space_id", "pathway_id", "event_id", "payment_option_id"},
    ),
    PurchaseIntentKind.collective_membership: (
        {"space_id"},
        {"plan_slug", "pathway_id", "event_id", "payment_option_id"},
    ),
    PurchaseIntentKind.pathway: (
        {"pathway_id"},
        # payment_option_id is *optional* here (may be legacy-priced),
        # so it appears in neither required nor disallowed sets.
        {"plan_slug", "event_id"},
    ),
    PurchaseIntentKind.gathering: (
        {"event_id"},
        {"plan_slug", "pathway_id", "payment_option_id"},
    ),
}


class InvalidIntentSubjectError(ValueError):
    """Raised when the caller passed a subject-field combination that
    doesn't match the declared kind."""


def _validate_subject_for_kind(
    kind: PurchaseIntentKind,
    *,
    plan_slug: str | None,
    space_id: str | None,
    pathway_id: str | None,
    event_id: str | None,
    payment_option_id: str | None,
) -> None:
    required, disallowed = _KIND_SUBJECT_RULES[kind]
    values: dict[str, str | None] = {
        "plan_slug": plan_slug,
        "space_id": space_id,
        "pathway_id": pathway_id,
        "event_id": event_id,
        "payment_option_id": payment_option_id,
    }
    missing = [f for f in required if not values.get(f)]
    if missing:
        raise InvalidIntentSubjectError(
            f"kind={kind.value} requires: {sorted(missing)}"
        )
    present_disallowed = [f for f in disallowed if values.get(f)]
    if present_disallowed:
        raise InvalidIntentSubjectError(
            f"kind={kind.value} must not carry: {sorted(present_disallowed)}"
        )


# ---------------------------------------------------------------------------
# Safe intent construction
# ---------------------------------------------------------------------------


def build_intent(
    *,
    kind: PurchaseIntentKind,
    plan_slug: str | None = None,
    space_id: str | None = None,
    pathway_id: str | None = None,
    event_id: str | None = None,
    payment_option_id: str | None = None,
    payer_user_id: str | None = None,
    created_by_user_id: str | None = None,
) -> PurchaseIntent:
    """Build (but do not persist) a valid PurchaseIntent in the
    ``pending`` state.

    Persistence is left to the caller so a route handler can wrap this
    in its own transaction — the same pattern used by
    ``create_password_reset_token`` for its own SAVEPOINT hygiene.

    Validation performed:
      * Raises :class:`InvalidIntentSubjectError` if the subject
        fields don't match the declared kind.

    Explicitly NOT performed here (belongs in later stages):
      * Verifying that the referenced entity exists / is purchasable.
      * Setting pricing (``currency``, ``gross_amount_cents``,
        ``platform_fee_bps``) — these are snapshotted at Session-
        creation time.
      * Generating a claim token — that is a per-Session concern.
    """
    _validate_subject_for_kind(
        kind,
        plan_slug=plan_slug,
        space_id=space_id,
        pathway_id=pathway_id,
        event_id=event_id,
        payment_option_id=payment_option_id,
    )
    return PurchaseIntent(
        id=str(uuid4()),
        kind=kind,
        status=PurchaseIntentStatus.pending,
        plan_slug=plan_slug,
        space_id=space_id,
        pathway_id=pathway_id,
        event_id=event_id,
        payment_option_id=payment_option_id,
        payer_user_id=payer_user_id,
        created_by_user_id=created_by_user_id or payer_user_id,
    )


# ---------------------------------------------------------------------------
# Notes for later stages (do not delete)
# ---------------------------------------------------------------------------
#
# Stage 2 will add:
#   * attach_stripe_session(intent, session_id, customer_id=None)
#   * attach_claim_token(intent, raw_token, ttl_hours=24)
#           — hashes the raw token, records claim_token_hash and
#             claim_token_expires_at. Callers keep the raw token to
#             embed in Stripe success URLs; storage is hash-only.
#   * mark_paid(intent, paid_at, claim_email)
#   * consume(intent, consuming_user)
#           — Stage-1 note: consumption must verify (a) intent.status
#             == "paid", (b) supplied token hashes to
#             intent.claim_token_hash, (c) consuming_user's email
#             matches intent.claim_email (case-insensitive).
#
# Nothing in this list may be implemented until the relevant later
# stage is explicitly authorised.
