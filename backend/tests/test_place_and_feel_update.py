"""
Tests for the Place & Feel path through ``PATCH /api/creator/spaces/{slug}``.

Confirms:

  * Saving connection_style='online' clears any existing SpacePlace
    link.
  * Saving connection_style='in_person' with a primary_place_id
    creates the SpacePlace link.
  * Saving with primary_place_id="" clears an existing link.
  * Switching from in_person to online clears the link even if the
    Creator did not touch the picker.
  * A stale/non-existent primary_place_id returns 400 rather than
    silently linking to nothing.
  * Draft Collectives (status='draft') resolve + link the same way
    as active Collectives — publishing controls discoverability,
    not whether the relationship exists.
"""

from __future__ import annotations

import uuid

import pytest

# Ensure User's community_care FKs resolve in isolation.
import app.models.community_care  # noqa: F401
from app.creator.routes import update_space
from app.creator.schemas import SpaceUpdateRequest
from app.models.place import Place, SpacePlace


def _place(**overrides) -> Place:
    defaults = dict(
        id=f"place_{uuid.uuid4().hex[:12]}",
        slug=f"test-{uuid.uuid4().hex[:8]}",
        name="Test City",
        country_code="AU",
    )
    defaults.update(overrides)
    return Place(**defaults)


def _link_count(db, space) -> int:
    return db.query(SpacePlace).filter(SpacePlace.space_id == space.id).count()


class TestPlaceAndFeelUpdate:
    def test_online_clears_link(self, db, make_space, make_user):
        creator = make_user(role="creator")
        space = make_space(creator=creator, connection_style="in_person")
        place = _place(slug="melb", name="Melbourne")
        db.add(place)
        db.flush()
        db.add(SpacePlace(space_id=space.id, place_id=place.id))
        db.flush()
        assert _link_count(db, space) == 1

        update_space(
            slug=space.slug,
            body=SpaceUpdateRequest(connection_style="online"),
            db=db,
            current_user=creator,
        )

        assert _link_count(db, space) == 0

    def test_in_person_with_place_id_creates_link(self, db, make_space, make_user):
        creator = make_user(role="creator")
        space = make_space(creator=creator, connection_style="online")
        place = _place(slug="hobart", name="Hobart")
        db.add(place)
        db.flush()

        update_space(
            slug=space.slug,
            body=SpaceUpdateRequest(
                connection_style="in_person",
                primary_place_id=place.id,
            ),
            db=db,
            current_user=creator,
        )

        assert _link_count(db, space) == 1
        db.refresh(space)
        assert space.connection_style == "in_person"

    def test_both_replaces_existing_link(self, db, make_space, make_user):
        creator = make_user(role="creator")
        space = make_space(creator=creator, connection_style="in_person")
        old_place = _place(slug="a", name="A")
        new_place = _place(slug="b", name="B")
        db.add_all([old_place, new_place])
        db.flush()
        db.add(SpacePlace(space_id=space.id, place_id=old_place.id))
        db.flush()

        update_space(
            slug=space.slug,
            body=SpaceUpdateRequest(
                connection_style="both",
                primary_place_id=new_place.id,
            ),
            db=db,
            current_user=creator,
        )

        assert _link_count(db, space) == 1
        row = db.query(SpacePlace).filter(SpacePlace.space_id == space.id).one()
        assert row.place_id == new_place.id

    def test_empty_string_place_id_clears_link(self, db, make_space, make_user):
        creator = make_user(role="creator")
        space = make_space(creator=creator, connection_style="in_person")
        place = _place(slug="p", name="P")
        db.add(place)
        db.flush()
        db.add(SpacePlace(space_id=space.id, place_id=place.id))
        db.flush()

        update_space(
            slug=space.slug,
            body=SpaceUpdateRequest(
                connection_style="in_person",
                primary_place_id="",
            ),
            db=db,
            current_user=creator,
        )

        assert _link_count(db, space) == 0

    def test_unknown_place_id_returns_400(self, db, make_space, make_user):
        from fastapi import HTTPException

        creator = make_user(role="creator")
        space = make_space(creator=creator, connection_style="online")

        with pytest.raises(HTTPException) as exc:
            update_space(
                slug=space.slug,
                body=SpaceUpdateRequest(
                    connection_style="in_person",
                    primary_place_id="place_does_not_exist",
                ),
                db=db,
                current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_draft_collective_links_place_on_save(self, db, make_space, make_user):
        """Publishing controls discoverability, not whether the
        Geographic Location link exists. Drafts save the link too."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft", connection_style="online")
        place = _place(slug="canberra", name="Canberra")
        db.add(place)
        db.flush()

        update_space(
            slug=space.slug,
            body=SpaceUpdateRequest(
                connection_style="in_person",
                primary_place_id=place.id,
            ),
            db=db,
            current_user=creator,
        )

        assert _link_count(db, space) == 1

    def test_response_includes_primary_place(self, db, make_space, make_user):
        creator = make_user(role="creator")
        space = make_space(creator=creator, connection_style="online")
        place = _place(slug="perth", name="Perth", region="Western Australia")
        db.add(place)
        db.flush()

        resp = update_space(
            slug=space.slug,
            body=SpaceUpdateRequest(
                connection_style="in_person",
                primary_place_id=place.id,
            ),
            db=db,
            current_user=creator,
        )

        assert resp["connection_style"] == "in_person"
        assert resp["primary_place"] is not None
        assert resp["primary_place"]["name"] == "Perth"
        assert resp["primary_place"]["region"] == "Western Australia"
