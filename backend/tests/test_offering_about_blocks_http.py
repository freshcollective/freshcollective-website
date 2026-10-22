"""The Offering About page over real HTTP, end to end.

Why this file exists
--------------------

A creator reported *"Couldn't add text block. Please try again."* on a
production draft Offering. That wording is the frontend editor's
``catch`` branch — the ``fetch`` itself threw, or the OK response was
not parseable JSON — **not** its ``!res.ok`` branch, which would have
printed a status code. So the first question is whether the backend
route is implicated at all.

These tests answer that by driving the five endpoints the way the
browser does: ``TestClient`` against the mounted app, real JSON bodies,
real status codes, responses read **through** the Pydantic
``response_model``. A direct handler call would not have been enough
evidence either way — it skips response-model filtering, so a field the
handler sets but the model omits looks present when it is not.

The eight steps the report asked to be covered are one test
(:func:`test_the_whole_lifecycle_over_http`), in order, because the bug
being chased is a *sequence* failure rather than a single call failing:
add, type, save, reload, edit, reorder, delete, and what the member
preview then reads.

The other classes pin down the things that would quietly break the same
editor again: the shared ops module is used by four owner kinds now, so
each assertion here names the owner kind it is about.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.creator._offering_about_routes import OFFERING_OWNER_KIND
from app.creator.schemas import AboutBlockResponse
from app.main import app
from app.models.offering import Offering, OfferingPricingKind, OfferingStatus
from app.models.platform import PathwayAboutBlock
from app.services import offering_covers as covers


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def offering(db, make_space):
    """A draft Offering in a pilot Collective — the reported state."""
    space = make_space()
    off = Offering(
        id=_uid("off"), space_id=space.id,
        created_by_user_id=space.creator_id,
        slug=f"o-{uuid.uuid4().hex[:8]}",
        title="Morning Pages Workbook",
        summary="Twelve weeks of gentle daily pages.",
        default_cover_key=covers.DEFAULT_COVERS[0].key,
        status=OfferingStatus.draft.value,
        pricing_kind=OfferingPricingKind.free.value,
        price_cents=None,
    )
    db.add(off)
    db.flush()
    return space, off


@pytest.fixture
def client(db, offering, offerings_pilot):
    """Authenticated as the Collective's owner, with the pilot admitting it."""
    space, _off = offering
    from app.models.user import User
    owner = db.query(User).filter(User.id == space.creator_id).one()

    offerings_pilot(space.slug)

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_creator_user] = lambda: owner
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_creator_user, None)


def _base(space, off) -> str:
    return f"/api/creator/spaces/{space.slug}/offerings/{off.slug}/about-blocks"


# ---------------------------------------------------------------------------
# The reported failure, and the eight-step lifecycle behind it
# ---------------------------------------------------------------------------


class TestTheReportedFailure:
    """Is the backend implicated in 'Couldn't add text block'?"""

    def test_adding_a_text_block_returns_201_with_a_json_body(
        self, client, offering,
    ):
        space, off = offering
        res = client.post(_base(space, off), json={"block_type": "text"})
        assert res.status_code == 201, res.text
        # The editor's success path does an unguarded ``res.json()``.
        # A 201 with an unparseable body would land in its ``catch``
        # and print exactly the reported message, so parseability is
        # part of the contract, not an incidental detail.
        body = res.json()
        assert isinstance(body, dict)
        assert body["block_type"] == "text"
        assert body["owner_kind"] == OFFERING_OWNER_KIND
        assert body["owner_id"] == off.id
        assert body["pathway_id"] is None
        assert body["position"] == 0
        assert body["id"]

    def test_the_response_validates_against_the_declared_model(
        self, client, offering,
    ):
        """Read through ``AboutBlockResponse``, not around it.

        A direct handler call returns the ORM row and cannot see what
        the response model drops. The editor consumes the filtered
        JSON, so that is what gets asserted.
        """
        space, off = offering
        res = client.post(_base(space, off), json={"block_type": "text"})
        model = AboutBlockResponse.model_validate(res.json())
        assert model.owner_kind == OFFERING_OWNER_KIND
        assert model.owner_id == off.id
        assert model.block_type == "text"
        assert model.content is None
        assert model.created_at and model.updated_at

    @pytest.mark.parametrize("block_type", [
        "text", "heading", "image", "callout", "divider", "link",
        "button", "video_embed", "columns", "resource",
    ])
    def test_every_block_type_the_picker_offers_can_be_added(
        self, client, offering, block_type,
    ):
        """The report named Text, but a single broken owner kind would
        have failed all of them — so all of them are checked."""
        space, off = offering
        res = client.post(_base(space, off), json={"block_type": block_type})
        assert res.status_code == 201, f"{block_type}: {res.text}"
        assert res.json()["block_type"] == block_type


