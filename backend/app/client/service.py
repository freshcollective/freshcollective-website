from sqlalchemy.orm import Session

from app.models.user import User


def get_member_profile(user: User) -> User:
    return user
