"""``/community/search`` reaches the search handler, not the post lookup.

The route was declared after ``/{slug}/community/{post_id}``, and FastAPI
matches in declaration order, so the literal path ``/community/search``
was captured as a post id and answered 404 "Post not found" — while
``CommunitySearch.tsx`` called it. Nothing failed loudly; search simply
never worked.

The ordering itself is the regression, so the first test asserts the
handler was actually reached rather than merely that a 200 came back, and
the second proves a genuine post id still resolves — a fix that broke
that would be worse than the bug.

The rest of the file is the coverage this endpoint never had, now that it
can run at all: author labels come from the canonical ladder, and no
member's email address appears in a result.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_verified_current_user
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    CreatorProfile,
    PostComment,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.member_identity import NEUTRAL_DISPLAY_NAME

AUTHOR_EMAIL = "searchable.person.1985@her-own-domain.test"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_current_user] = lambda: user


def _join(db, user, space, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=role, status=SpaceMembershipStatus.active,
    ))
    db.flush()


@pytest.fixture
def searchable(db, make_user, make_space):
    """A Collective with one post and one comment by an unnamed author."""
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
        channel_id=channel.id, title="On tending a garden",
        body="Something about marigolds", post_type="discussion",
        publication_status="published", is_visible=True,
    )
    db.add(post)
    db.flush()
    db.add(PostComment(id=_uid("pc"), post_id=post.id, author_id=author.id,
                       body="I grow marigolds too", is_visible=True))
    db.commit()
    return space, author, reader, post


# ---------------------------------------------------------------------------
# The routing itself
# ---------------------------------------------------------------------------

class TestTheRouteReachesTheSearchHandler:
    def test_search_is_not_read_as_a_post_id(self, client, searchable):
        """The regression. It answered 404 "Post not found"."""
        space, _author, reader, _post = searchable
        as_user(reader)

        res = client.get(
            f"/api/spaces/{space.slug}/community/search", params={"q": "marigolds"}
        )

        assert res.status_code == 200, res.text
        # Shape proves *which* handler ran: the post lookup returns a post,
        # never a query/total/hits envelope.
        assert set(res.json()) == {"query", "total", "hits"}
        assert res.json()["query"] == "marigolds"

    def test_the_search_handler_actually_finds_things(self, client, searchable):
        space, _author, reader, post = searchable
        as_user(reader)

        body = client.get(
            f"/api/spaces/{space.slug}/community/search", params={"q": "marigolds"}
        ).json()

        assert body["total"] >= 1
        assert {h["post_id"] for h in body["hits"]} == {post.id}
        assert {h["kind"] for h in body["hits"]} == {"post", "comment"}

    def test_a_genuine_post_id_still_resolves(self, client, searchable):
        """The parameterised route must still work; a fix that shadowed
        posts instead would be a worse bug than the one it replaced."""
        space, _author, reader, post = searchable
        as_user(reader)

        res = client.get(f"/api/spaces/{space.slug}/community/{post.id}")

        assert res.status_code == 200, res.text
        assert res.json()["id"] == post.id
        assert res.json()["title"] == "On tending a garden"

    def test_an_unknown_post_id_is_still_a_404(self, client, searchable):
        space, _author, reader, _post = searchable
        as_user(reader)

        res = client.get(f"/api/spaces/{space.slug}/community/cp_nope")

        assert res.status_code == 404

    def test_the_declaration_order_is_the_thing_under_test(self):
        """Pinned directly, so a future reordering fails here and explains
        itself rather than silently breaking search again."""
        paths = [getattr(r, "path", "") for r in app.routes]
        assert paths.index("/api/spaces/{slug}/community/search") < paths.index(
            "/api/spaces/{slug}/community/{post_id}"
        )


# ---------------------------------------------------------------------------
# What results say, now that they can be reached
# ---------------------------------------------------------------------------

class TestWhatResultsDisclose:
    def test_no_author_email_in_results(self, client, searchable):
        space, _author, reader, _post = searchable
        as_user(reader)

        res = client.get(
            f"/api/spaces/{space.slug}/community/search", params={"q": "marigolds"}
        )

        assert res.status_code == 200
        assert AUTHOR_EMAIL not in res.text
        assert "searchable.person" not in res.text

    def test_an_unnamed_author_reads_as_the_neutral_label(self, client, searchable):
        space, _author, reader, _post = searchable
        as_user(reader)

        body = client.get(
            f"/api/spaces/{space.slug}/community/search", params={"q": "marigolds"}
        ).json()

        assert {h["author_name"] for h in body["hits"]} == {NEUTRAL_DISPLAY_NAME}

    def test_a_hit_is_named_the_same_as_the_post_it_opens(
        self, client, db, searchable
    ):
        """Search names an author from ``User.name``, not from a public
        profile's display name — matching ``PostAuthor`` on the post the
        hit links to, and matching what the query itself filters on. A
        result that read "Marigold Grower" and opened a post signed
        "Member" would be worse than either.
        """
        space, author, reader, post = searchable
        db.add(CreatorProfile(user_id=author.id, display_name="Marigold Grower",
                              is_public=True))
        db.commit()
        as_user(reader)

        hits = client.get(
            f"/api/spaces/{space.slug}/community/search", params={"q": "marigolds"}
        ).json()["hits"]
        on_the_post = client.get(
            f"/api/spaces/{space.slug}/community/{post.id}"
        ).json()["author"]["display_name"]

        assert {h["author_name"] for h in hits} == {on_the_post}
        assert on_the_post == NEUTRAL_DISPLAY_NAME

    def test_searching_by_author_name_reveals_no_address(
        self, client, db, make_user, make_space
    ):
        """The author-match branch chose its excerpt from
        ``author.name or author.email``."""
        space = make_space()
        author = make_user(name="Wilhelmina", email=AUTHOR_EMAIL)
        reader = make_user(name="Reader")
        _join(db, author, space)
        _join(db, reader, space)
        channel = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Common Room",
            slug="common-room", is_default=True, is_system=True, channel_type="open",
        )
        db.add(channel)
        db.flush()
        db.add(CommunityPost(
            id=_uid("cp"), space_id=space.id, author_id=author.id,
            channel_id=channel.id, title="A title", body="A body",
            post_type="discussion", publication_status="published",
            is_visible=True,
        ))
        db.commit()
        as_user(reader)

        res = client.get(
            f"/api/spaces/{space.slug}/community/search",
            params={"q": "Wilhelmina"},
        )

        assert res.status_code == 200, res.text
        assert res.json()["total"] >= 1
        assert [h["match_field"] for h in res.json()["hits"]] == ["author"]
        assert AUTHOR_EMAIL not in res.text
        assert "searchable.person" not in res.text

    def test_an_outsider_cannot_search(self, client, searchable, make_user, db):
        space, _author, _reader, _post = searchable
        db.commit()
        as_user(make_user(name="Outsider"))

        res = client.get(
            f"/api/spaces/{space.slug}/community/search", params={"q": "marigolds"}
        )

        assert res.status_code == 404

    def test_an_empty_query_is_an_empty_result_not_an_error(
        self, client, searchable
    ):
        space, _author, reader, _post = searchable
        as_user(reader)

        res = client.get(f"/api/spaces/{space.slug}/community/search")

        assert res.status_code == 200
        assert res.json() == {"query": "", "total": 0, "hits": []}

    def test_the_hit_field_set(self, client, searchable):
        space, _author, reader, _post = searchable
        as_user(reader)

        hit = client.get(
            f"/api/spaces/{space.slug}/community/search", params={"q": "marigolds"}
        ).json()["hits"][0]

        assert set(hit) == {
            "kind", "post_id", "post_type", "post_title",
            "author_name", "excerpt", "created_at", "match_field",
        }
