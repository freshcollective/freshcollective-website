"""The member's own switch for Ways to Connect.

``users.ways_to_connect_enabled`` — "Include me in Ways to Connect".
Recognition is derived, never stored, so this setting is the only
thing a member can say about it. The tests here cover the column and
the settings endpoint that exposes it; the *effect* of switching it
off lives in ``test_recognition_service.py``, where the derivation is.

The endpoint is the existing ``/api/auth/me`` pair rather than a new
one. That is load-bearing for privacy: both routes read
``current_user`` from the auth dependency and take no user id of any
kind, so there is no shape of request that updates somebody else.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.user import User


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user


# ---------------------------------------------------------------------------
# Column / model
# ---------------------------------------------------------------------------

class TestTheColumn:
    def test_a_new_member_is_excluded_by_default(self, db):
        """Silence means no.

        The reverse of what this file asserted at launch. Participation
        is affirmative now: nobody is surfaced to other people on the
        strength of a shared Gathering until they have said yes.

        Built from the model directly, not from ``make_user`` — that
        factory opts in deliberately so the rest of the suite can be
        about Recognition rather than consent, which would make this
        assertion a test of the fixture instead of the product. The
        signup path and the database column are covered in
        ``test_ways_to_connect_opt_in_default.py``.
        """
        import uuid as _uuid

        alice = User(
            id=f"u_{_uuid.uuid4().hex[:12]}",
            email=f"default-{_uuid.uuid4().hex[:8]}@example.test",
            name="Default Member",
            role="user",
            password_hash="$2b$12$" + "0" * 53,
        )
        db.add(alice)
        db.flush()
        assert alice.ways_to_connect_enabled is False

    def test_the_orm_default_matches_the_database_default(self, db):
        """Inserted without the column named, the DB server default
        supplies it — so a row created outside the ORM agrees with one
        created through it."""
        import uuid as _uuid

        alice = User(
            id=f"u_{_uuid.uuid4().hex[:12]}",
            email=f"orm-{_uuid.uuid4().hex[:8]}@example.test",
            name="ORM Default",
            role="user",
            password_hash="$2b$12$" + "0" * 53,
        )
        db.add(alice)
        db.flush()
        db.expire(alice)
        assert alice.ways_to_connect_enabled is False

    def test_it_is_not_nullable(self, db, make_user):
        from sqlalchemy import inspect as sa_inspect

        col = sa_inspect(User).columns["ways_to_connect_enabled"]
        assert col.nullable is False

    def test_explicit_false_persists(self, db, make_user):
        alice = make_user(ways_to_connect_enabled=False)
        db.flush()
        db.expire(alice)
        assert alice.ways_to_connect_enabled is False

    def test_it_can_be_switched_back_on(self, db, make_user):
        alice = make_user(ways_to_connect_enabled=False)
        alice.ways_to_connect_enabled = True
        db.flush()
        db.expire(alice)
        assert alice.ways_to_connect_enabled is True


# ---------------------------------------------------------------------------
# Reading it
# ---------------------------------------------------------------------------

class TestReadingTheSetting:
    def test_get_me_reports_the_current_value(self, client, db, make_user):
        alice = make_user()
        as_user(alice)

        body = client.get("/api/auth/me").json()

        assert body["ways_to_connect_enabled"] is True

    def test_get_me_reports_a_switched_off_setting(self, client, db, make_user):
        alice = make_user(ways_to_connect_enabled=False)
        as_user(alice)

        body = client.get("/api/auth/me").json()

        assert body["ways_to_connect_enabled"] is False


# ---------------------------------------------------------------------------
# Changing it
# ---------------------------------------------------------------------------

class TestChangingTheSetting:
    def test_a_member_can_switch_it_off(self, client, db, make_user):
        alice = make_user()
        as_user(alice)

        res = client.patch("/api/auth/me", json={"ways_to_connect_enabled": False})

        assert res.status_code == 200
        assert res.json()["ways_to_connect_enabled"] is False

    def test_switching_it_off_persists(self, client, db, make_user):
        alice = make_user()
        as_user(alice)

        client.patch("/api/auth/me", json={"ways_to_connect_enabled": False})
        db.expire(alice)

        assert alice.ways_to_connect_enabled is False
        assert client.get("/api/auth/me").json()["ways_to_connect_enabled"] is False

    def test_a_member_can_switch_it_back_on(self, client, db, make_user):
        alice = make_user(ways_to_connect_enabled=False)
        as_user(alice)

        res = client.patch("/api/auth/me", json={"ways_to_connect_enabled": True})
        db.expire(alice)

        assert res.json()["ways_to_connect_enabled"] is True
        assert alice.ways_to_connect_enabled is True

    def test_omitting_the_field_leaves_it_alone(self, client, db, make_user):
        """The rest of the profile form must not silently re-enable a
        setting the member turned off."""
        alice = make_user(ways_to_connect_enabled=False)
        as_user(alice)

        res = client.patch("/api/auth/me", json={"name": "Alice Renamed"})
        db.expire(alice)

        assert res.status_code == 200
        assert alice.name == "Alice Renamed"
        assert alice.ways_to_connect_enabled is False

    def test_false_is_a_value_not_an_absence(self, client, db, make_user):
        """Guards the ``is not None`` check in ``update_me``. A
        truthiness test there would make switching off a no-op — the
        one operation this setting exists for."""
        alice = make_user()
        as_user(alice)

        client.patch("/api/auth/me", json={"ways_to_connect_enabled": False})
        db.expire(alice)

        assert alice.ways_to_connect_enabled is False

    def test_a_non_boolean_is_rejected(self, client, db, make_user):
        alice = make_user()
        as_user(alice)

        res = client.patch("/api/auth/me", json={"ways_to_connect_enabled": "maybe"})

        assert res.status_code == 422
        db.expire(alice)
        assert alice.ways_to_connect_enabled is True

    def test_null_is_treated_as_not_supplied(self, client, db, make_user):
        alice = make_user(ways_to_connect_enabled=False)
        as_user(alice)

        res = client.patch("/api/auth/me", json={"ways_to_connect_enabled": None})
        db.expire(alice)

        assert res.status_code == 200
        assert alice.ways_to_connect_enabled is False


# ---------------------------------------------------------------------------
# Whose setting it is
# ---------------------------------------------------------------------------

class TestOnlyYourOwn:
    def test_the_route_takes_no_user_id_at_all(self, client, db, make_user):
        """Structural, not incidental: ``/api/auth/me`` resolves the
        subject from the auth dependency. There is no path, query or
        body parameter that names another member, so 'update someone
        else' has no request shape to express."""
        alice, bob = make_user(), make_user()
        as_user(alice)

        res = client.patch(
            "/api/auth/me",
            json={
                "ways_to_connect_enabled": False,
                # All ignored — none of these name the subject.
                "id": bob.id,
                "user_id": bob.id,
                "email": bob.email,
            },
        )
        db.expire(alice)
        db.expire(bob)

        assert res.status_code == 200
        assert alice.ways_to_connect_enabled is False
        assert bob.ways_to_connect_enabled is True
        assert res.json()["id"] == alice.id

    def test_each_member_reads_their_own_value(self, client, db, make_user):
        alice = make_user(ways_to_connect_enabled=False)
        bob = make_user()

        as_user(alice)
        assert client.get("/api/auth/me").json()["ways_to_connect_enabled"] is False

        as_user(bob)
        assert client.get("/api/auth/me").json()["ways_to_connect_enabled"] is True

    def test_signing_out_is_required(self, client, db):
        """No anonymous read of the setting."""
        app.dependency_overrides.pop(get_current_user, None)
        assert client.get("/api/auth/me").status_code in (401, 403)
