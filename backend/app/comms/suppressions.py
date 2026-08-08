"""Communication suppressions — hard-block list keyed by hashed address.

Brought forward from M6 in Milestone 5a so the routing decision layer
(M5b) can consult it before creating a live intent.

Responsibility split:

  * M5 (this module) — read-side helpers + manual admin write path
    for operator quarantine before webhook automation lands.
  * M6 — inbound provider webhook processors that automatically
    populate/update rows from bounce, complaint, and unsubscribe
    events. Those handlers will call :func:`record_suppression`
    with the appropriate ``source_provider`` and ``reason``.

Design notes
------------

* Addresses are **never stored** — only a SHA-256 hex digest of the
  normalised (lowercased, whitespace-stripped) value. This means the
  suppression list can be queried without becoming a PII inventory of
  everyone who bounced.
* Normalisation is deliberate but conservative: lowercase + strip.
  We do NOT canonicalise (no Gmail dot-stripping etc.) so a
  suppression against ``a.b@gmail.com`` does not also suppress
  ``ab@gmail.com``. The trade-off favours precision over recall.
* Look-ups are keyed on ``(address_type, address_value_hash)``.
* :func:`record_suppression` is idempotent — repeat calls for the
  same (type, hash) update ``last_seen_at`` and ``reason`` rather
  than inserting duplicates.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.comms.models import CommunicationSuppression


ALL_ADDRESS_TYPES = ("email", "phone", "push_token")
ALL_REASONS = ("bounced", "complained", "manual", "unsubscribed")

AddressType = Literal["email", "phone", "push_token"]
SuppressionReason = Literal["bounced", "complained", "manual", "unsubscribed"]


class UnknownAddressTypeError(ValueError):
    """The address_type is not a member of the enum."""


class UnknownReasonError(ValueError):
    """The suppression reason is not a member of the enum."""


def _normalise(address_type: str, address: str) -> str:
    """Normalise an address for hashing. Conservative:

    * Lowercase + strip whitespace for every address type.
    * No canonicalisation beyond that — e.g. Gmail dot-stripping is
      NOT applied. Precision matters more than recall here; we would
      rather send twice to distinct-looking addresses than
      accidentally suppress a valid one.

    ``address_type`` is included for future validation (phone numbers
    may deserve a distinct normalisation strategy; today they get the
    same treatment).
    """
    if address_type not in ALL_ADDRESS_TYPES:
        raise UnknownAddressTypeError(
            f"Unknown address_type: {address_type!r}. "
            f"Expected one of {ALL_ADDRESS_TYPES}."
        )
    return address.strip().lower()


def hash_address(address_type: str, address: str) -> str:
    """Public helper — returns the hex digest used as the lookup key.
    Exposed so tests and admin tooling can compute the same key without
    duplicating the normalisation logic.
    """
    normalised = _normalise(address_type, address)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _new_suppression_id() -> str:
    return f"csu_{uuid.uuid4().hex[:12]}"


def is_address_suppressed(
    db: Session,
    *,
    address_type: AddressType,
    address: str,
) -> CommunicationSuppression | None:
    """Return the current suppression row for an address, or None.

    Callers (the M5b decision layer) treat a non-None return as
    "do not create a live intent for this recipient on this channel";
    the intent moves to ``state='suppressed'`` with the reason
    captured on the intent row.
    """
    digest = hash_address(address_type, address)
    return db.execute(
        select(CommunicationSuppression).where(
            CommunicationSuppression.address_type == address_type,
            CommunicationSuppression.address_value_hash == digest,
        )
    ).scalar_one_or_none()


def record_suppression(
    db: Session,
    *,
    address_type: AddressType,
    address: str,
    reason: SuppressionReason,
    source_provider: str | None = None,
) -> CommunicationSuppression:
    """Insert-or-update the suppression row for an address.

    * If no row exists → INSERT with ``first_seen_at = last_seen_at = NOW()``.
    * If a row exists → UPDATE ``last_seen_at``, ``reason`` (latest
      wins), and ``source_provider`` (if the caller supplied one).
      ``first_seen_at`` is preserved.

    Idempotent by (address_type, address_value_hash). Callers can
    safely re-invoke without duplicate rows.
    """
    if reason not in ALL_REASONS:
        raise UnknownReasonError(
            f"Unknown reason: {reason!r}. Expected one of {ALL_REASONS}."
        )
    digest = hash_address(address_type, address)
    existing = db.execute(
        select(CommunicationSuppression).where(
            CommunicationSuppression.address_type == address_type,
            CommunicationSuppression.address_value_hash == digest,
        )
    ).scalar_one_or_none()

    now = _now_naive()
    if existing is not None:
        existing.last_seen_at = now
        existing.reason = reason
        if source_provider is not None:
            existing.source_provider = source_provider
        db.flush()
        return existing

    row = CommunicationSuppression(
        id=_new_suppression_id(),
        address_type=address_type,
        address_value_hash=digest,
        reason=reason,
        source_provider=source_provider,
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(row)
    db.flush()
    return row


def remove_suppression(
    db: Session,
    *,
    address_type: AddressType,
    address: str,
) -> bool:
    """Delete a suppression row. Returns True if a row was removed,
    False if none matched. Intended for operator use after manual
    review confirms an address should receive again.
    """
    digest = hash_address(address_type, address)
    row = db.execute(
        select(CommunicationSuppression).where(
            CommunicationSuppression.address_type == address_type,
            CommunicationSuppression.address_value_hash == digest,
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
