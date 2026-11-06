"""Stage 1B.3 — would the resolver price this purchase the same way?

Runs on a Gathering Series checkout that has **already** passed every
guard and had every value determined, immediately before Stripe is
contacted. It reads, compares, logs, and changes nothing. The existing
checkout stays authoritative in both flag states.

What makes this different from the display shadow
-------------------------------------------------
``purchase_arrangement_shadow`` (Stage 1B.2A) compares what a member is
*shown*. This compares what a member is about to be *charged*. The
second is the one that matters for trust, and it is also the one where
a mistake is unrecoverable, which is why it observes for a window
before it is allowed to influence anything.

It also asks a sharper question. The display shadow compares two lists
and checks they describe the same set. This takes the two identifiers
the member actually supplied and asks ``resolve_arrangement`` to
re-derive the price from them — the price-integrity entry point built
in Stage 1A for exactly this purpose. That call raises
:class:`ArrangementNotFound` when the named arrangement does not belong
to the experience it was claimed for, so "the resolver agrees" also
means "the resolver found the same Option and the same schedule under
this Series", not merely a matching number somewhere.

The honest limit, stated structurally rather than in a footnote
---------------------------------------------------------------
**The resolver has no member in its question.** It answers what the
creator configured. The authoritative checkout additionally evaluates
things the resolver never looks at:

* ``check_same_option_not_active`` — does this member already hold it?
* the ban guard
* ``resolve_fee_context`` — the creator's plan, and whether it permits
  paid offers
* ``pathway_commerce.check_sellable_or_raise`` — an archived Pathway in
  a bundle

So a clean comparison here does **not** mean the two systems would make
the same accept/refuse decision. It means they agree on *the comparable
axis*: arrangement identity, currency, the amount charged now, the
total committed, and the instalment shape — plus the arrangement-level
availability both sides do evaluate (publication state, fulfillable
grants, schedule validity, the instalment flag, price validity).

Rather than leave that as prose, every comparison carries
:data:`NOT_COMPARED` naming the dimensions neither agreement nor
disagreement covers. A verdict of ``agree`` is therefore always
readable as "agrees about price and identity, and says nothing about
member eligibility".

Writes nothing
--------------
No session mutation, no Stripe call, no diagnostic row. The only output
is a log line.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: Verdicts. Deliberately four, not two — "we did not compare" and "the
#: comparison itself broke" must never be filed as agreement.
VERDICT_AGREE = "agree"
VERDICT_DISAGREE = "disagree"
VERDICT_NOT_COMPARABLE = "not_comparable"
VERDICT_SHADOW_ERROR = "shadow_error"

#: Guards the authoritative checkout evaluates and the resolver, by
#: design, does not. Carried on every comparison so a reader of the
#: logs can never mistake ``agree`` for "these two systems would make
#: the same decision".
NOT_COMPARED: tuple[str, ...] = (
    "member_already_holds_option",
    "member_banned",
    "creator_plan_eligibility",
    "pathway_sellable",
)

#: One log prefix for the whole feature, so a window can be counted
#: with a single search.
LOG_PREFIX = "purchase_arrangements_checkout_shadow"


@dataclass(frozen=True)
class AuthoritativeCheckout:
    """What the existing checkout has already decided.

    Built by the caller from the values the legacy path resolved — not
    recomputed here. Reconstructing the legacy answer inside the shadow
    would make the comparison a test of this module rather than of the
    resolver.

    ``immediate_charge_cents`` is the amount about to reach Stripe:
    ``price_cents`` for pay-in-full, and the first instalment for a
    plan, because ``stripe_finite_plan`` builds the subscription price
    from ``installment_amount_cents``. The schedule's stored
    ``upfront_amount_cents`` is **not** it — nothing collects that, and
    treating it as the first charge was the discrepancy corrected in
    7a21fab.

    ``total_amount_cents`` for a plan is ``per x count``, which is what
    ``finite_plan_orchestration`` commits as ``total_expected`` —
    derived rather than read from the schedule's own total column. The
    two agree for any valid schedule because
    ``validate_recurring_installments_row`` enforces strict equality,
    and comparing against the derived figure is what would catch them
    drifting.
    """

    experience_kind: str
    experience_id: str
    payment_option_id: str
    payment_option_schedule_id: str
    schedule_type: str
    currency: str
    immediate_charge_cents: int
    total_amount_cents: int
    installment_amount_cents: int | None = None
    installment_count: int | None = None
    interval: str | None = None


@dataclass(frozen=True)
class FieldDifference:
    field_name: str
    legacy: Any
    resolver: Any

    def as_log(self) -> str:
        return f"{self.field_name}: legacy={self.legacy!r} resolver={self.resolver!r}"


@dataclass
class CheckoutComparison:
    verdict: str
    authoritative: AuthoritativeCheckout
    reason: str | None = None
    differences: list[FieldDifference] = field(default_factory=list)
    #: The resolver's own availability answer, for the record. Not an
    #: accept/refuse comparison — see the module docstring.
    resolver_available: bool | None = None
    resolver_unavailable_reason: str | None = None

    def as_log(self) -> str:
        a = self.authoritative
        parts = [
            LOG_PREFIX,
            f"verdict={self.verdict}",
            f"kind={a.experience_kind}",
            f"experience={a.experience_id}",
            f"option={a.payment_option_id}",
            f"schedule={a.payment_option_schedule_id}",
            f"schedule_type={a.schedule_type}",
            f"currency={a.currency}",
            f"immediate={a.immediate_charge_cents}",
            f"total={a.total_amount_cents}",
        ]
        if a.installment_count is not None:
            parts.append(
                f"instalments={a.installment_count}x{a.installment_amount_cents}"
                f"/{a.interval or '-'}"
            )
        if self.resolver_available is not None:
            parts.append(f"resolver_available={self.resolver_available}")
        if self.resolver_unavailable_reason:
            parts.append(f"resolver_reason={self.resolver_unavailable_reason}")
        if self.reason:
            parts.append(f"reason={self.reason}")
        parts.append(f"not_compared={','.join(NOT_COMPARED)}")
        return " ".join(parts)

    def log(self) -> None:
        """Agreement at info, anything else at warning.

        Agreement is logged — not silent — because an observation window
        that produced nothing is not evidence of agreement, and a
        countable line per comparison is the only way to tell the two
        apart. The same lesson as the display shadow.
        """
        line = self.as_log()
        if self.verdict == VERDICT_AGREE:
            logger.info("%s", line)
            return
        logger.warning("%s", line)
        for diff in self.differences:
            logger.warning("%s   %s", LOG_PREFIX, diff.as_log())


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------

#: Money and shape fields compared, mapping the authoritative attribute
#: to the resolver's. Written out so the set is auditable rather than
#: whatever ``dataclasses.fields`` happens to contain.
COMPARED_FIELDS: tuple[tuple[str, str], ...] = (
    ("schedule_type", "schedule_type"),
    ("currency", "currency"),
    ("immediate_charge_cents", "upfront_amount_cents"),
    ("total_amount_cents", "total_amount_cents"),
    ("installment_amount_cents", "installment_amount_cents"),
    ("installment_count", "installment_count"),
    ("interval", "interval"),
)


def compare_checkout(
    db: Session, *, authoritative: AuthoritativeCheckout,
) -> CheckoutComparison:
    """Ask the resolver to re-derive this purchase, and compare.

    Never raises for a comparison outcome — an arrangement the resolver
    cannot find is a *verdict*, not an exception, because the caller is
    mid-checkout and must not be disturbed by a diagnostic.
    """
    from app.services.purchase_arrangements import (
        ArrangementNotFound,
        option_arrangement_id,
        resolve_arrangement,
    )

    arrangement_id = option_arrangement_id(
        authoritative.payment_option_id,
        authoritative.payment_option_schedule_id,
    )

    try:
        arrangement = resolve_arrangement(
            db,
            kind=authoritative.experience_kind,
            experience_id=authoritative.experience_id,
            arrangement_id=arrangement_id,
        )
    except ArrangementNotFound:
        # The identifiers the member supplied do not name an
        # arrangement the resolver can find under this experience. A
        # real disagreement about identity, and exactly what
        # ``resolve_arrangement`` exists to refuse — so it is reported
        # rather than smoothed over by picking another schedule.
        return CheckoutComparison(
            verdict=VERDICT_DISAGREE,
            authoritative=authoritative,
            reason="resolver_cannot_find_this_arrangement",
        )

    differences: list[FieldDifference] = []
    for legacy_name, resolver_name in COMPARED_FIELDS:
        legacy_value = getattr(authoritative, legacy_name)
        resolver_value = getattr(arrangement, resolver_name)
        if legacy_value != resolver_value:
            differences.append(FieldDifference(
                field_name=legacy_name,
                legacy=legacy_value,
                resolver=resolver_value,
            ))

    # Arrangement-level availability. Both sides evaluate publication
    # state, fulfillable grants, schedule validity, the instalment flag
    # and price validity — so the authoritative path having reached
    # here means it considered the arrangement sellable, and the
    # resolver saying otherwise is a genuine disagreement about a rule
    # they share.
    #
    # It is NOT a statement about accept/refuse: the member-specific
    # guards in NOT_COMPARED are not in this comparison at all.
    if not arrangement.available_for_new_purchase:
        differences.append(FieldDifference(
            field_name="arrangement_availability",
            legacy="sellable",
            resolver=arrangement.unavailable_reason or "unavailable",
        ))

    return CheckoutComparison(
        verdict=VERDICT_DISAGREE if differences else VERDICT_AGREE,
        authoritative=authoritative,
        differences=differences,
        resolver_available=arrangement.available_for_new_purchase,
        resolver_unavailable_reason=arrangement.unavailable_reason,
    )


def not_comparable(
    authoritative: AuthoritativeCheckout, reason: str,
) -> CheckoutComparison:
    """A comparison that was not attempted, recorded as such.

    Used when the caller cannot supply an experience to resolve against
    — a Payment Option with no Series grant, for instance. Filed as its
    own verdict so it can never be counted as agreement.
    """
    return CheckoutComparison(
        verdict=VERDICT_NOT_COMPARABLE,
        authoritative=authoritative,
        reason=reason,
    )


def compare_checkout_quietly(
    db: Session, *, authoritative: AuthoritativeCheckout,
) -> None:
    """Run the comparison for its log line, swallowing everything.

    The caller is a checkout that has already decided and is about to
    contact Stripe. A diagnostic that raised here would turn a valid
    purchase into a 500 to report something nobody asked it to report,
    so every failure — including a bug in this module — becomes a
    ``shadow_error`` line and is dropped.

    Logged at warning with a traceback rather than silently, so a
    broken shadow is visible as a broken shadow. Deliberately *not*
    re-raised and deliberately not an ``ERROR`` log: an expected
    diagnostic limitation must not become Sentry noise on the checkout
    path.
    """
    try:
        compare_checkout(db, authoritative=authoritative).log()
    except Exception:  # noqa: BLE001 — see docstring
        try:
            logger.warning(
                "%s verdict=%s option=%s schedule=%s",
                LOG_PREFIX, VERDICT_SHADOW_ERROR,
                authoritative.payment_option_id,
                authoritative.payment_option_schedule_id,
                exc_info=True,
            )
        except Exception:  # noqa: BLE001 — logging itself failed
            pass


# ---------------------------------------------------------------------------
# Building the authoritative view from what checkout already resolved
# ---------------------------------------------------------------------------


def series_id_for_option(db: Session, payment_option_id: str) -> str | None:
    """The Gathering Series this Option grants, or ``None``.

    Read-only, and the narrowest query that answers the question. The
    unified checkout endpoint is kind-agnostic — a request never names a
    Series — so the experience to resolve against has to come from the
    Option's own grant.

    ``None`` for an Option that grants no Series, which is how this
    stage stays scoped to Gathering Series without the caller having to
    know the kind in advance.
    """
    from app.models.payment_option_grant import (
        GRANT_KIND_EVENT_SERIES,
        PaymentOptionGrant,
    )

    row = (
        db.query(PaymentOptionGrant.series_id)
        .filter(
            PaymentOptionGrant.payment_option_id == payment_option_id,
            PaymentOptionGrant.grant_kind == GRANT_KIND_EVENT_SERIES,
            PaymentOptionGrant.series_id.isnot(None),
        )
        .order_by(PaymentOptionGrant.id)
        .first()
    )
    return row[0] if row else None


def authoritative_from_pay_in_full(
    *, series_id: str, resolved,
) -> AuthoritativeCheckout:
    """The legacy pay-in-full decision, as resolved.

    ``price_cents`` is both the immediate charge and the total: one
    charge, inside Stripe Checkout.
    """
    schedule = resolved.payment_schedule
    return AuthoritativeCheckout(
        experience_kind="event_series",
        experience_id=series_id,
        payment_option_id=resolved.payment_option.id,
        payment_option_schedule_id=schedule.id,
        schedule_type=schedule.schedule_type,
        currency=resolved.currency,
        immediate_charge_cents=resolved.price_cents,
        total_amount_cents=resolved.price_cents,
        installment_amount_cents=None,
        installment_count=None,
        interval=None,
    )


def authoritative_from_finite_plan(
    *, series_id: str, resolved,
) -> AuthoritativeCheckout:
    """The legacy finite-plan decision, as resolved.

    The immediate charge is the first instalment — what
    ``stripe_finite_plan`` prices the subscription at — and the total is
    ``per x count``, which is the ``total_expected`` the plan row
    commits. Both read from the schedule the legacy path already
    validated, not recomputed from the request.
    """
    schedule = resolved.payment_schedule
    per = schedule.installment_amount_cents
    count = schedule.installment_count
    total = (per * count) if (per is not None and count is not None) else 0
    return AuthoritativeCheckout(
        experience_kind="event_series",
        experience_id=series_id,
        payment_option_id=resolved.payment_option.id,
        payment_option_schedule_id=schedule.id,
        schedule_type=schedule.schedule_type,
        currency=resolved.currency,
        immediate_charge_cents=per or 0,
        total_amount_cents=total,
        installment_amount_cents=per,
        installment_count=count,
        interval=schedule.interval or schedule.stripe_interval,
    )


__all__ = [
    "COMPARED_FIELDS",
    "LOG_PREFIX",
    "NOT_COMPARED",
    "VERDICT_AGREE",
    "VERDICT_DISAGREE",
    "VERDICT_NOT_COMPARABLE",
    "VERDICT_SHADOW_ERROR",
    "AuthoritativeCheckout",
    "CheckoutComparison",
    "FieldDifference",
    "authoritative_from_finite_plan",
    "authoritative_from_pay_in_full",
    "compare_checkout",
    "compare_checkout_quietly",
    "not_comparable",
    "series_id_for_option",
]
