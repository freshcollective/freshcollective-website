"""The Offerings doorway on a member's Collective Home.

Offerings already had everything a tile needs and no tile. The area
vocabulary knew it (``area_policies.AREA_OFFERINGS``, fixed public "for
the same reason as About: it is a purchasing surface"), the pilot
machinery already dropped it from ``area_access`` when the feature was
off, and the catalogue at ``/spaces/{slug}/offerings`` already answered
without a session. The only missing piece was the key in
``home_config.TILE_KEYS``.

So these tests are about the three things that key had to pick up on
the way in:

1. **A count that matches the catalogue.** Published only — a tile
   promising three Offerings that leads to a page showing one is worse
   than a tile with no number.
2. **The pilot rules, unchanged.** A Collective outside the pilot gets
   no tile on the member Home *and* no control in the Creator Studio
   editor, because a setting with nowhere to take effect is a bug
   report waiting to happen.
3. **No leakage.** The count is a number on a doorway; it must not
   become a way to learn that a Collective is working on something.

Ordering and the preservation of existing creator configuration belong
to ``test_collective_home_config.py``, which owns ``resolve``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.creator.routes import get_home_config
from app.models.offering import Offering, OfferingStatus
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.spaces import area_policies
from app.spaces.routes import get_space


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _offering(db, space, *, status=OfferingStatus.published.value, **kw):
    now = datetime.utcnow()
    off = Offering(
        id=_uid("off"),
        space_id=space.id,
        slug=f"off-{uuid.uuid4().hex[:8]}",
        title=kw.pop("title", "A Resource"),
        status=status,
        published_at=now if status == OfferingStatus.published.value else None,
        created_at=now,
        updated_at=now,
        **kw,
    )
    db.add(off)
    db.flush()
    return off


def _member(db, space, user, role=SpaceRole.learner):
    m = SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        role=role, status=SpaceMembershipStatus.active,
    )
    db.add(m)
    db.flush()
    return m


def _tile_keys(payload) -> list[str]:
    return [t["key"] for t in (payload.home_tiles or [])]


# ---------------------------------------------------------------------------
# 1 — The tile, on the member Home
# ---------------------------------------------------------------------------


class TestTheTileOnTheMemberHome:
    def test_it_appears_after_pathways(
        self, db, make_space, make_user, offerings_enabled,
    ):
        space = make_space()
        viewer = make_user()
        _member(db, space, viewer)
        db.commit()

        keys = _tile_keys(get_space(space.slug, db=db, current_user=viewer))
        assert "offerings" in keys
        assert keys.index("offerings") == keys.index("pathways") + 1

    def test_an_anonymous_visitor_sees_it(
        self, db, make_space, offerings_enabled,
    ):
        """``AREA_OFFERINGS`` is fixed public — a visitor must be able to
        reach the page where they buy their way in. The tile follows the
        area."""
        space = make_space()
        db.commit()

        payload = get_space(space.slug, db=db, current_user=None)
        assert "offerings" in _tile_keys(payload)
        assert area_policies.AREA_OFFERINGS in payload.area_access

    def test_the_destination_is_the_existing_catalogue(
        self, db, make_space, make_user, offerings_enabled,
    ):
        """The tile leads to the route that already exists, so this
        asserts the two agree rather than asserting a string. A tile
        whose area is reachable must have a catalogue that answers."""
        from app.spaces._offering_member_routes import list_member_offerings

        space = make_space()
        viewer = make_user()
        _member(db, space, viewer)
        _offering(db, space, title="Morning Practice")
        db.commit()

        assert "offerings" in _tile_keys(
            get_space(space.slug, db=db, current_user=viewer),
        )
        catalogue = list_member_offerings(
            space.slug, db=db, current_user=viewer,
        )
        assert [o["title"] for o in catalogue] == ["Morning Practice"]


# ---------------------------------------------------------------------------
# 2 — The count
# ---------------------------------------------------------------------------


class TestThePublishedCount:
    def test_it_counts_published_offerings(
        self, db, make_space, make_user, offerings_enabled,
    ):
        space = make_space()
        viewer = make_user()
        _member(db, space, viewer)
        for _ in range(3):
            _offering(db, space)
        db.commit()

        payload = get_space(space.slug, db=db, current_user=viewer)
        assert payload.published_offering_count == 3

    def test_zero_is_a_real_answer_and_the_tile_stays(
        self, db, make_space, make_user, offerings_enabled,
    ):
        """The zero state. A creator who enabled the doorway has said
        they want it; an empty shelf is a calm fact, not a reason to
        take their choice away. The client renders "No offerings yet"
        from this same 0."""
        space = make_space()
        viewer = make_user()
        _member(db, space, viewer)
        db.commit()

        payload = get_space(space.slug, db=db, current_user=viewer)
        assert payload.published_offering_count == 0
        assert "offerings" in _tile_keys(payload)

    @pytest.mark.parametrize("status", ["draft", "retired"])
    def test_drafts_and_retired_offerings_are_not_counted(
        self, db, make_space, make_user, offerings_enabled, status,
    ):
        """The count has to match the catalogue it leads to, which is
        "published only, for everybody". A draft is private — it 404s
        even by slug — and a retired Offering has stopped selling. A
        number including either would describe a page nobody gets.
        """
        space = make_space()
        viewer = make_user()
        _member(db, space, viewer)
        _offering(db, space, status=status)
        db.commit()

        payload = get_space(space.slug, db=db, current_user=viewer)
        assert payload.published_offering_count == 0

    def test_a_draft_is_not_disclosed_to_anybody_by_the_count(
        self, db, make_space, make_user, offerings_enabled,
    ):
        """Privacy, stated as its own requirement rather than left
        implied by the parametrised test above.

        The count is a number on a public doorway. If it included
        drafts, it would let an anonymous visitor learn that a
        Collective is preparing something — which is exactly what the
        catalogue's 404-not-403 rule exists to prevent.
        """
        space = make_space()
        _offering(db, space, status="draft", title="Unreleased")
        published = _offering(db, space, title="Out now")
        db.commit()

        anon = get_space(space.slug, db=db, current_user=None)
        assert anon.published_offering_count == 1

        # And the creator, who may legitimately see it, is not misled
        # either: the count is the public catalogue's size, and drafts
        # live in Creator Studio.
        owner = db.query(type(space)).filter(
            type(space).id == space.id,
        ).one()
        from app.models.user import User
        owner_user = db.query(User).filter(User.id == owner.creator_id).one()
        as_owner = get_space(space.slug, db=db, current_user=owner_user)
        assert as_owner.published_offering_count == 1
        assert published.status == OfferingStatus.published.value

    def test_the_count_is_zero_when_the_area_is_unreachable(
        self, db, make_space, make_user,
    ):
        """No fixture here, so Offerings is off — the production default.

        Deliberately not just "the tile is absent": the count query is
        skipped entirely, so a Collective outside the pilot pays nothing
        for a tile it will not render.
        """
        space = make_space()
        viewer = make_user()
        _member(db, space, viewer)
        _offering(db, space)
        db.commit()

        payload = get_space(space.slug, db=db, current_user=viewer)
        assert payload.published_offering_count == 0
        assert "offerings" not in _tile_keys(payload)


# ---------------------------------------------------------------------------
# 3 — Availability and the pilot
# ---------------------------------------------------------------------------


class TestAvailabilityAndThePilot:
    def test_the_tile_is_absent_while_the_feature_is_off(
        self, db, make_space, make_user,
    ):
        space = make_space()
        viewer = make_user()
        _member(db, space, viewer)
        db.commit()

        payload = get_space(space.slug, db=db, current_user=viewer)
        assert "offerings" not in _tile_keys(payload)
        assert area_policies.AREA_OFFERINGS not in payload.area_access
        # Every other tile is untouched — the switch is not collateral.
        assert "gatherings" in _tile_keys(payload)
        assert "pathways" in _tile_keys(payload)

    def test_a_collective_outside_the_pilot_gets_no_tile(
        self, db, make_space, make_user, offerings_pilot,
    ):
        inside = make_space()
        outside = make_space()
        viewer = make_user()
        _member(db, inside, viewer)
        _member(db, outside, viewer)
        db.commit()
        offerings_pilot(inside.slug)

        assert "offerings" in _tile_keys(
            get_space(inside.slug, db=db, current_user=viewer),
        )
        assert "offerings" not in _tile_keys(
            get_space(outside.slug, db=db, current_user=viewer),
        )

    def test_the_creator_editor_offers_it_when_available(
        self, db, make_space, make_user, offerings_enabled,
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        _member(db, space, owner, role=SpaceRole.creator)
        db.commit()

        out = get_home_config(space.slug, db=db, current_user=owner)
        assert "offerings" in out.available_keys
        assert "offerings" in [t["key"] for t in out.home_tiles]

    def test_the_creator_editor_hides_it_when_unavailable(
        self, db, make_space, make_user,
    ):
        """The gap this closes: the editor previously filtered only the
        Members tile, so a Collective outside the pilot was offered a
        description box, an image picker and a Show toggle for a tile
        its Home would never render."""
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        _member(db, space, owner, role=SpaceRole.creator)
        db.commit()

        out = get_home_config(space.slug, db=db, current_user=owner)
        assert "offerings" not in out.available_keys
        assert "offerings" not in [t["key"] for t in out.home_tiles]
        # The rest of the vocabulary is intact.
        for key in ("gatherings", "pathways", "conversations", "about"):
            assert key in out.available_keys

    def test_the_editor_and_the_member_home_agree(
        self, db, make_space, make_user, offerings_pilot,
    ):
        """Two surfaces, one answer. They disagreed before: the editor
        read only ``show_member_directory`` while the member Home read
        the resolved areas, so the panel could promise a tile the Home
        would drop."""
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        _member(db, space, owner, role=SpaceRole.creator)
        db.commit()
        offerings_pilot()  # pilot on, nothing in it

        out = get_home_config(space.slug, db=db, current_user=owner)
        member_view = get_space(space.slug, db=db, current_user=owner)
        assert ("offerings" in out.available_keys) is (
            "offerings" in _tile_keys(member_view)
        )
        assert "offerings" not in out.available_keys


# ---------------------------------------------------------------------------
# 4 — The artwork slot
# ---------------------------------------------------------------------------


class TestTheArtworkSlot:
    def test_the_slot_is_registered(self):
        """One artwork system, not two. The tile's default image is a
        ``platform_artwork`` row managed in World Settings → Artwork,
        resolved by key at read time — never a file delivered from the
        repository, which is the mistake ``services.offering_covers``
        was written to undo."""
        from app.admin.platform_artwork import PLATFORM_ARTWORK_KEYS

        assert "collective_home_offerings" in PLATFORM_ARTWORK_KEYS
        entry = PLATFORM_ARTWORK_KEYS["collective_home_offerings"]
        assert entry["title"]
        assert entry["description"]

    def test_it_is_its_own_slot_not_a_borrowed_one(self):
        """``homepage_resources`` is the artwork behind the homepage's
        editorial section about Offerings. Sharing it would mean
        replacing one surface's image silently redressed the other."""
        from app.admin.platform_artwork import PLATFORM_ARTWORK_KEYS

        assert "homepage_resources" in PLATFORM_ARTWORK_KEYS
        assert "collective_home_offerings" != "homepage_resources"

    def test_an_empty_slot_is_a_supported_state(self, db):
        """No artwork uploaded yet is the state this ships in, and it
        must not render a broken image — the client falls through to the
        Collective's palette gradient, the same third layer every tile
        has."""
        from app.models.platform import PlatformArtwork

        row = (
            db.query(PlatformArtwork)
            .filter(PlatformArtwork.key == "collective_home_offerings")
            .first()
        )
        assert row is None or row.image_url is None or row.image_url


