"""Creator eligibility + auto-role space membership reconciliation.

A user is an *eligible Creator* when all three conditions hold:

  * ``users.role == 'creator'``
  * ``users.creator_suspended_at IS NULL``
  * ``users.creator_cancelled_at IS NULL``

The predicate is used everywhere the auto-grant rule for
Fresh-Collective-managed collectives (currently: World Builders) needs
to decide whether a user should have automatic membership. Suspension
pauses membership; cancellation or role change removes it; restoration
re-activates the existing row rather than inserting a duplicate.

The auto-grant rule is expressed *structurally*, not by collective
slug: any ``Space`` with ``auto_grant_role IS NOT NULL`` gets an
auto-role membership for every user holding that role and passing the
eligibility predicate. Nothing in this module references the World
Builders slug — it discovers spaces by the flag.

Only memberships with ``source='auto_role'`` are ever touched by this
module. Explicit joins, invitations, purchases, and owner memberships
are never swept.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.platform import (
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


# The one canonical marker on ``space_memberships.source`` for
# memberships this module manages. Any other source (joined, invited,
# purchase, creator_owner, or legacy NULL) is off-limits.
AUTO_ROLE_SOURCE = "auto_role"


def is_eligible_creator(user: User) -> bool:
    """True when the user is an active, non-suspended, non-cancelled Creator.

    The single source of truth for "should this user have auto-Creator
    access?". All grant / pause / reactivate / revoke decisions read
    this — never a partial subset of the fields.
    """
    return (
        user.role == UserRole.creator.value
        and user.creator_suspended_at is None
        and user.creator_cancelled_at is None
    )


def apply_creator_eligibility_change(user: User, db: Session) -> None:
    """Reconcile every auto-role membership for ``user`` against their
    current eligibility. Called from role-change, suspension-change,
    and cancellation-change flows. Idempotent — safe to call at any
    time; if state already matches, no writes happen.

    Behaviour per auto-grant space (currently only World Builders):

      * eligible + no membership          → INSERT active auto_role row
      * eligible + status=paused          → UPDATE → active
      * eligible + status=removed         → UPDATE → active (reactivate row)
      * eligible + status=active          → no-op
      * suspended + status=active         → UPDATE → paused
      * suspended + status=paused         → no-op
      * cancelled or role changed + any   → UPDATE → removed
      * cancelled + status=removed        → no-op

    Only rows with ``source='auto_role'`` are touched. Explicitly-joined
    or invited memberships are always preserved as they are.
    """
    eligible = is_eligible_creator(user)
    now = datetime.utcnow()

    # ``UserRole.creator.value`` is stored on the space's
    # ``auto_grant_role`` column when the space wants "any user whose
    # role is Creator gets automatic access." A future space could set
    # a different role (e.g. admin); the query below finds any space
    # whose auto-grant role matches the user's current role, plus any
    # space where the user has an existing auto_role membership that
    # may need to be reconciled (e.g. cleared because they no longer
    # match the space's auto_grant_role).
    #
    # For the user's *current* role, we might want to GRANT.
    # For other roles' spaces where they still hold an auto_role
    # membership, we need to REMOVE.
    role_specific_spaces = (
        db.query(Space)
        .filter(Space.auto_grant_role == user.role)
        .all()
    )
    stale_auto_role_memberships = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.source == AUTO_ROLE_SOURCE,
        )
        .all()
    )

    # First: reconcile the spaces the user *should* have access to.
    for space in role_specific_spaces:
        existing = _find_auto_role_membership(user.id, space.id, db)
        if eligible:
            if existing is None:
                db.add(
                    SpaceMembership(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        space_id=space.id,
                        role=SpaceRole.learner,
                        status=SpaceMembershipStatus.active,
                        source=AUTO_ROLE_SOURCE,
                        joined_at=now,
                    )
                )
            elif existing.status != SpaceMembershipStatus.active:
                existing.status = SpaceMembershipStatus.active
        else:
            # Not eligible — user is a creator but suspended or cancelled.
            if existing is None:
                continue
            # Suspension → pause; cancellation or role change → remove.
            if user.creator_suspended_at is not None and user.creator_cancelled_at is None:
                if existing.status != SpaceMembershipStatus.paused:
                    existing.status = SpaceMembershipStatus.paused
            else:
                if existing.status != SpaceMembershipStatus.removed:
                    existing.status = SpaceMembershipStatus.removed

    # Second: sweep any auto_role memberships in spaces the user's
    # current role no longer matches (e.g. role changed from creator
    # to admin, so the World Builders membership should be removed).
    role_matched_space_ids = {s.id for s in role_specific_spaces}
    for membership in stale_auto_role_memberships:
        if membership.space_id in role_matched_space_ids:
            continue  # handled above
        # This membership was auto-granted for a role the user no
        # longer holds. Remove it.
        if membership.status != SpaceMembershipStatus.removed:
            membership.status = SpaceMembershipStatus.removed


def reconcile_at_session_time(user: User, db: Session) -> None:
    """Session-time safety net: idempotently reconcile the user's
    auto-role memberships whenever they sign in / a session ping
    resolves. Skips fast when nothing could possibly need fixing.

    Every explicit write flow (admin role change, Community Care
    cancellation) also calls the reconciler directly. This wrapper
    exists to catch the edge cases those flows may have missed —
    e.g. seed data, migrations, or DB manipulation — without
    requiring a scheduled job.

    Cheap short-circuit: if there is no auto-grant space matching
    the user's current role AND no existing auto_role membership
    for the user, there is nothing to do. Otherwise fall through
    to the full reconciler and commit if it made any changes.
    """
    role_match_count = (
        db.query(func.count(Space.id))
        .filter(Space.auto_grant_role == user.role)
        .scalar()
    ) or 0
    stale_count = (
        db.query(func.count(SpaceMembership.id))
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.source == AUTO_ROLE_SOURCE,
        )
        .scalar()
    ) or 0
    if role_match_count == 0 and stale_count == 0:
        return

    try:
        apply_creator_eligibility_change(user, db)
        if db.new or db.dirty:
            db.commit()
    except Exception:  # pragma: no cover — safety net must never break auth
        db.rollback()
        logger.exception(
            "Session-time auto-role reconciliation failed for user=%s", user.id
        )


def _find_auto_role_membership(
    user_id: str, space_id: str, db: Session
) -> SpaceMembership | None:
    """Return the single auto_role membership for (user, space), or
    None. Only ever considers ``source='auto_role'`` — a coexisting
    ``source='joined'`` row is deliberately invisible to the reconciler
    so it is never swept."""
    return (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.space_id == space_id,
            SpaceMembership.source == AUTO_ROLE_SOURCE,
        )
        .first()
    )