class TestTheWholeLifecycle:

    def test_the_whole_lifecycle_over_http(self, client, db, offering):
        space, off = offering
        base = _base(space, off)

        # 1. Add a text block.
        first = client.post(base, json={"block_type": "text"})
        assert first.status_code == 201, first.text
        block_id = first.json()["id"]

        # 2. Enter content, 3. save — the editor PATCHes as you type.
        saved = client.patch(
            f"{base}/{block_id}",
            json={"content": "Twelve weeks, one page a morning."},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["content"] == "Twelve weeks, one page a morning."

        # 4. Refresh the page — a fresh GET is what the reload does.
        listed = client.get(base)
        assert listed.status_code == 200, listed.text
        rows = listed.json()
        assert len(rows) == 1
        assert rows[0]["content"] == "Twelve weeks, one page a morning."
        assert rows[0]["id"] == block_id

        # 5. Edit the block.
        edited = client.patch(
            f"{base}/{block_id}", json={"content": "Edited copy."},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["content"] == "Edited copy."

        # 6. Reorder blocks — needs a second one to be meaningful.
        second = client.post(base, json={"block_type": "heading"})
        assert second.status_code == 201, second.text
        second_id = second.json()["id"]
        # Positions must be distinct before a reorder can prove anything.
        assert {r["position"] for r in client.get(base).json()} == {0, 1}

        flipped = client.patch(
            f"{base}/reorder", json={"ids": [second_id, block_id]},
        )
        assert flipped.status_code == 200, flipped.text
        assert [r["id"] for r in flipped.json()] == [second_id, block_id]
        assert [r["position"] for r in flipped.json()] == [0, 1]
        # And it survives a reload rather than only the response.
        assert [r["id"] for r in client.get(base).json()] == [second_id, block_id]

        # 7. Delete a block.
        gone = client.delete(f"{base}/{block_id}")
        assert gone.status_code == 204, gone.text
        remaining = client.get(base).json()
        assert [r["id"] for r in remaining] == [second_id]

        # 8. What the member preview reads — the same rows, by owner.
        from app.creator import _about_block_ops as ops
        member_side = ops.blocks_query(
            db, owner_kind=OFFERING_OWNER_KIND, owner_id=off.id,
        ).all()
        assert [b.id for b in member_side] == [second_id]

    def test_positions_do_not_collide_on_the_second_block(
        self, client, offering,
    ):
        """The ``(max or -1) + 1`` bug the shared module fixed.

        With ``0 or -1`` the second block also lands on position 0 and
        order falls back to insertion order. Three blocks make the
        regression unmistakable.
        """
        space, off = offering
        base = _base(space, off)
        ids = [
            client.post(base, json={"block_type": "text"}).json()["id"]
            for _ in range(3)
        ]
        rows = client.get(base).json()
        assert [r["position"] for r in rows] == [0, 1, 2]
        assert [r["id"] for r in rows] == ids


# ---------------------------------------------------------------------------
# Scoping — the shared module now serves four owner kinds
# ---------------------------------------------------------------------------


class TestScoping:

    def test_blocks_are_stamped_with_the_offering_owner_kind(
        self, client, db, offering,
    ):
        space, off = offering
        block_id = client.post(
            _base(space, off), json={"block_type": "text"},
        ).json()["id"]
        row = db.query(PathwayAboutBlock).filter(
            PathwayAboutBlock.id == block_id,
        ).one()
        assert row.owner_kind == OFFERING_OWNER_KIND
        assert row.owner_id == off.id
        # Setting the legacy FK would point the row at a Pathway that
        # does not own it, and pathway_id-only readers would then render
        # an Offering's content on a Pathway page.
        assert row.pathway_id is None

    def test_another_offerings_block_id_is_a_404_here(
        self, client, db, offering, make_space,
    ):
        space, off = offering
        other = Offering(
            id=_uid("off"), space_id=space.id,
            created_by_user_id=space.creator_id,
            slug=f"o-{uuid.uuid4().hex[:8]}", title="Other",
            summary="Other.",
            default_cover_key=covers.DEFAULT_COVERS[0].key,
            status=OfferingStatus.draft.value,
            pricing_kind=OfferingPricingKind.free.value,
        )
        db.add(other)
        db.flush()
        theirs = client.post(
            _base(space, other), json={"block_type": "text"},
        ).json()["id"]

        res = client.patch(f"{_base(space, off)}/{theirs}",
                           json={"content": "x"})
        assert res.status_code == 404
        res = client.delete(f"{_base(space, off)}/{theirs}")
        assert res.status_code == 404

    def test_a_pathway_owned_row_is_invisible_to_the_offering_routes(
        self, client, db, offering,
    ):
        """The four owner kinds share one table; they must not share rows."""
        space, off = offering
        stray = PathwayAboutBlock(
            id=_uid("ab"), owner_kind="pathway", owner_id=_uid("pw"),
            pathway_id=None, block_type="text", position=0,
            content="Belongs to a Pathway.",
        )
        db.add(stray)
        db.flush()
        listed = client.get(_base(space, off)).json()
        assert stray.id not in [r["id"] for r in listed]


class TestTheFeatureGates:

    def test_a_collective_outside_the_pilot_is_a_404(
        self, db, offering, make_space, monkeypatch,
    ):
        """Backend enforcement must stay exactly as it is.

        This is the behaviour the creator hit as *Not found* — asserted
        here so the frontend nav fix cannot be mistaken for a relaxation
        of the server-side rule.
        """
        from app.core.config import settings
        from app.models.user import User

        space, off = offering
        owner = db.query(User).filter(User.id == space.creator_id).one()
        monkeypatch.setattr(settings, "offerings_enabled", True)
        monkeypatch.setattr(settings, "offerings_pilot_collectives", "")

        def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_creator_user] = lambda: owner
        try:
            c = TestClient(app, follow_redirects=False)
            res = c.post(_base(space, off), json={"block_type": "text"})
            assert res.status_code == 404, res.text
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_creator_user, None)

    def test_the_whole_router_is_closed_when_offerings_are_disabled(
        self, db, offering, monkeypatch,
    ):
        from app.core.config import settings
        from app.models.user import User

        space, off = offering
        owner = db.query(User).filter(User.id == space.creator_id).one()
        monkeypatch.setattr(settings, "offerings_enabled", False)

        def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_creator_user] = lambda: owner
        try:
            c = TestClient(app, follow_redirects=False)
            for call in (
                lambda: c.get(_base(space, off)),
                lambda: c.post(_base(space, off), json={"block_type": "text"}),
            ):
                assert call().status_code == 404
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_creator_user, None)


