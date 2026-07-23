from sqlalchemy.orm import Session

from app.models.user import User
from app.services.creator_eligibility import apply_creator_eligibility_change


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.created_at.desc()).all()


def set_user_role(db: Session, user_id: str, role: str) -> User | None:
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
