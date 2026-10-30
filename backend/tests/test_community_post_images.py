"""Several images on one Conversation post.

``community_posts.image_url`` held one URL, so sharing a handful of
photographs meant publishing a post and adding the rest as replies.
``image_urls`` sits beside it: the list is the truth, ``image_url``
keeps its first entry, and every read resolves ``image_urls or
[image_url]`` in one place.

The half worth testing is the compatibility: a post written before the
column existed must read back exactly as it did, and a client that
still sends a single ``image_url`` must behave exactly as it did. The
other half is the boundary — five, and only files this Collective
actually holds.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_verified_current_user
from app.community.routes import MAX_POST_IMAGES, post_images
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_current_user] = lambda: user


@pytest.fixture
def collective(db, make_user, make_space):
    creator = make_user(role="creator", name="Ada Leader")
    space = make_space(creator=creator)
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=creator.id, space_id=space.id,
        role=SpaceRole.creator, status=SpaceMembershipStatus.active,
    ))
    member = make_user(name="Mem Ber")
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=member.id, space_id=space.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
    ))
    # Posts land in a Channel; the default one is what the composer
    # targets when none is named.
    db.add(ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="Common Room",
        slug="common-room", is_default=True, is_system=True,
        is_archived=False, channel_type="open",
        member_posting_allowed=True, comments_allowed=True,
    ))
    db.commit()
    return space, creator, member


def img(slug: str, n: int) -> str:
    return f"/api/uploads/media/{slug}/community/photo{n}.jpg"


# ---------------------------------------------------------------------------
# Reading — the fallback, applied once
# ---------------------------------------------------------------------------

class TestHowImagesAreRead:
    def test_a_post_from_before_the_column_reads_as_one_image(self):
        legacy = CommunityPost(image_url="/api/uploads/media/x/community/old.jpg")
        legacy.image_urls = None
        assert post_images(legacy) == ["/api/uploads/media/x/community/old.jpg"]

    def test_a_text_only_post_has_no_images(self):
        post = CommunityPost(image_url=None)
        post.image_urls = None
        assert post_images(post) == []

    def test_the_list_wins_when_both_are_set(self):
        post = CommunityPost(image_url="/a.jpg")
        post.image_urls = ["/one.jpg", "/two.jpg"]
        assert post_images(post) == ["/one.jpg", "/two.jpg"]

    def test_an_empty_list_falls_back_rather_than_hiding_the_image(self):
        post = CommunityPost(image_url="/a.jpg")
        post.image_urls = []
        assert post_images(post) == ["/a.jpg"]

    def test_order_is_the_order_it_was_given(self):
        post = CommunityPost(image_url=None)
        post.image_urls = ["/c.jpg", "/a.jpg", "/b.jpg"]
        assert post_images(post) == ["/c.jpg", "/a.jpg", "/b.jpg"]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

class TestPostingImages:
    def _post(self, client, space, **extra):
        return client.post(
            f"/api/spaces/{space.slug}/community",
            json={"body": "Look at these.", **extra},
        )

    def test_a_text_only_post_is_unchanged(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        res = self._post(client, space, body="Just words.")
        assert res.status_code in (200, 201)
        assert res.json()["image_url"] is None
        assert res.json()["image_urls"] == []

    def test_one_image(self, client, db, collective):
        space, _creator, member = collective
        as_user(member)
        res = self._post(client, space, image_urls=[img(space.slug, 1)])
        assert res.status_code in (200, 201)
        body = res.json()
        assert body["image_urls"] == [img(space.slug, 1)]
        # The old column carries the first image, so nothing reading it
        # has to change.
        assert body["image_url"] == img(space.slug, 1)

    def test_two_images(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        urls = [img(space.slug, 1), img(space.slug, 2)]
        res = self._post(client, space, image_urls=urls)
        assert res.json()["image_urls"] == urls
        assert res.json()["image_url"] == urls[0]

    def test_five_images(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        urls = [img(space.slug, n) for n in range(1, 6)]
        res = self._post(client, space, image_urls=urls)
        assert res.status_code in (200, 201)
        assert res.json()["image_urls"] == urls

    def test_six_is_refused(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        urls = [img(space.slug, n) for n in range(1, 7)]
        res = self._post(client, space, image_urls=urls)
        assert res.status_code == 422
        assert str(MAX_POST_IMAGES) in res.json()["detail"]

    def test_an_older_client_sending_only_image_url_still_works(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        res = self._post(client, space, image_url=img(space.slug, 9))
        assert res.status_code in (200, 201)
        assert res.json()["image_url"] == img(space.slug, 9)
        assert res.json()["image_urls"] == [img(space.slug, 9)]

    def test_the_same_file_twice_is_collapsed(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        one = img(space.slug, 1)
        res = self._post(client, space, image_urls=[one, one, img(space.slug, 2)])
        assert res.json()["image_urls"] == [one, img(space.slug, 2)]

    def test_blank_entries_are_dropped(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        res = self._post(client, space, image_urls=["", "  ", img(space.slug, 1)])
        assert res.json()["image_urls"] == [img(space.slug, 1)]


# ---------------------------------------------------------------------------
# You may only attach what this Collective holds
# ---------------------------------------------------------------------------

class TestYouCannotAttachSomebodyElsesFile:
    def _post(self, client, space, urls):
        return client.post(
            f"/api/spaces/{space.slug}/community",
            json={"body": "Look.", "image_urls": urls},
        )

    def test_a_file_from_another_collective_is_refused(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        res = self._post(client, space, ["/api/uploads/media/other-place/community/x.jpg"])
        assert res.status_code == 422
        assert "uploaded to this Collective" in res.json()["detail"]

    def test_a_path_outside_the_community_namespace_is_refused(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        res = self._post(client, space, [f"/api/uploads/media/{space.slug}/logos/x.jpg"])
        assert res.status_code == 422

    def test_an_absolute_url_elsewhere_is_refused(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        res = self._post(client, space, ["https://example.org/evil.jpg"])
        assert res.status_code == 422

    def test_a_traversal_attempt_is_refused(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        res = self._post(
            client, space,
            [f"/api/uploads/media/{space.slug}/community/../../other/x.jpg"],
        )
        # ``..`` satisfies the prefix and still names a file outside
        # it, so the prefix alone is not enough.
        assert res.status_code == 422

    def test_the_rule_applies_to_the_legacy_single_field_too(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        res = client.post(
            f"/api/spaces/{space.slug}/community",
            json={"body": "Look.", "image_url": "/api/uploads/media/elsewhere/community/x.jpg"},
        )
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# Everything else about a post is untouched
# ---------------------------------------------------------------------------

class TestNothingElseChanged:
    def test_the_feed_and_the_detail_agree(self, client, db, collective):
        space, _creator, member = collective
        as_user(member)
        urls = [img(space.slug, 1), img(space.slug, 2), img(space.slug, 3)]
        created = client.post(
            f"/api/spaces/{space.slug}/community",
            json={"body": "Three.", "image_urls": urls},
        ).json()

        detail = client.get(f"/api/spaces/{space.slug}/community/{created['id']}")
        assert detail.status_code == 200
        assert detail.json()["image_urls"] == urls

    def test_a_legacy_row_renders_through_the_api(self, client, db, collective):
        """A post as the database held it before this change."""
        space, _creator, member = collective
        row = db.query(CommunityPost).filter(
            CommunityPost.space_id == space.id).first()
        if row is None:
            as_user(member)
            created = client.post(
                f"/api/spaces/{space.slug}/community",
                json={"body": "Legacy.", "image_url": img(space.slug, 7)},
            ).json()
            row = db.query(CommunityPost).filter(CommunityPost.id == created["id"]).one()
        # Exactly what an un-migrated row looks like.
        row.image_urls = None
        row.image_url = img(space.slug, 7)
        db.commit()

        as_user(member)
        detail = client.get(f"/api/spaces/{space.slug}/community/{row.id}")
        assert detail.status_code == 200
        assert detail.json()["image_url"] == img(space.slug, 7)
        assert detail.json()["image_urls"] == [img(space.slug, 7)]

    def test_comments_are_out_of_scope_and_unchanged(self):
        from app.community.schemas import CreateCommentRequest

        fields = CreateCommentRequest.model_fields
        assert "image_url" in fields
        assert "image_urls" not in fields, "replies were deliberately left alone"
