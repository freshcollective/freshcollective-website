"""Ways to Connect participation is opt-in.

A member is not surfaced to other people because of a shared Gathering
until they have said yes. The feature launched the other way round
(migration 138 defaulted the column ``true``), so these tests pin the
new default where it actually has to hold — the real signup path and
the database column — rather than through ``make_user``, which opts in
on purpose so the rest of the suite can be about Recognition instead of
consent.

Run with:

    cd backend
    .venv/bin/python -m pytest tests/test_ways_to_connect_opt_in_default.py
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import app.models.community_care  # noqa: F401
from app.auth.service import create_user
from app.models.user import User


class TestTheDefaultIsOff:
    def test_the_real_signup_path_opts_a_new_member_out(self, db):
        """``create_user`` is the only place a User row is born. If this
        regresses, every new account is published to strangers."""
        user = create_user(
            db,
            name="New Member",
            email=f"new-{uuid.uuid4().hex[:8]}@example.test",
            password="hunter2hunter2",
        )
        assert user.ways_to_connect_enabled is False

    def test_the_model_default_is_off(self, db):
        """A row built without the column named — the path any future
        creation site would take."""
        user = User(
            id=f"u_{uuid.uuid4().hex[:12]}",
            email=f"model-{uuid.uuid4().hex[:8]}@example.test",
            name="Model Default",
            role="user",
            password_hash="$2b$12$" + "0" * 53,
        )
        db.add(user)
        db.flush()
        assert user.ways_to_connect_enabled is False

    def test_the_database_column_default_is_off(self, db):
        """Not just the application default. An INSERT that bypasses
        SQLAlchemy — a migration, a script, psql — must land opted out
        too, which is the whole reason migration 150 exists.
        """
        row = db.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'users' "
            "AND column_name = 'ways_to_connect_enabled'"
        )).scalar()
        assert row is not None
        assert "false" in row.lower(), row

    def test_a_raw_insert_lands_opted_out(self, db):
        uid = f"u_{uuid.uuid4().hex[:12]}"
        db.execute(text(
            "INSERT INTO users (id, email, name, role, password_hash, "
            "email_verified_at, created_at, updated_at) "
            "VALUES (:id, :email, 'Raw', 'user', 'x', now(), now(), now())"
        ), {"id": uid, "email": f"raw-{uuid.uuid4().hex[:8]}@example.test"})
        db.flush()
        value = db.execute(text(
            "SELECT ways_to_connect_enabled FROM users WHERE id = :id"
        ), {"id": uid}).scalar()
        assert value is False

    def test_the_model_and_the_migration_agree(self, db):
        """The database default comes from migration 150, so a model
        whose ``server_default`` drifted back to ``true`` would change
        nothing today and everything on the next ``create_all`` — a
        fresh database, or a test harness that builds the schema from
        the models rather than the migration chain.

        Asserted against the declared default on the column rather than
        the live catalogue, which the migration already covers above.
        """
        from sqlalchemy import inspect as sa_inspect

        col = sa_inspect(User).columns["ways_to_connect_enabled"]
        declared = str(col.server_default.arg) if col.server_default else None
        assert declared is not None, "the model declares no server default"
        assert "false" in declared.lower(), declared
        assert col.default is not None and col.default.arg is False

    def test_the_column_is_still_not_nullable(self, db):
        """There is no "hasn't decided" third state. Under opt-in,
        silence *is* false, and a nullable column would invite a caller
        to forget the coalesce and read NULL as participating."""
        nullable = db.execute(text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'users' "
            "AND column_name = 'ways_to_connect_enabled'"
        )).scalar()
        assert nullable == "NO"


class TestNothingAutoEnables:
    """Signup, onboarding, joining a Collective, booking a Gathering and
    enrolling in a Pathway must none of them flip the switch. Consent to
    one thing is not consent to another."""

    def test_only_the_profile_patch_writes_the_field(self):
        """A source sweep, because the risk is a *future* caller rather
        than a present one: the field is a plain boolean column and
        nothing stops an unrelated flow setting it as a convenience."""
        import re
        from pathlib import Path

        app_root = Path(__file__).resolve().parent.parent / "app"
        offenders = []
        for path in app_root.rglob("*.py"):
            code = re.sub(r"#.*", "", path.read_text())
            for match in re.finditer(
                r"ways_to_connect_enabled\s*=\s*(\w+)", code,
            ):
                rel = str(path.relative_to(app_root))
                # The model's own default, and the profile PATCH reading
                # from its payload, are the two legitimate writers.
                if rel == "models/user.py":
                    continue
                if rel == "auth/routes.py" and match.group(1) in {
                    "payload", "user",
                }:
                    continue
                offenders.append(f"{rel}: {match.group(0)}")
        assert not offenders, (
            "something other than the member's own profile update writes "
            f"participation: {offenders}"
        )

    def test_signup_does_not_opt_the_member_in(self, db):
        user = create_user(
            db,
            name="Signup",
            email=f"signup-{uuid.uuid4().hex[:8]}@example.test",
            password="hunter2hunter2",
        )
        db.refresh(user)
        assert user.ways_to_connect_enabled is False

    def test_joining_a_collective_does_not_opt_the_member_in(
        self, db, make_space,
    ):
        from datetime import datetime

        from app.models.platform import (
            SpaceMembership, SpaceMembershipStatus, SpaceRole,
        )

        user = create_user(
            db,
            name="Joiner",
            email=f"joiner-{uuid.uuid4().hex[:8]}@example.test",
            password="hunter2hunter2",
        )
        space = make_space()
        db.add(SpaceMembership(
            id=f"sm_{uuid.uuid4().hex[:12]}",
            user_id=user.id,
            space_id=space.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()
        db.refresh(user)
        assert user.ways_to_connect_enabled is False


class TestOptingInAndOut:
    """The canonical write path, and that it is reversible."""

    @pytest.fixture
    def client(self, db):
        from fastapi.testclient import TestClient

        from app.core.database import get_db
        from app.main import app

        app.dependency_overrides[get_db] = lambda: db
        yield TestClient(app)
        app.dependency_overrides.clear()

    def _as(self, user):
        from app.auth.dependencies import get_current_user
        from app.main import app

        app.dependency_overrides[get_current_user] = lambda: user

    def test_the_profile_patch_turns_it_on(self, client, db, make_user):
        user = make_user(ways_to_connect_enabled=False)
        self._as(user)

        res = client.patch(
            "/api/auth/me", json={"ways_to_connect_enabled": True},
        )

        assert res.status_code == 200
        assert res.json()["ways_to_connect_enabled"] is True
        db.refresh(user)
        assert user.ways_to_connect_enabled is True

    def test_it_turns_off_again(self, client, db, make_user):
        """Applied on "is not None" rather than truthiness — a falsy
        check would silently ignore the only value that matters here."""
        user = make_user(ways_to_connect_enabled=True)
        self._as(user)

        res = client.patch(
            "/api/auth/me", json={"ways_to_connect_enabled": False},
        )

        assert res.status_code == 200
        assert res.json()["ways_to_connect_enabled"] is False
        db.refresh(user)
        assert user.ways_to_connect_enabled is False

    def test_omitting_the_field_leaves_it_alone(self, client, db, make_user):
        """Saving a bio must not reset participation."""
        user = make_user(ways_to_connect_enabled=True)
        self._as(user)

        res = client.patch("/api/auth/me", json={"name": "Renamed"})

        assert res.status_code == 200
        db.refresh(user)
        assert user.ways_to_connect_enabled is True

    def test_a_member_cannot_set_it_for_somebody_else(
        self, client, db, make_user,
    ):
        """The endpoint writes ``current_user`` and takes no user id, so
        there is no request shape that expresses it — asserted rather
        than assumed, because that is the only thing protecting it."""
        import inspect

        from app.auth import routes

        sig = inspect.signature(routes.update_me)
        assert "user_id" not in sig.parameters

        other = make_user(ways_to_connect_enabled=False)
        actor = make_user(ways_to_connect_enabled=False)
        self._as(actor)
        client.patch("/api/auth/me", json={"ways_to_connect_enabled": True})
        db.refresh(other)
        assert other.ways_to_connect_enabled is False
