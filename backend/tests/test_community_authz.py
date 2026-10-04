"""SEC-005 — community/member authorisation regression tests.

Locks the object-scoping + membership invariants for the three
endpoints hardened by the SEC-005 remediation:

  * ``POST /api/spaces/{slug}/community/{post_id}/reactions/{emoji}``
    (``toggle_post_reaction``)
  * ``POST /api/spaces/{slug}/community/{post_id}/comments/{comment_id}
     /reactions/{emoji}`` (``toggle_comment_reaction``)
  * ``POST /api/spaces/{slug}/community/upload-image``
    (``upload_community_image``)

Also adds a small cross-Collective IDOR regression matrix over adjacent
community endpoints (``hide_community_post``, ``hide_community_comment``,
``get_community_post``, ``create_comment``) to keep the whole family of
object-supplied endpoints locked against the same class of attack.

Route bodies are exercised directly (as ``test_pathways_progress_authz.py``
and ``test_community_care_stage_2c.py`` do); the authorisation logic
lives in the handlers and their shared helpers, so we don't need
TestClient/cookie plumbing to prove the invariants.

Note on unauthenticated callers: ``get_current_user`` runs at the
FastAPI dependency layer, not inside the handler body. Its behaviour
(401 on missing/invalid session cookie) is exhaustively covered by
``test_auth_dependencies.py`` and is not re-exercised here — every
call in this file has already resolved ``current_user``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest
from fastapi import BackgroundTasks, HTTPException

# Ensure User's community_care FKs resolve in isolation, matching the
# pattern used by the rest of the auth-z test files.
import app.models.community_care  # noqa: F401

from app.community.routes import (
    create_comment,
    get_community_post,
    hide_community_comment,
    hide_community_post,
    toggle_comment_reaction,
    toggle_post_reaction,
    upload_community_image,
)
from app.community.schemas import CreateCommentRequest
from app.models.community_care import MemberRestriction
from app.models.platform import (
    CommunityPost,
    CommentReaction,
    ConversationChannel,
    PostComment,
    PostReaction,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def make_channel(db):
    def _factory(space, *, is_default=True, channel_type="open",
                 is_archived=False, member_posting_allowed=True,
                 comments_allowed=True) -> ConversationChannel:
        c = ConversationChannel(
            id=_uid("ch"),
            space_id=space.id,
            name="Common Room" if is_default else "Extra",
            slug="common-room" if is_default else f"ch-{uuid.uuid4().hex[:8]}",
            is_default=is_default,
            is_system=is_default,
            is_archived=is_archived,
            channel_type=channel_type,
            member_posting_allowed=member_posting_allowed,
            comments_allowed=comments_allowed,
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
def make_post(db, make_channel):
    def _factory(*, space, author, channel=None) -> CommunityPost:
        ch = channel or make_channel(space)
        p = CommunityPost(
            id=_uid("cp"),
            space_id=space.id,
            author_id=author.id,
            channel_id=ch.id,
            title="Post",
            body="Body",
            post_type="discussion",
        )
        db.add(p)
        db.flush()
        return p
    return _factory


@pytest.fixture
def make_comment(db):
    def _factory(*, post, author) -> PostComment:
        c = PostComment(
            id=_uid("pc"),
            post_id=post.id,
            author_id=author.id,
            body="A reply",
        )
        db.add(c)
        db.flush()
        return c
    return _factory


@pytest.fixture
def two_spaces(db, make_user, make_space, make_channel, make_post, make_comment):
    """Two independent Collectives, each with an active member of their
    own, a default channel, a post, and a comment on that post. Used by
    the cross-Collective / cross-object IDOR checks."""
    space_a = make_space()
    space_b = make_space()
    member_a = make_user(role="user")
    member_b = make_user(role="user")
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=member_a.id, space_id=space_a.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        joined_at=datetime.utcnow(),
    ))
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=member_b.id, space_id=space_b.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        joined_at=datetime.utcnow(),
    ))
    channel_a = make_channel(space_a)
    channel_b = make_channel(space_b)
    author_a = make_user(role="user")
    author_b = make_user(role="user")
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=author_a.id, space_id=space_a.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        joined_at=datetime.utcnow(),
    ))
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=author_b.id, space_id=space_b.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        joined_at=datetime.utcnow(),
    ))
    post_a = make_post(space=space_a, author=author_a, channel=channel_a)
    post_b = make_post(space=space_b, author=author_b, channel=channel_b)
    comment_a = make_comment(post=post_a, author=author_a)
    comment_b = make_comment(post=post_b, author=author_b)
    db.flush()
    return {
        "space_a": space_a, "space_b": space_b,
        "member_a": member_a, "member_b": member_b,
        "channel_a": channel_a, "channel_b": channel_b,
        "post_a": post_a, "post_b": post_b,
        "comment_a": comment_a, "comment_b": comment_b,
    }


# ---------------------------------------------------------------------------
# SEC-005-A — toggle_post_reaction
# ---------------------------------------------------------------------------

class TestPostReactionAuthorization:
    def test_active_member_reaction_succeeds(
        self, db, make_user, make_space, make_membership, make_post,
    ):
        space = make_space()
        member = make_user(role="user")
        author = make_user(role="user")
        make_membership(user=member, space=space)
        make_membership(user=author, space=space)
        post = make_post(space=space, author=author)

        result = toggle_post_reaction(
            slug=space.slug, post_id=post.id, emoji="❤️",
            db=db, current_user=member,
        )
        assert result == {"reacted": True}
        row = db.query(PostReaction).filter_by(
            post_id=post.id, user_id=member.id, emoji="❤️",
        ).one()
        assert row is not None

    def test_active_member_second_call_toggles_off(
        self, db, make_user, make_space, make_membership, make_post,
    ):
        space = make_space()
        member = make_user(role="user")
        author = make_user(role="user")
        make_membership(user=member, space=space)
        make_membership(user=author, space=space)
        post = make_post(space=space, author=author)

        assert toggle_post_reaction(
            slug=space.slug, post_id=post.id, emoji="❤️",
            db=db, current_user=member,
        )["reacted"] is True
        assert toggle_post_reaction(
            slug=space.slug, post_id=post.id, emoji="❤️",
            db=db, current_user=member,
        )["reacted"] is False
        assert db.query(PostReaction).filter_by(
            post_id=post.id, user_id=member.id, emoji="❤️",
        ).first() is None

    def test_non_member_reaction_rejected(
        self, db, make_user, make_space, make_membership, make_post,
    ):
        """SEC-005-A regression — pre-fix code let any authenticated
        caller react to any post regardless of membership."""
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        post = make_post(space=space, author=author)
        stranger = make_user(role="user")

        with pytest.raises(HTTPException) as exc:
            toggle_post_reaction(
                slug=space.slug, post_id=post.id, emoji="❤️",
                db=db, current_user=stranger,
            )
        assert exc.value.status_code == 403
        assert db.query(PostReaction).filter_by(post_id=post.id).count() == 0

    def test_paused_member_reaction_rejected(
        self, db, make_user, make_space, make_membership, make_post,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        post = make_post(space=space, author=author)
        paused = make_user(role="user")
        make_membership(user=paused, space=space,
                        status=SpaceMembershipStatus.paused)

        with pytest.raises(HTTPException) as exc:
            toggle_post_reaction(
                slug=space.slug, post_id=post.id, emoji="❤️",
                db=db, current_user=paused,
            )
        assert exc.value.status_code == 403

    def test_removed_member_reaction_rejected(
        self, db, make_user, make_space, make_membership, make_post,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        post = make_post(space=space, author=author)
        removed = make_user(role="user")
        make_membership(user=removed, space=space,
                        status=SpaceMembershipStatus.removed)

        with pytest.raises(HTTPException) as exc:
            toggle_post_reaction(
                slug=space.slug, post_id=post.id, emoji="❤️",
                db=db, current_user=removed,
            )
        assert exc.value.status_code == 403

    def test_cross_collective_post_id_returns_404(
        self, db, two_spaces,
    ):
        """SEC-005-A key regression — supplying Collective A's slug
        with a post_id from Collective B must NOT succeed even if the
        caller is a legitimate member of A."""
        with pytest.raises(HTTPException) as exc:
            toggle_post_reaction(
                slug=two_spaces["space_a"].slug,
                post_id=two_spaces["post_b"].id,
                emoji="❤️",
                db=db, current_user=two_spaces["member_a"],
            )
        assert exc.value.status_code == 404
        # And nothing was written in either Collective.
        assert db.query(PostReaction).count() == 0

    def test_archived_channel_reaction_rejected(
        self, db, make_user, make_space, make_channel, make_membership, make_post,
    ):
        space = make_space()
        member = make_user(role="user")
        author = make_user(role="user")
        make_membership(user=member, space=space)
        make_membership(user=author, space=space)
        archived = make_channel(space, is_default=False, is_archived=True)
        post = make_post(space=space, author=author, channel=archived)

        with pytest.raises(HTTPException) as exc:
            toggle_post_reaction(
                slug=space.slug, post_id=post.id, emoji="❤️",
                db=db, current_user=member,
            )
        assert exc.value.status_code == 403

    def test_private_channel_non_channel_member_rejected(
        self, db, make_user, make_space, make_channel, make_membership, make_post,
    ):
        """Even a legitimate Collective member cannot react in a
        private channel they don't belong to."""
        space = make_space()
        member = make_user(role="user")
        author = make_user(role="user")
        make_membership(user=member, space=space)
        make_membership(user=author, space=space)
        priv = make_channel(space, is_default=False, channel_type="private")
        post = make_post(space=space, author=author, channel=priv)

        with pytest.raises(HTTPException) as exc:
            toggle_post_reaction(
                slug=space.slug, post_id=post.id, emoji="❤️",
                db=db, current_user=member,
            )
        assert exc.value.status_code == 403

    def test_cc_posting_restricted_member_rejected(
        self, db, make_user, make_space, make_membership, make_post,
    ):
        space = make_space()
        member = make_user(role="user")
        author = make_user(role="user")
        make_membership(user=member, space=space)
        make_membership(user=author, space=space)
        post = make_post(space=space, author=author)
        db.add(MemberRestriction(
            id=_uid("mr"),
            user_id=member.id, space_id=space.id, kind="posting",
            starts_at=datetime.utcnow(),
        ))
        db.flush()

        with pytest.raises(HTTPException) as exc:
            toggle_post_reaction(
                slug=space.slug, post_id=post.id, emoji="❤️",
                db=db, current_user=member,
            )
        assert exc.value.status_code == 403

    def test_moderator_caretaker_reaction_succeeds(
        self, db, make_user, make_space, make_membership, make_post,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        mod = make_user(role="user")
        make_membership(user=mod, space=space, role=SpaceRole.moderator)
        post = make_post(space=space, author=author)

        assert toggle_post_reaction(
            slug=space.slug, post_id=post.id, emoji="❤️",
            db=db, current_user=mod,
        )["reacted"] is True

    def test_creator_membership_caretaker_reaction_succeeds(
        self, db, make_user, make_space, make_membership, make_post,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        creator_mem = make_user(role="user")
        make_membership(user=creator_mem, space=space, role=SpaceRole.creator)
        post = make_post(space=space, author=author)

        assert toggle_post_reaction(
            slug=space.slug, post_id=post.id, emoji="❤️",
            db=db, current_user=creator_mem,
        )["reacted"] is True


# ---------------------------------------------------------------------------
# SEC-005-B — toggle_comment_reaction
# ---------------------------------------------------------------------------

class TestCommentReactionAuthorization:
    def test_active_member_reaction_succeeds(
        self, db, make_user, make_space, make_membership, make_post, make_comment,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        member = make_user(role="user")
        make_membership(user=member, space=space)
        post = make_post(space=space, author=author)
        comment = make_comment(post=post, author=author)

        assert toggle_comment_reaction(
            slug=space.slug, post_id=post.id, comment_id=comment.id, emoji="❤️",
            db=db, current_user=member,
        )["reacted"] is True

    def test_active_member_second_call_toggles_off(
        self, db, make_user, make_space, make_membership, make_post, make_comment,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        member = make_user(role="user")
        make_membership(user=member, space=space)
        post = make_post(space=space, author=author)
        comment = make_comment(post=post, author=author)

        toggle_comment_reaction(
            slug=space.slug, post_id=post.id, comment_id=comment.id, emoji="❤️",
            db=db, current_user=member,
        )
        result = toggle_comment_reaction(
            slug=space.slug, post_id=post.id, comment_id=comment.id, emoji="❤️",
            db=db, current_user=member,
        )
        assert result["reacted"] is False

    def test_non_member_rejected(
        self, db, make_user, make_space, make_membership, make_post, make_comment,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        post = make_post(space=space, author=author)
        comment = make_comment(post=post, author=author)
        stranger = make_user(role="user")

        with pytest.raises(HTTPException) as exc:
            toggle_comment_reaction(
                slug=space.slug, post_id=post.id, comment_id=comment.id,
                emoji="❤️", db=db, current_user=stranger,
            )
        assert exc.value.status_code == 403
        assert db.query(CommentReaction).count() == 0

    def test_paused_member_rejected(
        self, db, make_user, make_space, make_membership, make_post, make_comment,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        post = make_post(space=space, author=author)
        comment = make_comment(post=post, author=author)
        paused = make_user(role="user")
        make_membership(user=paused, space=space,
                        status=SpaceMembershipStatus.paused)

        with pytest.raises(HTTPException) as exc:
            toggle_comment_reaction(
                slug=space.slug, post_id=post.id, comment_id=comment.id,
                emoji="❤️", db=db, current_user=paused,
            )
        assert exc.value.status_code == 403

    def test_removed_member_rejected(
        self, db, make_user, make_space, make_membership, make_post, make_comment,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        post = make_post(space=space, author=author)
        comment = make_comment(post=post, author=author)
        removed = make_user(role="user")
        make_membership(user=removed, space=space,
                        status=SpaceMembershipStatus.removed)

        with pytest.raises(HTTPException) as exc:
            toggle_comment_reaction(
                slug=space.slug, post_id=post.id, comment_id=comment.id,
                emoji="❤️", db=db, current_user=removed,
            )
        assert exc.value.status_code == 403

    def test_cross_collective_post_id_returns_404(
        self, db, two_spaces,
    ):
        """Slug A + post B + comment B — pre-fix would have inserted
        the reaction against comment B via unscoped filter."""
        with pytest.raises(HTTPException) as exc:
            toggle_comment_reaction(
                slug=two_spaces["space_a"].slug,
                post_id=two_spaces["post_b"].id,
                comment_id=two_spaces["comment_b"].id,
                emoji="❤️",
                db=db, current_user=two_spaces["member_a"],
            )
        assert exc.value.status_code == 404
        assert db.query(CommentReaction).count() == 0

    def test_cross_post_comment_id_returns_404(
        self, db, make_user, make_space, make_channel, make_membership,
        make_post, make_comment,
    ):
        """Slug A + post A1 + comment attached to post A2 (different
        post in the same Collective). Pre-fix code ignored the
        post_id URL param entirely and reacted using the comment_id
        alone."""
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        member = make_user(role="user")
        make_membership(user=member, space=space)
        channel = make_channel(space)
        post_1 = make_post(space=space, author=author, channel=channel)
        post_2 = make_post(space=space, author=author, channel=channel)
        comment_on_2 = make_comment(post=post_2, author=author)

        with pytest.raises(HTTPException) as exc:
            toggle_comment_reaction(
                slug=space.slug, post_id=post_1.id,
                comment_id=comment_on_2.id, emoji="❤️",
                db=db, current_user=member,
            )
        assert exc.value.status_code == 404
        assert db.query(CommentReaction).count() == 0

    def test_archived_channel_rejected(
        self, db, make_user, make_space, make_channel, make_membership, make_post, make_comment,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        member = make_user(role="user")
        make_membership(user=member, space=space)
        archived = make_channel(space, is_default=False, is_archived=True)
        post = make_post(space=space, author=author, channel=archived)
        comment = make_comment(post=post, author=author)

        with pytest.raises(HTTPException) as exc:
            toggle_comment_reaction(
                slug=space.slug, post_id=post.id, comment_id=comment.id,
                emoji="❤️", db=db, current_user=member,
            )
        assert exc.value.status_code == 403

    def test_cc_posting_restricted_member_rejected(
        self, db, make_user, make_space, make_membership, make_post, make_comment,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        member = make_user(role="user")
        make_membership(user=member, space=space)
        post = make_post(space=space, author=author)
        comment = make_comment(post=post, author=author)
        db.add(MemberRestriction(
            id=_uid("mr"),
            user_id=member.id, space_id=space.id, kind="posting",
            starts_at=datetime.utcnow(),
        ))
        db.flush()

        with pytest.raises(HTTPException) as exc:
            toggle_comment_reaction(
                slug=space.slug, post_id=post.id, comment_id=comment.id,
                emoji="❤️", db=db, current_user=member,
            )
        assert exc.value.status_code == 403

    def test_moderator_caretaker_succeeds(
        self, db, make_user, make_space, make_membership, make_post, make_comment,
    ):
        space = make_space()
        author = make_user(role="user")
        make_membership(user=author, space=space)
        mod = make_user(role="user")
        make_membership(user=mod, space=space, role=SpaceRole.moderator)
        post = make_post(space=space, author=author)
        comment = make_comment(post=post, author=author)

        assert toggle_comment_reaction(
            slug=space.slug, post_id=post.id, comment_id=comment.id,
            emoji="❤️", db=db, current_user=mod,
        )["reacted"] is True


# ---------------------------------------------------------------------------
# SEC-005-C — upload_community_image
# ---------------------------------------------------------------------------

class _FakeUploadFile:
    """Minimal UploadFile duck-type sufficient for the handler's
    ``.read()``, ``.filename``, ``.content_type`` access. Backed by a
    small in-memory buffer so the tests don't touch disk."""
    def __init__(self, *, data: bytes = b"", filename: str = "img.jpg",
                 content_type: str = "image/jpeg") -> None:
        self._data = data
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._data


def _call_upload(handler_coro):
    """Run the async handler synchronously — mirrors the pattern used
    by ``test_password_reset_authz._call_forgot_password``."""
    return asyncio.run(handler_coro)


@pytest.fixture
def stub_save_media_file(monkeypatch):
    """Prevent real disk writes during upload tests. The handler still
    exercises the auth path in full; only the storage side-effect is
    stubbed."""
    def _fake_save(*, data, original_name, mime_type, space_slug):
        return (
            f"media/{space_slug}/x.jpg",
            f"/api/uploads/media/{space_slug}/x.jpg",
            "image",
            "x.jpg",
            len(data),
        )
    monkeypatch.setattr("app.community.routes.save_media_file", _fake_save)


class TestCommunityImageUploadAuthorization:
    def test_active_member_upload_succeeds(
        self, db, make_user, make_space, make_membership,
        stub_save_media_file,
    ):
        space = make_space()
        member = make_user(role="user")
        make_membership(user=member, space=space)

        result = _call_upload(upload_community_image(
            slug=space.slug,
            file=_FakeUploadFile(data=b"\x00" * 16),
            db=db, current_user=member,
        ))
        assert "url" in result
        assert space.slug in result["url"]

    def test_non_member_upload_rejected(
        self, db, make_user, make_space, stub_save_media_file,
    ):
        """SEC-005-C — pre-fix code let any authenticated user write
        into any Collective's storage namespace."""
        space = make_space()
        stranger = make_user(role="user")

        with pytest.raises(HTTPException) as exc:
            _call_upload(upload_community_image(
                slug=space.slug,
                file=_FakeUploadFile(data=b"\x00" * 16),
                db=db, current_user=stranger,
            ))
        assert exc.value.status_code == 403

    def test_removed_member_upload_rejected(
        self, db, make_user, make_space, make_membership,
        stub_save_media_file,
    ):
        space = make_space()
        removed = make_user(role="user")
        make_membership(user=removed, space=space,
                        status=SpaceMembershipStatus.removed)

        with pytest.raises(HTTPException) as exc:
            _call_upload(upload_community_image(
                slug=space.slug,
                file=_FakeUploadFile(data=b"\x00" * 16),
                db=db, current_user=removed,
            ))
        assert exc.value.status_code == 403

    def test_paused_member_upload_rejected(
        self, db, make_user, make_space, make_membership,
        stub_save_media_file,
    ):
        space = make_space()
        paused = make_user(role="user")
        make_membership(user=paused, space=space,
                        status=SpaceMembershipStatus.paused)

        with pytest.raises(HTTPException) as exc:
            _call_upload(upload_community_image(
                slug=space.slug,
                file=_FakeUploadFile(data=b"\x00" * 16),
                db=db, current_user=paused,
            ))
        assert exc.value.status_code == 403

    def test_moderator_caretaker_upload_succeeds(
        self, db, make_user, make_space, make_membership,
        stub_save_media_file,
    ):
        space = make_space()
        mod = make_user(role="user")
        make_membership(user=mod, space=space, role=SpaceRole.moderator)

        result = _call_upload(upload_community_image(
            slug=space.slug,
            file=_FakeUploadFile(data=b"\x00" * 16),
            db=db, current_user=mod,
        ))
        assert "url" in result

    def test_platform_admin_upload_succeeds_without_membership(
        self, db, make_user, make_space, stub_save_media_file,
    ):
        """Existing ``is_caretaker`` bypass — a platform admin is a
        caretaker of every Collective. Not being widened here; this
        test just pins the current behaviour so a future narrowing
        (e.g. under SEC-005-E) is deliberate."""
        space = make_space()
        admin = make_user(role="admin")

        result = _call_upload(upload_community_image(
            slug=space.slug,
            file=_FakeUploadFile(data=b"\x00" * 16),
            db=db, current_user=admin,
        ))
        assert "url" in result


# ---------------------------------------------------------------------------
# Cross-Collective IDOR regression matrix — adjacent community endpoints
# ---------------------------------------------------------------------------
# These endpoints already appeared correctly scoped in the SEC-005 audit
# (they use ``CommunityPost.space_id == space.id`` filters). The tests
# below lock that behaviour so a future refactor cannot silently drop
# the scope check.

class TestCrossCollectiveIDORMatrix:
    def test_hide_post_with_cross_collective_id_returns_404(
        self, db, two_spaces,
    ):
        with pytest.raises(HTTPException) as exc:
            hide_community_post(
                slug=two_spaces["space_a"].slug,
                post_id=two_spaces["post_b"].id,
                db=db, current_user=two_spaces["member_a"],
            )
        assert exc.value.status_code == 404
        # And the target post is still visible in its own Collective.
        db.refresh(two_spaces["post_b"])
        assert two_spaces["post_b"].is_visible is True

    def test_hide_comment_with_cross_collective_id_returns_404(
        self, db, two_spaces,
    ):
        with pytest.raises(HTTPException) as exc:
            hide_community_comment(
                slug=two_spaces["space_a"].slug,
                post_id=two_spaces["post_a"].id,
                comment_id=two_spaces["comment_b"].id,
                db=db, current_user=two_spaces["member_a"],
            )
        assert exc.value.status_code == 404
        db.refresh(two_spaces["comment_b"])
        assert two_spaces["comment_b"].is_visible is True

    def test_get_post_with_cross_collective_id_returns_404(
        self, db, two_spaces,
    ):
        with pytest.raises(HTTPException) as exc:
            get_community_post(
                slug=two_spaces["space_a"].slug,
                post_id=two_spaces["post_b"].id,
                db=db, current_user=two_spaces["member_a"],
            )
        assert exc.value.status_code == 404

    def test_create_comment_with_cross_collective_post_id_returns_404(
        self, db, two_spaces,
    ):
        with pytest.raises(HTTPException) as exc:
            create_comment(
                slug=two_spaces["space_a"].slug,
                post_id=two_spaces["post_b"].id,
                body=CreateCommentRequest(body="hello"),
                background_tasks=BackgroundTasks(),
                db=db, current_user=two_spaces["member_a"],
            )
        assert exc.value.status_code == 404
        assert db.query(PostComment).filter_by(
            post_id=two_spaces["post_b"].id,
        ).count() == 1  # just the original seeded comment_b, no new insert


class TestCommunityImageUploadIsImagesOnly:
    """``upload-image`` writes through ``save_media_file``, which is the
    shared Media Library writer and accepts documents, audio and video
    up to 250 MB. The composer's ``accept`` attribute is a file-picker
    hint, not a constraint, so the endpoint has to say what it means.
    """

    def _upload(self, db, user, space, **file_kw):
        return _call_upload(upload_community_image(
            slug=space.slug,
            file=_FakeUploadFile(data=b"\x00" * 16, **file_kw),
            db=db, current_user=user,
        ))

    @pytest.fixture
    def member_and_space(self, db, make_user, make_space, make_membership):
        space = make_space()
        member = make_user(role="user")
        make_membership(user=member, space=space)
        return member, space

    @pytest.mark.parametrize(
        "filename", ["photo.jpg", "photo.jpeg", "photo.PNG", "photo.webp"],
    )
    def test_permitted_image_types_are_accepted(
        self, db, member_and_space, stub_save_media_file, filename,
    ):
        member, space = member_and_space
        assert "url" in self._upload(db, member, space, filename=filename)

    @pytest.mark.parametrize(
        "filename",
        [
            "notes.pdf",      # document — 25 MB ceiling
            "clip.mp4",       # video — 250 MB ceiling
            "song.mp3",       # audio — 50 MB ceiling
            "sheet.xlsx",
            "drawing.svg",    # never permitted anywhere, and not sanitised
            "payload.html",
            "archive.zip",
            "noextension",
        ],
    )
    def test_everything_else_is_rejected(
        self, db, member_and_space, stub_save_media_file, filename,
    ):
        member, space = member_and_space
        with pytest.raises(HTTPException) as exc:
            self._upload(db, member, space, filename=filename)
        assert exc.value.status_code == 400

    def test_a_declared_image_content_type_does_not_launder_the_extension(
        self, db, member_and_space, stub_save_media_file,
    ):
        """The request says image/jpeg; the file is a .mp4. The
        extension decides, because the extension is what the stored key
        and every later reader go by."""
        member, space = member_and_space
        with pytest.raises(HTTPException) as exc:
            self._upload(
                db, member, space,
                filename="clip.mp4", content_type="image/jpeg",
            )
        assert exc.value.status_code == 400

    def test_the_stored_content_type_is_derived_not_echoed(
        self, db, member_and_space, monkeypatch,
    ):
        """What the browser claims is stored on the object and served
        back with it, so a .png announced as text/html would be served
        as text/html. The extension decides instead."""
        member, space = member_and_space
        seen: dict = {}

        def _fake_save(*, data, original_name, mime_type, space_slug):
            seen["mime_type"] = mime_type
            return ("k", "/api/uploads/k", "image", "k", len(data))

        monkeypatch.setattr("app.community.routes.save_media_file", _fake_save)
        self._upload(
            db, member, space,
            filename="photo.png", content_type="text/html",
        )
        assert seen["mime_type"] == "image/png"

    def test_rejection_happens_before_the_body_is_read(
        self, db, member_and_space, monkeypatch,
    ):
        """A 250 MB video should not be pulled into memory just to be
        turned away."""
        member, space = member_and_space
        read_called = {"yes": False}

        class _Watchful(_FakeUploadFile):
            async def read(self):
                read_called["yes"] = True
                return b""

        with pytest.raises(HTTPException):
            _call_upload(upload_community_image(
                slug=space.slug,
                file=_Watchful(filename="clip.mp4"),
                db=db, current_user=member,
            ))
        assert not read_called["yes"], "the file was read before rejection"

    def test_membership_is_still_checked_first(
        self, db, make_user, make_space, stub_save_media_file,
    ):
        """Type validation must not become a way to probe Collectives
        you are not in: a stranger gets 403 whatever they send."""
        space = make_space()
        stranger = make_user(role="user")
        for filename in ("photo.png", "clip.mp4"):
            with pytest.raises(HTTPException) as exc:
                self._upload(db, stranger, space, filename=filename)
            assert exc.value.status_code == 403, filename


class TestImageMimeTableAgrees:
    def test_every_permitted_image_extension_has_a_content_type(self):
        """``_IMAGE_MIME_BY_EXT`` is indexed directly after the
        extension check passes, so a new image type added to
        ``MEDIA_EXTENSION_MAP`` without a matching entry here would be a
        KeyError — a 500 on upload rather than a clear rejection."""
        from app.community.routes import _IMAGE_MIME_BY_EXT
        from app.core.storage import MEDIA_EXTENSION_MAP

        image_exts = {
            ext for ext, (kind, _max) in MEDIA_EXTENSION_MAP.items()
            if kind == "image"
        }
        assert image_exts == set(_IMAGE_MIME_BY_EXT), (
            "MEDIA_EXTENSION_MAP and _IMAGE_MIME_BY_EXT have drifted"
        )

    def test_svg_is_not_permitted_anywhere(self):
        from app.core.storage import MEDIA_EXTENSION_MAP
        assert ".svg" not in MEDIA_EXTENSION_MAP
