"""Purchase / payment-plan lifecycle emit helpers (R3).

One module owns the shared resolution logic (member-facing experience
name + primary member URL + repair URL) and the five emits R3
introduces. Domain services (webhook handlers, ``finite_plan_lifecycle``)
call these helpers immediately after the state transition they own has
been recorded on the session but before commit — matching the R2A/R2B
pattern where the emit is transactional with the domain change and the
caller schedules routing after commit.

Never raises out. Any comms failure (unknown event, resolver errors,
etc.) is caught and logged so a payment/access lifecycle transition is
never blocked by a downstream communication failure. Product lifecycle
is authoritative; comms is downstream.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption
from app.models.platform import EventSeries, Pathway, Space
from app.services import member_links as _links
from app.models.purchase_plan import PurchasePlan
from app.models.user import User

if TYPE_CHECKING:
    from app.comms.models import CommunicationEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PurchaseCommsContext:
    """Fields common to every R3 email/in-app payload.

    ``member_url`` is the primary post-purchase / post-recovery
    destination — deep-linked to the affected experience where a
    single primary destination is honest, or ``/dashboard`` when the
    payment option grants multiple experiences with no honest single
    landing. See A4 in R3 audit.

    ``repair_url`` is the deep-link to the affected experience whose
    ``PlanRecoveryBanner`` / ``RepairPaymentCta`` starts the
    authenticated repair flow. Falls back to ``/dashboard`` when the
    experience cannot be resolved. Only meaningful for failure /
    suspension events.
    """
    first_name: str
    experience_name: str
    member_url: str
    repair_url: str


def _first_name(user: User) -> str:
    if not user.name:
        return ""
    return user.name.strip().split(" ", 1)[0]


def _origin() -> str:
    from app.core.public_url import public_app_url
    return public_app_url()


def _member_url_for_option(db: Session, option: PaymentOption | None) -> str:
    """Deep-link to the member surface for the option's affected
    experience, or ``/dashboard`` when we can't honestly resolve one.

    Feeds both ``member_url`` and ``repair_url`` on every one of the six
    purchase-lifecycle emails, so a wrong answer here is not only a
    misdirected receipt — it is a payment-recovery CTA that lands
    somewhere ``PlanRecoveryBanner`` does not render.

    The Series branch used to match ``"series"``. The platform writes
    ``"event_series"`` (``creator._gathering_series_routes``), so the
    branch was unreachable and every Series purchase and every Series
    instalment-recovery email linked to ``/dashboard``. Both spellings
    are accepted now — see ``member_links.SERIES_ATTACH_KINDS`` — and
    the paths themselves are built in ``services.member_links`` so this
    module and ``gathering_booking_emit`` cannot drift apart again.
    """
    fallback = _links.dashboard_url()
    if option is None or not option.attaches_to_id:
        return fallback

    space = db.query(Space).filter(Space.id == option.space_id).one_or_none()
    if space is None:
        return fallback
    kind = (option.attaches_to_kind or "").lower()

    if kind == "pathway":
        pw = db.query(Pathway).filter(Pathway.id == option.attaches_to_id).one_or_none()
        return _links.pathway_member_url(space, pw) or fallback

    if kind in _links.SERIES_ATTACH_KINDS:
        series = (
            db.query(EventSeries)
            .filter(EventSeries.id == option.attaches_to_id)
            .one_or_none()
        )
        return _links.series_member_url(space, series) or fallback

    if kind == "offering":
        # Offerings Phase C/D. Without this branch a member who had just
        # bought a workbook was sent to ``/dashboard`` by their own
        # purchase confirmation — technically true, and no help at all
        # in finding the thing they paid for.
        from app.models.offering import Offering
        offering = (
            db.query(Offering)
            .filter(Offering.id == option.attaches_to_id)
            .one_or_none()
        )
        return _links.offering_member_url(space, offering) or fallback

    # ``space`` — the grants-first sentinel, where the option grants
    # many things and no single destination is honest — and any future
    # kind. Fall back rather than invent a URL. Both are named in
    # ``member_links``, so a kind nothing has heard of fails a test
    # rather than silently becoming a dashboard link.
    return fallback


def resolve_context(
    db: Session,
    *,
    user: User,
    payment_option: PaymentOption | None,
) -> PurchaseCommsContext:
    experience_name = ""
    if payment_option is not None and payment_option.name:
        experience_name = payment_option.name
    member_url = _member_url_for_option(db, payment_option)
    # R3 A5: repair CTA links to the affected experience (its existing
    # PlanRecoveryBanner starts the authenticated repair flow). Same URL
    # as ``member_url`` — no separate global "my plans" surface exists.
    repair_url = member_url
    return PurchaseCommsContext(
        first_name=_first_name(user),
        experience_name=experience_name,
        member_url=member_url,
        repair_url=repair_url,
    )


# ---------------------------------------------------------------------------
# Emit helpers — one per event
# ---------------------------------------------------------------------------


def _safe_emit(fn):
    """Decorator that logs+swallows any exception so a comms failure
    never propagates out to the payment/access lifecycle."""
    def _wrapped(*args, **kwargs) -> "CommunicationEvent | None":
        try:
            return fn(*args, **kwargs)
        except Exception:  # pragma: no cover — safety net
            logger.exception(
                "purchase_lifecycle_emit: %s raised; comms is downstream, "
                "payment/access lifecycle unaffected.",
                fn.__name__,
            )
            return None
    _wrapped.__name__ = fn.__name__
    _wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
    return _wrapped


@_safe_emit
def emit_purchase_completed(
    db: Session,
    *,
    user: User,
    payment_option: PaymentOption | None,
    payment_mode: str,           # 'single' | 'plan'
    amount_cents: int | None,
    currency: str | None,
    plan: PurchasePlan | None = None,
) -> "CommunicationEvent | None":
    """Emit for a single successful purchase or a FIP first-instalment.

    Idempotency contract: the caller has already confirmed this is the
    single fulfilment write (not a replay). For single-pay the caller
    checks ``txn.fulfilment_status``; for FIP first the caller checks
    ``plan.status == pending_setup`` and the invoice uniqueness index.
    """
    from app.comms import Source, emit as comms_emit
    ctx = resolve_context(db, user=user, payment_option=payment_option)
    payload = {
        "first_name":      ctx.first_name,
        "experience_name": ctx.experience_name,
        "member_url":      ctx.member_url,
        "payment_mode":    payment_mode,
        "amount_cents":    amount_cents,
        "currency":        currency,
    }
    if plan is not None and payment_mode == "plan":
        payload["installments_paid"]     = plan.installments_paid
        payload["installments_expected"] = plan.installments_expected
    return comms_emit(
        db,
        event_type="purchase.completed",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="purchase_plan" if plan else "payment_transaction",
        subject_id=plan.id if plan else None,
        payload=payload,
    )


@_safe_emit
def emit_instalment_failed(
    db: Session,
    *,
    user: User,
    plan: PurchasePlan,
    payment_option: PaymentOption | None,
) -> "CommunicationEvent | None":
    """Emit on the ``active → payment_problem`` transition. Grace
    deadline (``plan.grace_expires_at``) carried in payload so the
    template can name the date without querying the plan again."""
    from app.comms import Source, emit as comms_emit
    ctx = resolve_context(db, user=user, payment_option=payment_option)
    grace_iso = plan.grace_expires_at.isoformat() if plan.grace_expires_at else None
    payload = {
        "first_name":            ctx.first_name,
        "experience_name":       ctx.experience_name,
        "member_url":            ctx.member_url,
        "repair_url":            ctx.repair_url,
        "amount_cents":          plan.installment_amount_cents,
        "currency":              plan.currency,
        "grace_expires_at":      grace_iso,
        "installments_paid":     plan.installments_paid,
        "installments_expected": plan.installments_expected,
    }
    return comms_emit(
        db,
        event_type="payment.instalment_failed",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="purchase_plan",
        subject_id=plan.id,
        context={"plan_id": plan.id},
        payload=payload,
    )


@_safe_emit
def emit_first_payment_failed(
    db: Session,
    *,
    user: User,
    plan: PurchasePlan,
    payment_option: PaymentOption | None,
    invoice_id: str | None = None,
) -> "CommunicationEvent | None":
    """Emit when the FIRST instalment is declined and the plan is
    terminated (FIP4A).

    Deliberately not ``payment.instalment_failed``: that event tells a
    member their access continues during a grace window. Neither
    applies here — the plan never started, no access was granted, and
    the provider schedule has been cancelled, so there is no retry to
    wait for.

    Dedupe is keyed on the plan, not the invoice. A plan fails its
    first payment at most once in its lifetime — the termination helper
    marks it ``failed`` and its entry guard short-circuits every
    subsequent delivery. Keying on the invoice would be weaker: the
    synchronous card-decline path has no invoice id to key on (the
    exception is raised before one is returned), and a later webhook
    quoting a different invoice for the same dead plan would earn a
    second email. ``invoice_id`` is carried in the payload for
    traceability only.
    """
    from app.comms import Source, emit as comms_emit
    ctx = resolve_context(db, user=user, payment_option=payment_option)
    payload = {
        "first_name":            ctx.first_name,
        "experience_name":       ctx.experience_name,
        # The existing offer page — the member starts again from there.
        # Rule D is unblocked by the termination, so a fresh plan is
        # immediately allowed. No repair flow is linked: a ``failed``
        # plan is not repair-eligible.
        "retry_url":             ctx.member_url,
        "amount_cents":          plan.installment_amount_cents,
        "currency":              plan.currency,
        "installments_expected": plan.installments_expected,
        "invoice_id":            invoice_id,
    }
    return comms_emit(
        db,
        event_type="purchase.first_payment_failed",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="purchase_plan",
        subject_id=plan.id,
        context={"plan_id": plan.id},
        payload=payload,
        dedupe_key=f"first_payment_failed:{plan.id}",
    )


@_safe_emit
def emit_access_suspended(
    db: Session,
    *,
    user: User,
    plan: PurchasePlan,
    payment_option: PaymentOption | None,
) -> "CommunicationEvent | None":
    """Emit on the ``payment_problem → suspended`` transition."""
    from app.comms import Source, emit as comms_emit
    ctx = resolve_context(db, user=user, payment_option=payment_option)
    payload = {
        "first_name":            ctx.first_name,
        "experience_name":       ctx.experience_name,
        "member_url":            ctx.member_url,
        "repair_url":            ctx.repair_url,
        "installments_paid":     plan.installments_paid,
        "installments_expected": plan.installments_expected,
    }
    return comms_emit(
        db,
        event_type="access.suspended",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="purchase_plan",
        subject_id=plan.id,
        context={"plan_id": plan.id},
        payload=payload,
    )


@_safe_emit
def emit_payment_recovered(
    db: Session,
    *,
    user: User,
    plan: PurchasePlan,
    payment_option: PaymentOption | None,
    was_suspended: bool,
) -> "CommunicationEvent | None":
    """Emit on the ``{payment_problem, suspended} → active`` transition
    from a NON-final instalment. ``was_suspended`` distinguishes "access
    remains active" (grace recovery) from "access is active again"
    (post-suspension recovery)."""
    from app.comms import Source, emit as comms_emit
    ctx = resolve_context(db, user=user, payment_option=payment_option)
    payload = {
        "first_name":            ctx.first_name,
        "experience_name":       ctx.experience_name,
        "member_url":            ctx.member_url,
        "was_suspended":         bool(was_suspended),
        "amount_cents":          plan.installment_amount_cents,
        "currency":              plan.currency,
        "installments_paid":     plan.installments_paid,
        "installments_expected": plan.installments_expected,
    }
    return comms_emit(
        db,
        event_type="payment.recovered",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="purchase_plan",
        subject_id=plan.id,
        context={"plan_id": plan.id},
        payload=payload,
    )


@_safe_emit
def emit_plan_completed(
    db: Session,
    *,
    user: User,
    plan: PurchasePlan,
    payment_option: PaymentOption | None,
) -> "CommunicationEvent | None":
    """Emit on the ``* → completed`` transition (final scheduled
    instalment lands). If completion also happened to recover from
    payment_problem/suspended, callers should suppress the
    ``payment.recovered`` emit — completion is the more meaningful
    member moment."""
    from app.comms import Source, emit as comms_emit
    ctx = resolve_context(db, user=user, payment_option=payment_option)
    payload = {
        "first_name":            ctx.first_name,
        "experience_name":       ctx.experience_name,
        "member_url":            ctx.member_url,
        "currency":              plan.currency,
        "total_paid_cents":      plan.total_expected_cents,
        "installments_paid":     plan.installments_paid,
        "installments_expected": plan.installments_expected,
    }
    return comms_emit(
        db,
        event_type="purchase.plan_completed",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="purchase_plan",
        subject_id=plan.id,
        context={"plan_id": plan.id},
        payload=payload,
    )


# ---------------------------------------------------------------------------
# The other side of a purchase — telling the Collective's leaders
# ---------------------------------------------------------------------------

def _money(amount_cents: int | None, currency: str | None) -> str:
    """'A$250' / '£40'. Empty when we do not have both parts."""
    if not amount_cents or amount_cents <= 0:
        return ""
    code = (currency or "AUD").upper()
    symbol = {"AUD": "A$", "NZD": "NZ$", "USD": "US$", "GBP": "£", "EUR": "€"}.get(code)
    whole = amount_cents / 100
    rendered = f"{whole:,.0f}" if amount_cents % 100 == 0 else f"{whole:,.2f}"
    return f"{symbol}{rendered}" if symbol else f"{rendered} {code}"


#: How each kind of purchase reads in the creator's notification.
#: ``attaches_to_kind`` values on the left; the verb that is true of
#: them on the right.
_PURCHASE_VERBS: dict[str, str] = {
    "offering":     "purchased",
    "pathway":      "joined",
    "event_series": "joined",
    "gathering":    "booked",
    "event":        "booked",
}


def _purchase_verb(experience_kind: str | None) -> str:
    """The verb for this kind of purchase.

    Defaults to ``joined`` for anything unrecognised — the wording that
    shipped, and correct for the Pathway and Series purchases that were
    the only kinds when it was written. An unknown future kind therefore
    reads as it always did rather than as something worse.
    """
    return _PURCHASE_VERBS.get((experience_kind or "").strip(), "joined")


def _purchase_phrase(
    experience_kind: str | None, *, free: bool,
) -> tuple[str, str]:
    """``(verb, suffix)`` — the predicate wrapped around the name.

    Two parts rather than one because the name sits in the middle of
    the sentence: *purchased* **Test Workbook**, but *added* **Test
    Workbook** *to their collection*. A verb alone cannot say the
    second, and moving the name out of the slot default would silently
    rewrite every override an admin has already saved.

    The suffix is empty for every paid purchase, so the paid wording is
    byte-identical to what it was before free acquisitions existed.
    """
    if free and (experience_kind or "").strip() == "offering":
        # Nothing was paid, so "purchased" would be false and
        # "acquired" is not how anybody speaks. What actually happened
        # is that it is now in their collection — the same words the
        # member sees on their own side of it.
        return "added", " to their collection"
    return _purchase_verb(experience_kind), ""


@_safe_emit
def emit_purchase_received_creator(
    db: Session,
    *,
    space_id: str,
    buyer: User,
    experience_name: str,
    payment_mode: str,            # 'single' | 'plan' | 'free'
    amount_cents: int | None,
    currency: str | None,
    dedupe_key: str,
    session_count: int | None = None,
    experience_kind: str | None = None,
    free: bool = False,
) -> "CommunicationEvent | None":
    """Tell the Collective's leaders that a paid signup succeeded.

    One notification per meaningful purchase. A Term pass fans out into
    dozens of ``EventBooking`` rows and is still one sale, so this is
    emitted where the *purchase* is fulfilled — never per entitlement and
    never per booking. ``session_count`` is how many Gatherings came with
    it, for the copy; it does not multiply anything.

    For a finite payment plan the caller emits at the FIRST successful
    payment, because that is when access is actually granted — not at
    checkout, where only a card has been captured.

    ``dedupe_key`` is the transaction or plan id. The partial unique
    index on ``(event_type, dedupe_key)`` makes a repeat emit a no-op at
    the database level, so a Stripe redelivery cannot produce a second
    notification even if a caller's own short-circuit is bypassed.

    Recipients are resolved by ``routing/resolvers/collective.py`` —
    owner plus active leader memberships, minus the buyer.

    ``free=True`` is a free Offering acquisition. It is the same news
    to a creator — somebody now has their work — so it travels as the
    same event through the same recipient rules and the same
    preferences, and differs only in wording: no amount, no revenue
    claim, and no payment transaction anywhere behind it.
    """
    from app.comms import Source, emit as comms_emit
    from app.models.platform import Space
    from app.services.member_identity import display_name as member_display_name

    space = db.query(Space).filter(Space.id == space_id).first()
    if space is None:
        return None

    origin = _origin()
    _verb, _suffix = _purchase_phrase(experience_kind, free=free)
    payload = {
        "space_id":        space.id,
        "collective_name": space.name,
        # Through the canonical ladder: never an email local part, and
        # "Member" when somebody has not set a name.
        "buyer_name":      member_display_name(buyer),
        "experience_name": experience_name or "",
        "payment_mode":    payment_mode,
        "amount_display":  _money(amount_cents, currency),
        "amount_cents":    amount_cents,
        "currency":        currency,
        "session_count":   session_count,
        # What KIND of thing was bought, so the copy can use the right
        # verb. A workbook is purchased, a Pathway is joined, a
        # Gathering is booked — one verb for all three read wrongly for
        # two of them. Empty when the caller cannot tell, which falls
        # back to the original "joined" wording rather than guessing.
        "experience_kind": (experience_kind or ""),
        "purchase_verb":   _verb,
        "purchase_suffix": _suffix,
        # True for a free acquisition. Carried so the copy can say that
        # plainly instead of leaving a creator to infer it from a
        # missing amount — and so nothing downstream reads the absent
        # amount as revenue that failed to record.
        "is_free":         bool(free),
        "cta_url":         f"{origin}/creator-studio/people",
    }
    return comms_emit(
        db,
        event_type="collective.purchase.received",
        source_type=Source.COLLECTIVE,
        source_id=space.id,
        actor_user_id=buyer.id,
        subject_type="space",
        subject_id=space.id,
        context={"space_id": space.id},
        payload=payload,
        dedupe_key=dedupe_key,
    )
