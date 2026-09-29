"""Holding a limited code's slot while a member is away at Stripe.

The rule everything here serves:

    A limited-code slot may only be reused when FC knows the prior
    checkout can no longer complete.

Not "when its clock ran out". The difference is a real double-charge. A
reservation nominally expiring at 11:00, a member who paid at 10:59:59,
and a completion webhook delayed to 11:01: a clock-only rule frees the
slot at 11:00, lets a second member buy at 11:00:30, and then the first
member's webhook arrives and is also valid. Two successful payments
against a one-use code, and no way to refuse either — both cards have
been charged.

So ``session_expires_at`` makes a reservation *eligible for
verification*, never free. Release requires positive knowledge, which
arrives one of four ways: Stripe told us the session expired; we asked
Stripe and it said so; the reservation never reached Stripe at all; or
Stripe rejected the session outright. Anything else stays held. A held
reservation we cannot resolve keeps consuming its slot, which is the
cost this design accepts — and why the diagnostic columns exist.

Conversion never consults the clock. A completion arriving after the
nominal expiry is still a completion, and rejecting it would produce the
mirror-image failure: money taken, nothing granted.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.discount_code import (
    DiscountCode,
    DiscountRedemption,
    DiscountReservation,
    ReservationStatus,
)
from app.services.discount_pricing import (
    AppliedDiscount,
    DiscountError,
    DiscountRejection,
)

logger = logging.getLogger(__name__)

#: How long a member has at Stripe. The SAME value drives the Stripe
#: Session's ``expires_at`` and this reservation's verification
#: threshold, so the two cannot drift apart — which is the invariant
#: that makes "past expiry" mean the same thing on both sides.
CHECKOUT_WINDOW = timedelta(minutes=60)

#: Stripe may prune an idempotency key once it is at least 24h old, and a
#: pruned key makes a replay a NEW request rather than a replay of the
#: original. Past this age a replay proves nothing, so we never attempt
#: one: an unresolved reservation stays held and is surfaced for a human
#: instead of risking a second Session against a member who may already
#: have paid. Well inside 24h on purpose — the normal path resolves in
#: sixty minutes.
IDEMPOTENCY_RECOVERY_MAX_AGE = timedelta(hours=6)


# ---------------------------------------------------------------------------
# Counting — what a code has actually committed
# ---------------------------------------------------------------------------


def consumed_slots(
    db: Session,
    discount_code_id: str,
    *,
    excluding_attempt: tuple[str, str, str] | None = None,
) -> int:
    """Permanent redemptions plus reservations still able to complete.

    This is the authoritative figure ``max_redemptions`` is measured
    against. Note what is absent: any comparison against ``now``. A held
    reservation counts whether or not its window has elapsed, because
    until it is verified dead the member holding it may still be paying.

    ``excluding_attempt`` is ``(user_id, payment_option_id,
    payment_option_schedule_id)`` — that purchase attempt's own hold is
    left out of the count. Without it a member who reserved the last slot
    would be told the code was fully used by their own reservation the
    moment they retried, or reloaded the page, which is the most likely
    way anyone would meet this code path at all.
    """
    redemptions = db.query(func.count(DiscountRedemption.id)).filter(
        DiscountRedemption.discount_code_id == discount_code_id,
    ).scalar() or 0

    held_q = db.query(func.count(DiscountReservation.id)).filter(
        DiscountReservation.discount_code_id == discount_code_id,
        DiscountReservation.status == ReservationStatus.held.value,
    )
    if excluding_attempt is not None:
        user_id, option_id, schedule_id = excluding_attempt
        held_q = held_q.filter(~(
            (DiscountReservation.user_id == user_id)
            & (DiscountReservation.payment_option_id == option_id)
            & (DiscountReservation.payment_option_schedule_id == schedule_id)
        ))
    return int(redemptions) + int(held_q.scalar() or 0)


def held_reservation_count(db: Session, discount_code_id: str) -> int:
    """Unresolved reservations. Used by the CRUD guards, which must not
    let a definition be deleted or narrowed out from under money that is
    still in flight."""
    return int(
        db.query(func.count(DiscountReservation.id)).filter(
            DiscountReservation.discount_code_id == discount_code_id,
            DiscountReservation.status == ReservationStatus.held.value,
        ).scalar() or 0
    )


# ---------------------------------------------------------------------------
# Reserving
# ---------------------------------------------------------------------------


@dataclass
class ReservationOutcome:
    """What the caller should do next.

    ``reused`` distinguishes a fresh hold from an existing one. A reused
    reservation that already has a Stripe Session needs no new Session at
    all — the member is handed back the one they abandoned, which is both
    cheaper and the only way a retry cannot consume a second slot.
    """

    reservation: DiscountReservation
    reused: bool


def _lock_code(db: Session, discount_code_id: str) -> None:
    """Serialise concurrent buyers of the final slot on the code row.

    The lock is held only for the counting-and-insert transaction and is
    released before Stripe is contacted. Holding a row lock across a
    network call to a third party is how a slow provider becomes a
    database incident.
    """
    db.execute(
        text("SELECT id FROM discount_codes WHERE id = :id FOR UPDATE"),
        {"id": discount_code_id},
    )


def reserve_or_reuse(
    db: Session,
    *,
    applied: AppliedDiscount,
    code: DiscountCode,
    user_id: str,
    payment_option_id: str,
    payment_option_schedule_id: str,
    now: datetime,
) -> ReservationOutcome:
    """Take (or re-find) this purchase attempt's slot. Commits.

    Ordering matters and is deliberate: the member's OWN held
    reservation is looked for BEFORE capacity is counted. A member
    retrying the same purchase must not be told the code is fully used by
    their own hold — which is exactly what a capacity-first
    implementation would do on a one-use code.

    Raises :class:`DiscountError` with ``LIMIT_REACHED`` when the code is
    genuinely exhausted by other people's redemptions and reservations.
    """
    _lock_code(db, code.id)

    existing = (
        db.query(DiscountReservation)
        .filter(
            DiscountReservation.discount_code_id == code.id,
            DiscountReservation.user_id == user_id,
            DiscountReservation.payment_option_id == payment_option_id,
            DiscountReservation.payment_option_schedule_id == payment_option_schedule_id,
            DiscountReservation.status == ReservationStatus.held.value,
        )
        .first()
    )
    if existing is not None:
        db.commit()
        return ReservationOutcome(reservation=existing, reused=True)

    limit = code.max_redemptions
    own_attempt = (user_id, payment_option_id, payment_option_schedule_id)
    if limit is not None and consumed_slots(
        db, code.id, excluding_attempt=own_attempt,
    ) >= limit:
        db.rollback()
        raise DiscountError(
            DiscountRejection.LIMIT_REACHED,
            "That code has reached its redemption limit.",
        )

    reservation = DiscountReservation(
        id=f"dres_{uuid.uuid4().hex[:24]}",
        discount_code_id=code.id,
        space_id=code.space_id,
        user_id=user_id,
        payment_option_id=payment_option_id,
        payment_option_schedule_id=payment_option_schedule_id,
        status=ReservationStatus.held.value,
        original_amount_cents=applied.amounts.original_cents,
        discount_amount_cents=applied.amounts.discount_cents,
        final_amount_cents=applied.amounts.final_cents,
        currency=applied.amounts.currency,
        discount_snapshot_json=applied.snapshot,
        session_idempotency_key="",   # set below, derived from the id
        session_expires_at=now + CHECKOUT_WINDOW,
        intended_payment_transaction_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
    )
    # Derived from the reservation id so a replay is addressable, and
    # versioned like ``stripe_finite_plan._idem`` so a poisoned key can
    # be retired deliberately rather than by mutation.
    reservation.session_idempotency_key = f"dres:{reservation.id}:session:v1"
    db.add(reservation)
    db.commit()
    return ReservationOutcome(reservation=reservation, reused=False)


def attach_session(
    db: Session,
    *,
    reservation: DiscountReservation,
    session_id: str,
    session_params: dict[str, Any],
    payment_transaction_id: str | None,
    now: datetime,
) -> None:
    """Record the Stripe Session against the reservation. Commits.

    The params are stored as sent, so a later recovery replay can re-send
    them byte-for-byte. A replay that recomputed anything from ``now``
    would be a different request wearing the same idempotency key.
    """
    reservation.provider_checkout_session_id = session_id
    reservation.session_create_params_json = _jsonable(session_params)
    if payment_transaction_id:
        reservation.payment_transaction_id = payment_transaction_id
    reservation.updated_at = now
    db.commit()


def release(
    db: Session, *, reservation: DiscountReservation, reason: str, now: datetime,
) -> None:
    """Free the slot. Only ever called with positive knowledge. Commits."""
    if reservation.status != ReservationStatus.held.value:
        return
    reservation.status = ReservationStatus.released.value
    reservation.released_at = now
    reservation.release_reason = reason[:60]
    reservation.updated_at = now
    db.commit()
    logger.info(
        "discount reservation released: id=%s code=%s reason=%s",
        reservation.id, reservation.discount_code_id, reason,
    )


def _jsonable(value: Any) -> Any:
    """Stripe params contain datetimes and nested dicts; JSONB wants
    primitives. Converted here rather than at each call site so the
    stored shape is consistent."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return int(value.timestamp())
    return value


