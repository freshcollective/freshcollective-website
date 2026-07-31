"""
Tests for the Physical Location editorial blurb drafter.

Two surfaces:

  * The deterministic template in ``app.services.place_blurb`` — must
    never invent activity, must be honest when nothing is happening
    yet, and must respect the country / region shape rules.
  * The admin endpoint ``POST /api/admin/physical-locations/{slug}/blurb/draft``
    — must not persist, must expose whether existing text would be
    overwritten so the client can require confirmation, and must
    aggregate themes the same way ``/api/places`` does.
"""

from __future__ import annotations

import uuid

import pytest

import app.models.community_care  # noqa: F401 — sibling FKs
from app.admin.physical_locations import draft_location_blurb
from app.models.place import Place, SpacePlace
from app.services.place_blurb import draft_blurb


def _place(**overrides) -> Place:
    defaults = dict(
        id=f"place_{uuid.uuid4().hex[:12]}",
        slug=f"blurb-{uuid.uuid4().hex[:8]}",
        name="Blurb Town",
        country_code="AU",
        status="active",
    )
    defaults.update(overrides)
    return Place(**defaults)


# ---------------------------------------------------------------------------
# Template — deterministic fallback
# ---------------------------------------------------------------------------

class TestTemplate:
    def test_active_with_themes(self):
        text = draft_blurb(
            name="Melbourne",
            region="Victoria",
            country_code="AU",
            themes=["Wellbeing", "Movement", "Leadership"],
            active_collective_count=3,
        )
        assert "Melbourne" in text
        # Themes are lowercased for natural reading.
        assert "wellbeing, movement and leadership" in text
        assert "Victoria" in text
        assert "Australia" in text

    def test_caps_themes_at_three(self):
        text = draft_blurb(
            name="Elsewhere",
            region=None,
            country_code="AU",
            themes=["A", "B", "C", "D", "E"],
            active_collective_count=5,
        )
        # First three make it in; the rest are dropped.
        assert "a, b and c" in text
        assert " d" not in text.lower()

    def test_dedup_case_insensitive_via_caller(self):
        # De-duplication is the caller's job (mirrors what
        # /api/places does). The template just formats what it gets.
        text = draft_blurb(
            name="X",
            region=None,
            country_code="AU",
            themes=["Wellbeing"],
            active_collective_count=1,
        )
        assert "wellbeing" in text

    def test_no_themes_no_activity_is_honest(self):
        # Zero linked Collectives means the draft must NOT claim
        # anything is happening. "Nothing is happening here yet" is
        # the safe, honest floor.
        text = draft_blurb(
            name="Nowhere",
            region="Nowhere Region",
            country_code="AU",
            themes=[],
            active_collective_count=0,
        )
        assert "Nothing is happening here yet" in text
        assert "Nowhere" in text
        assert "Nowhere Region" in text
        # And it must not invent themes or Collectives.
        assert "wellbeing" not in text.lower()

    def test_single_collective_uses_singular(self):
        text = draft_blurb(
            name="Solo",
            region="Victoria",
            country_code="AU",
            themes=["Wellbeing"],
            active_collective_count=1,
        )
        assert "the Collective taking shape here" in text
        assert "Collectives and gatherings" not in text

    def test_unknown_country_code_falls_back_to_the_code(self):
        text = draft_blurb(
            name="X",
            region=None,
            country_code="ZZ",
            themes=[],
            active_collective_count=0,
        )
        assert "ZZ" in text

    def test_region_missing_still_names_country(self):
        text = draft_blurb(
            name="X",
            region=None,
            country_code="NZ",
            themes=["Movement"],
            active_collective_count=1,
        )
        assert "in New Zealand" in text
        # No stray comma from a missing region.
        assert ", ," not in text

    @pytest.mark.parametrize("banned", [
        "bustling", "vibrant", "must-see", "hidden gem",
    ])
    def test_avoids_marketing_language(self, banned):
        text = draft_blurb(
            name="Anywhere",
            region="Victoria",
            country_code="AU",
            themes=["Wellbeing", "Movement"],
            active_collective_count=3,
        )
        assert banned.lower() not in text.lower()


# ---------------------------------------------------------------------------
# Admin endpoint
# ---------------------------------------------------------------------------

class TestAdminDraftEndpoint:
    def test_returns_draft_without_persisting(self, db, make_user):
        admin = make_user(role="admin")
        p = _place(slug="untouched", name="Untouched", blurb=None)
        db.add(p)
        db.flush()

        result = draft_location_blurb(slug="untouched", db=db, _=admin)
        assert result.draft
        assert result.source == "template"
        assert result.existing_blurb_present is False
        # DB row must be untouched.
        db.refresh(p)
        assert p.blurb is None

    def test_flags_existing_blurb_for_confirmation(self, db, make_user):
        admin = make_user(role="admin")
        p = _place(slug="already-written", name="Already", blurb="Hand-written copy.")
        db.add(p)
        db.flush()

        result = draft_location_blurb(slug="already-written", db=db, _=admin)
        assert result.existing_blurb_present is True
        # Existing text still in place — endpoint must not overwrite.
        db.refresh(p)
        assert p.blurb == "Hand-written copy."

    def test_aggregates_themes_from_active_collectives(
        self, db, make_user, make_space,
    ):
        admin = make_user(role="admin")
        p = _place(slug="themed", name="Themed")
        db.add(p)
        db.flush()
        s1 = make_space(themes=["Wellbeing", "Movement"])
        s2 = make_space(themes=["Leadership"])
        drafted = make_space(status="draft", themes=["Should not appear"])
        db.add_all([
            SpacePlace(space_id=s1.id, place_id=p.id),
            SpacePlace(space_id=s2.id, place_id=p.id),
            SpacePlace(space_id=drafted.id, place_id=p.id),
        ])
        db.flush()

        result = draft_location_blurb(slug="themed", db=db, _=admin)
        text = result.draft.lower()
        for theme in ("wellbeing", "movement", "leadership"):
            assert theme in text
        assert "should not appear" not in text

    def test_missing_slug_is_404(self, db, make_user):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as ex:
            draft_location_blurb(slug="ghost", db=db, _=admin)
        assert ex.value.status_code == 404
