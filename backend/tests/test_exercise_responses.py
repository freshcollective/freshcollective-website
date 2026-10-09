"""A member's private response to one Exercise block.

Round 2, item 9. Exercise blocks had instructions and nowhere to answer
them.

Most of this file is about two promises that are easy to make and easy
to break quietly.

The first is independence. A step can hold several exercises, and
``step_progress`` — where the step reflection lives — holds exactly one
response per member per step. So the interesting assertions are not
"a response can be saved" but "saving this one left that one alone", and
"saving any of them left ``reflection_text`` exactly as it was".

The second is privacy. It has to hold in the backend, not in the
rendering: every read and write is filtered to ``current_user.id``, a
block id borrowed from another step or another Pathway is a 404, and
there is no creator or admin route that returns this text at all. Those
are asserted here rather than assumed from the absence of a UI.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_exercise_responses.py
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.auth.dependencies import get_current_user, get_verified_current_user
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    ExerciseResponse,
    Pathway,
    PathwayStep,
    PathwayStepBlock,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    StepProgress,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Substrate
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db):
    """A client with the database overridden but *not* authentication.

    Auth is overridden per-test by ``as_member`` so that the
    unauthenticated case can still be exercised — overriding it here
    would make a 401 untestable.
    """
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_member(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_current_user] = lambda: user


def _join(db, user, space, *, role: SpaceRole = SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=role, status=SpaceMembershipStatus.active,
    ))
    db.flush()


def _pathway(db, space, *, status: str = "active", access_type: str = "free") -> Pathway:
    p = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}", title="A Pathway",
        status=status, access_type=access_type,
    )
    db.add(p)
    db.flush()
    return p


def _step(db, pathway, *, position: int = 0) -> PathwayStep:
    s = PathwayStep(
        id=_uid("st"), pathway_id=pathway.id,
        slug=f"st-{uuid.uuid4().hex[:8]}", title="A Step", position=position,
    )
    db.add(s)
    db.flush()
    return s


def _block(
    db, step, *, block_type: str = "exercise", position: int = 0,
    response_enabled: bool | None = None, label: str | None = None,
) -> PathwayStepBlock:
    b = PathwayStepBlock(
        id=_uid("b"), step_id=step.id, block_type=block_type, position=position,
        content='{"type":"doc","content":[]}', label=label,
        response_enabled=response_enabled,
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def world(db, make_user, make_space):
    """A free, active Pathway with one step and three exercises."""
    space = make_space()
    member = make_user()
    _join(db, member, space)
    pathway = _pathway(db, space)
    step = _step(db, pathway)
    blocks = [_block(db, step, position=i, label=f"Exercise {i + 1}") for i in range(3)]
    return {
        "space": space, "member": member, "pathway": pathway,
        "step": step, "blocks": blocks,
    }


def url(world, block, *, space=None, pathway=None, step=None) -> str:
    s = space or world["space"]
    p = pathway or world["pathway"]
    st = step or world["step"]
    return (
        f"/api/spaces/{s.slug}/pathways/{p.slug}/steps/{st.slug}"
        f"/exercises/{block.id}/response"
    )


def stored(db, user, block) -> str | None:
    row = (
        db.query(ExerciseResponse)
        .filter(
            ExerciseResponse.user_id == user.id,
            ExerciseResponse.block_id == block.id,
        )
        .first()
    )
    return row.response_text if row else None


# ---------------------------------------------------------------------------
# Independence — the promise the data model exists to keep
# ---------------------------------------------------------------------------


class TestIndependence:
    def test_three_exercises_in_one_step_save_separately(self, db, client, world):
        member, blocks = world["member"], world["blocks"]
        as_member(member)
        for i, b in enumerate(blocks):
            res = client.patch(url(world, b), json={"response_text": f"answer {i}"})
            assert res.status_code == 200, res.text

        assert db.query(ExerciseResponse).filter(
            ExerciseResponse.user_id == member.id,
        ).count() == 3
        for i, b in enumerate(blocks):
            assert stored(db, member, b) == f"answer {i}"

    def test_saving_one_leaves_the_others_untouched(self, db, client, world):
        member, blocks = world["member"], world["blocks"]
        as_member(member)
        for i, b in enumerate(blocks):
            client.patch(url(world, b), json={"response_text": f"original {i}"})

        client.patch(url(world, blocks[1]), json={"response_text": "rewritten"})

        assert stored(db, member, blocks[0]) == "original 0"
        assert stored(db, member, blocks[1]) == "rewritten"
        assert stored(db, member, blocks[2]) == "original 2"

    def test_two_members_on_one_exercise_do_not_collide(self, db, client, world, make_user):
        block = world["blocks"][0]
        other = make_user()
        _join(db, other, world["space"])

        as_member(world["member"])
        client.patch(url(world, block), json={"response_text": "mine"})
        as_member(other)
        client.patch(url(world, block), json={"response_text": "theirs"})

        assert stored(db, world["member"], block) == "mine"
        assert stored(db, other, block) == "theirs"
        assert db.query(ExerciseResponse).filter(
            ExerciseResponse.block_id == block.id,
        ).count() == 2

    def test_re_saving_updates_rather_than_duplicating(self, db, client, world):
        member, block = world["member"], world["blocks"][0]
        as_member(member)
        for text in ("first", "second", "third"):
            client.patch(url(world, block), json={"response_text": text})
        assert db.query(ExerciseResponse).filter(
            ExerciseResponse.user_id == member.id,
            ExerciseResponse.block_id == block.id,
        ).count() == 1
        assert stored(db, member, block) == "third"

    def test_the_database_itself_refuses_a_duplicate(self, db, world):
        # This constraint is the concurrency guarantee, not just a tidy
        # index: the save is a single INSERT ... ON CONFLICT, so a racing
        # second save conflicts here and becomes an update instead of a
        # second row. Without it the race would be silent.
        member, block = world["member"], world["blocks"][0]
        db.add(ExerciseResponse(
            id=_uid("er"), user_id=member.id, block_id=block.id, response_text="a",
        ))
        db.flush()
        db.add(ExerciseResponse(
            id=_uid("er"), user_id=member.id, block_id=block.id, response_text="b",
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_the_save_is_one_atomic_upsert(self):
        # Asserted on the source because a read-then-write version would
        # pass every test above while still racing in production.
        import pathlib
        src = pathlib.Path("app/spaces/_exercise_response_routes.py").read_text()
        assert "on_conflict_do_update" in src
        assert "exercise_responses_user_block_unique" in src


# ---------------------------------------------------------------------------
# The step reflection is a different thing and must stay untouched
# ---------------------------------------------------------------------------


class TestTheStepReflectionIsUnaffected:
    def test_saving_exercises_never_writes_reflection_text(self, db, client, world):
        member, blocks, step = world["member"], world["blocks"], world["step"]
        db.add(StepProgress(
            id=_uid("sp"), user_id=member.id, step_id=step.id,
            completed_at=None, reflection_text="my private reflection",
        ))
        db.flush()

        as_member(member)
        for i, b in enumerate(blocks):
            client.patch(url(world, b), json={"response_text": f"exercise {i}"})

        progress = (
            db.query(StepProgress)
            .filter(StepProgress.user_id == member.id, StepProgress.step_id == step.id)
            .one()
        )
        assert progress.reflection_text == "my private reflection"

    def test_no_step_progress_row_is_created_by_an_exercise_save(self, db, client, world):
        # An exercise response is not progress. Creating a StepProgress
        # row as a side effect would make a step look started.
        member, block = world["member"], world["blocks"][0]
        as_member(member)
        client.patch(url(world, block), json={"response_text": "x"})
        assert db.query(StepProgress).filter(
            StepProgress.user_id == member.id,
        ).count() == 0

    def test_an_exercise_response_is_not_reachable_from_step_progress(self, db):
        # The two tables share no column. Stated as a test because the
        # alternative design — a JSON column on step_progress — would
        # have put them in one row, where one bug reaches both.
        assert "reflection_text" not in ExerciseResponse.__table__.columns
        assert "response_text" not in StepProgress.__table__.columns


# ---------------------------------------------------------------------------
# Privacy, enforced by the backend
# ---------------------------------------------------------------------------


class TestPrivacy:
    def test_a_member_reads_only_their_own_response(self, db, client, world, make_user):
        block = world["blocks"][0]
        other = make_user()
        _join(db, other, world["space"])
        as_member(world["member"])
        client.patch(url(world, block), json={"response_text": "mine only"})

        as_member(other)
        res = client.get(url(world, block))
        assert res.status_code == 200
        assert res.json()["response_text"] is None

    def test_one_member_cannot_overwrite_another(self, db, client, world, make_user):
        block = world["blocks"][0]
        other = make_user()
        _join(db, other, world["space"])
        as_member(world["member"])
        client.patch(url(world, block), json={"response_text": "mine"})

        as_member(other)
        client.patch(url(world, block), json={"response_text": "theirs"})

        assert stored(db, world["member"], block) == "mine"

    def test_an_unauthenticated_request_is_refused(self, client, world):
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_verified_current_user, None)
        block = world["blocks"][0]
        assert client.get(url(world, block)).status_code in (401, 403)
        assert client.patch(
            url(world, block), json={"response_text": "x"},
        ).status_code in (401, 403)

    def test_a_member_without_pathway_access_is_refused(self, db, client, make_user, make_space):
        space = make_space()
        member = make_user()
        _join(db, member, space)
        pathway = _pathway(db, space, status="draft")
        step = _step(db, pathway)
        block = _block(db, step)
        as_member(member)
        target = (
            f"/api/spaces/{space.slug}/pathways/{pathway.slug}"
            f"/steps/{step.slug}/exercises/{block.id}/response"
        )
        assert client.get(target).status_code == 403
        assert client.patch(target, json={"response_text": "x"}).status_code == 403

    def test_no_creator_or_admin_route_returns_this_text(self):
        # The strongest available statement: no route outside the member
        # endpoints mentions the model at all, so there is no surface to
        # audit rather than one that merely happens to omit the field.
        import pathlib
        offenders = []
        for p in pathlib.Path("app").rglob("*.py"):
            rel = str(p)
            if rel.endswith("_exercise_response_routes.py"):
                continue
            if rel.endswith("models/platform.py"):
                continue
            text = p.read_text()
            if "ExerciseResponse" in text or "exercise_responses" in text:
                offenders.append(rel)
        assert offenders == [], f"exercise responses are referenced outside the member API: {offenders}"


# ---------------------------------------------------------------------------
# Block identity — a bare UUID is not an authorisation
# ---------------------------------------------------------------------------


class TestBlockMustBelongToTheStep:
    def test_a_block_from_another_step_is_not_found(self, db, client, world):
        other_step = _step(db, world["pathway"], position=1)
        foreign = _block(db, other_step)
        as_member(world["member"])
        # Addressed through the first step's URL — the block exists, but
        # not here.
        assert client.get(url(world, foreign)).status_code == 404
        assert client.patch(
            url(world, foreign), json={"response_text": "x"},
        ).status_code == 404

    def test_a_block_from_another_pathway_is_not_found(self, db, client, world):
        other_pathway = _pathway(db, world["space"])
        other_step = _step(db, other_pathway)
        foreign = _block(db, other_step)
        as_member(world["member"])
        assert client.get(url(world, foreign)).status_code == 404

    def test_a_non_exercise_block_has_no_response_area(self, db, client, world):
        text_block = _block(db, world["step"], block_type="text", position=9)
        as_member(world["member"])
        assert client.get(url(world, text_block)).status_code == 404
        assert client.patch(
            url(world, text_block), json={"response_text": "x"},
        ).status_code == 404

    def test_an_unknown_block_id_is_not_found(self, client, world):
        as_member(world["member"])
        class Fake:
            id = str(uuid.uuid4())
        assert client.get(url(world, Fake())).status_code == 404


# ---------------------------------------------------------------------------
# The creator's toggle
# ---------------------------------------------------------------------------


class TestResponsesEnabledToggle:
    def test_a_block_authored_before_the_field_existed_is_enabled(self, db, client, world):
        # response_enabled IS NULL — every Exercise block in production.
        block = world["blocks"][0]
        assert block.response_enabled is None
        as_member(world["member"])
        res = client.get(url(world, block))
        assert res.status_code == 200
        assert res.json()["response_enabled"] is True
        assert client.patch(
            url(world, block), json={"response_text": "allowed"},
        ).status_code == 200

    def test_explicitly_enabled_behaves_the_same(self, db, client, world):
        block = _block(db, world["step"], response_enabled=True, position=7)
        as_member(world["member"])
        assert client.get(url(world, block)).json()["response_enabled"] is True
        assert client.patch(
            url(world, block), json={"response_text": "ok"},
        ).status_code == 200

    def test_disabled_refuses_new_writing(self, db, client, world):
        block = _block(db, world["step"], response_enabled=False, position=8)
        as_member(world["member"])
        res = client.patch(url(world, block), json={"response_text": "nope"})
        assert res.status_code == 403
        assert stored(db, world["member"], block) is None

    def test_disabling_preserves_what_was_already_written(self, db, client, world):
        block = world["blocks"][0]
        as_member(world["member"])
        client.patch(url(world, block), json={"response_text": "written while open"})

        block.response_enabled = False
        db.flush()

        # Still stored, and still readable by its author — the toggle
        # withdraws the invitation to add more, it does not confiscate.
        assert stored(db, world["member"], block) == "written while open"
        res = client.get(url(world, block))
        assert res.status_code == 200
        assert res.json()["response_text"] == "written while open"
        assert res.json()["response_enabled"] is False

    def test_re_enabling_restores_both_access_and_the_writing(self, db, client, world):
        block = world["blocks"][0]
        as_member(world["member"])
        client.patch(url(world, block), json={"response_text": "earlier"})
        block.response_enabled = False
        db.flush()
        block.response_enabled = True
        db.flush()

        res = client.get(url(world, block))
        assert res.json()["response_text"] == "earlier"
        assert res.json()["response_enabled"] is True
        assert client.patch(
            url(world, block), json={"response_text": "later"},
        ).status_code == 200
        assert stored(db, world["member"], block) == "later"


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------


class TestReadBack:
    def test_an_unanswered_exercise_reads_as_empty_not_missing(self, client, world):
        as_member(world["member"])
        res = client.get(url(world, world["blocks"][0]))
        assert res.status_code == 200
        body = res.json()
        assert body["response_text"] is None
        assert body["updated_at"] is None
        assert body["block_id"] == world["blocks"][0].id

    def test_a_saved_response_comes_back_on_the_next_visit(self, client, world):
        block = world["blocks"][0]
        as_member(world["member"])
        client.patch(url(world, block), json={"response_text": "what I noticed"})
        body = client.get(url(world, block)).json()
        assert body["response_text"] == "what I noticed"
        assert body["updated_at"] is not None

    def test_an_empty_save_clears_rather_than_erroring(self, db, client, world):
        block = world["blocks"][0]
        as_member(world["member"])
        client.patch(url(world, block), json={"response_text": "something"})
        res = client.patch(url(world, block), json={"response_text": ""})
        assert res.status_code == 200
        assert stored(db, world["member"], block) == ""

    def test_an_overlong_response_is_refused(self, client, world):
        as_member(world["member"])
        res = client.patch(
            url(world, world["blocks"][0]),
            json={"response_text": "x" * 20_001},
        )
        assert res.status_code == 422