# ---------------------------------------------------------------------------
# Converting — the purchase completed
# ---------------------------------------------------------------------------


def convert_to_redemption(
    db: Session,
    *,
    reservation: DiscountReservation,
    payment_transaction_id: str,
    now: datetime,
    commit: bool = True,
) -> DiscountRedemption | None:
    """Turn a held reservation into a permanent redemption.

    ``commit=False`` joins the caller's transaction, which is how the
    webhook uses it: the redemption must land or not land together with
    the fulfilment it accompanies. Committing separately would leave a
    window where the purchase is marked succeeded but the code is not
    spent — and because a redelivered event short-circuits on
    ``status == succeeded``, that window would never be revisited.

    **No clock check.** A webhook may arrive after
    ``session_expires_at`` — Stripe retries for days, and our own
    processing can lag. Refusing a completion because a local timestamp
    has passed would take the member's money and grant them nothing,
    which is worse than the double-spend the expiry exists to prevent.

    Exactly once, enforced by the database rather than by care: the
    partial unique index ``uq_discount_redemptions_code_txn`` makes a
    second redemption for the same (code, transaction) a constraint
    violation. A redelivered webhook therefore finds the reservation
    already ``converted`` and returns the existing row.

    Uses the reservation's FROZEN amounts and snapshot. The live code may
    by now be deactivated, edited or expired; none of that may change
    what this member was charged, and re-running eligibility here would
    let a Creator's later edit retroactively invalidate a completed
    payment.
    """
    locked = db.execute(
        text("SELECT status FROM discount_reservations WHERE id = :id FOR UPDATE"),
        {"id": reservation.id},
    ).first()
    if locked is None:  # pragma: no cover — caller loaded it
        return None
    db.refresh(reservation)

    if reservation.status == ReservationStatus.converted.value:
        existing = (
            db.query(DiscountRedemption)
            .filter(
                DiscountRedemption.discount_code_id == reservation.discount_code_id,
                DiscountRedemption.payment_transaction_id == payment_transaction_id,
            )
            .first()
        )
        if commit:
            db.commit()
        return existing

    if reservation.status == ReservationStatus.released.value:
        # Released means FC had positive knowledge this could not
        # complete — and yet it did. The slot may already have gone to
        # someone else, so the redemption is still recorded (the member
        # paid and their purchase is real), but this is a genuine
        # inconsistency and must be shouted about rather than logged at
        # debug and forgotten.
        logger.error(
            "discount reservation completed AFTER release: id=%s code=%s "
            "reason=%s txn=%s — slot may be oversold; investigate.",
            reservation.id, reservation.discount_code_id,
            reservation.release_reason, payment_transaction_id,
        )

    redemption = DiscountRedemption(
        id=f"dredeem_{uuid.uuid4().hex[:22]}",
        discount_code_id=reservation.discount_code_id,
        space_id=reservation.space_id,
        user_id=reservation.user_id,
        payment_transaction_id=payment_transaction_id,
        original_amount_cents=reservation.original_amount_cents,
        discount_amount_cents=reservation.discount_amount_cents,
        final_amount_cents=reservation.final_amount_cents,
        currency=reservation.currency,
        redeemed_at=now,
    )
    db.add(redemption)

    reservation.status = ReservationStatus.converted.value
    reservation.converted_at = now
    reservation.payment_transaction_id = payment_transaction_id
    reservation.updated_at = now
    if commit:
        db.commit()
    else:
        db.flush()
    logger.info(
        "discount reservation converted: id=%s code=%s txn=%s",
        reservation.id, reservation.discount_code_id, payment_transaction_id,
    )
    return redemption


