"""SEC-005-E — platform-creator scoping regression tests.

Locks the invariant that platform ``User.role == "creator"`` is a
platform *capability* (may enter Creator Studio), NOT global authority
over other creators' Collectives. Per-Collective access must derive
from one of:

  * platform ``admin`` (preserved for general helpers; **not** for
    private/direct-message access);
  * ``Space.creator_id`` ownership;
  * an active ``SpaceMembership`` with an appropriate role.

Covered helpers (exercised directly, mirroring the pattern used by the
rest of the auth-z suite):

  * ``spaces.routes._get_member_space``
  * ``spaces.routes._compute_pathway_access``
  * ``spaces.routes._check_pathway_access``
  * ``services.channel_permissions.is_caretaker``
  * ``services.event_permissions._is_caretaker``
  * ``community.routes._can_moderate``
  * ``messages.routes._get_managed_space``  (stricter — no admin bypass)

Also adds:
  * endpoint-level coverage proving a stranger platform creator cannot
    reach a private/link-only Collective's community, draft pathways,
    or creator-side DMs;
  * a World Builders-shaped test proving auto-granted learner
    membership yields member-level read access but NOT caretaker
    authority;
  * a narrowly-scoped structural regression grep that rejects any
    future re-introduction of ``role in ("admin", "creator")`` (or the
    reverse ordering) as an authorisation branch in ``backend/app``,
    while allowlisting legitimate platform feature gates
    (``get_creator_user`` in ``auth/dependencies.py`` and its
    ``creator/routes.py`` module docstring).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

# Ensure User's community_care FKs resolve in isolation, matching the
# pattern used by the rest of the auth-z test files.
import app.models.community_care  # noqa: F401

from app.community.routes import (
    _can_moderate,
    hide_community_post,
    list_community_posts,
    toggle_post_reaction,
)
from app.messages.routes import _get_managed_space as _messages_get_managed_space
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    Pathway,
    PathwayStatus,
    PostComment,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.channel_permissions import (
    has_space_caretaker_membership,
    is_active_space_member,
    is_caretaker,
    is_space_owner,
)
from app.services.event_permissions import _is_caretaker as _event_is_caretaker
from app.spaces.routes import (
    _check_pathway_access,
    _compute_pathway_access,
    _get_member_space,
    list_pathways_progress,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def make_channel(db):
    def _factory(space, *, is_default=True, channel_type="open") -> ConversationChannel:
        c = ConversationChannel(
            id=_uid("ch"),
            space_id=space.id,
            name="Common Room" if is_default else "Extra",
            slug="common-room" if is_default else f"ch-{uuid.uuid4().hex[:8]}",
            is_default=is_default,
            is_system=is_default,
            channel_type=channel_type,
        )
        db.add(c)
        db.flush()
        return c
    return _factory


@pytest.fixture
def make_membership(db):
    def _factory(*, user, space, role=SpaceRole.learner,
                 status=SpaceMembershipStatus.active) -> SpaceMembership:
        m = SpaceMembership(
            id=_uid("sm"),
            user_id=user.id,
            space_id=space.id,
            role=role,
            status=status,
            joined_at=datetime.utcnow(),
        )
        db.add(m)
        db.flush()
        return m
    return _factory


@pytest.fixture
def make_pathway(db):
    def _factory(*, space, status=PathwayStatus.active,
                 access_type="free", slug=None) -> Pathway:
        p = Pathway(
            id=_uid("pw"),
            space_id=space.id,
            slug=slug or f"pw-{uuid.uuid4().hex[:8]}",
            title="Test Pathway",
            status=status,
            position=0,
            access_type=access_type,
        )
        db.add(p)
        db.flush()
        return p
    return _factory


@pytest.fixture
def owned_space(db, make_user, make_space):
    """Space + its owner. Owner has NO SpaceMembership row (legacy
    shape) so tests exercise the ownership branch explicitly."""
    owner = make_user(role="creator")
    space = make_space(creator=owner)
    # Deliberately do NOT create a SpaceMembership — legacy owners
    # without membership rows must still retain authority via the
    # Space.creator_id branch.
    return {"owner": owner, "space": space}


@pytest.fixture
def platform_creator(make_user):
    """A user with platform capability but zero per-Collective
    relationship to the tested space."""
    return make_user(role="creator")


# ---------------------------------------------------------------------------
# 1. spaces.routes._get_member_space
# ---------------------------------------------------------------------------

class TestGetMemberSpace:
    def test_platform_creator_stranger_denied(
        self, db, owned_space, platform_creator,
    ):
        """SEC-005-E — the classic bypass: platform creator with no
        membership in Collective X can no longer access X."""
        with pytest.raises(HTTPException) as exc:
            _get_member_space(owned_space["space"].slug, platform_creator, db)
        assert exc.value.status_code == 404

    def test_owner_without_membership_allowed(self, db, owned_space):
        space = _get_member_space(
            owned_space["space"].slug, owned_space["owner"], db,
        )
        assert space.id == owned_space["space"].id

    def test_active_creator_membership_allowed(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.creator)
        assert _get_member_space(owned_space["space"].slug, u, db).id \
            == owned_space["space"].id

    def test_active_moderator_membership_allowed(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.moderator)
        assert _get_member_space(owned_space["space"].slug, u, db).id \
            == owned_space["space"].id

    def test_active_learner_membership_allowed(
        self, db, make_user, owned_space, make_membership,
    ):
        """`_get_member_space` accepts *any* active membership for
        read-side access — this is the SEC-004 semantic and is
        unchanged."""
        u = make_user(role="user")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.learner)
        assert _get_member_space(owned_space["space"].slug, u, db).id \
            == owned_space["space"].id

    def test_paused_creator_membership_denied_when_not_owner(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.creator,
                        status=SpaceMembershipStatus.paused)
        with pytest.raises(HTTPException) as exc:
            _get_member_space(owned_space["space"].slug, u, db)
        assert exc.value.status_code == 404

    def test_removed_creator_membership_denied_when_not_owner(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.creator,
                        status=SpaceMembershipStatus.removed)
        with pytest.raises(HTTPException) as exc:
            _get_member_space(owned_space["space"].slug, u, db)
        assert exc.value.status_code == 404

    def test_platform_admin_preserved(
        self, db, make_user, owned_space,
    ):
        admin = make_user(role="admin")
        assert _get_member_space(owned_space["space"].slug, admin, db).id \
            == owned_space["space"].id

    def test_normal_active_member_unchanged(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="user")
        make_membership(user=u, space=owned_space["space"])
        assert _get_member_space(owned_space["space"].slug, u, db).id \
            == owned_space["space"].id

    def test_normal_non_member_denied(
        self, db, make_user, owned_space,
    ):
        u = make_user(role="user")
        with pytest.raises(HTTPException) as exc:
            _get_member_space(owned_space["space"].slug, u, db)
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 2. spaces.routes._compute_pathway_access
# ---------------------------------------------------------------------------

class TestComputePathwayAccess:
    def test_platform_creator_stranger_denied_on_draft(
        self, db, owned_space, platform_creator, make_pathway,
    ):
        pw = make_pathway(space=owned_space["space"],
                          status=PathwayStatus.draft)
        assert _compute_pathway_access(
            platform_creator, pw, owned_space["space"], db,
        ) is False

    def test_owner_without_membership_allowed_on_draft(
        self, db, owned_space, make_pathway,
    ):
        pw = make_pathway(space=owned_space["space"],
                          status=PathwayStatus.draft)
        assert _compute_pathway_access(
            owned_space["owner"], pw, owned_space["space"], db,
        ) is True

    def test_active_creator_membership_allowed_on_draft(
        self, db, make_user, owned_space, make_membership, make_pathway,
    ):
        pw = make_pathway(space=owned_space["space"],
                          status=PathwayStatus.draft)
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.creator)
        assert _compute_pathway_access(
            u, pw, owned_space["space"], db,
        ) is True

    def test_active_learner_membership_denied_on_draft(
        self, db, make_user, owned_space, make_membership, make_pathway,
    ):
        pw = make_pathway(space=owned_space["space"],
                          status=PathwayStatus.draft)
        u = make_user(role="user")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.learner)
        assert _compute_pathway_access(
            u, pw, owned_space["space"], db,
        ) is False

    def test_platform_admin_preserved_on_draft(
        self, db, make_user, owned_space, make_pathway,
    ):
        pw = make_pathway(space=owned_space["space"],
                          status=PathwayStatus.draft)
        admin = make_user(role="admin")
        assert _compute_pathway_access(
            admin, pw, owned_space["space"], db,
        ) is True


# ---------------------------------------------------------------------------
# 3. spaces.routes._check_pathway_access
# ---------------------------------------------------------------------------

class TestCheckPathwayAccess:
    def test_platform_creator_stranger_denied_on_draft(
        self, db, owned_space, platform_creator, make_pathway,
    ):
        pw = make_pathway(space=owned_space["space"],
                          status=PathwayStatus.draft)
        with pytest.raises(HTTPException) as exc:
            _check_pathway_access(
                platform_creator, pw, owned_space["space"], db,
            )
        assert exc.value.status_code == 403

    def test_owner_without_membership_allowed_on_draft(
        self, db, owned_space, make_pathway,
    ):
        pw = make_pathway(space=owned_space["space"],
                          status=PathwayStatus.draft)
        # No raise = allowed.
        _check_pathway_access(
            owned_space["owner"], pw, owned_space["space"], db,
        )

    def test_removed_creator_membership_denied_when_not_owner(
        self, db, make_user, owned_space, make_membership, make_pathway,
    ):
        pw = make_pathway(space=owned_space["space"],
                          status=PathwayStatus.draft)
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.creator,
                        status=SpaceMembershipStatus.removed)
        with pytest.raises(HTTPException) as exc:
            _check_pathway_access(u, pw, owned_space["space"], db)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 4. services.channel_permissions.is_caretaker
# ---------------------------------------------------------------------------

class TestChannelIsCaretaker:
    def test_platform_creator_stranger_denied(
        self, db, owned_space, platform_creator,
    ):
        assert is_caretaker(
            platform_creator, owned_space["space"], db,
        ) is False

    def test_owner_without_membership_allowed(self, db, owned_space):
        assert is_caretaker(
            owned_space["owner"], owned_space["space"], db,
        ) is True

    def test_active_creator_membership_allowed(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.creator)
        assert is_caretaker(u, owned_space["space"], db) is True

    def test_active_moderator_membership_allowed(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.moderator)
        assert is_caretaker(u, owned_space["space"], db) is True

    def test_active_learner_membership_denied(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.learner)
        assert is_caretaker(u, owned_space["space"], db) is False

    def test_paused_creator_membership_denied_when_not_owner(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.creator,
                        status=SpaceMembershipStatus.paused)
        assert is_caretaker(u, owned_space["space"], db) is False

    def test_removed_creator_membership_denied_when_not_owner(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.creator,
                        status=SpaceMembershipStatus.removed)
        assert is_caretaker(u, owned_space["space"], db) is False

    def test_platform_admin_preserved(
        self, db, make_user, owned_space,
    ):
        admin = make_user(role="admin")
        assert is_caretaker(admin, owned_space["space"], db) is True


# ---------------------------------------------------------------------------
# 5. services.event_permissions._is_caretaker
# ---------------------------------------------------------------------------

class TestEventIsCaretaker:
    def test_platform_creator_stranger_denied(
        self, db, owned_space, platform_creator,
    ):
        assert _event_is_caretaker(
            platform_creator, owned_space["space"], db,
        ) is False

    def test_owner_without_membership_allowed(self, db, owned_space):
        assert _event_is_caretaker(
            owned_space["owner"], owned_space["space"], db,
        ) is True

    def test_active_moderator_membership_allowed(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.moderator)
        assert _event_is_caretaker(u, owned_space["space"], db) is True

    def test_platform_admin_preserved(
        self, db, make_user, owned_space,
    ):
        admin = make_user(role="admin")
        assert _event_is_caretaker(admin, owned_space["space"], db) is True


# ---------------------------------------------------------------------------
# 6. community.routes._can_moderate
# ---------------------------------------------------------------------------

class TestCommunityCanModerate:
    def test_platform_creator_stranger_denied(
        self, db, owned_space, platform_creator,
    ):
        assert _can_moderate(
            platform_creator, owned_space["space"], db,
        ) is False

    def test_owner_without_membership_allowed(self, db, owned_space):
        assert _can_moderate(
            owned_space["owner"], owned_space["space"], db,
        ) is True

    def test_active_creator_membership_allowed(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.creator)
        assert _can_moderate(u, owned_space["space"], db) is True

    def test_learner_denied(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.learner)
        assert _can_moderate(u, owned_space["space"], db) is False

    def test_platform_admin_preserved(
        self, db, make_user, owned_space,
    ):
        admin = make_user(role="admin")
        assert _can_moderate(admin, owned_space["space"], db) is True


# ---------------------------------------------------------------------------
# 7. messages.routes._get_managed_space  (stricter — no admin bypass)
# ---------------------------------------------------------------------------

class TestMessagesGetManagedSpace:
    def test_platform_creator_stranger_denied(
        self, db, owned_space, platform_creator,
    ):
        with pytest.raises(HTTPException) as exc:
            _messages_get_managed_space(
                owned_space["space"].slug, platform_creator, db,
            )
        assert exc.value.status_code == 403

    def test_platform_admin_denied(
        self, db, make_user, owned_space,
    ):
        """SEC-005-E policy: private-message access does NOT inherit
        from platform admin. A future explicit safety/reporting
        workflow must go through its own gated endpoint."""
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as exc:
            _messages_get_managed_space(
                owned_space["space"].slug, admin, db,
            )
        assert exc.value.status_code == 403

    def test_owner_without_membership_allowed(self, db, owned_space):
        space = _messages_get_managed_space(
            owned_space["space"].slug, owned_space["owner"], db,
        )
        assert space.id == owned_space["space"].id

    def test_active_creator_membership_allowed(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.creator)
        space = _messages_get_managed_space(
            owned_space["space"].slug, u, db,
        )
        assert space.id == owned_space["space"].id

    def test_active_moderator_membership_allowed(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.moderator)
        space = _messages_get_managed_space(
            owned_space["space"].slug, u, db,
        )
        assert space.id == owned_space["space"].id

    def test_learner_denied(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="creator")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.learner)
        with pytest.raises(HTTPException) as exc:
            _messages_get_managed_space(
                owned_space["space"].slug, u, db,
            )
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Endpoint-level — stranger platform creator against a private
# link-only Collective
# ---------------------------------------------------------------------------

class TestPrivateCollectiveStrangerCreator:
    """A platform creator who has NO membership in a private/link-only
    Collective must not reach its community, its pathways, its
    moderation surface, or its creator-side DM management. Verifies
    the endpoint composition of the helpers above."""

    @pytest.fixture
    def private_space_with_content(
        self, db, make_user, make_space, make_channel, make_membership,
        make_pathway,
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner, is_public=False)
        # Give the owner an explicit membership so their side of the
        # flow is unambiguously exercised via both branches.
        make_membership(user=owner, space=space, role=SpaceRole.creator)
        channel = make_channel(space)
        author = make_user(role="user")
        make_membership(user=author, space=space)
        post = CommunityPost(
            id=_uid("cp"), space_id=space.id, author_id=author.id,
            channel_id=channel.id, title="Post", body="Body",
            post_type="discussion",
        )
        db.add(post)
        draft_pw = make_pathway(space=space, status=PathwayStatus.draft)
        db.flush()
        return {"space": space, "owner": owner, "channel": channel,
                "author": author, "post": post, "draft_pathway": draft_pw}

    def test_stranger_creator_cannot_read_community(
        self, db, private_space_with_content, platform_creator,
    ):
        with pytest.raises(HTTPException) as exc:
            list_community_posts(
                slug=private_space_with_content["space"].slug,
                channel=None, db=db, current_user=platform_creator,
            )
        assert exc.value.status_code == 404

    def test_stranger_creator_cannot_read_draft_pathways(
        self, db, private_space_with_content, platform_creator,
    ):
        # `list_pathways_progress` uses `_get_member_space` up front —
        # non-members receive 404 as the outer response.
        with pytest.raises(HTTPException) as exc:
            list_pathways_progress(
                slug=private_space_with_content["space"].slug,
                db=db, current_user=platform_creator,
            )
        assert exc.value.status_code == 404

    def test_stranger_creator_cannot_moderate(
        self, db, private_space_with_content, platform_creator,
    ):
        with pytest.raises(HTTPException) as exc:
            hide_community_post(
                slug=private_space_with_content["space"].slug,
                post_id=private_space_with_content["post"].id,
                db=db, current_user=platform_creator,
            )
        # Post exists in space → scope OK → _can_moderate returns False
        # (stranger not owner, not caretaker membership) → 403.
        assert exc.value.status_code == 403

    def test_stranger_creator_cannot_react(
        self, db, private_space_with_content, platform_creator,
    ):
        with pytest.raises(HTTPException) as exc:
            toggle_post_reaction(
                slug=private_space_with_content["space"].slug,
                post_id=private_space_with_content["post"].id,
                emoji="❤️",
                db=db, current_user=platform_creator,
            )
        # can_react → can_view_channel → is_active_space_member False
        # → False → 403 "You cannot react to this post."
        assert exc.value.status_code == 403

    def test_stranger_creator_cannot_reach_creator_dms(
        self, db, private_space_with_content, platform_creator,
    ):
        with pytest.raises(HTTPException) as exc:
            _messages_get_managed_space(
                private_space_with_content["space"].slug,
                platform_creator, db,
            )
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# World Builders-shaped — auto-granted learner membership
# ---------------------------------------------------------------------------

class TestAutoGrantedLearnerAccess:
    """When the eligibility reconciler auto-inserts a
    ``SpaceMembership(role=learner, source=auto_role)`` for a platform
    creator on the World Builders shape, the creator gains member-level
    access to that Collective but must NOT acquire caretaker
    authority."""

    def test_auto_granted_learner_can_read_community(
        self, db, make_user, make_space, make_channel, make_membership,
    ):
        space = make_space(is_public=False)
        make_channel(space)
        wb_creator = make_user(role="creator")
        # Simulate the eligibility reconciler's insert shape.
        m = SpaceMembership(
            id=_uid("sm"), user_id=wb_creator.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            source="auto_role", joined_at=datetime.utcnow(),
        )
        db.add(m)
        db.flush()

        posts = list_community_posts(
            slug=space.slug, channel=None, db=db, current_user=wb_creator,
        )
        # No posts seeded; empty list is a successful read.
        assert posts == []

    def test_auto_granted_learner_is_not_caretaker(
        self, db, make_user, make_space,
    ):
        space = make_space(is_public=False)
        wb_creator = make_user(role="creator")
        m = SpaceMembership(
            id=_uid("sm"), user_id=wb_creator.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            source="auto_role", joined_at=datetime.utcnow(),
        )
        db.add(m)
        db.flush()
        assert is_caretaker(wb_creator, space, db) is False
        assert _can_moderate(wb_creator, space, db) is False


# ---------------------------------------------------------------------------
# Shared vocabulary — is_space_owner + has_space_caretaker_membership
# ---------------------------------------------------------------------------

class TestSharedVocabulary:
    def test_is_space_owner_true_for_owner(self, owned_space):
        assert is_space_owner(
            owned_space["owner"], owned_space["space"],
        ) is True

    def test_is_space_owner_false_for_stranger(
        self, owned_space, platform_creator,
    ):
        assert is_space_owner(
            platform_creator, owned_space["space"],
        ) is False

    def test_is_space_owner_none_user_is_false(self, owned_space):
        assert is_space_owner(None, owned_space["space"]) is False

    def test_has_space_caretaker_membership(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="user")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.moderator)
        assert has_space_caretaker_membership(
            u.id, owned_space["space"].id, db,
        ) is True

    def test_has_space_caretaker_membership_false_for_learner(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="user")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.learner)
        assert has_space_caretaker_membership(
            u.id, owned_space["space"].id, db,
        ) is False

    def test_is_active_space_member_true_for_learner(
        self, db, make_user, owned_space, make_membership,
    ):
        u = make_user(role="user")
        make_membership(user=u, space=owned_space["space"],
                        role=SpaceRole.learner)
        assert is_active_space_member(
            u.id, owned_space["space"].id, db,
        ) is True


# ---------------------------------------------------------------------------
# Structural regression — narrow grep against reintroduction
# ---------------------------------------------------------------------------

class TestStructuralRegression:
    """Reject any future reintroduction of ``role in ("admin", "creator")``
    (or the reverse ordering) as an authorisation branch anywhere in
    ``backend/app``. Allowlists legitimate platform feature gates:

      * ``auth/dependencies.py`` — ``get_creator_user`` is the Creator
        Studio route-level gate; it correctly accepts both roles as a
        feature capability check (not per-Collective authority).
      * ``creator/routes.py`` module docstring — describes the above
        gate, not authorisation logic.

    The pattern is deliberately narrow — checking only for the exact
    tuple ``("admin"|"creator", "creator"|"admin")`` — so it does NOT
    reject legitimate non-authorisation uses of ``User.role`` (e.g.
    creator eligibility, plan/subscription logic, admin dashboard
    counts). Those never take the tuple form we prohibit here."""

    _APP_ROOT = Path(__file__).resolve().parent.parent / "app"
    _ALLOWED = {
        # Route-level feature gate for Creator Studio.
        _APP_ROOT / "auth" / "dependencies.py",
        # Module docstring describing get_creator_user.
        _APP_ROOT / "creator" / "routes.py",
    }
    _PATTERN = re.compile(
        r"role\s+in\s+\(\s*[\"'](admin|creator)[\"']\s*,\s*[\"'](creator|admin)[\"']\s*\)"
    )

    def test_no_paired_role_bypass_outside_allowlist(self):
        offenders: list[str] = []
        for py in self._APP_ROOT.rglob("*.py"):
            if py in self._ALLOWED:
                continue
            src = py.read_text()
            for i, line in enumerate(src.splitlines(), start=1):
                if self._PATTERN.search(line):
                    offenders.append(f"{py.relative_to(self._APP_ROOT)}:{i}: {line.strip()}")
        assert not offenders, (
            "SEC-005-E — role in ('admin','creator') / ('creator','admin') "
            "reintroduced as an authorisation branch:\n  "
            + "\n  ".join(offenders)
            + "\nIf this is a legitimate non-authorisation use, either "
            "rewrite it to check the specific role you mean or extend "
            "TestStructuralRegression._ALLOWED with an explanation."
        )
