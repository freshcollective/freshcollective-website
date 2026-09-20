"""Does this person currently hold access to anything in this
Collective?

A Collective-level question, deliberately distinct from the per-object
predicates beside it. ``compute_series_access`` answers "may they open
*this* Series"; this answers "are they currently inside the paying
relationship at all", which is what an area doorway needs.

Built from the same row state those predicates read, and therefore
from the same idea of what access is:

* an ``AccessPass`` in this Space, ``status='active'``, not past its
  ``valid_until``;
* a ``PathwayEntitlement`` in this Space, ``status='active'``, not past
  its ``ends_at``.

Never from payment history. A transaction, a refund, a plan's state —
none of them are consulted, because none of them are access. That
matters in both directions:

* a **complimentary or manually granted** pass qualifies exactly as a
  purchased one does, since the row shape is identical and only
  ``source`` differs;
* a **suspended** plan does not, because suspension writes
  ``status='suspended'`` on the rows themselves.

``expired``, ``revoked``, ``cancelled`` and ``pending`` all fail for
the same reason: the status column already says so.

No ``valid_from`` filter, matching ``compute_series_access``: someone
who has bought next term holds that access now and should not be shut
out of the doorway until it starts.

Leaders and admins are handled by the caller
(``services.space_viewer``), not here — this function answers about
access, and administering a Collective is not access.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.platform import EntitlementStatus, PathwayEntitlement


def has_active_access(
    db: Session, *, user_id: str, space_id: str, now: datetime | None = None,
) -> bool:
    """One EXISTS over the two access tables.

    Both halves are covered by the composite
    ``(user_id, space_id, status)`` indexes added in migration 137, so
    this is an index lookup rather than a scan. Call it once per
    request — ``resolve_area_access`` does, and only when a Collective
    actually uses the ``active_access`` policy.
    """
    moment = now or datetime.utcnow()

    pass_exists = (
        select(AccessPass.id)
        .where(
            AccessPass.user_id == user_id,
            AccessPass.space_id == space_id,
            AccessPass.status == AccessPassStatus.active,
            or_(
                AccessPass.valid_until.is_(None),
                AccessPass.valid_until > moment,
            ),
        )
        .limit(1)
    )
    if db.execute(pass_exists).first() is not None:
        return True

    entitlement_exists = (
        select(PathwayEntitlement.id)
        .where(
            PathwayEntitlement.user_id == user_id,
            PathwayEntitlement.space_id == space_id,
            PathwayEntitlement.status == EntitlementStatus.active,
            or_(
                PathwayEntitlement.ends_at.is_(None),
                PathwayEntitlement.ends_at > moment,
            ),
        )
        .limit(1)
    )
    return db.execute(entitlement_exists).first() is not None
