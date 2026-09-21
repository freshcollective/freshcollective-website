"""Discover Places, reached the way a browser reaches it.

The existing Place tests call ``list_places(db)`` directly. That is
fine for what it covers and blind to what broke: a helper inserted
between ``@router.get("")`` and its function took the decorator with
it, so ``/api/places`` answered a zero-argument helper returning a
SQLAlchemy TextClause. The function stayed perfect and stopped being
a route. 4021 tests passed; the page showed "communities are just
beginning to take root", which is the frontend's fallback for a 500.

So these go through the app, not the function.
"""

from __future__ import annotations

import pathlib
import re
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_optional_user
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.place import Place, SpacePlace
from app.models.platform import Event


@pytest.fixture
def discovery_enabled(monkeypatch):
    monkeypatch.setattr(settings, "discovery_pillar_enabled", True)
    yield


@pytest.fixture
def client(db, discovery_enabled):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_optional_user] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def melbourne(db, make_space):
    """An active Place with one active public Collective linked."""
    space = make_space(is_public=True)
    place = Place(
        id=f"place_{uuid.uuid4().hex[:12]}",
        slug=f"melbourne-{uuid.uuid4().hex[:6]}",
        name="Melbourne", country_code="AU", region="Victoria",
        status="active",
    )
    db.add(place)
    db.add(SpacePlace(space_id=space.id, place_id=place.id))
    db.flush()
    return space, place


class TestTheRouteIsActuallyBound:
    def test_the_list_answers_over_http(self, client, melbourne):
        """The assertion the whole file exists for."""
        res = client.get("/api/places")
        assert res.status_code == 200, res.text
        assert isinstance(res.json(), list)

    def test_it_returns_the_place_in_the_expected_shape(self, client, melbourne):
        _, place = melbourne
        rows = client.get("/api/places").json()
        mine = [p for p in rows if p["slug"] == place.slug]
        assert len(mine) == 1, "the active Place is missing from the list"
        row = mine[0]
        for field in ("id", "slug", "name", "country_code",
                      "upcoming_gathering_count"):
            assert field in row, field
        assert row["name"] == "Melbourne"

    def test_the_handler_is_list_places_and_not_a_helper(self):
        """Names the failure directly: the decorator must sit on the
        function that serves the route."""
        bound = [
            r.endpoint.__name__ for r in app.routes
            if getattr(r, "path", None) == "/api/places"
            and "GET" in getattr(r, "methods", set())
        ]
        assert bound == ["list_places"], bound