# ---------------------------------------------------------------------------
# The eligibility field Creator Studio navigation depends on
# ---------------------------------------------------------------------------


class TestOfferingsAvailableOnSpaceDetail:
    """``GET /api/creator/spaces/{slug}`` must answer per Collective.

    This is the field that decides whether Creator Studio renders its
    Offerings nav entry. It was reported that the entry appeared for
    Collectives outside the pilot — on an ordinary creator account as
    well as an administrator's — so the topology here is the one from
    the report: one Collective inside the pilot and two outside it,
    all owned by the same creator.

    Asserted over real HTTP and therefore through ``SpaceDetail``. A
    direct call to ``_space_detail_response`` would return the dict
    before response-model filtering and could not show whether the
    field actually reaches the client.
    """

    @pytest.fixture
    def three_collectives(self, db, make_space, make_user):
        creator = make_user(role="creator")
        pilot = make_space(creator=creator, slug="moonlit-circle",
                           name="Moonlit Circle")
        outside_a = make_space(creator=creator, slug="life-in-full-colour",
                               name="Life in Full Colour")
        outside_b = make_space(creator=creator, slug="nourish-connect-thrive",
                               name="Nourish Connect Thrive")
        return creator, pilot, outside_a, outside_b

    def _client(self, db, user):
        def _override_db():
            yield db
        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_creator_user] = lambda: user
        return TestClient(app, follow_redirects=False)

    def _teardown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_creator_user, None)

    def test_the_pilot_collective_is_eligible_and_the_others_are_not(
        self, db, three_collectives, offerings_pilot,
    ):
        creator, pilot, out_a, out_b = three_collectives
        offerings_pilot(pilot.slug)
        c = self._client(db, creator)
        try:
            got = {
                s.slug: c.get(f"/api/creator/spaces/{s.slug}").json()
                for s in (pilot, out_a, out_b)
            }
        finally:
            self._teardown()

        assert got[pilot.slug]["offerings_available"] is True
        assert got[out_a.slug]["offerings_available"] is False
        assert got[out_b.slug]["offerings_available"] is False
        # Every other Collective-scoped surface is unaffected — the
        # pilot must not read as a plan tier or a broken Collective.
        for slug in (out_a.slug, out_b.slug):
            assert got[slug]["status"] == "active"
            assert got[slug]["slug"] == slug

    def test_the_pilot_admits_by_id_as_well_as_slug(
        self, db, three_collectives, offerings_pilot,
    ):
        """A rename must not drop a Collective out of the pilot.

        Production configures the pilot with Moonlit Circle's stable
        id for exactly this reason, so the field has to agree.
        """
        creator, pilot, out_a, _out_b = three_collectives
        offerings_pilot(pilot.id)
        c = self._client(db, creator)
        try:
            assert c.get(
                f"/api/creator/spaces/{pilot.slug}"
            ).json()["offerings_available"] is True
            assert c.get(
                f"/api/creator/spaces/{out_a.slug}"
            ).json()["offerings_available"] is False
        finally:
            self._teardown()

    def test_nobody_is_eligible_while_the_master_switch_is_off(
        self, db, three_collectives, monkeypatch,
    ):
        """Even a Collective named in the pilot list."""
        from app.core.config import settings

        creator, pilot, out_a, out_b = three_collectives
        monkeypatch.setattr(settings, "offerings_enabled", False)
        monkeypatch.setattr(
            settings, "offerings_pilot_collectives", pilot.slug,
        )
        c = self._client(db, creator)
        try:
            for s in (pilot, out_a, out_b):
                assert c.get(
                    f"/api/creator/spaces/{s.slug}"
                ).json()["offerings_available"] is False, s.slug
        finally:
            self._teardown()

    def test_an_empty_pilot_list_makes_nobody_eligible(
        self, db, three_collectives, monkeypatch,
    ):
        from app.core.config import settings

        creator, pilot, out_a, out_b = three_collectives
        monkeypatch.setattr(settings, "offerings_enabled", True)
        monkeypatch.setattr(settings, "offerings_pilot_collectives", "")
        c = self._client(db, creator)
        try:
            for s in (pilot, out_a, out_b):
                assert c.get(
                    f"/api/creator/spaces/{s.slug}"
                ).json()["offerings_available"] is False, s.slug
        finally:
            self._teardown()

    def test_general_release_makes_everyone_eligible(
        self, db, three_collectives, monkeypatch,
    ):
        from app.core.config import settings
        from app.services import offering_pilot

        creator, pilot, out_a, out_b = three_collectives
        monkeypatch.setattr(settings, "offerings_enabled", True)
        monkeypatch.setattr(
            settings, "offerings_pilot_collectives", offering_pilot.ALLOW_ALL,
        )
        c = self._client(db, creator)
        try:
            for s in (pilot, out_a, out_b):
                assert c.get(
                    f"/api/creator/spaces/{s.slug}"
                ).json()["offerings_available"] is True, s.slug
        finally:
            self._teardown()

    def test_the_field_defaults_to_false_rather_than_absent(self):
        """A client reading a payload without it must hide the feature.

        The schema default is what makes the frontend's
        ``=== true`` check safe on an older cached response.
        """
        from app.creator.schemas import SpaceDetail

        field = SpaceDetail.model_fields["offerings_available"]
        assert field.default is False

    def test_eligibility_uses_the_shared_predicate_not_a_second_copy(self):
        """One authority for the pilot, two surfaces reading it."""
        import inspect

        from app.creator import routes as creator_routes

        src = inspect.getsource(creator_routes._space_detail_response)
        assert "offerings_available_for(space)" in src
        # Not a re-derivation from settings in this function.
        assert "offerings_pilot_collectives" not in src
