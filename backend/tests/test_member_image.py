"""The one resolver for "what picture goes next to this member's name?".

Two halves. The letter derivation and the fallback ladder are pure and
tested directly; the three defects this work item fixed are tested
through the API, because each of them was a defect precisely in how a
route behaved rather than in what a function returned.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_optional_user
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    CreatorProfile,
    PlatformArtwork,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.member_image import (
    NEUTRAL_CARD_KEY,
    MemberCardArtwork,
    MemberImageKind,
    alphabet_letter,
    member_card_key,
    resolve_member_image,
    visible_photo_url,
)


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    # Both, because member surfaces differ: the directory resolves its
    # viewer through ``get_optional_user`` so it can 404 an outsider,
    # while the profile route requires a signed-in caller.
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user


def _default_channel(db, space):
    """Every Collective has one; the mention-search endpoint refuses
    without it."""
    from app.models.platform import ConversationChannel
    c = ConversationChannel(
        id=str(uuid.uuid4()), space_id=space.id,
        name="Common Room", slug="common-room",
        is_default=True, is_system=True, channel_type="open",
    )
    db.add(c)
    db.flush()
    return c


def _profile(db, user, **kw):
    cp = CreatorProfile(user_id=user.id, **kw)
    db.add(cp)
    db.flush()
    return cp


def _join(db, user, space, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=str(uuid.uuid4()), user_id=user.id, space_id=space.id,
        role=role, status=SpaceMembershipStatus.active,
    ))
    db.flush()


def _install_cards(db, letters=(), neutral=False):
    for letter in letters:
        db.add(PlatformArtwork(
            key=member_card_key(letter),
            image_url=f"/api/uploads/platform-artwork/card_{letter.lower()}.png",
        ))
    if neutral:
        db.add(PlatformArtwork(
            key=NEUTRAL_CARD_KEY,
            image_url="/api/uploads/platform-artwork/card_neutral.png",
        ))
    db.flush()


# ---------------------------------------------------------------------------
# Deriving the letter
# ---------------------------------------------------------------------------

class TestAlphabetLetter:
    def test_a_plain_name(self):
        assert alphabet_letter("Sarah") == "S"

    def test_one_letter_not_two(self):
        """The card set has twenty-six entries; it cannot address "SJ"."""
        assert alphabet_letter("Sarah Jones") == "S"

    def test_lowercase_is_folded_up(self):
        assert alphabet_letter("sarah") == "S"

    def test_leading_whitespace_is_ignored(self):
        assert alphabet_letter("   Sarah") == "S"

    def test_accents_fold_to_their_base_letter(self):
        assert alphabet_letter("Émile") == "E"
        assert alphabet_letter("Ólafur") == "O"
        assert alphabet_letter("Ångström") == "A"

    def test_a_name_with_no_latin_initial_has_no_letter(self):
        """Permanent category, not a failure — these take the neutral
        card."""
        for name in ("翔", "Дмитрий", "🌱 moss", "7 Wonders", "—", "!!"):
            assert alphabet_letter(name) is None, name

    def test_no_name_has_no_letter(self):
        assert alphabet_letter(None) is None
        assert alphabet_letter("") is None
        assert alphabet_letter("   ") is None

    def test_it_does_not_hunt_past_a_non_letter(self):
        """"7 Wonders" is not a W. Reaching deeper into the string for a
        letter would surprise the person it belongs to."""
        assert alphabet_letter("7 Wonders") is None


# ---------------------------------------------------------------------------
# Visibility of the uploaded photo
# ---------------------------------------------------------------------------

class TestPhotoVisibility:
    def test_a_public_profile_with_a_photo_shows_it(self, db, make_user):
        cp = _profile(db, make_user(), avatar_url="/api/uploads/avatars/a.png",
                      is_public=True)
        assert visible_photo_url(cp) == "/api/uploads/avatars/a.png"

    def test_a_private_profile_does_not(self, db, make_user):
        cp = _profile(db, make_user(), avatar_url="/api/uploads/avatars/a.png",
                      is_public=False)
        assert visible_photo_url(cp) is None

    def test_no_profile_at_all(self):
        assert visible_photo_url(None) is None

    def test_a_public_profile_with_no_photo(self, db, make_user):
        assert visible_photo_url(_profile(db, make_user(), is_public=True)) is None


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------

class TestTheLadder:
    def test_a_visible_photo_wins(self, db, make_user):
        _install_cards(db, letters=("S",), neutral=True)
        cp = _profile(db, make_user(), avatar_url="/api/uploads/avatars/a.png",
                      is_public=True)
        image = resolve_member_image(
            display_name="Sarah", profile=cp,
            artwork=MemberCardArtwork.load(db),
        )
        assert image.kind is MemberImageKind.PHOTO
        assert image.url == "/api/uploads/avatars/a.png"
        assert image.initial == "S", "the letter rides along as alt text"

    def test_the_alphabet_card_comes_next(self, db, make_user):
        _install_cards(db, letters=("S",), neutral=True)
        image = resolve_member_image(
            display_name="Sarah", profile=None,
            artwork=MemberCardArtwork.load(db),
        )
        assert image.kind is MemberImageKind.ALPHABET
        assert image.url.endswith("card_s.png")

    def test_a_private_photo_falls_to_the_card(self, db, make_user):
        """The card is platform artwork and is not gated by the member's
        visibility setting — so a private member still gets a designed
        square rather than a bare letter."""
        _install_cards(db, letters=("S",))
        cp = _profile(db, make_user(), avatar_url="/api/uploads/avatars/a.png",
                      is_public=False)
        image = resolve_member_image(
            display_name="Sarah", profile=cp,
            artwork=MemberCardArtwork.load(db),
        )
        assert image.kind is MemberImageKind.ALPHABET

    def test_no_usable_letter_takes_the_neutral_card(self, db):
        _install_cards(db, letters=("S",), neutral=True)
        image = resolve_member_image(
            display_name="翔", profile=None,
            artwork=MemberCardArtwork.load(db),
        )
        assert image.kind is MemberImageKind.NEUTRAL
        assert image.url.endswith("card_neutral.png")
        assert image.initial is None

    def test_an_unnamed_member_takes_the_neutral_card(self, db):
        _install_cards(db, neutral=True)
        image = resolve_member_image(
            display_name=None, profile=None,
            artwork=MemberCardArtwork.load(db),
        )
        assert image.kind is MemberImageKind.NEUTRAL

    def test_a_missing_letter_card_falls_through_to_neutral(self, db):
        """Only some of A–Z installed. A member whose letter is absent
        gets the neutral card rather than a broken image."""
        _install_cards(db, letters=("A",), neutral=True)
        image = resolve_member_image(
            display_name="Zoe", profile=None,
            artwork=MemberCardArtwork.load(db),
        )
        assert image.kind is MemberImageKind.NEUTRAL

    def test_with_no_artwork_installed_everyone_gets_a_letter(self, db):
        """Today's state: the assets are not supplied, so the ladder
        bottoms out at the initial and the surfaces look as they did."""
        image = resolve_member_image(
            display_name="Sarah", profile=None,
            artwork=MemberCardArtwork.load(db),
        )
        assert image.kind is MemberImageKind.INITIAL
        assert image.url is None
        assert image.initial == "S"

    def test_a_row_with_no_image_url_does_not_count_as_installed(self, db):
        """An artwork slot can exist before its file does."""
        db.add(PlatformArtwork(key=member_card_key("S"), image_url=None))
        db.flush()
        image = resolve_member_image(
            display_name="Sarah", profile=None,
            artwork=MemberCardArtwork.load(db),
        )
        assert image.kind is MemberImageKind.INITIAL

    def test_none_artwork_is_a_usable_empty(self):
        image = resolve_member_image(
            display_name="Sarah", profile=None,
            artwork=MemberCardArtwork.none(),
        )
        assert image.kind is MemberImageKind.INITIAL


# ---------------------------------------------------------------------------
# Defect 1 — a photo must not make somebody a Creator
# ---------------------------------------------------------------------------

class TestAProfileRowIsNotCreatorhood:
    def test_an_ordinary_member_with_a_profile_row_is_not_a_creator(
        self, client, db, make_user, make_space
    ):
        """The defect: ``is_creator`` was ``cp is not None``, and every
        member who uploads a photo gets a ``cp``. Setting a profile
        picture awarded a Creator badge."""
        member = make_user(role="user", name="Ordinary")
        _profile(db, member, avatar_url="/api/uploads/avatars/a.png",
                 is_public=True)
        as_user(make_user())

        body = client.get(f"/api/profile/{member.id}").json()

        assert body["is_creator"] is False
        assert body["spaces_led"] == []

    def test_a_real_creator_still_reads_as_one(
        self, client, db, make_user, make_space
    ):
        creator = make_user(role="creator", name="Real Creator")
        make_space(creator=creator, name="Their Collective")
        as_user(make_user())

        body = client.get(f"/api/profile/{creator.id}").json()

        assert body["is_creator"] is True
        assert "Their Collective" in body["spaces_led"]

    def test_a_creator_whose_role_was_cancelled_is_not_one(
        self, client, db, make_user
    ):
        from datetime import datetime
        gone = make_user(role="creator", creator_cancelled_at=datetime.utcnow())
        as_user(make_user())

        assert client.get(f"/api/profile/{gone.id}").json()["is_creator"] is False

    def test_collectives_led_no_longer_depends_on_having_a_profile(
        self, client, db, make_user, make_space
    ):
        """Previously ``spaces_led`` was only computed when a profile row
        existed, so a Creator who never filled one in led nothing."""
        creator = make_user(role="creator", name="No Profile")
        make_space(creator=creator, name="Still Theirs")
        as_user(make_user())

        body = client.get(f"/api/profile/{creator.id}").json()

        assert body["spaces_led"] == ["Still Theirs"]

    def test_the_collective_directory_agrees(
        self, client, db, make_user, make_space
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner, show_member_directory=True)
        member = make_user(role="user", name="Ordinary")
        _profile(db, member, avatar_url="/api/uploads/avatars/a.png", is_public=True)
        for u in (owner, member):
            _join(db, u, space)
        as_user(member)

        rows = client.get(f"/api/spaces/{space.slug}/members").json()
        by_name = {r["display_name"]: r for r in rows}

        assert by_name["Ordinary"]["is_creator"] is False


# ---------------------------------------------------------------------------
# Defect 2 — visibility must not depend on the order of two actions
# ---------------------------------------------------------------------------

class TestVisibilityIsOrderIndependent:
    """Four routes to the same place; all four must end up private.

    A member is private until they say otherwise, whatever order they
    save their profile and upload a photo in.
    """

    def _png(self):
        # Smallest thing the endpoint will accept as an image.
        return (
            "avatar.png",
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
            "image/png",
        )

    def test_saving_the_profile_first_leaves_it_private(
        self, client, db, make_user
    ):
        member = make_user(role="user")
        as_user(member)

        res = client.patch("/api/auth/me", json={
            "name": "Ordinary", "bio": "hello", "is_public": False,
        })

        assert res.status_code == 200
        assert res.json()["is_public"] is False

    def test_uploading_a_photo_first_leaves_it_private(
        self, client, db, make_user
    ):
        """The one that was wrong: the column's server default is true,
        so a row created without naming ``is_public`` came out public."""
        member = make_user(role="user")
        as_user(member)

        res = client.post("/api/auth/me/avatar", files={"file": self._png()})

        assert res.status_code == 200
        assert res.json()["is_public"] is False

    def test_uploading_then_saving_leaves_it_private(
        self, client, db, make_user
    ):
        member = make_user(role="user")
        as_user(member)

        client.post("/api/auth/me/avatar", files={"file": self._png()})
        res = client.patch("/api/auth/me", json={"bio": "hello"})

        assert res.json()["is_public"] is False

    def test_saving_then_uploading_leaves_it_private(
        self, client, db, make_user
    ):
        member = make_user(role="user")
        as_user(member)

        client.patch("/api/auth/me", json={"bio": "hello"})
        res = client.post("/api/auth/me/avatar", files={"file": self._png()})

        assert res.json()["is_public"] is False

    def test_explicitly_going_public_is_honoured(self, client, db, make_user):
        member = make_user(role="user")
        as_user(member)

        client.post("/api/auth/me/avatar", files={"file": self._png()})
        res = client.patch("/api/auth/me", json={"is_public": True})

        assert res.json()["is_public"] is True

    def test_a_private_members_photo_is_not_shown_to_others(
        self, client, db, make_user
    ):
        member = make_user(role="user", name="Quiet")
        as_user(member)
        client.post("/api/auth/me/avatar", files={"file": self._png()})

        as_user(make_user())
        body = client.get(f"/api/profile/{member.id}").json()

        assert body["avatar_url"] is None
        assert body["image"]["kind"] != "photo"


# ---------------------------------------------------------------------------
# Defect 3 — the settings page returned 500 for members without a row
# ---------------------------------------------------------------------------

class TestLazyProfileCreationWorks:
    def test_saving_profile_fields_without_an_existing_row_succeeds(
        self, client, db, make_user
    ):
        """``creator_profiles`` is keyed on ``user_id`` and has no ``id``
        column; both creation paths passed one, so every member without a
        profile row got a 500 from their own settings page."""
        member = make_user(role="user")
        as_user(member)

        res = client.patch("/api/auth/me", json={
            "bio": "hello", "profile_tagline": "tag", "is_public": False,
        })

        assert res.status_code == 200
        assert res.json()["bio"] == "hello"

    def test_uploading_an_avatar_without_an_existing_row_succeeds(
        self, client, db, make_user
    ):
        member = make_user(role="user")
        as_user(member)

        res = client.post("/api/auth/me/avatar", files={
            "file": ("a.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png"),
        })

        assert res.status_code == 200
        assert res.json()["avatar_url"] is not None

    def test_exactly_one_profile_row_is_created(self, client, db, make_user):
        member = make_user(role="user")
        as_user(member)

        client.patch("/api/auth/me", json={"bio": "one"})
        client.post("/api/auth/me/avatar", files={
            "file": ("a.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png"),
        })
        client.patch("/api/auth/me", json={"bio": "two"})

        rows = db.query(CreatorProfile).filter(
            CreatorProfile.user_id == member.id
        ).all()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Every surface answers the same way
# ---------------------------------------------------------------------------

class TestSurfacesAgree:
    def test_the_directory_and_the_profile_resolve_the_same_image(
        self, client, db, make_user, make_space
    ):
        _install_cards(db, letters=("O",), neutral=True)
        owner = make_user(role="creator")
        space = make_space(creator=owner, show_member_directory=True)
        member = make_user(role="user", name="Ordinary")
        for u in (owner, member):
            _join(db, u, space)
        as_user(member)

        directory = {
            r["display_name"]: r
            for r in client.get(f"/api/spaces/{space.slug}/members").json()
        }
        profile = client.get(f"/api/profile/{member.id}").json()

        assert directory["Ordinary"]["image"] == profile["image"]
        assert profile["image"]["kind"] == "alphabet"

    def test_mention_suggestions_now_resolve_an_image(
        self, client, db, make_user, make_space
    ):
        """This endpoint read ``avatar_url`` off ``User``, which has no
        such column, so it always returned nothing."""
        _install_cards(db, letters=("M",), neutral=True)
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        member = make_user(role="user", name="Mentionable")
        for u in (owner, member):
            _join(db, u, space)
        as_user(owner)

        _default_channel(db, space)
        rows = client.get(
            f"/api/spaces/{space.slug}/members/search", params={"q": "Mention"},
        ).json()

        assert rows, "the member should be suggested"
        assert rows[0]["image"]["kind"] == "alphabet"
        assert rows[0]["image"]["url"].endswith("card_m.png")
