"""Copying one Pathway step into a new, independent step.

For a creator building a Pathway where every step follows the same
shape — introduction, content, reflection, exercise, resources —
rebuilding that scaffolding ten times is the work this removes.

What makes the copy independent
-------------------------------
Everything is built **field by field** rather than cloned, the same way
``duplicate_event`` builds a Gathering. Nothing instance-specific is
filtered out of a copy; it is simply never read. A column added to
``PathwayStep`` or ``PathwayStepBlock`` later is absent from the
duplicate until somebody decides it should be carried, which is the
safe direction for that mistake.

Member activity cannot follow, by construction rather than by care:

* ``StepProgress`` (completion + the step's reflection text) and
  ``StepComment`` are keyed on ``step_id``, and the duplicate has a new
  one.
* ``ExerciseResponse`` is keyed on ``block_id``, and every copied block
  gets a new id. A member's exercise answers therefore stay attached to
  the block they were written against — which is also why the blocks
  cannot be copied by reusing ids.
* ``PathwayStepManualRelease`` is per-member and is not read here, so a
  member who was individually released into the original is not
  released into the copy.

Media is referenced, never re-uploaded
--------------------------------------
``media_asset_id`` and ``resource_id`` are copied as the ids they are.
Both point at collective-level records — a Media Library asset and a
SpaceResource — which already serve many blocks across many steps, so
pointing one more block at an asset is the established arrangement and
costs no storage. ``ON DELETE SET NULL`` on both means deleting the
asset later leaves every referring block as a stub rather than
destroying the surrounding step; and deleting a *block*, in either
step, never touches the asset. ``StepResource.url`` is copied for the
same reason: it is a path to a file the original already serves.

Ordering
--------
The duplicate lands immediately after its source, and everything below
shifts down by one. Two position columns do that: ``position`` is
Pathway-wide and ``section_position`` orders steps inside a section, so
a sectioned step shifts in both. Positions are not guaranteed
contiguous — ``create_step`` appends ``max + 1`` and deleting leaves
gaps — so the shift is written as ``position + 1 WHERE position >
source``, which is correct with gaps and does not renumber anything it
does not have to.

The caller holds a row lock on the Pathway for the duration (see
``duplicate_step``), so two duplications in one Pathway cannot
interleave their shifts and land on the same position.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.platform import (
    PathwayStep,
    PathwayStepBlock,
    StepResource,
)

#: Appended to the copied title. The creator renames it immediately;
#: this exists so the two are tellable apart in a list until they do.
COPY_SUFFIX = "(Copy)"

#: Step columns carried to the duplicate. Named rather than derived so
#: adding a column to the model does not silently start copying it.
#:
#: Absent on purpose: ``id`` and ``slug`` (new identity), ``title``
#: (suffixed), ``position`` and ``section_position`` (computed),
#: ``pathway_id`` (the same Pathway — duplicating across Pathways is
#: not this operation), ``created_at`` and ``updated_at`` (the row is
#: new).
STEP_FIELDS = (
    "content_type",
    "content_body",
    "content_url",
    "estimated_minutes",
    "is_required",
    "section_id",
    "reflection_enabled",
    "discussion_enabled",
    "banner_image_url",
    # Release configuration is configuration, not activity: a drip rule
    # describes when the step opens, and a creator duplicating a step
    # in a dripped Pathway wants the same rule. ``manual`` carries over
    # as ``manual``, which means the copy starts locked for everyone
    # until released — no member inherits a release, because those
    # live in their own per-member table.
    "release_type",
    "release_offset_days",
    "release_at",
    "release_timezone",
    "release_previous_state",
)

#: Block columns carried to the duplicate. ``id`` and ``step_id`` are
#: new; ``created_at`` / ``updated_at`` belong to the new row.
BLOCK_FIELDS = (
    "block_type",
    "position",
    "content",
    "label",
    "caption",
    "heading",
    "response_enabled",
    "embed_url",
    # References, not copies — see the module docstring.
    "media_asset_id",
    "resource_id",
    "container_style",
)

#: Step-resource columns carried to the duplicate.
RESOURCE_FIELDS = (
    "title",
    "description",
    "resource_type",
    "url",
    "file_name",
    "file_size",
    "mime_type",
    "position",
    "is_downloadable",
)


def copied_title(title: str, suffix: str = COPY_SUFFIX) -> str:
    """``"Understanding Your Patterns"`` → ``"… (Copy)"``.

    Truncated to the column width (300) if the suffix would overflow,
    trimming the title rather than dropping the suffix: a creator
    scanning a list needs to see which one is the copy more than they
    need the last few characters of a very long title.
    """
    base = (title or "").strip()
    candidate = f"{base} {suffix}".strip()
    limit = PathwayStep.__table__.columns["title"].type.length
    if len(candidate) <= limit:
        return candidate
    room = limit - len(suffix) - 1
    return f"{base[:max(room, 0)].rstrip()} {suffix}".strip()


def _shift_down(db: Session, source: PathwayStep) -> None:
    """Make room immediately after ``source``.

    Two columns, two shifts. ``position`` orders the whole Pathway;
    ``section_position`` orders a section's own steps, and is NULL for
    an unsectioned step. A sectioned step therefore needs both, or the
    duplicate would sit correctly in one view and wrongly in the other.
    """
    db.execute(
        update(PathwayStep)
        .where(
            PathwayStep.pathway_id == source.pathway_id,
            PathwayStep.position > source.position,
        )
        .values(position=PathwayStep.position + 1)
    )
    if source.section_id is not None and source.section_position is not None:
        db.execute(
            update(PathwayStep)
            .where(
                PathwayStep.section_id == source.section_id,
                PathwayStep.section_position > source.section_position,
            )
            .values(section_position=PathwayStep.section_position + 1)
        )


def duplicate_step_row(
    db: Session, source: PathwayStep, *, slug: str,
) -> PathwayStep:
    """The new step itself, positioned after ``source``.

    Does not commit — the caller owns the transaction, so a failure
    part-way through copying blocks leaves no half-built step and no
    disturbed ordering.
    """
    _shift_down(db, source)

    duplicate = PathwayStep(
        id=str(uuid4()),
        pathway_id=source.pathway_id,
        slug=slug,
        title=copied_title(source.title),
        position=source.position + 1,
        section_position=(
            source.section_position + 1
            if source.section_position is not None else None
        ),
        **{field: getattr(source, field) for field in STEP_FIELDS},
    )
    db.add(duplicate)
    db.flush()
    return duplicate


def duplicate_blocks(
    db: Session, source: PathwayStep, duplicate: PathwayStep,
) -> int:
    """Copy the content blocks, in order, with new identities.

    Returns how many were copied. ``position`` is carried verbatim so
    the structure a creator built — introduction, video, reflection,
    exercise, resource — arrives in that order rather than reshuffled.
    """
    blocks = (
        db.query(PathwayStepBlock)
        .filter(PathwayStepBlock.step_id == source.id)
        .order_by(PathwayStepBlock.position)
        .all()
    )
    for block in blocks:
        db.add(PathwayStepBlock(
            id=str(uuid4()),
            step_id=duplicate.id,
            **{field: getattr(block, field) for field in BLOCK_FIELDS},
        ))
    db.flush()
    return len(blocks)


def duplicate_resources(
    db: Session, source: PathwayStep, duplicate: PathwayStep,
) -> int:
    """Copy the step's supplementary resources.

    Creator content, not member activity: a title, a link or a path to
    a file the original already serves. Nothing is re-uploaded.
    """
    resources = (
        db.query(StepResource)
        .filter(StepResource.step_id == source.id)
        .order_by(StepResource.position)
        .all()
    )
    for resource in resources:
        db.add(StepResource(
            id=str(uuid4()),
            step_id=duplicate.id,
            **{field: getattr(resource, field) for field in RESOURCE_FIELDS},
        ))
    db.flush()
    return len(resources)


def duplicate_step(
    db: Session, source: PathwayStep, *, slug: str,
) -> PathwayStep:
    """Copy ``source`` into a new step immediately after it.

    One transaction, which the caller commits. Blocks and resources are
    copied before anything is committed, so a failure cannot leave a
    step with half its content or a Pathway with two steps claiming one
    position.
    """
    duplicate = duplicate_step_row(db, source, slug=slug)
    duplicate_blocks(db, source, duplicate)
    duplicate_resources(db, source, duplicate)
    return duplicate


__all__ = [
    "BLOCK_FIELDS",
    "COPY_SUFFIX",
    "RESOURCE_FIELDS",
    "STEP_FIELDS",
    "copied_title",
    "duplicate_blocks",
    "duplicate_resources",
    "duplicate_step",
    "duplicate_step_row",
]
