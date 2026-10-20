"""One place that answers "how much may this creator upload?".

Phase B5. Every limit decision — the upload endpoint, the replacement
endpoint, the publication check — reads its numbers from here, which is
the whole point: the approved allowances differ per plan, and a second
copy of them in a second endpoint is how two endpoints come to disagree.

Three things live here and nowhere else:

  1. :func:`resolve_offering_limits` — a plan's allowance, reduced by the
     platform ceiling.
  2. :func:`bundle_usage` — how much of that allowance an Offering is
     already using, under the approved counting rules.
  3. :func:`guard_upload` — the two together, raising the refusal.

The pure rules (what a file may *be*) stay in
``app.services.offering_files``. This module is the part that needs a
database and a plan.

Counting rules, and why each one is what it is
----------------------------------------------

**Resources, not rows.** A ZIP contributes its member files to the count,
an Office package contributes one. Both come from
``offering_files.resource_count``, computed once at upload from the
archive's central directory. Counting rows instead would make a ZIP an
unlimited container, and counting an .xlsx's internal parts would charge
a creator twenty resources for one spreadsheet.

**Slots, not versions.** A pending replacement occupies the slot of the
file it will replace rather than taking a new one, which it signals with
``replaces_file_id``. Without that, replacing a file on a Community plan
would be impossible — the one permitted slot would already be full — and
on any plan the allowance would shrink every time a creator corrected a
typo.

**The larger of the two, while a replacement is in flight.** A slot under
replacement is charged ``max(old, new)``, not the sum. The sum would
permanently charge a creator for both versions, which the approved rules
forbid; charging only the new one would let a 10 MB file be "replaced" by
a 10 MB file inside a bundle already at its ceiling and then have the
replacement fail, leaving the Offering over its limit. ``max`` is exactly
the steady state once the replacement resolves, in either direction.

**Approved and in-flight files only.** ``passed``, ``pending`` and
``error`` consume the allowance; ``rejected`` and ``quarantined`` do not.
A creator must not have their allowance eaten by an upload the platform
refused, nor by a file the platform itself withdrew — in both cases the
file is not something a purchaser can download, and in neither case was
the outcome the creator's choice. ``error`` counts because it is
retryable: it is still in flight, and its bytes are still in R2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.offering import (
    Offering,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
)
from app.models.platform import Space
from app.models.user import User
from app.services.offering_files import (
    MAX_OFFERING_BUNDLE_BYTES,
    MAX_OFFERING_FILE_BYTES,
    MAX_OFFERING_FILE_COUNT,
    OfferingFileRejected,
    OfferingLimits,
    validate_offering_upload,
)

logger = logging.getLogger(__name__)


#: Validation states that consume the allowance. See the module
#: docstring — this tuple is the approved "current approved files and
#: their pending replacements" rule, written once.
CONSUMING_STATUSES: tuple[str, ...] = (
    FVS.passed.value,
    FVS.pending.value,
    FVS.error.value,
)


# ---------------------------------------------------------------------------
# Resolving a plan
# ---------------------------------------------------------------------------


def resolve_offering_limits(owner: User | None, db: Session) -> OfferingLimits:
    """The allowance that applies to ``owner``'s Offerings.

    ``owner`` is the **Collective's owner**, not necessarily the caller.
    Offering management is owner-only in Phase 1, so the two coincide
    today; resolving the owner anyway matches
    ``guard_member_allowance`` and ``offering_readiness.evaluate``, and
    means the answer does not change if a delegated role is ever added.

    Every number is ``min(plan, platform ceiling)``. Two consequences,
    both intended:

      * A plan that asserts no cap (Founding Creator, Organisation)
        lands on the platform ceiling rather than on no limit. A
        founder's 500 MB upload would hit the same 512 MB instance as
        anyone else's.
      * A Platform Owner — who has no creator plan at all — also lands
        on the ceiling. There is deliberately **no bypass here**, unlike
        ``guard_offering_limit`` where a bypass is harmless because the
        cost of an extra row is a row. The cost of an unbounded upload
        is the API process.
    """
    # Local import: ``plan_guards`` imports model modules that import
    # this one's siblings, and the cycle is real at module scope.
    from app.creator.plan_guards import resolve_creator_plan

    plan = resolve_creator_plan(owner, db) if owner is not None else None

    if plan is None:
        # No plan resolved — a Platform Owner, an orphaned Collective, or
        # an unrecognised slug. The ceiling, never "unlimited".
        return OfferingLimits(
            max_files=MAX_OFFERING_FILE_COUNT,
            max_file_bytes=MAX_OFFERING_FILE_BYTES,
            max_bundle_bytes=MAX_OFFERING_BUNDLE_BYTES,
            zip_bundles_allowed=True,
            plan_name="current",
        )

    def capped(plan_value: int | None, ceiling: int) -> int:
        return ceiling if plan_value is None else min(plan_value, ceiling)

    return OfferingLimits(
        max_files=capped(plan.offering_files_max, MAX_OFFERING_FILE_COUNT),
        max_file_bytes=capped(
            plan.offering_file_max_bytes, MAX_OFFERING_FILE_BYTES,
        ),
        max_bundle_bytes=capped(
            plan.offering_bundle_max_bytes, MAX_OFFERING_BUNDLE_BYTES,
        ),
        zip_bundles_allowed=plan.offering_zip_bundles_enabled,
        plan_name=plan.display_name,
    )


def limits_for_space(space: Space, db: Session) -> OfferingLimits:
    """The allowance for an Offering in ``space``, via its owner."""
    owner = (
        db.query(User).filter(User.id == space.creator_id).first()
        if space.creator_id
        else None
    )
    return resolve_offering_limits(owner, db)


# ---------------------------------------------------------------------------
# Measuring an Offering
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BundleUsage:
    """What one Offering's current bundle already consumes."""

    #: Downloadable resources, ZIP members counted individually.
    resources: int
    #: Bytes, with a slot under replacement charged at ``max(old, new)``.
    bytes_used: int
    #: Rows in the current bundle, for display. Not the limit's unit.
    rows: int

    def over(self, limits: OfferingLimits) -> bool:
        return (
            self.resources > limits.max_files
            or self.bytes_used > limits.max_bundle_bytes
        )