def find_by_session(db: Session, session_id: str) -> DiscountReservation | None:
    return (
        db.query(DiscountReservation)
        .filter(DiscountReservation.provider_checkout_session_id == session_id)
        .first()
    )


# ---------------------------------------------------------------------------
# Verifying a stale reservation against Stripe
# ---------------------------------------------------------------------------


#: Outcomes of a verification attempt, recorded on the row so a stuck
#: reservation can be explained later without re-deriving anything.
VERIFY_RELEASED = "released"
VERIFY_CONVERTIBLE = "completed"
VERIFY_STILL_OPEN = "still_open"
VERIFY_UNVERIFIABLE = "unverifiable"
VERIFY_TOO_OLD = "too_old_to_recover"


def _record_verification(
    db: Session, *, reservation: DiscountReservation, status: str,
    error: str | None, now: datetime,
) -> None:
    reservation.verification_attempts = (reservation.verification_attempts or 0) + 1
    reservation.last_verification_at = now
    reservation.last_verification_status = status[:40]
    reservation.last_verification_error = error
    reservation.updated_at = now
    db.commit()


def verify_stale_reservation(
    db: Session, *, reservation: DiscountReservation, now: datetime,
) -> str:
    """Ask Stripe whether this reservation can still complete.

    Called only when someone else wants the slot and this reservation is
    past its window. Returns one of the ``VERIFY_*`` constants; releases
    or reports, never guesses.

    The ladder:

      * no Stripe Session was ever recorded, and the reservation is young
        enough that an idempotency replay still proves something → replay
        to find out whether a Session exists after all (the crash between
        creating the Session and persisting its id);
      * no Session recorded and too old to replay → stays held, reported
        as ``too_old_to_recover``. Deliberately unresolved: a member may
        have paid against a Session we lost track of;
      * Session ``complete`` → convertible. We missed the webhook; the
        member paid;
      * Session ``expired`` → release;
      * Session ``open`` → ask Stripe to expire it, then re-read. If the
        expire call fails because the state moved underneath us, the
        re-read decides;
      * Stripe unreachable → stays held.
    """
    from app.services import discount_stripe_sessions as sessions

    if reservation.status != ReservationStatus.held.value:  # pragma: no cover
        return reservation.status

    if not reservation.provider_checkout_session_id:
        age = now - (reservation.created_at or now)
        if age > IDEMPOTENCY_RECOVERY_MAX_AGE:
            _record_verification(
                db, reservation=reservation, status=VERIFY_TOO_OLD,
                error=(
                    "No Stripe Session id was persisted and the reservation is "
                    "older than the idempotency recovery window, so a replay "
                    "would create a new request rather than prove anything. "
                    "Left held deliberately: a payment may exist against a "
                    "Session this row lost track of."
                ),
                now=now,
            )
            logger.warning(
                "discount reservation unresolvable: id=%s code=%s age=%s — no "
                "session id and past the %s idempotency window. Slot stays "
                "held; recheck Stripe rather than releasing.",
                reservation.id, reservation.discount_code_id, age,
                IDEMPOTENCY_RECOVERY_MAX_AGE,
            )
            return VERIFY_TOO_OLD

        recovered = sessions.recover_session_id(reservation=reservation)
        if recovered is None:
            # The replay produced no Session, so none was ever created.
            # Nothing can charge this member.
            release(db, reservation=reservation, reason="never_reached_stripe", now=now)
            _record_verification(
                db, reservation=reservation, status=VERIFY_RELEASED,
                error=None, now=now,
            )
            return VERIFY_RELEASED
        reservation.provider_checkout_session_id = recovered
        reservation.updated_at = now
        db.commit()

    try:
        status = sessions.session_status(reservation.provider_checkout_session_id)
    except sessions.StripeUnavailable as exc:
        _record_verification(
            db, reservation=reservation, status=VERIFY_UNVERIFIABLE,
            error=str(exc), now=now,
        )
        logger.warning(
            "discount reservation unverifiable: id=%s code=%s session=%s err=%s "
            "— staying held rather than risking a second charge.",
            reservation.id, reservation.discount_code_id,
            reservation.provider_checkout_session_id, exc,
        )
        return VERIFY_UNVERIFIABLE

    if status == "complete":
        _record_verification(
            db, reservation=reservation, status=VERIFY_CONVERTIBLE,
            error=None, now=now,
        )
        logger.warning(
            "discount reservation found COMPLETE during verification: id=%s "
            "code=%s session=%s — completion webhook was missed.",
            reservation.id, reservation.discount_code_id,
            reservation.provider_checkout_session_id,
        )
        return VERIFY_CONVERTIBLE

    if status == "expired":
        release(db, reservation=reservation, reason="stripe_session_expired", now=now)
        _record_verification(
            db, reservation=reservation, status=VERIFY_RELEASED, error=None, now=now,
        )
        return VERIFY_RELEASED

    # 'open' — still live past our window. Close it explicitly rather
    # than waiting on Stripe's own 24h expiry, then re-read: the expire
    # call can lose a race with a member paying at that very moment, and
    # the re-read is what decides.
    try:
        sessions.expire_session(reservation.provider_checkout_session_id)
    except sessions.StripeStateChanged:
        pass
    except sessions.StripeUnavailable as exc:
        _record_verification(
            db, reservation=reservation, status=VERIFY_UNVERIFIABLE,
            error=f"expire failed: {exc}", now=now,
        )
        return VERIFY_UNVERIFIABLE

    try:
        status = sessions.session_status(reservation.provider_checkout_session_id)
    except sessions.StripeUnavailable as exc:
        _record_verification(
            db, reservation=reservation, status=VERIFY_UNVERIFIABLE,
            error=f"re-read after expire failed: {exc}", now=now,
        )
        return VERIFY_UNVERIFIABLE

    if status == "complete":
        _record_verification(
            db, reservation=reservation, status=VERIFY_CONVERTIBLE, error=None, now=now,
        )
        logger.warning(
            "discount reservation completed during expire attempt: id=%s "
            "code=%s — treating as paid, not released.",
            reservation.id, reservation.discount_code_id,
        )
        return VERIFY_CONVERTIBLE
    if status == "expired":
        release(db, reservation=reservation, reason="expired_by_fc", now=now)
        _record_verification(
            db, reservation=reservation, status=VERIFY_RELEASED, error=None, now=now,
        )
        return VERIFY_RELEASED

    _record_verification(
        db, reservation=reservation, status=VERIFY_STILL_OPEN,
        error=f"session still {status!r} after expire attempt", now=now,
    )
    return VERIFY_STILL_OPEN


