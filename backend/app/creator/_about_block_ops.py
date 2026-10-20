"""Owner-agnostic About-block operations.

``pathway_about_blocks`` has been polymorphic since migration 113 —
``owner_kind`` + ``owner_id`` — and three surfaces already write to it:
Pathways, Gathering Series and Events. Each carries its own copy of the
same five handlers, and the bodies differ only in which owner they
resolve and which ``owner_kind`` they stamp.

Offerings is the fourth, and a fourth copy is where the drift starts.
So the shared parts live here: the field validation (embed URLs, nav
URLs, media URLs, button normalisation), the position arithmetic, the
scoping, and the media/resource ownership checks. A caller supplies the
owner and gets the behaviour.

Scope of this change
--------------------

The three existing surfaces are **not** migrated onto this module. They
work, they are covered by tests, and rewriting live endpoints to prove a
point about duplication is a risk this phase has no reason to take. What
this does is stop the count going to four. Migrating the other three is
a clean follow-up with its own test run.

What is deliberately *not* here
-------------------------------

Authorisation. Each surface decides who may edit its About page —
Offerings is owner-only where Pathways accepts any manager — so the
caller resolves the Space and the owner before calling anything here.
A shared module that also decided permissions would be one edit away
from granting a moderator access to a product they cannot otherwise
touch.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.models.platform import (
    CreatorMediaAsset,
    PathwayAboutBlock,
    Space,
    SpaceResource,
    StepBlockType,
)


def blocks_query(db: Session, *, owner_kind: str, owner_id: str):
    """Every block for one owner, in display order, with media loaded."""
    return (
        db.query(PathwayAboutBlock)
        .options(
            selectinload(PathwayAboutBlock.media_asset),
            selectinload(PathwayAboutBlock.resource),
        )
        .filter(
            PathwayAboutBlock.owner_kind == owner_kind,
            PathwayAboutBlock.owner_id == owner_id,
        )
        .order_by(PathwayAboutBlock.position)
    )


def get_block(
    db: Session, *, owner_kind: str, owner_id: str, block_id: str,
) -> PathwayAboutBlock:
    """One block, scoped to its owner.

    Scoped rather than fetched by id alone, so a block id belonging to
    another Collective's Pathway is a 404 here rather than something
    this caller can edit.
    """
    block = (
        db.query(PathwayAboutBlock)
        .filter(
            PathwayAboutBlock.id == block_id,
            PathwayAboutBlock.owner_kind == owner_kind,
            PathwayAboutBlock.owner_id == owner_id,
        )
        .first()
    )
    if block is None:
        raise HTTPException(status_code=404, detail="About block not found.")
    return block


def assert_media_in_space(
    db: Session, *, space: Space, media_asset_id: str | None,
    resource_id: str | None,
) -> None:
    """A block may only reference media belonging to its own Collective."""
    if media_asset_id:
        found = (
            db.query(CreatorMediaAsset.id)
            .filter(
                CreatorMediaAsset.id == media_asset_id,
                CreatorMediaAsset.space_id == space.id,
            )
            .first()
        )
        if not found:
            raise HTTPException(
                status_code=404, detail="Media asset not found in this space.",
            )
    if resource_id:
        found = (
            db.query(SpaceResource.id)
            .filter(
                SpaceResource.id == resource_id,
                SpaceResource.space_id == space.id,
            )
            .first()
        )
        if not found:
            raise HTTPException(
                status_code=404, detail="Resource not found in this space.",
            )


def validate_block_fields(block_type, fields: dict) -> dict:
    """Apply the per-type URL rules to a create or update payload.

    Mutates and returns ``fields``. The rules are lifted unchanged from
    the Series implementation, which is itself the corrected version of
    the Pathway one (SEC-016-1 added ``validate_nav_url`` to ``link``
    and ``video_embed``, and ``validate_media_url`` to ``image``).

    Accepts either a ``StepBlockType`` or its string value, because a
    create request carries the string and an update reads the enum off
    the stored row.
    """
    # Local imports: these live in modules that import creator routes,
    # and the cycle is real at module scope.
    from app.creator.routes import _normalise_button_fields
    from app.services.embed_validator import (
        EmbedValidationError,
        extract_and_validate_embed_url,
    )
    from app.services.content_url import (
        ContentUrlError,
        validate_media_url,
        validate_nav_url,
    )

    kind = block_type.value if hasattr(block_type, "value") else str(block_type)
    url = fields.get("embed_url")

    if kind == StepBlockType.embed.value and url:
        try:
            fields["embed_url"] = extract_and_validate_embed_url(url)
        except EmbedValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif kind in (StepBlockType.link.value, StepBlockType.video_embed.value) and url:
        try:
            fields["embed_url"] = validate_nav_url(url)
        except ContentUrlError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif kind == StepBlockType.image.value and url:
        try:
            fields["embed_url"] = validate_media_url(url)
        except ContentUrlError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif kind == StepBlockType.button.value:
        _normalise_button_fields(fields)

    return fields


def create_block(
    db: Session, *, space: Space, owner_kind: str, owner_id: str, body,
) -> PathwayAboutBlock:
    """Append a block to an owner's About page. Commits."""
    assert_media_in_space(
        db, space=space,
        media_asset_id=body.media_asset_id, resource_id=body.resource_id,
    )

    fields = validate_block_fields(body.block_type, {
        "embed_url": body.embed_url,
        "label": body.label,
        "caption": body.caption,
        "content": body.content,
    })

    if body.position is not None:
        position = body.position
    else:
        top = (
            db.query(func.max(PathwayAboutBlock.position))
            .filter(
                PathwayAboutBlock.owner_kind == owner_kind,
                PathwayAboutBlock.owner_id == owner_id,
            )
            .scalar()
        )
        # ``top is None`` rather than ``top or -1``.
        #
        # The three existing About-block endpoints all write
        # ``(max_pos or -1) + 1``, which is wrong whenever the highest
        # position is **0**: ``0 or -1`` is ``-1``, so the second block
        # lands on position 0 alongside the first, and so does every
        # block after it. The order then falls back to insertion order
        # and a reorder is the only thing that ever separates them.
        # Caught by the ordering test in ``test_offering_creator_studio``.
        position = 0 if top is None else top + 1

    block = PathwayAboutBlock(
        id=str(uuid4()),
        owner_kind=owner_kind,
        owner_id=owner_id,
        # Non-pathway owners leave the legacy FK NULL. Setting it would
        # point this row at a Pathway that does not own it, and the
        # member-side readers that still filter on ``pathway_id`` alone
        # would then render an Offering's content on a Pathway page.
        pathway_id=None,
        block_type=body.block_type,
        position=position,
        content=fields["content"],
        label=fields["label"],
        caption=fields["caption"],
        heading=body.heading,
        embed_url=fields["embed_url"],
        media_asset_id=body.media_asset_id,
        resource_id=body.resource_id,
        container_style=body.container_style,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset", "resource"])
    return block


def update_block(
    db: Session, *, space: Space, owner_kind: str, owner_id: str,
    block_id: str, body,
) -> PathwayAboutBlock:
    """Patch a block. Only fields present in the body are touched."""
    block = get_block(
        db, owner_kind=owner_kind, owner_id=owner_id, block_id=block_id,
    )

    patch = body.model_dump(exclude_unset=True)
    assert_media_in_space(
        db, space=space,
        media_asset_id=patch.get("media_asset_id"),
        resource_id=patch.get("resource_id"),
    )
    # The stored type decides the rules — a patch cannot change a
    # block's type, so trusting the row is correct and means a payload
    # cannot talk its way into a different validator.
    validate_block_fields(block.block_type, patch)

    for field, value in patch.items():
        setattr(block, field, value)
    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset", "resource"])
    return block


def reorder_blocks(
    db: Session, *, owner_kind: str, owner_id: str, ids: list[str],
) -> list[PathwayAboutBlock]:
    """Set positions from the given order. Ids not owned here are ignored.

    Ignored rather than refused, matching the three existing surfaces:
    the client sends the order it rendered, and an id that has since
    been deleted elsewhere should not fail the whole reorder.
    """
    blocks = {
        b.id: b
        for b in db.query(PathwayAboutBlock).filter(
            PathwayAboutBlock.owner_kind == owner_kind,
            PathwayAboutBlock.owner_id == owner_id,
        ).all()
    }
    for position, block_id in enumerate(ids):
        if block_id in blocks:
            blocks[block_id].position = position
    db.commit()
    return blocks_query(db, owner_kind=owner_kind, owner_id=owner_id).all()


def delete_block(
    db: Session, *, owner_kind: str, owner_id: str, block_id: str,
) -> None:
    block = get_block(
        db, owner_kind=owner_kind, owner_id=owner_id, block_id=block_id,
    )
    db.delete(block)
    db.commit()


__all__ = [
    "blocks_query",
    "get_block",
    "assert_media_in_space",
    "validate_block_fields",
    "create_block",
    "update_block",
    "reorder_blocks",
    "delete_block",
]
