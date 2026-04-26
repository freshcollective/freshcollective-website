from sqlalchemy.orm import Session

from app.models.user import User


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.created_at.desc()).all()


def set_user_role(db: Session, user_id: str, role: str) -> User | None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    if role not in ("user", "admin"):
        raise ValueError("Invalid role.")
    user.role = role
    db.commit()
    db.refresh(user)
    return user
