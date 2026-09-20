"""The member-directory setting, and the guidance columns beside it.

``show_member_directory`` decides whether the people in a Collective
can see each other. It has existed since migration 027 with no way to
change it; this is the first time a creator can. The tests that matter
most here are the ones that prove the *reach* of the switch — it is not
a layout preference, and four separate surfaces read it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user, get_verified_creator_user
from app.core.database import get_db
from app.main import app
from app.spaces.home_config import resolve


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_creator_user] = lambda: user


class TestReadingTheSetting:
    def test_the_creator_can_see_the_current_value(self, client, db, make_space, make_user):
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner, show_member_directory=True)
        db.flush()
        as_user(owner)
        res = client.get(f"/api/creator/spaces/{space.slug}")
        assert res.status_code == 200, res.text
        assert res.json()["show_member_directory"] is True

    def test_a_collective_that_has_never_been_configured_reads_closed(
        self, client, db, make_space, make_user,
    ):
        """The column default, surfaced rather than guessed at — every
        existing Collective is sitting on it."""
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner)
        db.flush()
        as_user(owner)
        assert client.get(f"/api/creator/spaces/{space.slug}").json()[
            "show_member_directory"] is False


class TestChangingIt:
    def test_the_owner_can_open_and_close_it(self, client, db, make_space, make_user):
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner)
        db.flush()
        as_user(owner)
        url = f"/api/creator/spaces/{space.slug}"

        assert client.patch(url, json={"show_member_directory": True}).status_code == 200
        db.refresh(space)
        assert space.show_member_directory is True

        assert client.patch(url, json={"show_member_directory": False}).status_code == 200
        db.refresh(space)
        assert space.show_member_directory is False

    def test_omitting_the_field_leaves_it_alone(self, client, db, make_space, make_user):
        """Every other form on this endpoint sends a partial body; none
        of them may switch a privacy setting as a side effect."""
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner, show_member_directory=True)
        db.flush()
        as_user(owner)
        res = client.patch(f"/api/creator/spaces/{space.slug}", json={"tagline": "New words"})
        assert res.status_code == 200, res.text
        db.refresh(space)
        assert space.show_member_directory is True

    def test_an_auto_managed_collective_may_still_choose(
        self, client, db, make_space, make_user,
    ):
        """World Builders is frozen on access and pricing because Fresh
        Collective owns those. Whether its members can see each other is
        a member-experience decision, and stays with the creator."""
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner, auto_grant_role="creator")
        db.flush()
        as_user(owner)
        res = client.patch(
            f"/api/creator/spaces/{space.slug}", json={"show_member_directory": True},
        )
        assert res.status_code == 200, res.text
        db.refresh(space)
        assert space.show_member_directory is True


class TestPermissions:
    def test_a_signed_out_caller_cannot_change_it(self, client, db, make_space):
        space = make_space(is_public=True)
        db.flush()
        res = client.patch(
            f"/api/creator/spaces/{space.slug}", json={"show_member_directory": True},
        )
        assert res.status_code in (401, 403), res.text
        db.refresh(space)
        assert space.show_member_directory is False

    def test_an_ordinary_member_cannot_change_it(
        self, client, db, make_space, make_user,
    ):
        import uuid as _uuid
        from app.models.platform import SpaceMembership

        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner)
        member = make_user(role="user")
        db.add(SpaceMembership(
            id=str(_uuid.uuid4()), user_id=member.id, space_id=space.id,
            role="learner", status="active",
        ))
        db.flush()
        as_user(member)
        res = client.patch(
            f"/api/creator/spaces/{space.slug}", json={"show_member_directory": True},
        )
        assert res.status_code in (401, 403, 404), res.text
        db.refresh(space)
        assert space.show_member_directory is False

    def test_a_creator_of_another_collective_cannot_change_this_one(
        self, client, db, make_space, make_user,
    ):
        space = make_space(is_public=True)
        outsider = make_user(role="creator")
        db.flush()
        as_user(outsider)
        res = client.patch(
            f"/api/creator/spaces/{space.slug}", json={"show_member_directory": True},
        )
        assert res.status_code in (403, 404), res.text
        db.refresh(space)
        assert space.show_member_directory is False


class TestWhatTheSwitchReaches:
    def test_open_offers_the_members_tile(self):
        keys = [t["key"] for t in resolve(None, show_member_directory=True)]
        assert "members" in keys

    def test_closed_removes_it(self):
        keys = [t["key"] for t in resolve(None, show_member_directory=False)]
        assert "members" not in keys

    def test_home_configuration_cannot_force_it_back(self):
        stored = {"tiles": [{"key": "members", "visible": True}, {"key": "about"}]}
        keys = [t["key"] for t in resolve(stored, show_member_directory=False)]
        assert "members" not in keys

    def test_the_tile_list_the_editor_offers_follows_the_same_rule(
        self, client, db, make_space, make_user,
    ):
        """The editor asks the server which tiles it may offer, so the
        rule lives in one place rather than being re-implemented in the
        browser."""
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner)
        db.flush()
        as_user(owner)
        url = f"/api/creator/spaces/{space.slug}"

        closed = client.get(f"{url}/home-config").json()["available_keys"]
        assert "members" not in closed

        client.patch(url, json={"show_member_directory": True})
        opened = client.get(f"{url}/home-config").json()["available_keys"]
        assert "members" in opened

    def test_recognition_still_excludes_closed_collectives(self):
        """Not a behaviour change — a guard. Recognition treats a closed
        directory as "do not surface this co-membership", and giving
        creators a switch must not quietly widen that."""
        from pathlib import Path
        src = Path("app/services/recognition_service.py").read_text()
        assert src.count("Space.show_member_directory.is_(True)") == 2


class TestGuidanceColumnsSurvive:
    def test_saving_the_sidebar_fields_does_not_disturb_the_retired_ones(
        self, client, db, make_space, make_user,
    ):
        """The "This week" editor is gone but its column is not. A save
        from the form that replaced it must leave the stored text — and
        the three retired title columns — exactly as they were."""
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner)
        space.guidance_focus_body = '{"type":"doc","content":[{"type":"text","text":"kept"}]}'
        space.guidance_focus_title = "Term focus"
        space.guidance_start_title = "Welcome to EMBODY"
        space.guidance_links_title = "Helpful links"
        db.flush()
        as_user(owner)

        # Exactly the body the Sidebar guidance form now sends.
        res = client.patch(f"/api/creator/spaces/{space.slug}", json={
            "guidance_start_body": '{"type":"doc","content":[{"type":"text","text":"hello"}]}',
            "guidance_links_body": None,
        })
        assert res.status_code == 200, res.text

        db.refresh(space)
        assert space.guidance_focus_body == \
            '{"type":"doc","content":[{"type":"text","text":"kept"}]}'
        assert space.guidance_focus_title == "Term focus"
        assert space.guidance_start_title == "Welcome to EMBODY"
        assert space.guidance_links_title == "Helpful links"
        assert "hello" in (space.guidance_start_body or "")

    def test_the_column_is_still_there(self, db):
        from sqlalchemy import inspect
        columns = {c["name"] for c in inspect(db.bind).get_columns("spaces")}
        for retired in (
            "guidance_focus_body", "guidance_focus_title",
            "guidance_start_title", "guidance_links_title",
        ):
            assert retired in columns, f"{retired} was dropped"
