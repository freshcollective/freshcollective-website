"""No member ever receives another member's email address.

``PostAuthor`` and ``StepCommentAuthor`` both declared ``email: str`` as
a serialised field, populated from the author's ``User`` row. Every
member who could read a post, a comment, a search result or a Pathway
step discussion therefore received the full email address of everyone
who had written in it — not the local part, the whole address. The field
existed only so a computed ``display_name`` could fall back to
``email.split("@")[0]``, and the frontend's step-discussion avatar read
it directly to derive initials.

These tests read the payloads as an ordinary member and assert the
author's address is absent. They deliberately assert on the *whole
serialised body* rather than on a named key, because the defect was a
field nobody meant to send.

Creator Studio is not covered here, and deliberately not changed: a
creator legitimately holds member contact details, and
``test_creator_member_email_still_available`` at the end pins that the
tightening did not reach those endpoints.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import (
    get_current_user,
    get_optional_user,
    get_verified_current_user,
)
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    Pathway,
    PathwayStep,
    PostComment,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)

#: The address that must never appear. Distinctive so a substring test
#: cannot pass by accident.
AUTHOR_EMAIL = "wrote.the.post.1985@her-own-domain.test"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_verified_current_user] = lambda: user


def _join(db, user, space, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=role, status=SpaceMembershipStatus.active,
    ))
    db.flush()


@pytest.fixture
def community(db, make_user, make_space):
    """A Collective with a post and a comment, both by an unnamed author.

    Unnamed on purpose: that is the case the removed field was there to
    serve, so it is the case most likely to leak the address.
    """
    space = make_space()
    author = make_user(name=None, email=AUTHOR_EMAIL)
    reader = make_user(name="Reader")
    _join(db, author, space)
    _join(db, reader, space)

    channel = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="Common Room",
        slug="common-room", is_default=True, is_system=True, channel_type="open",
    )
    db.add(channel)
    db.flush()

    post = CommunityPost(
        id=_uid("cp"), space_id=space.id, author_id=author.id,
        channel_id=channel.id, title="Something I noticed",
        body="A body worth searching for", post_type="discussion",
    )
    db.add(post)
    db.flush()
    db.add(PostComment(id=_uid("pc"), post_id=post.id,
                       author_id=author.id, body="And a comment"))
    db.commit()
    return space, author, reader, post


class TestCommunityPayloads:
    def test_the_post_list_carries_no_address(self, client, community):
        space, author, reader, _post = community
        as_user(reader)

        res = client.get(f"/api/spaces/{space.slug}/community")

        assert res.status_code == 200
        assert AUTHOR_EMAIL not in res.text
        assert "wrote.the.post" not in res.text

    def test_the_post_detail_carries_no_address(self, client, community):
        space, author, reader, post = community
        as_user(reader)

        res = client.get(f"/api/spaces/{space.slug}/community/{post.id}")

        assert res.status_code == 200
        assert AUTHOR_EMAIL not in res.text
        assert "wrote.the.post" not in res.text

    def test_the_author_field_set_is_exactly_id_name_display_name(
        self, client, community
    ):
        space, _author, reader, post = community
        as_user(reader)

        body = client.get(f"/api/spaces/{space.slug}/community/{post.id}").json()

        assert set(body["author"]) == {"id", "name", "display_name"}

    def test_an_unnamed_author_reads_as_the_neutral_label(self, client, community):
        space, _author, reader, post = community
        as_user(reader)

        body = client.get(f"/api/spaces/{space.slug}/community/{post.id}").json()

        assert body["author"]["display_name"] == "Member"

    def test_comment_authors_carry_no_address_either(self, client, community):
        space, _author, reader, post = community
        as_user(reader)

        body = client.get(f"/api/spaces/{space.slug}/community/{post.id}").json()

        assert body["comments"], "fixture no longer produces a comment"
        for comment in body["comments"]:
            assert set(comment["author"]) == {"id", "name", "display_name"}

    # Community search is deliberately not covered here.
    # ``GET /api/spaces/{slug}/community/search`` is unreachable: it is
    # registered after ``/{slug}/community/{post_id}``, so FastAPI matches
    # "search" as a post id and answers 404 "Post not found". The handler's
    # author names were tightened along with the rest, but no test can
    # exercise them until the route ordering is fixed — a separate defect,
    # not folded into this one.
    def test_a_comment_you_write_yourself_returns_no_address(
        self, client, community
    ):
        """The write path builds its own author payload, so it is a second
        place the field had to be removed."""
        space, _author, reader, post = community
        as_user(reader)

        res = client.post(
            f"/api/spaces/{space.slug}/community/{post.id}/comments",
            json={"body": "Replying"},
        )

        assert res.status_code in (200, 201), res.text
        assert "@" not in res.json()["author"].get("display_name", "")
        assert set(res.json()["author"]) == {"id", "name", "display_name"}


class TestPathwayStepDiscussion:
    @pytest.fixture
    def step_discussion(self, db, make_user, make_space):
        space = make_space()
        author = make_user(name=None, email=AUTHOR_EMAIL)
        reader = make_user(name="Reader")
        _join(db, author, space)
        _join(db, reader, space)

        pathway = Pathway(
            id=_uid("p"), space_id=space.id, slug="the-path",
            title="The Path", status="active", position=0,
        )
        db.add(pathway)
        db.flush()
        step = PathwayStep(
            id=_uid("st"), pathway_id=pathway.id, slug="welcome",
            title="Welcome", content_type="text", position=0,
        )
        db.add(step)
        db.flush()
        from app.models.platform import StepComment

        db.add(StepComment(id=_uid("sc"), step_id=step.id,
                           author_id=author.id, body="First thought",
                           is_visible=True))
        db.commit()
        return space, pathway, step, reader

    def test_listing_step_comments_carries_no_address(
        self, client, step_discussion
    ):
        space, pathway, step, reader = step_discussion
        as_user(reader)

        res = client.get(
            f"/api/spaces/{space.slug}/pathways/{pathway.slug}"
            f"/steps/{step.slug}/comments"
        )

        assert res.status_code == 200, res.text
        assert AUTHOR_EMAIL not in res.text
        assert "wrote.the.post" not in res.text
        assert set(res.json()[0]["author"]) == {"id", "name", "display_name"}
        assert res.json()[0]["author"]["display_name"] == "Member"

    def test_writing_a_step_comment_returns_no_address(
        self, client, step_discussion
    ):
        space, pathway, step, reader = step_discussion
        as_user(reader)

        res = client.post(
            f"/api/spaces/{space.slug}/pathways/{pathway.slug}"
            f"/steps/{step.slug}/comments",
            json={"body": "My thought"},
        )

        assert res.status_code in (200, 201), res.text
        assert set(res.json()["author"]) == {"id", "name", "display_name"}


class TestCreatorStudioIsUnchanged:
    def test_creator_member_email_still_available(
        self, client, db, make_user, make_space
    ):
        """A creator legitimately holds member contact details. This
        tightening was about member-facing payloads and must not have
        reached the administrative ones."""
        creator = make_user(role="creator", name="The Creator")
        space = make_space(creator=creator)
        member = make_user(name="A Member", email="member@example.test")
        _join(db, member, space)
        db.commit()
        as_user(creator)

        res = client.get(f"/api/creator/spaces/{space.slug}/members")

        assert res.status_code == 200, res.text
        assert "member@example.test" in res.text
