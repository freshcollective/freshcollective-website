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
from app.models.connections import MemberHello
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


def _entitled_viewer(db, make_user, make_space, target):
    """A signed-in viewer who may legitimately read ``target``'s profile.

    These tests are about what a profile *says*, not about who may read
    it — ``member_visibility`` decides that, and
    ``test_member_profile_access`` pins it. They used to sign in as a bare
    stranger, which ``GET /api/profile/{user_id}`` allowed; it does not
    any more, so they need a genuinely shared Collective with its
    directory open.
    """
    space = make_space(show_member_directory=True)
    viewer = make_user()
    _join(db, viewer, space)
    _join(db, target, space)
    return viewer


def _join(db, user, space, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=str(uuid.uuid4()), user_id=user.id, space_id=space.id,
        role=role, status=SpaceMembershipStatus.active,
    ))
    db.flush()


def _visible_space(make_space, **kw):
    kw.setdefault("show_member_directory", True)
    return make_space(**kw)


@pytest.fixture
def flag_on(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "ways_to_connect_enabled", True)


def _two_attended(db, make_event, users, space, *, label="Sitting"):
    """Two attended Gatherings — the two signals a person card needs."""
    from datetime import datetime, timedelta
    from app.models.platform import BookingStatus, EventBooking
    now = datetime.utcnow()
    for n, days in enumerate((14, 45)):
        starts = now - timedelta(days=days)
        ev = make_event(space=space, starts_at=starts,
                        ends_at=starts + timedelta(hours=1),
                        title=f"{label} {n + 1}")
        ev.attendance_completed_at = starts + timedelta(hours=2)
        for u in users:
            db.add(EventBooking(
                id=str(uuid.uuid4()), event_id=ev.id, user_id=u.id,
                status=BookingStatus.confirmed, attendance_status="attended",
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
        as_user(_entitled_viewer(db, make_user, make_space, member))

        body = client.get(f"/api/profile/{member.id}").json()

        assert body["is_creator"] is False
        assert body["spaces_led"] == []

    def test_a_real_creator_still_reads_as_one(
        self, client, db, make_user, make_space
    ):
        creator = make_user(role="creator", name="Real Creator")
        make_space(creator=creator, name="Their Collective")
        as_user(_entitled_viewer(db, make_user, make_space, creator))

        body = client.get(f"/api/profile/{creator.id}").json()

        assert body["is_creator"] is True
        assert "Their Collective" in body["spaces_led"]

    def test_a_creator_whose_role_was_cancelled_is_not_one(
        self, client, db, make_user, make_space
    ):
        from datetime import datetime
        gone = make_user(role="creator", creator_cancelled_at=datetime.utcnow())
        as_user(_entitled_viewer(db, make_user, make_space, gone))

        assert client.get(f"/api/profile/{gone.id}").json()["is_creator"] is False

    def test_collectives_led_no_longer_depends_on_having_a_profile(
        self, client, db, make_user, make_space
    ):
        """Previously ``spaces_led`` was only computed when a profile row
        existed, so a Creator who never filled one in led nothing."""
        creator = make_user(role="creator", name="No Profile")
        make_space(creator=creator, name="Still Theirs")
        as_user(_entitled_viewer(db, make_user, make_space, creator))

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
        self, client, db, make_user, make_space
    ):
        member = make_user(role="user", name="Quiet")
        as_user(member)
        client.post("/api/auth/me/avatar", files={"file": self._png()})

        as_user(_entitled_viewer(db, make_user, make_space, member))
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


# ---------------------------------------------------------------------------
# The initial must never out-reveal the surrounding surface
# ---------------------------------------------------------------------------

class TestTheInitialRevealsNothingExtra:
    """An alphabet card must not disclose more identity than the surface
    it sits on already does.

    The guarantee is that every call site feeds the resolver *the same
    expression it renders as ``display_name``* — so the letter is the
    first letter of a name the viewer is already being shown. These
    tests pin that, because it is a property of the call sites rather
    than of the resolver, and a future caller could break it by passing
    a private profile's name while rendering the public one.
    """

    def test_a_private_profiles_display_name_never_reaches_the_image(
        self, client, db, make_user, make_space
    ):
        """The sharpest case: a member whose private profile says
        "Zelda" but whose platform name is "Sarah". The surface shows
        Sarah, so the card must be S — never Z."""
        _install_cards(db, letters=("S", "Z"), neutral=True)
        member = make_user(role="user", name="Sarah")
        _profile(db, member, display_name="Zelda", is_public=False)
        as_user(_entitled_viewer(db, make_user, make_space, member))

        body = client.get(f"/api/profile/{member.id}").json()

        assert body["display_name"] == "Sarah"
        assert body["image"]["initial"] == "S"
        assert body["image"]["url"].endswith("card_s.png")
        assert "Zelda" not in client.get(f"/api/profile/{member.id}").text

    def test_a_public_profiles_display_name_does_drive_the_card(
        self, client, db, make_user, make_space
    ):
        """The mirror: once the member has published that name, the card
        follows it, because the surface shows it."""
        _install_cards(db, letters=("S", "Z"), neutral=True)
        member = make_user(role="user", name="Sarah")
        _profile(db, member, display_name="Zelda", is_public=True)
        as_user(_entitled_viewer(db, make_user, make_space, member))

        body = client.get(f"/api/profile/{member.id}").json()

        assert body["display_name"] == "Zelda"
        assert body["image"]["initial"] == "Z"

    def test_the_initial_matches_the_rendered_name_on_the_public_profile(
        self, client, db, make_user, make_space
    ):
        _install_cards(db, letters=tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        member = make_user(role="user", name="Priya")
        _profile(db, member, is_public=False)
        as_user(_entitled_viewer(db, make_user, make_space, member))

        body = client.get(f"/api/profile/{member.id}").json()

        assert body["image"]["initial"] == body["display_name"][0].upper()

    def test_the_initial_matches_the_rendered_name_in_the_directory(
        self, client, db, make_user, make_space
    ):
        _install_cards(db, letters=tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        owner = make_user(role="creator")
        space = make_space(creator=owner, show_member_directory=True)
        member = make_user(role="user", name="Priya")
        _profile(db, member, display_name="Hidden", is_public=False)
        for u in (owner, member):
            _join(db, u, space)
        as_user(member)

        rows = client.get(f"/api/spaces/{space.slug}/members").json()
        row = next(r for r in rows if r["id"] == member.id)

        assert row["display_name"] == "Priya"
        assert row["image"]["initial"] == "P"

    def test_a_hidden_learner_yields_no_row_and_therefore_no_initial(
        self, client, db, make_user, make_space
    ):
        """With the directory closed, a learner is filtered out of the
        query entirely — there is no row to carry a letter."""
        _install_cards(db, letters=tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        owner = make_user(role="creator")
        space = make_space(creator=owner, show_member_directory=False)
        hidden = make_user(role="user", name="Priya")
        viewer = make_user(role="user", name="Viewer")
        for u in (owner, hidden, viewer):
            _join(db, u, space)
        as_user(viewer)

        rows = client.get(f"/api/spaces/{space.slug}/members").json()

        assert all(r["id"] != hidden.id for r in rows)
        assert "Priya" not in client.get(f"/api/spaces/{space.slug}/members").text

    def test_ways_to_connect_matches_its_own_display_name(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        _install_cards(db, letters=tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        alice = make_user()
        bob = make_user(name="Bob")
        _profile(db, bob, display_name="Hidden", is_public=False)
        space = _visible_space(make_space)
        for u in (alice, bob):
            _join(db, u, space)
        _two_attended(db, make_event, (alice, bob), space)
        as_user(alice)

        person = client.get("/api/ways-to-connect").json()["people"][0]

        assert person["display_name"] == "Bob"
        assert person["image"]["initial"] == "B"

    def test_an_unnamed_member_carries_no_letter_anywhere(
        self, client, db, flag_on, make_user, make_space, make_event
    ):
        """No name rendered, so no letter returned — the neutral card,
        with ``initial`` null."""
        _install_cards(db, letters=tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), neutral=True)
        alice = make_user()
        bob = make_user(name=None)
        space = _visible_space(make_space)
        for u in (alice, bob):
            _join(db, u, space)
        _two_attended(db, make_event, (alice, bob), space)
        as_user(alice)

        person = client.get("/api/ways-to-connect").json()["people"][0]

        assert person["display_name"] is None
        assert person["image"]["initial"] is None
        assert person["image"]["kind"] == "neutral"

    def test_mention_suggestions_match_their_own_rendered_name(
        self, client, db, make_user, make_space
    ):
        _install_cards(db, letters=tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        _default_channel(db, space)
        member = make_user(role="user", name="Mira")
        _profile(db, member, display_name="Hidden", is_public=False)
        for u in (owner, member):
            _join(db, u, space)
        as_user(owner)

        rows = client.get(
            f"/api/spaces/{space.slug}/members/search", params={"q": "Mira"},
        ).json()

        assert rows[0]["display_name"] == "Mira"
        assert rows[0]["image"]["initial"] == "M"


# ---------------------------------------------------------------------------
# The rung below a photo
# ---------------------------------------------------------------------------


class TestAPhotoCarriesItsFallback:
    """A photo is the only tier that can fail after the server picks it.

    It is member-supplied, it can disappear from storage, and the
    failure is discovered in a browser long after this decision was
    made. Before ``fallback_url`` existed the client had nothing left
    to try, so a member with a broken photo dropped to a bare glyph —
    worse treatment than a member with no photo at all, who gets a
    designed card.
    """

    def _photo(self, db, make_user, name="Anna"):
        cp = _profile(
            db, make_user(), avatar_url="/api/uploads/avatars/a.png",
            is_public=True,
        )
        return resolve_member_image(
            display_name=name, profile=cp, artwork=MemberCardArtwork.load(db),
        )

    def test_the_fallback_is_the_members_own_card(self, db, make_user):
        _install_cards(db, letters=("A",), neutral=True)
        image = self._photo(db, make_user)
        assert image.kind is MemberImageKind.PHOTO
        assert image.fallback_url.endswith("card_a.png")

    def test_it_is_the_neutral_card_when_the_letter_has_none(
        self, db, make_user,
    ):
        _install_cards(db, letters=("B",), neutral=True)
        image = self._photo(db, make_user)
        assert image.fallback_url.endswith("card_neutral.png")

    def test_a_name_with_no_latin_initial_falls_to_neutral(
        self, db, make_user,
    ):
        _install_cards(db, letters=("A",), neutral=True)
        image = self._photo(db, make_user, name="左 Lin")
        assert image.fallback_url.endswith("card_neutral.png")

    def test_with_no_artwork_installed_there_is_nothing_to_fall_to(
        self, db, make_user,
    ):
        """Honest None rather than a path that would 404 in turn. The
        client then shows the initial, which is the correct end of the
        ladder when the artwork genuinely does not exist."""
        image = self._photo(db, make_user)
        assert image.fallback_url is None
        assert image.initial == "A"

    def test_only_a_photo_carries_one(self, db, make_user):
        """A card has no rung below it worth naming: if the artwork
        itself fails the initial is all that is left, and the client
        already has it."""
        _install_cards(db, letters=("S",), neutral=True)
        card = resolve_member_image(
            display_name="Sarah", profile=None,
            artwork=MemberCardArtwork.load(db),
        )
        assert card.kind is MemberImageKind.ALPHABET
        assert card.fallback_url is None

    def test_a_private_photo_contributes_no_fallback(self, db, make_user):
        """The member is not showing a photo at all, so the card is the
        picture rather than a fallback for one."""
        _install_cards(db, letters=("S",), neutral=True)
        cp = _profile(
            db, make_user(), avatar_url="/api/uploads/avatars/a.png",
            is_public=False,
        )
        image = resolve_member_image(
            display_name="Sarah", profile=cp,
            artwork=MemberCardArtwork.load(db),
        )
        assert image.kind is MemberImageKind.ALPHABET
        assert image.fallback_url is None

    def test_it_crosses_the_api_boundary(self, db, make_user):
        """Useless if the payload drops it."""
        from app.services.member_image import MemberImagePayload

        _install_cards(db, letters=("A",), neutral=True)
        cp = _profile(
            db, make_user(), avatar_url="/api/uploads/avatars/a.png",
            is_public=True,
        )
        payload = MemberImagePayload.resolve(
            display_name="Anna", profile=cp,
            artwork=MemberCardArtwork.load(db),
        )
        assert payload.kind == "photo"
        assert payload.fallback_url.endswith("card_a.png")


class TestEveryLetterResolves:
    """Not just A. The twenty-seven slots are generated, so a defect in
    key derivation would hit some letters and not others — exactly the
    shape of the report that prompted this."""

    @pytest.mark.parametrize(
        "letter,name",
        [
            ("A", "Anna Byrne"),
            ("J", "Jo Marsden"),
            ("M", "Maya Fuller"),
            ("R", "Rosemary Ngata"),
            ("Z", "Zahra Okonjo"),
        ],
    )
    def test_the_letters_card_is_found(self, db, letter, name):
        _install_cards(db, letters=(letter,), neutral=True)
        image = resolve_member_image(
            display_name=name, profile=None,
            artwork=MemberCardArtwork.load(db),
        )
        assert image.kind is MemberImageKind.ALPHABET
        assert image.url.endswith(f"card_{letter.lower()}.png")
        assert image.initial == letter

    @pytest.mark.parametrize(
        "name,letter",
        [
            ("anna byrne", "A"),          # lowercase display name
            ("  jo marsden", "J"),        # leading whitespace
            ("Émile Zola", "E"),          # accent folded to its base
            ("ZAHRA", "Z"),               # already uppercase
        ],
    )
    def test_the_key_is_derived_case_and_accent_insensitively(
        self, db, name, letter,
    ):
        """The lookup key is lowercase on both sides. A name's own case
        and accents must not decide whether a card is found."""
        _install_cards(db, letters=(letter,), neutral=True)
        image = resolve_member_image(
            display_name=name, profile=None,
            artwork=MemberCardArtwork.load(db),
        )
        assert image.kind is MemberImageKind.ALPHABET
        assert image.url.endswith(f"card_{letter.lower()}.png")

    def test_all_twenty_six_plus_neutral_resolve_when_installed(self, db):
        """The whole set at once, because the admin page offers it as a
        set and a single missing letter is invisible one card at a
        time."""
        import string

        letters = tuple(string.ascii_uppercase)
        _install_cards(db, letters=letters, neutral=True)
        artwork = MemberCardArtwork.load(db)
        for letter in letters:
            image = resolve_member_image(
                display_name=f"{letter}ana", profile=None, artwork=artwork,
            )
            assert image.kind is MemberImageKind.ALPHABET, letter
            assert image.url.endswith(f"card_{letter.lower()}.png"), letter
        neutral = resolve_member_image(
            display_name="左 Lin", profile=None, artwork=artwork,
        )
        assert neutral.kind is MemberImageKind.NEUTRAL


class TestOneResolverForEverySurface:
    """Ways to Connect and Messages must agree about one person.

    Not a style point. The two surfaces sit next to each other in the
    same journey — you meet somebody on a card and then open a
    conversation with them — so a different picture or a different
    fallback between the two reads as a different person.
    """

    def test_no_route_builds_a_member_image_by_hand(self):
        """The guard against a seventh avatar implementation.

        Every surface must go through ``MemberImagePayload.resolve``;
        constructing the wire shape directly is how the surfaces
        disagreed before the resolver existed.
        """
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent / "app"
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == "member_image.py":
                continue
            src = path.read_text()
            # Comments stripped: the modules describe the payload in
            # prose, and a blunt substring check trips on the
            # description rather than on a breach.
            code = re.sub(r"#.*", "", src)
            if "MemberImagePayload(" in code:
                offenders.append(str(path.relative_to(root)))
        assert not offenders, (
            "these build the payload directly instead of resolving it: "
            f"{offenders}"
        )

    def test_both_surfaces_resolve_one_member_identically(
        self, client, db, make_user, make_space, make_event, flag_on,
    ):
        """The same two people, read through both routes."""
        _install_cards(db, letters=("A", "B"), neutral=True)
        a, b = make_user(name="Anna Byrne"), make_user(name="Bea Lowe")
        space = _visible_space(make_space)
        for u in (a, b):
            _join(db, u, space)
        _two_attended(db, make_event, (a, b), space)
        # A photo on one of them, so the tier that carries a fallback is
        # the one being compared.
        _profile(db, b, avatar_url="/api/uploads/avatars/b.png", is_public=True)
        db.add(MemberHello(id=str(uuid.uuid4()), from_user_id=a.id, to_user_id=b.id))
        db.add(MemberHello(id=str(uuid.uuid4()), from_user_id=b.id, to_user_id=a.id))
        db.flush()

        as_user(a)

        ways = client.get("/api/ways-to-connect").json()
        card = next(p for p in ways["people"] if p["id"] == b.id)

        opened = client.post("/api/messages/open", json={"user_id": b.id}).json()
        thread = client.get(f"/api/messages/{opened['thread_id']}").json()

        assert card["image"] == thread["other"]["image"], (
            "the same person, two surfaces, one picture"
        )
        assert card["image"]["kind"] == "photo"
        assert card["image"]["fallback_url"].endswith("card_b.png")
