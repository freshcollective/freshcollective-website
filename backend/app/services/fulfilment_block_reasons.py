"""Why a fulfilment was blocked, in words an administrator can act on.

Nine code paths set ``fulfilment_status='blocked'`` and every one of
them now records which of these it was. They divide into two classes
that call for opposite responses, which is the entire reason the column
exists:

``TEMPORARY_*``
    The payment arrangement is fine; the data is not. Fix the cause and
    let Stripe re-deliver — the handlers are idempotent, so the purchase
    fulfils on the retry. **Do not cancel the plan**; that would destroy
    a valid arrangement over a repairable fault.

``INELIGIBLE_*``
    The buyer is no longer eligible for the membership the purchase
    depends on. No replay will fix it. Somebody has to choose between
    readmitting them and cancelling the plan — and that choice is a
    person's, which is why nothing here acts on these values.

Kept as plain strings rather than an enum: they are written to a
``String(200)`` for a human to read, and a new blocking path should be
able to describe itself without a migration. The constants exist so the
nine sites agree on wording, not to constrain the column.
"""

#: The grants snapshot on the transaction will not deserialise.
TEMPORARY_SNAPSHOT_UNREADABLE = "snapshot_unreadable"
#: The plan has no grants snapshot at all (should not happen for
#: FIP2-created plans).
TEMPORARY_SNAPSHOT_MISSING = "snapshot_missing"
#: The intent resolver reported a fatal error — typically a row the
#: Payment Option points at no longer exists.
TEMPORARY_RESOLVER_ERROR = "resolver_error"
#: Pre-write validation failed: something the intent references is
#: missing, so the whole bundle was refused rather than half-applied.
TEMPORARY_VALIDATION_FAILED = "validation_failed"
#: The applier ran and did not report success.
TEMPORARY_APPLY_FAILED = "apply_failed"

#: The buyer cannot be given the membership this purchase depends on —
#: a creator removal with rejoining blocked, an admin revocation, or a
#: removal of unrecorded provenance. Carries the specific reason from
#: ``checkout_orchestration.membership_undeliverable_reason``.
INELIGIBLE_MEMBERSHIP = "membership_ineligible"


def ineligible(reason: str) -> str:
    """``membership_ineligible:rejoin_blocked`` and friends.

    The suffix is what ``membership_undeliverable_reason`` returned, so
    an administrator can tell a lifted-by-the-creator block from an
    admin revocation without opening another page.
    """
    return f"{INELIGIBLE_MEMBERSHIP}:{reason}"


def is_temporary(stored: str | None) -> bool:
    """Whether a replay could plausibly fix this.

    ``None`` (a historical row, reason not recorded) is NOT reported as
    temporary — we do not know, and claiming a replay will fix it would
    be the same guess this column exists to avoid.
    """
    if not stored:
        return False
    return stored.startswith("snapshot_") or stored in (
        TEMPORARY_RESOLVER_ERROR,
        TEMPORARY_VALIDATION_FAILED,
        TEMPORARY_APPLY_FAILED,
    )


def needs_a_decision(stored: str | None) -> bool:
    """Whether somebody has to choose between readmission and
    cancelling the plan. A replay will not help."""
    return bool(stored) and stored.startswith(INELIGIBLE_MEMBERSHIP)


__all__ = [
    "INELIGIBLE_MEMBERSHIP",
    "TEMPORARY_APPLY_FAILED",
    "TEMPORARY_RESOLVER_ERROR",
    "TEMPORARY_SNAPSHOT_MISSING",
    "TEMPORARY_SNAPSHOT_UNREADABLE",
    "TEMPORARY_VALIDATION_FAILED",
    "ineligible",
    "is_temporary",
    "needs_a_decision",
]