class TestEveryRouteDecoratorSitsOnItsFunction:
    """The structural guard. One mechanical edit detached a decorator
    and no test noticed, because every test called the function. This
    reads the source instead."""

    @staticmethod
    def _offences() -> list[str]:
        """Two smells, because the corruption that shipped is invisible
        to the obvious check.

        ``@router.get(...)`` / blank line / ``def _helper():`` is
        syntactically identical to a correctly decorated function — so
        "is the next statement a def?" passes it happily. What gives it
        away is the pair:

        * **a blank or comment line between the decorator and its
          def** — no formatter produces that, but a mechanical
          insertion does; and
        * **a private name on a route handler** — a path answering
          ``_space_gatherings_are_public`` is a mistake whatever the
          layout.
        """
        decorator = re.compile(
            r"^\s*@(router|app|\w*_router)\.(get|post|put|patch|delete|head|options)\("
        )
        bad: list[str] = []
        for path in sorted(pathlib.Path("app").rglob("*.py")):
            lines = path.read_text().split("\n")
            for i, line in enumerate(lines):
                if not decorator.match(line):
                    continue
                # Walk to the end of the decorator call itself.
                depth = line.count("(") - line.count(")")
                j = i + 1
                while j < len(lines) and depth > 0:
                    depth += lines[j].count("(") - lines[j].count(")")
                    j += 1
                # Stacked decorators are fine; nothing else is.
                gap: list[str] = []
                while j < len(lines) and lines[j].lstrip().startswith("@"):
                    j += 1
                while j < len(lines) and lines[j].strip() == "":
                    gap.append(lines[j])
                    j += 1
                if j >= len(lines):
                    bad.append(f"{path}:{i + 1} — decorator at end of file")
                    continue
                m = re.match(r"\s*(?:async\s+)?def\s+(\w+)", lines[j])
                if not m:
                    bad.append(
                        f"{path}:{i + 1} — followed by: {lines[j].strip()[:70]}"
                    )
                    continue
                if gap:
                    bad.append(
                        f"{path}:{i + 1} — blank line before def {m.group(1)}; "
                        "a decorator separated from its function is how one "
                        "gets attached to the wrong one"
                    )
                elif m.group(1).startswith("_"):
                    bad.append(
                        f"{path}:{i + 1} — route handler is private: "
                        f"{m.group(1)}"
                    )
        return bad

    def test_no_route_decorator_is_detached(self):
        offences = self._offences()
        assert offences == [], (
            "A route decorator is not attached to the function that serves "
            "it, so that path answers the wrong callable:\n  "
            + "\n  ".join(offences)
        )

    def test_the_guard_would_have_caught_the_real_corruption(self, tmp_path):
        """A guard that cannot fail is decoration. This reproduces the
        exact shape that shipped."""
        broken = tmp_path / "app" / "broken.py"
        broken.parent.mkdir(parents=True)
        broken.write_text(
            '@router.get("", response_model=list[PlaceSummary])\n'
            "\n"
            "def _helper():\n"
            "    return 1\n"
            "\n"
            "\n"
            "def list_places(db):\n"
            "    return []\n"
        )
        import os
        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            offences = self._offences()
        finally:
            os.chdir(cwd)
        assert offences, "the guard failed to notice a detached decorator"
        assert "broken.py" in offences[0]

    def test_a_correctly_attached_decorator_passes(self, tmp_path):
        good = tmp_path / "app" / "good.py"
        good.parent.mkdir(parents=True)
        good.write_text(
            "@router.get(\n"
            '    "/{slug}",\n'
            "    response_model=PlaceDetail,\n"
            ")\n"
            "async def get_place(slug: str):\n"
            "    return None\n"
        )
        import os
        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            assert self._offences() == []
        finally:
            os.chdir(cwd)


class TestAPlaceSurvivesHavingNothingOnToday:
    """A Place is editorial. It must not vanish because its Collective
    has no public Gatherings this week — the area policy governs what
    is *shown*, never whether the Place exists."""

    def test_zero_public_gatherings_still_lists_the_place(
        self, client, melbourne,
    ):
        space, place = melbourne
        assert space.area_policies is None  # gatherings default: members
        rows = client.get("/api/places").json()
        row = next(p for p in rows if p["slug"] == place.slug)
        assert row["upcoming_gathering_count"] == 0

    def test_members_only_gatherings_do_not_remove_the_place(
        self, client, db, melbourne,
    ):
        space, place = melbourne
        db.add(Event(
            id=str(uuid.uuid4()), space_id=space.id, title="Members circle",
            starts_at=datetime.utcnow() + timedelta(days=2),
            is_published=True, is_public=True, status="active",
        ))
        db.flush()
        rows = client.get("/api/places").json()
        row = next(p for p in rows if p["slug"] == place.slug)
        assert row["upcoming_gathering_count"] == 0, "count should be 0…"
        assert row["name"] == "Melbourne", "…but the Place still appears"

    def test_public_gatherings_then_contribute_to_the_count(
        self, client, db, melbourne,
    ):
        space, place = melbourne
        space.area_policies = {"areas": {"gatherings": "public"}}
        db.add(Event(
            id=str(uuid.uuid4()), space_id=space.id, title="Open circle",
            starts_at=datetime.utcnow() + timedelta(days=2),
            is_published=True, is_public=True, status="active",
        ))
        db.flush()
        rows = client.get("/api/places").json()
        row = next(p for p in rows if p["slug"] == place.slug)
        assert row["upcoming_gathering_count"] == 1

    def test_a_place_with_no_collectives_at_all_still_lists(self, client, db):
        place = Place(
            id=f"place_{uuid.uuid4().hex[:12]}",
            slug=f"quiet-{uuid.uuid4().hex[:6]}", name="Quiet Town",
            country_code="AU", status="active",
        )
        db.add(place)
        db.flush()
        rows = client.get("/api/places").json()
        row = next((p for p in rows if p["slug"] == place.slug), None)
        assert row is not None, "an active Place must not need a Collective"
        assert row["upcoming_gathering_count"] == 0