def bundle_usage(
    db: Session, *, offering: Offering, excluding_file_id: str | None = None,
) -> BundleUsage:
    """Measure the current bundle under the approved counting rules.

    ``excluding_file_id`` leaves one row out, which is what makes the
    *replacement* check work: the endpoint measures the bundle without
    the slot being replaced, then validates the incoming file against
    that remainder plus its own size.

    One query, aggregated in Python. The row count is bounded by the file
    limit (50), so this is cheaper and far clearer than expressing
    "charge each slot the larger of its two versions" in SQL.
    """
    rows = (
        db.query(
            OfferingFile.id,
            OfferingFile.byte_size,
            OfferingFile.resource_count,
            OfferingFile.validation_status,
            OfferingFile.replaces_file_id,
        )
        .filter(
            OfferingFile.offering_id == offering.id,
            OfferingFile.superseded_at.is_(None),
            OfferingFile.validation_status.in_(CONSUMING_STATUSES),
        )
        .all()
    )

    # Slots keyed by the id of the row that holds them. A pending
    # replacement folds into its target's slot instead of adding one.
    slots: dict[str, tuple[int, int]] = {}   # id -> (bytes, resources)
    pending: list[tuple[str, int, int]] = []  # (target_id, bytes, resources)

    for row_id, size, resources, _status, replaces in rows:
        if row_id == excluding_file_id:
            continue
        size = int(size or 0)
        resources = max(1, int(resources or 1))
        if replaces:
            pending.append((replaces, size, resources))
        else:
            slots[row_id] = (size, resources)

    for target_id, size, resources in pending:
        if target_id in slots:
            # Charge the larger of the two versions — see the docstring.
            held_bytes, held_resources = slots[target_id]
            slots[target_id] = (
                max(held_bytes, size), max(held_resources, resources),
            )
        else:
            # The target is gone (removed, superseded, or excluded by the
            # caller), so this replacement stands on its own and takes a
            # slot of its own. Not charging it here would let a bundle
            # exceed its limit via a replacement whose target was then
            # deleted.
            slots[f"orphan:{target_id}:{len(slots)}"] = (size, resources)

    return BundleUsage(
        resources=sum(r for _b, r in slots.values()),
        bytes_used=sum(b for b, _r in slots.values()),
        rows=len(slots),
    )


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def guard_upload(
    db: Session,
    *,
    offering: Offering,
    limits: OfferingLimits,
    filename: str,
    content_type: str | None,
    byte_size: int,
    resource_count: int = 1,
    replacing_file_id: str | None = None,
) -> None:
    """Refuse an upload that would breach the plan, or the file rules.

    The single entry point every upload path calls. It composes the two
    halves rather than re-deriving either: the pure file rules from
    ``offering_files.validate_offering_upload``, and the live bundle
    measurement from :func:`bundle_usage`.

    ``replacing_file_id`` excludes the slot being replaced from the
    measurement, so a replacement is judged against what the bundle would
    look like afterwards.

    Raises ``HTTPException(422)`` with the creator-facing message and the
    machine-readable reason, so a caller needs no translation layer.
    """
    usage = bundle_usage(db, offering=offering, excluding_file_id=replacing_file_id)
    try:
        validate_offering_upload(
            filename=filename,
            content_type=content_type,
            byte_size=byte_size,
            limits=limits,
            existing_bundle_bytes=usage.bytes_used,
            existing_bundle_count=usage.resources,
            resource_count=resource_count,
        )
    except OfferingFileRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"reason": exc.reason, "message": exc.message},
        ) from exc


__all__ = [
    "CONSUMING_STATUSES",
    "BundleUsage",
    "resolve_offering_limits",
    "limits_for_space",
    "bundle_usage",
    "guard_upload",
]
