#!/usr/bin/env python3
"""
Dev-only script: create two test member accounts and add them to EMBODY.

Usage:
    cd /home/lindsey/fc-production/backend
    .venv/bin/python ../scripts/create_test_members.py

Idempotent — safe to run multiple times.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from uuid import uuid4
from datetime import datetime

# Import all models so SQLAlchemy relationships resolve correctly
import app.models.platform  # noqa: F401
import app.models.user  # noqa: F401

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.models.platform import Space, SpaceMembership, SpaceRole, SpaceMembershipStatus

SPACE_SLUG = "embody"
DEV_PASSWORD = "testpass123"

TEST_MEMBERS = [
    {"email": "test.member1@freshcollective.test", "name": "Test Member One"},
    {"email": "test.member2@freshcollective.test", "name": "Test Member Two"},
]


def main():
    db = SessionLocal()
    try:
        space = db.query(Space).filter(Space.slug == SPACE_SLUG).first()
        if not space:
            print(f"ERROR: Space with slug '{SPACE_SLUG}' not found.")
            print("Available spaces:")
            for s in db.query(Space).all():
                print(f"  {s.slug!r}  ({s.name})")
            sys.exit(1)

        print(f"Space: {space.name} (id={space.id})\n")

        for spec in TEST_MEMBERS:
            email = spec["email"]
            name = spec["name"]

            # Find or create user
            user = db.query(User).filter(User.email == email).first()
            if user:
                print(f"[found]   {email}  (id={user.id})")
            else:
                now = datetime.utcnow()
                user = User(
                    id=str(uuid4()),
                    email=email,
                    name=name,
                    password_hash=hash_password(DEV_PASSWORD),
                    role="user",
                    onboarding_completed_at=now,
                    created_at=now,
                    updated_at=now,
                )
                db.add(user)
                db.flush()
                print(f"[created] {email}  (id={user.id})")

            # Find or create membership
            membership = (
                db.query(SpaceMembership)
                .filter(
                    SpaceMembership.user_id == user.id,
                    SpaceMembership.space_id == space.id,
                )
                .first()
            )
            if membership:
                if membership.status != SpaceMembershipStatus.active:
                    membership.status = SpaceMembershipStatus.active
                    print(f"          membership re-activated (role={membership.role.value})")
                else:
                    print(f"          membership already active (role={membership.role.value})")
            else:
                membership = SpaceMembership(
                    id=str(uuid4()),
                    user_id=user.id,
                    space_id=space.id,
                    role=SpaceRole.learner,
                    status=SpaceMembershipStatus.active,
                    joined_at=datetime.utcnow(),
                )
                db.add(membership)
                print(f"          membership created (role=learner)")

        db.commit()
        print(f"\nDone. Log in as either user with password: {DEV_PASSWORD!r}")

    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