# ---------------------------------------------------------------------------
# Sweeping — resolving stale holds so a real buyer can have the slot
# ---------------------------------------------------------------------------


def stale_held_reservations(
    db: Session, *, discount_code_id: str, now: datetime,
) -> list[DiscountReservation]:
    """Held reservations past their checkout window, oldest first.

    Past the window is the only thing that makes one *eligible* for
    verification. It is emphatically not what makes it free.
    """
    return (
        db.query(DiscountReservation)
        .filter(
            DiscountReservation.discount_code_id == discount_code_id,
            DiscountReservation.status == ReservationStatus.held.value,
            DiscountReservation.session_expires_at <= now,
        )
        .order_by(DiscountReservation.session_expires_at.asc())
        .all()
    )


def sweep_stale_reservations(
    db: Session, *, discount_code_id: str, now: datetime,
) -> int:
    """Verify stale holds against Stripe; return how many were resolved.

    Called when a buyer has been refused for capacity, from OUTSIDE the
    code's row lock — every call in here is a network request, and holding
    a database lock across one makes a slow provider into a stuck table.
    The caller re-attempts the reservation afterwards, taking the lock
    again, and the second attempt either finds room or refuses honestly.

    A reservation that cannot be verified is left held on purpose. The
    buyer waiting on the slot is refused, which is the cost of never
    charging two people for a one-use code.
    """
    resolved = 0
    for reservation in stale_held_reservations(
        db, discount_code_id=discount_code_id, now=now,
    ):
        try:
            outcome = verify_stale_reservation(db, reservation=reservation, now=now)
        except Exception:
            # Verification is best-effort by nature — it talks to a third
            # party. An unexpected failure must not take down the
            # checkout that triggered it, and must not be read as
            # permission to release.
            logger.exception(
                "discount reservation verification raised: id=%s code=%s "
                "— leaving held.",
                reservation.id, discount_code_id,
            )
            continue
        if outcome == VERIFY_RELEASED:
            resolved += 1
        elif outcome == VERIFY_CONVERTIBLE:
            # The member paid and we missed the webhook. Their slot is
            # legitimately spent, so it does NOT become available — but
            # the redemption needs recording, and the webhook handler is
            # the one place that does that with the transaction in hand.
            # Logged loudly by ``verify_stale_reservation`` already.
            pass
    return resolved
