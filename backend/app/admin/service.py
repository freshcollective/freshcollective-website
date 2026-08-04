from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.creator_billing import CreatorPlanGrant, CreatorSubscription
from app.models.user import User
from app.services.creator_eligibility import apply_creator_eligibility_change


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.created_at.desc()).all()


def set_user_role(db: Session, user_id: str, role: str) -> User | None:
    """Admin-only role mutation. Deliberately refuses ``creator`` — the
    Creator role is set via plan activation (`promote_to_creator`), not
    by ad-hoc admin UI action."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    if role not in ("user", "admin"):
        raise ValueError("Invalid role.")
    user.role = role
    # Reconcile any auto-role memberships (e.g. World Builders) — the
    # user may have just transitioned OUT of Creator, in which case
    # their auto_role membership must be removed.
    apply_creator_eligibility_change(user, db)
    db.commit()
    db.refresh(user)
    return user


def record_grant_event(
    db: Session,
    *,
    subscription: CreatorSubscription,
    action: str,
    reason: str | None,
    note: str | None,
    actor_user_id: str | None,
) -> None:
    """Append a row to the creator_plan_grants history table.

    Extracted from ``admin/routes.py`` so any activation path
    (Stripe-driven, admin grant, future promotional access) records
    grants through the same primitive.
    """
    db.add(CreatorPlanGrant(
        id=str(uuid4()),
        subscription_id=subscription.id,
        action=action,
        creator_plan_id=subscription.creator_plan_id,
        starts_at=subscription.starts_at,
        ends_at=subscription.ends_at,
        reason=reason,
        note=note,
        actor_user_id=actor_user_id,
    ))


def promote_to_creator(user: User, db: Session) -> User:
    """Set ``user.role='creator'`` (idempotent) and reconcile
    eligibility-driven memberships (World Builders).

    Callable from any context (webhook, admin route, migration). Does
    not commit — the caller owns the transaction. The reconciler is
    itself idempotent per its docstring, so this function is safe to
    call multiple times in the same request.

    Deliberately separate from :func:`set_user_role`, which is the
    admin-UI mutation and refuses ``creator`` as a value: promoting a
    user to Creator is not an admin action, it is the effect of a
    successful plan activation.
    """
    if user.role != "creator":
        user.role = "creator"
    apply_creator_eligibility_change(user, db)
    return user
