"""A member's private written response to one Exercise block.

Registered on ``app.spaces.routes.router`` by side-effect import, the
same way ``_series_member_routes`` and ``_regular_sessions_routes`` are.

These are deliberately shaped like ``save_notes`` — the step-reflection
endpoint — because exercise responses are the same kind of thing: the
member's own writing, saved explicitly, visible to nobody else. The only
difference is granularity. A step has one reflection; it can hold
several exercises, so these are keyed on the block.

What the URL does and does not decide
-------------------------------------

The space / pathway / step path segments are not decoration. They are
what lets ``_check_pathway_access`` run before anything is read or
written, and what lets the handler assert the block really belongs to
the step being asked about — so a block id borrowed from another
pathway, or from a pathway the member cannot reach, is a 404 rather than
a side door into someone else's content.

Ownership is never taken from the URL or the body. Every query filters
on ``current_user.id``, which is resolved from the session cookie, so
there is no request shape that reads or writes another member's writing.

Concurrency
-----------

The save is a single ``INSERT ... ON CONFLICT (user_id, block_id) DO
UPDATE``. Two saves racing on the same exercise cannot produce two rows
— the unique constraint turns the loser into an update — and because
each response is its own row, a save on one exercise touches no other
and cannot reach ``step_progress.reflection_text`` at all.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.platform import (
    ExerciseResponse,
    PathwayStepBlock,
    StepBlockType,
)
from app.models.user import User
from app.spaces.routes import (
    _check_pathway_access,
    _get_pathway_or_404,
    _get_space_or_404,
    _get_step_or_404,
    router,
)

#: Maximum characters accepted in one response. Generous — this is
#: journalling, not a form field — but bounded so a single request
#: cannot be used to push unbounded text into the database.
MAX_RESPONSE_CHARS = 20_000


class ExerciseResponseOut(BaseModel):
    block_id: str
    response_text: str | None
    #: The resolved setting, not the raw column: NULL reads as enabled,
    #: so the client never has to know that blocks authored before this
    #: field existed store NULL. Mirrors ``reflection_enabled ?? true``.
    response_enabled: bool
    updated_at: datetime | None


class ExerciseResponseSaveRequest(BaseModel):
    response_text: str = Field(default="", max_length=MAX_RESPONSE_CHARS)


class ExerciseResponseSaveResponse(BaseModel):
    saved: bool
    updated_at: datetime | None


def _resolve_exercise_block(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    block_id: str,
    db: Session,
    current_user: User,
) -> PathwayStepBlock:
    """The block, or a 404 — having checked the member may be here.

    Four questions, in this order, because the cheapest refusals should
    come first and because the access check must precede any lookup
    that could confirm the existence of content the member cannot see:

      1. Is this a real Collective?                  (404)
      2. Is this a real Pathway in it?               (404)
      3. May this member reach that Pathway?         (403)
      4. Is this a real Exercise block in that step? (404)

    Step four is the one that matters for ownership: a block id is a
    bare UUID, so without tying it to the step in the URL a member with
    access to one Pathway could name a block from another. Mismatches
    are 404 rather than 403 — "not here" is the honest answer and it
    does not confirm the block exists elsewhere.
    """
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)

    block = (
        db.query(PathwayStepBlock)
        .filter(
            PathwayStepBlock.id == block_id,
            PathwayStepBlock.step_id == step.id,
        )
        .first()
    )
    if block is None:
        raise HTTPException(status_code=404, detail="Exercise not found.")
    if block.block_type != StepBlockType.exercise:
        # Only exercises carry a response area. Refusing here keeps the
        # table from filling with rows pointing at blocks that have
        # nowhere to display them.
        raise HTTPException(status_code=404, detail="Exercise not found.")
    return block


def _responses_enabled(block: PathwayStepBlock) -> bool:
    """NULL means enabled — see the column's note in the model."""
    return block.response_enabled is not False


@router.get(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/exercises/{block_id}/response",
    response_model=ExerciseResponseOut,
)
def get_exercise_response(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    block_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExerciseResponseOut:
    """This member's response to this exercise, if they have written one.

    Readable even when the creator has turned the response area off.
    The writing is the member's own, and withholding it from them would
    serve nobody — the toggle decides whether they can *add* to it. The
    resolved flag is returned alongside so the client knows which it is.
    """
    block = _resolve_exercise_block(
        slug, pathway_slug, step_slug, block_id, db, current_user,
    )
    row = (
        db.query(ExerciseResponse)
        .filter(
            ExerciseResponse.user_id == current_user.id,
            ExerciseResponse.block_id == block.id,
        )
        .first()
    )
    return ExerciseResponseOut(
        block_id=block.id,
        response_text=row.response_text if row else None,
        response_enabled=_responses_enabled(block),
        updated_at=row.updated_at if row else None,
    )


@router.patch(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/exercises/{block_id}/response",
    response_model=ExerciseResponseSaveResponse,
)
def save_exercise_response(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    block_id: str,
    body: ExerciseResponseSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExerciseResponseSaveResponse:
    """Write this member's response, creating or replacing their row.

    Enforced server-side rather than by hiding the text area: a creator
    who turns the response area off has withdrawn the invitation, and a
    request that arrives anyway is refused here.
    """
    block = _resolve_exercise_block(
        slug, pathway_slug, step_slug, block_id, db, current_user,
    )
    if not _responses_enabled(block):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This exercise is not accepting responses.",
        )

    now = datetime.utcnow()
    # One statement. The unique constraint on (user_id, block_id) is
    # what makes this safe under a race: a second concurrent save
    # conflicts and becomes an update instead of a duplicate row.
    stmt = (
        pg_insert(ExerciseResponse.__table__)
        .values(
            id=str(uuid4()),
            user_id=current_user.id,
            block_id=block.id,
            response_text=body.response_text,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="exercise_responses_user_block_unique",
            set_={"response_text": body.response_text, "updated_at": now},
        )
        .returning(ExerciseResponse.__table__.c.updated_at)
    )
    updated_at = db.execute(stmt).scalar_one()
    db.commit()
    return ExerciseResponseSaveResponse(saved=True, updated_at=updated_at)