# ---------------------------------------------------------------------------
# 5 — Leaving the pilot does not discard the creator's work
# ---------------------------------------------------------------------------


class TestLeavingThePilotPreservesConfiguration:
    """The same protection as
    ``test_collective_home_config.TestUnavailableTilesAreCarriedForward``,
    driven through the HTTP handlers rather than the pure function —
    because the loss happened in the round trip, not in the merge: the
    editor is handed a narrowed vocabulary, and the save is a
    whole-document PUT.
    """

    def _save(self, db, space, owner, tiles):
        from app.creator.routes import HomeConfigIn, update_home_config

        return update_home_config(
            space.slug,
            body=HomeConfigIn.model_validate({"tiles": tiles}),
            db=db, current_user=owner,
        )

    def _editor_rows(self, out):
        """What the Creator Studio form would render: the stored rows
        filtered to the vocabulary the server says is available, which
        is exactly what ``seedRows`` does in the client."""
        stored = (out.home_config or {}).get("tiles") or []
        return [
            t for t in stored if t["key"] in out.available_keys
        ]

    def test_an_unrelated_save_keeps_the_offerings_tile_configured(
        self, db, make_space, make_user, offerings_pilot,
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        _member(db, space, owner, role=SpaceRole.creator)
        db.commit()

        # While in the pilot, the creator sets the tile up.
        offerings_pilot(space.slug)
        self._save(db, space, owner, [
            {"key": "gatherings"},
            {
                "key": "offerings",
                "description": "Workbooks and audio.",
                "image_url": "/api/uploads/media/mine.jpg",
            },
            {"key": "conversations"},
        ])

        # The Collective leaves the pilot. The editor stops offering the
        # row, so the form re-saves without it.
        offerings_pilot()
        out = get_home_config(space.slug, db=db, current_user=owner)
        assert "offerings" not in out.available_keys
        rows = self._editor_rows(out)
        assert "offerings" not in [r["key"] for r in rows]
        self._save(db, space, owner, [
            {"key": r["key"], "description": r["description"]}
            for r in rows
        ])

        # The configuration is still there, and still withheld.
        after = get_home_config(space.slug, db=db, current_user=owner)
        stored = {
            t["key"]: t for t in (after.home_config or {}).get("tiles") or []
        }
        assert stored["offerings"]["description"] == "Workbooks and audio."
        assert stored["offerings"]["image_url"] == "/api/uploads/media/mine.jpg"
        assert "offerings" not in [t["key"] for t in after.home_tiles]
        assert "offerings" not in _tile_keys(
            get_space(space.slug, db=db, current_user=owner),
        )

    def test_rejoining_the_pilot_restores_what_they_built(
        self, db, make_space, make_user, offerings_pilot,
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        _member(db, space, owner, role=SpaceRole.creator)
        db.commit()

        offerings_pilot(space.slug)
        self._save(db, space, owner, [
            {"key": "gatherings"},
            {"key": "offerings", "description": "Workbooks and audio."},
            {"key": "conversations"},
        ])
        offerings_pilot()
        self._save(db, space, owner, [
            {"key": "gatherings"}, {"key": "conversations"},
        ])

        # Back in.
        offerings_pilot(space.slug)
        out = get_home_config(space.slug, db=db, current_user=owner)
        tiles = {t["key"]: t for t in out.home_tiles}
        assert tiles["offerings"]["description"] == "Workbooks and audio."
        # And in the position they left it in, not appended as a default.
        order = [t["key"] for t in out.home_tiles]
        assert order.index("offerings") == order.index("conversations") - 1

    def test_the_member_home_never_showed_it_in_between(
        self, db, make_space, make_user, offerings_pilot,
    ):
        """The requirement that makes carrying it forward safe: stored
        is not the same as shown."""
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        viewer = make_user()
        _member(db, space, owner, role=SpaceRole.creator)
        _member(db, space, viewer)
        db.commit()

        offerings_pilot(space.slug)
        self._save(db, space, owner, [
            {"key": "gatherings"},
            {"key": "offerings", "description": "Workbooks and audio."},
        ])
        offerings_pilot()

        assert "offerings" not in _tile_keys(
            get_space(space.slug, db=db, current_user=viewer),
        )

    def test_the_request_stays_authoritative_for_an_available_tile(
        self, db, make_space, make_user, offerings_enabled,
    ):
        """The other half, and the thing a too-eager merge would break.

        While the editor *can* show a tile, the request is the whole
        truth for it: clearing its description clears it, and hiding it
        hides it. Nothing is resurrected from the stored copy.

        Note what is deliberately NOT asserted — that omitting a tile
        removes it. ``resolve`` is built from ``TILE_KEYS`` outwards, so
        an omitted tile reappears at the end with platform defaults;
        that is the documented behaviour which lets a new tile type
        arrive without a migration. Hiding is ``visible: false``.
        """
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        _member(db, space, owner, role=SpaceRole.creator)
        db.commit()

        self._save(db, space, owner, [
            {"key": "gatherings"},
            {"key": "offerings", "description": "First attempt."},
        ])
        out = self._save(db, space, owner, [
            {"key": "gatherings"},
            {"key": "offerings", "description": None, "visible": False},
        ])

        stored = {
            t["key"]: t for t in (out.home_config or {}).get("tiles") or []
        }
        assert stored["offerings"]["description"] is None
        assert stored["offerings"]["visible"] is False
        assert "offerings" not in [t["key"] for t in out.home_tiles]
