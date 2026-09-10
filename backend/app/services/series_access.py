"""Canonical Series-access rule for Fresh Collective.

Symmetric with ``services.pathway_access.compute_pathway_access`` and
extracted from the historical ``spaces.routes._viewer_has_series_pass``
predicate. Every surface that needs to answer "can this user access
this Gathering Series right now?" — Reserve gating on individual
gatherings, the Series page's Your Access card, the offer-page target
snapshot, Series-scoped Conversation Channels, and the @mention
autocomplete for those Channels — routes through
:func:`compute_series_access`.

Recognised access sources
-------------------------

* platform admin (``User.role == "admin"``);
* Space owner (``Space.creator_id == user.id``);
* active caretaker ``SpaceMembership`` (role in ``creator`` /
  ``moderator``);
* an active, not-yet-expired ``AccessPass`` on this Space whose
  ``eligible_series_id`` matches the target Series. This one path
  covers pay-in-full, finite-payment-plan, and complimentary /
  manual-grant Series access uniformly — the AccessPass shape is
  identical for all three, only the ``payment_option_id`` /
  ``purchase_plan_id`` / ``source`` fields differ.

Explicitly not access sources
-----------------------------

* A confirmed ``EventBooking`` on a single gathering inside the
  Series. Attending one session doesn't buy you the term.
* An expired or cancelled ``AccessPass``. Source-aware revocation
  is automatic — the predicate reads current row state each call.
* ``Enrollment`` (a Pathway progress record) — Series and Pathway
  entitlement graphs don't overlap.

Advance-window semantics
------------------------

Deliberately no ``valid_from`` filter. A member who purchased a
future Series (e.g. Term 4 bought in September, pass ``valid_from``
set to the October start) legitimately holds the pass and should see
its Conversation from the moment the purchase clears. Per-event
window enforcement for booking lives in ``spaces.routes.book_event``
and compares the pass window against ``event.starts_at``.

Extraction rationale
--------------------
Kept in ``app.services`` (peer of ``pathway_access``,
``channel_permissions``, ``event_permissions``) so those modules and
``spaces.routes`` can all import it without creating a cycle.
``spaces.routes`` already imports from ``channel_permissions``; if
``channel_permissions`` needed to import back from ``spaces.routes``
for this predicate, we'd have a loop — this module dissolves that.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.platform import (
    EventSeries,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User


def compute_series_access(
    user: User | None,
    series: EventSeries,
    space: Space,
    db: Session,
    *,
    now: datetime | None = None,
) -> bool:
    """Return True if ``user`` currently has access to ``series``.

    Accepts ``None`` for unauthenticated visitors — series access is
    always gated (there is no free/included Series concept in the
    model today).

    ``now`` is optional; defaults to ``datetime.utcnow()``. Explicit
    injection is useful for tests that need to pin the moment against
    a specific pass window.
    """
    if user is None:
        return False
    if user.role == "admin":
        return True
    if space.creator_id == user.id:
        return True
    caretaker_row = (
        db.query(SpaceMembership.role)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
        )
        .first()
    )
    if caretaker_row:
        return True

    now = now or datetime.utcnow()
    pass_row = (
        db.query(AccessPass.id)
        .filter(
            AccessPass.user_id == user.id,
            AccessPass.space_id == space.id,
            AccessPass.eligible_series_id == series.id,
            AccessPass.status == AccessPassStatus.active,
            or_(
                AccessPass.valid_until.is_(None),
                AccessPass.valid_until > now,
            ),
        )
        .first()
    )
    return pass_row is not None
