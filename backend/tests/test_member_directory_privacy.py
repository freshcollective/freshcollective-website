"""Who may read a Collective's membership list.

The bug these pin down: the endpoint applied directory privacy only
when ``caller_role == "learner"``. An anonymous caller has no role, so
the branch never ran and any public Collective's full membership —
learner rows included, directory switched off or not — was readable
without signing in.

The rule now: the directory is member-only, and inside it the existing
learner/leader privacy is unchanged.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user, get_optional_user
from app.core.database import get_db
from app.main import app
from app.models.platform import SpaceMembership


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user


def as_anonymous():
    app.dependency_overrides[get_optional_user] = lambda: None


def join(db, user, space, role="learner"):
    db.add(SpaceMembership(
        id=str(uuid.uuid4()), user_id=user.id, space_id=space.id,
        role=role, status="active",
    ))
    db.flush()


@pytest.fixture
def collective(db, make_space, make_user):
    """A public Collective with a leader and two learners."""
    owner = make_user(role="creator")
    space = make_space(is_public=True, creator=owner, show_member_directory=True)
    join(db, owner, space, role="creator")
    learners = [make_user(role="user") for _ in range(2)]
    for learner in learners:
        join(db, learner, space)
    db.flush()
    return {"space": space, "owner": owner, "learners": learners}


def names(res):
    return [m["display_name"] for m in res.json()]


class TestOutsidersGetNothing:
    def test_a_signed_out_visitor_is_refused(self, client, collective):
        """The reported bug, stated as a test."""
        as_anonymous()
        res = client.get(f"/api/spaces/{collective['space'].slug}/members")
        assert res.status_code == 404, res.text
        assert "display_name" not in res.text

    def test_a_signed_out_visitor_is_refused_with_the_directory_closed_too(
        self, client, db, collective,
    ):
        collective["space"].show_member_directory = False
        db.flush()
        as_anonymous()
        res = client.get(f"/api/spaces/{collective['space'].slug}/members")
        assert res.status_code == 404, res.text

    def test_a_signed_in_stranger_is_refused(self, client, collective, make_user):
        as_user(make_user(role="user"))
        res = client.get(f"/api/spaces/{collective['space'].slug}/members")
        assert res.status_code == 404, res.text
        assert "display_name" not in res.text

    def test_a_creator_of_a_different_collective_is_refused(
        self, client, collective, make_user,
    ):
        """Being a creator somewhere is not a key to everywhere."""
        as_user(make_user(role="creator"))
        res = client.get(f"/api/spaces/{collective['space'].slug}/members")
        assert res.status_code == 404, res.text

    def test_refusal_does_not_confirm_the_collective_exists(self, client, collective):
        """404, not 403 — matching the platform's stance for private
        and link-only Collectives."""
        as_anonymous()
        real = client.get(f"/api/spaces/{collective['space'].slug}/members")
        fake = client.get("/api/spaces/no-such-collective-at-all/members")
        assert real.status_code == fake.status_code == 404
        assert real.json() == fake.json()


class TestMembersSeeWhatTheyShould:
    def test_a_learner_sees_everyone_when_the_directory_is_open(
        self, client, collective,
    ):
        as_user(collective["learners"][0])
        res = client.get(f"/api/spaces/{collective['space'].slug}/members")
        assert res.status_code == 200, res.text
        assert len(res.json()) == 3

    def test_a_learner_sees_only_leaders_when_it_is_closed(
        self, client, db, collective,
    ):
        collective["space"].show_member_directory = False
        db.flush()
        as_user(collective["learners"][0])
        res = client.get(f"/api/spaces/{collective['space'].slug}/members")
        assert res.status_code == 200, res.text
        roles = {m["space_role"] for m in res.json()}
        assert roles <= {"creator", "moderator"}, roles

    def test_a_leader_still_sees_everyone_when_it_is_closed(
        self, client, db, collective,
    ):
        """Closing the directory stops learners browsing each other; it
        is not a wall around the person running the Collective."""
        collective["space"].show_member_directory = False
        db.flush()
        as_user(collective["owner"])
        res = client.get(f"/api/spaces/{collective['space'].slug}/members")
        assert res.status_code == 200, res.text
        assert len(res.json()) == 3

    def test_a_moderator_counts_as_a_leader(self, client, db, collective, make_user):
        collective["space"].show_member_directory = False
        mod = make_user(role="user")
        join(db, mod, collective["space"], role="moderator")
        as_user(mod)
        res = client.get(f"/api/spaces/{collective['space'].slug}/members")
        assert res.status_code == 200, res.text
        assert len(res.json()) == 4

    def test_an_owner_who_also_holds_a_learner_row_is_still_a_leader(
        self, client, db, collective,
    ):
        """Legacy owners sometimes joined their own Collective as a
        learner. Standing must come from the strongest relationship the
        caller has, not the row that happens to be found — otherwise
        closing the directory hides the Collective from the person
        running it.
        """
        collective["space"].show_member_directory = False
        owner = collective["owner"]
        db.query(SpaceMembership).filter(
            SpaceMembership.user_id == owner.id,
            SpaceMembership.space_id == collective["space"].id,
        ).delete()
        join(db, owner, collective["space"], role="learner")
        as_user(owner)
        res = client.get(f"/api/spaces/{collective['space'].slug}/members")
        assert res.status_code == 200, res.text
        assert len(res.json()) == 3, "the owner should still see everyone"

    def test_an_owner_with_no_membership_row_still_qualifies(
        self, client, db, make_space, make_user,
    ):
        """Legacy Collectives predate auto-membership for owners."""
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner, show_member_directory=True)
        learner = make_user(role="user")
        join(db, learner, space)
        as_user(owner)
        res = client.get(f"/api/spaces/{space.slug}/members")
        assert res.status_code == 200, res.text
        assert len(res.json()) == 1

    def test_a_platform_admin_keeps_oversight(self, client, collective, make_user):
        """Unchanged from the existing platform convention — admins
        read Collective-scoped data across the platform."""
        as_user(make_user(role="admin"))
        res = client.get(f"/api/spaces/{collective['space'].slug}/members")
        assert res.status_code == 200, res.text


class TestPrivateCollectives:
    def test_a_private_collective_is_refused_to_outsiders(
        self, client, db, make_space, make_user,
    ):
        owner = make_user(role="creator")
        space = make_space(is_public=False, creator=owner)
        as_anonymous()
        assert client.get(f"/api/spaces/{space.slug}/members").status_code == 404
        as_user(make_user(role="user"))
        assert client.get(f"/api/spaces/{space.slug}/members").status_code == 404

    def test_its_members_still_read_it(self, client, db, make_space, make_user):
        owner = make_user(role="creator")
        space = make_space(is_public=False, creator=owner, show_member_directory=True)
        join(db, owner, space, role="creator")
        member = make_user(role="user")
        join(db, member, space)
        as_user(member)
        res = client.get(f"/api/spaces/{space.slug}/members")
        assert res.status_code == 200, res.text
        assert len(res.json()) == 2


class TestTheSharedPredicate:
    """``services.space_viewer`` is now the single rule. These cover it
    directly so the next endpoint that needs it inherits proven
    behaviour rather than re-deriving it."""

    def test_an_anonymous_viewer_qualifies_for_nothing(self, db, collective):
        from app.services.space_viewer import resolve_space_viewer
        v = resolve_space_viewer(db, None, collective["space"])
        assert not v.qualifies
        assert not v.is_leader

    def test_a_learner_qualifies_but_is_not_a_leader(self, db, collective):
        from app.services.space_viewer import resolve_space_viewer
        v = resolve_space_viewer(db, collective["learners"][0], collective["space"])
        assert v.qualifies
        assert not v.is_leader

    def test_leadership_is_asked_positively(self, db, collective, make_user):
        """The heart of the bug: the old code asked "is a learner?" and
        so treated every non-learner — anonymous included — as exempt
        from directory privacy."""
        from app.services.space_viewer import resolve_space_viewer
        stranger = make_user(role="user")
        v = resolve_space_viewer(db, stranger, collective["space"])
        assert not v.is_leader, "a stranger must never read as a leader"

    def test_an_inactive_membership_does_not_qualify(self, db, collective, make_user):
        from app.services.space_viewer import resolve_space_viewer
        lapsed = make_user(role="user")
        db.add(SpaceMembership(
            id=str(uuid.uuid4()), user_id=lapsed.id,
            space_id=collective["space"].id, role="learner", status="removed",
        ))
        db.flush()
        assert not resolve_space_viewer(db, lapsed, collective["space"]).qualifies


class TestRecognitionUnchanged:
    def test_recognition_still_filters_on_the_directory_flag(self):
        """This fix must not widen or narrow what Recognition surfaces."""
        from pathlib import Path
        src = Path("app/services/recognition_service.py").read_text()
        assert src.count("Space.show_member_directory.is_(True)") == 2


class TestOtherMemberSurfaces:
    def test_mention_search_requires_a_signed_in_caller(self):
        """The other endpoint returning member rows. Already scoped to
        the caller's Channel access — pinned so it stays that way."""
        from pathlib import Path
        src = Path("app/community/routes.py").read_text()
        start = src.index('@router.get("/{slug}/members/search"')
        block = src[start:start + 1400]
        assert "Depends(get_current_user)" in block
        assert "get_optional_user" not in block
        assert "accessible_user_ids_for_channel" in block


class TestPublicAttributionSurvives:
    """The fix must not strip a public Collective's About page of the
    one member fact a visitor legitimately needs: who runs it. That
    name now comes from the Space payload — where it was already
    published on ``PublicSpaceCard`` — rather than from the directory.
    """

    def test_the_space_payload_names_the_leader(
        self, client, db, make_space, make_user,
    ):
        owner = make_user(role="creator")
        owner.name = "Lindsey"
        space = make_space(is_public=True, creator=owner)
        db.flush()
        as_anonymous()
        res = client.get(f"/api/spaces/{space.slug}")
        assert res.status_code == 200, res.text
        assert res.json()["creator_name"] == "Lindsey"

    def test_the_about_page_reads_it_from_there(self):
        from pathlib import Path
        src = Path("../frontend/src/app/spaces/[slug]/about/page.tsx").read_text()
        assert "space.creator_name" in src
        assert "members.filter((m) => m.space_role === 'creator')" not in src
