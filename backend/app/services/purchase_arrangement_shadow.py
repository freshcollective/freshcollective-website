"""Stage 1B.2A — does the new resolver agree with what members see?

The existing member projection stays authoritative. This module asks
the Stage 1A resolver the same question the projection just answered,
compares the two, and logs any disagreement. It changes nothing a
member sees and nothing a member can buy.

Why shadow rather than switch
-----------------------------
The resolver has been correct in tests since Stage 1A and correct about
creator configuration since Stage 1B.1, but it has never been asked
about a real production Payment Option. A shadow run answers "would
this have charged the same price?" against real rows, with no
consequence if the answer is no — which is the evidence needed before
the resolver is allowed to influence a member's purchase.

What counts as a disagreement
-----------------------------
The two sides are shaped differently on purpose, and most of that is
presentation rather than pricing:

* The projection returns **options**, each carrying its published
  schedules. The resolver returns **arrangements**, one per schedule.
  Comparing an option against an arrangement would report a difference
  on every multi-schedule bundle. So both sides are flattened to
  ``(option_id, schedule_id)`` pairs first.
* The projection omits an option entirely when nothing on it is
  sellable. The resolver returns the arrangement with a *reason*. An
  arrangement the resolver marks unavailable and the projection omits
  is agreement, not a gap.
* The projection has no notion of a draft or archived Option — its
  query filters them out. The resolver describes them. Again agreement.

So the comparison is between the two **sellable sets** — what the
projection offers, and what the resolver calls
``available_for_new_purchase`` — plus a field-by-field money comparison
on the pairs both sides consider sellable. Anything else is noted at
debug level and is not a finding.

What is logged
--------------
Option ids, schedule ids, amounts, currencies, cadences and
availability. **No member is involved in this comparison at all** — the
projection's member-specific parts (which options the viewer already
holds, plan-recovery state) are applied by the endpoint *after* this
runs and are deliberately not compared. There is therefore no user id,
email, name or Stripe identifier to leak; amounts are the subject of
the comparison and are already public on the page being rendered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: Money and shape fields compared on a pair both sides sell. Each maps
#: the projection's field name to the resolver's, which differ in two
#: places because the projection predates the resolver's vocabulary.
COMPARED_FIELDS: tuple[tuple[str, str], ...] = (
    ("schedule_type", "schedule_type"),
    ("currency", "currency"),
    ("total_amount_cents", "total_amount_cents"),
    ("installment_amount_cents", "installment_amount_cents"),
    ("installment_count", "installment_count"),
    ("interval", "interval"),
)


@dataclass(frozen=True)
class Difference:
    """One disagreement, in terms safe to log."""

    kind: str
    option_id: str
    schedule_id: str | None
    field_name: str | None = None
    baseline: Any = None
    candidate: Any = None

    def as_log(self) -> str:
        parts = [
            f"kind={self.kind}",
            f"option={self.option_id}",
            f"schedule={self.schedule_id or '-'}",
        ]
        if self.field_name:
            parts.append(
                f"{self.field_name}: existing={self.baseline!r} "
                f"resolver={self.candidate!r}"
            )
        return " ".join(parts)


@dataclass
class ShadowReport:
    experience_kind: str
    experience_id: str
    #: Pairs both sides agree are sellable, with every compared field
    #: matching. The number worth watching.
    matched: int = 0
    #: Pairs both sides sell but which differ on a money field. These
    #: are the findings that block Stage 1B.2B.
    differences: list[Difference] = field(default_factory=list)
    #: Sellable to members today but the resolver would not sell.
    missing_from_resolver: list[Difference] = field(default_factory=list)
    #: The resolver would sell but members are not offered it.
    extra_in_resolver: list[Difference] = field(default_factory=list)

    @property
    def agrees(self) -> bool:
        return not (
            self.differences
            or self.missing_from_resolver
            or self.extra_in_resolver
        )

    def log(self) -> None:
        """Emit the result.

        Agreement is **info**, not debug. A shadow run where everything
        agrees produces no warnings, which is indistinguishable from
        the flag never having been switched on — so "no warnings" would
        be unreadable as evidence. One info line per comparison makes
        the window auditable: the lines can be counted, and
        ``matched=`` summed, to show comparisons actually executed.

        Disagreement is a warning, because a price difference is the
        thing this exists to catch and it must not sit in a stream
        nobody reads.

        Volume is acceptable: this runs on one low-traffic member
        endpoint, for a bounded window, behind a flag.
        """
        head = (
            f"purchase_arrangements_shadow {self.experience_kind}="
            f"{self.experience_id} matched={self.matched}"
        )
        if self.agrees:
            logger.info("%s agrees", head)
            return
        logger.warning(
            "%s DISAGREES differing=%d missing=%d extra=%d",
            head, len(self.differences), len(self.missing_from_resolver),
            len(self.extra_in_resolver),
        )
        for diff in (
            *self.differences,
            *self.missing_from_resolver,
            *self.extra_in_resolver,
        ):
            logger.warning("purchase_arrangements_shadow   %s", diff.as_log())


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _baseline_pairs(purchasable: list) -> dict[tuple[str, str], dict]:
    """Flatten the member projection to sellable ``(option, schedule)``
    pairs.

    ``is_member_checkoutable`` on the projected schedule is the
    authority for "a member can complete this", so only those pairs are
    taken — an option can legitimately carry a published schedule the
    member surface shows greyed out.
    """
    from app.spaces.purchase_schedule_view import schedule_view

    pairs: dict[tuple[str, str], dict] = {}
    for po in purchasable:
        for sched in po.schedules:
            view = schedule_view(sched, po.option)
            if not view.get("is_member_checkoutable"):
                continue
            pairs[(po.option.id, sched.id)] = {
                "schedule_type": view["schedule_type"],
                "currency": view["currency"],
                "total_amount_cents": view["total_amount_cents"],
                "installment_amount_cents": view["installment_amount_cents"],
                "installment_count": view["installment_count"],
                "interval": view["interval"],
                "included_titles": sorted(
                    t for t in (po.included_titles or []) if t
                ),
            }
    return pairs


def _candidate_pairs(arrangements) -> dict[tuple[str, str], dict]:
    """Flatten the resolver to the pairs it would sell."""
    pairs: dict[tuple[str, str], dict] = {}
    for a in arrangements:
        if a.payment_option_id is None or a.payment_option_schedule_id is None:
            # A direct price has no Option behind it. Series carry no
            # direct arrangement today, so this is defensive.
            continue
        if not a.available_for_new_purchase:
            continue
        pairs[(a.payment_option_id, a.payment_option_schedule_id)] = {
            "schedule_type": a.schedule_type,
            "currency": a.currency,
            # The projection coerces a null total to 0; match that here
            # so a missing total is not reported as a currency-shaped
            # difference on every pay-in-full row.
            "total_amount_cents": a.total_amount_cents or 0,
            "installment_amount_cents": a.installment_amount_cents,
            "installment_count": a.installment_count,
            "interval": a.interval,
            "included_titles": sorted(
                inc.title for inc in a.included if inc.title
            ),
        }
    return pairs


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------


def compare_series(
    db: Session, *, series, space, purchasable: list,
) -> ShadowReport:
    """Compare the member Series projection against the resolver.

    ``purchasable`` is the projection's own output, passed in rather
    than recomputed so the comparison is against exactly what the
    member was served — recomputing it would compare the resolver
    against a second evaluation that could itself differ.
    """
    from app.services.purchase_arrangements import KIND_SERIES, arrangements_for

    report = ShadowReport(
        experience_kind=KIND_SERIES, experience_id=series.id,
    )

    found = arrangements_for(db, kind=KIND_SERIES, experience_id=series.id)
    baseline = _baseline_pairs(purchasable)
    candidate = _candidate_pairs(found.arrangements if found else ())

    for key in sorted(baseline.keys() - candidate.keys()):
        report.missing_from_resolver.append(
            Difference(
                kind="sellable_to_members_but_not_to_resolver",
                option_id=key[0], schedule_id=key[1],
            )
        )
    for key in sorted(candidate.keys() - baseline.keys()):
        report.extra_in_resolver.append(
            Difference(
                kind="resolver_would_sell_but_members_are_not_offered_it",
                option_id=key[0], schedule_id=key[1],
            )
        )

    for key in sorted(baseline.keys() & candidate.keys()):
        differed = False
        for base_name, cand_name in COMPARED_FIELDS:
            left = baseline[key][base_name]
            right = candidate[key][cand_name]
            if left != right:
                differed = True
                report.differences.append(
                    Difference(
                        kind="field_mismatch", option_id=key[0],
                        schedule_id=key[1], field_name=base_name,
                        baseline=left, candidate=right,
                    )
                )
        # Included experiences, compared as a set of titles. The
        # projection lists the Series title plus included Pathway
        # titles; the resolver lists one entry per grant. Order and
        # duplicates are presentation, so both are sorted sets.
        left_titles = set(baseline[key]["included_titles"])
        right_titles = set(candidate[key]["included_titles"])
        if left_titles != right_titles:
            differed = True
            report.differences.append(
                Difference(
                    kind="included_experiences_differ", option_id=key[0],
                    schedule_id=key[1], field_name="included_titles",
                    baseline=sorted(left_titles), candidate=sorted(right_titles),
                )
            )
        if not differed:
            report.matched += 1

    return report


def compare_series_quietly(db: Session, *, series, space, purchasable: list) -> None:
    """Run the comparison for its logs, swallowing everything.

    The call site is a member-facing endpoint whose response is already
    built. A shadow comparison that raised would turn a working page
    into a 500 to report a discrepancy nobody asked it to report, so
    every failure — including a bug in this module — is logged and
    dropped.
    """
    try:
        compare_series(
            db, series=series, space=space, purchasable=purchasable,
        ).log()
    except Exception:  # noqa: BLE001 — see docstring
        logger.warning(
            "purchase_arrangements_shadow failed for series=%s",
            getattr(series, "id", "-"), exc_info=True,
        )


__all__ = [
    "COMPARED_FIELDS",
    "Difference",
    "ShadowReport",
    "compare_series",
    "compare_series_quietly",
]
