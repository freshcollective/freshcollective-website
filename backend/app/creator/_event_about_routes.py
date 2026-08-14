"""Creator-side About block CRUD for individual Gatherings (Events).

Extends the same polymorphic ``pathway_about_blocks`` table that
already carries Pathway (``owner_kind='pathway'``) and Gathering
Series (``owner_kind='event_series'``) content — see migration 113.
Events add ``owner_kind='event'``.

Reuses every existing primitive:
    * request/response schemas (``AboutBlockCreateRequest`` etc.)
    * button/embed normalisers
    * media/resource lookup helpers

The same frontend ``AboutPageEditor`` + ``AboutBlockRenderer``
render the payload without a code-path split.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.creator.routes import (
    _get_managed_space,
    _normalise_button_fields,
    get_creator_user,
    router,
)
from app.creator.schemas import (
    AboutBlockCreateRequest,
    AboutBlockReorderRequest,
    AboutBlockResponse,
    AboutBlockUpdateRequest,
)
from app.services.embed_validator import (
    EmbedValidationError,
    extract_and_validate_embed_url,
)
from app.models.platform import (
    CreatorMediaAsset,
    Event,
    PathwayAboutBlock,
    Space,
    SpaceResource,
    StepBlockType,
)
from app.models.user import User


_EVENT_OWNER_KIND = "event"


def _get_managed_event(space: Space, event_id: str, db: Session) -> Event:
    ev = (
        db.query(Event)
        .filter(Event.id == event_id, Event.space_id == space.id)
        .first()
    )
    if not ev:
        raise HTTPException(status_code=404, detail="Gathering not found.")
    return ev


def _event_about_blocks_query(event: Event, db: Session):
    return (
        db.query(PathwayAboutBlock)
        .options(
            selectinload(PathwayAboutBlock.media_asset),
            selectinload(PathwayAboutBlock.resource),
        )
        .filter(
            PathwayAboutBlock.owner_kind == _EVENT_OWNER_KIND,
            PathwayAboutBlock.owner_id == event.id,
        )
        .order_by(PathwayAboutBlock.position)
    )


@router.get(
    "/spaces/{slug}/events/{event_id}/about-blocks",
    response_model=list[AboutBlockResponse],
)
def list_event_about_blocks(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayAboutBlock]:
    space = _get_managed_space(slug, current_user, db)
    event = _get_managed_event(space, event_id, db)
    return _event_about_blocks_query(event, db).all()


@router.post(
    "/spaces/{slug}/events/{event_id}/about-blocks",
    response_model=AboutBlockResponse,
    status_code=201,
)
def create_event_about_block(
    slug: str,
    event_id: str,
    body: AboutBlockCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayAboutBlock:
    space = _get_managed_space(slug, current_user, db)
    event = _get_managed_event(space, event_id, db)

    if body.media_asset_id:
        asset = db.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id == body.media_asset_id,
            CreatorMediaAsset.space_id == space.id,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found in this space.")

    if body.resource_id:
        linked = db.query(SpaceResource).filter(
            SpaceResource.id == body.resource_id,
            SpaceResource.space_id == space.id,
        ).first()
        if not linked:
            raise HTTPException(status_code=404, detail="Resource not found in this space.")

    embed_url = body.embed_url
    content = body.content
    label = body.label
    caption = body.caption
    if body.block_type == "embed" and embed_url:
        try:
            embed_url = extract_and_validate_embed_url(embed_url)
        except EmbedValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    elif body.block_type == "button":
        normalised = _normalise_button_fields({
            "embed_url": embed_url,
            "label": label,
            "caption": caption,
            "content": content,
        })
        embed_url = normalised["embed_url"]
        label = normalised["label"]
        caption = normalised["caption"]
        content = normalised["content"]

    if body.position is not None:
        position = body.position
    else:
        max_pos = (
            db.query(func.max(PathwayAboutBlock.position))
            .filter(
                PathwayAboutBlock.owner_kind == _EVENT_OWNER_KIND,
                PathwayAboutBlock.owner_id == event.id,
            )
            .scalar()
        )
        position = (max_pos or -1) + 1

    block = PathwayAboutBlock(
        id=str(uuid4()),
        owner_kind=_EVENT_OWNER_KIND,
        owner_id=event.id,
        pathway_id=None,
        block_type=body.block_type,
        position=position,
        content=content,
        label=label,
        caption=caption,
        embed_url=embed_url,
        media_asset_id=body.media_asset_id,
        resource_id=body.resource_id,
        container_style=body.container_style,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset", "resource"])
    return block


# ``/reorder`` MUST register before ``/{block_id}`` — FastAPI matches
# in declaration order and would otherwise treat "reorder" as an id.
@router.patch(
    "/spaces/{slug}/events/{event_id}/about-blocks/reorder",
    response_model=list[AboutBlockResponse],
)
def reorder_event_about_blocks(
    slug: str,
    event_id: str,
    body: AboutBlockReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayAboutBlock]:
    space = _get_managed_space(slug, current_user, db)
    event = _get_managed_event(space, event_id, db)

    blocks = {
        b.id: b
        for b in db.query(PathwayAboutBlock)
        .filter(
            PathwayAboutBlock.owner_kind == _EVENT_OWNER_KIND,
            PathwayAboutBlock.owner_id == event.id,
        )
        .all()
    }
    for pos, block_id in enumerate(body.ids):
        if block_id in blocks:
            blocks[block_id].position = pos
    db.commit()
    return _event_about_blocks_query(event, db).all()


@router.patch(
    "/spaces/{slug}/events/{event_id}/about-blocks/{block_id}",
    response_model=AboutBlockResponse,
)
def update_event_about_block(
    slug: str,
    event_id: str,
    block_id: str,
    body: AboutBlockUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayAboutBlock:
    space = _get_managed_space(slug, current_user, db)
    event = _get_managed_event(space, event_id, db)

    block = (
        db.query(PathwayAboutBlock)
        .filter(
            PathwayAboutBlock.id == block_id,
            PathwayAboutBlock.owner_kind == _EVENT_OWNER_KIND,
            PathwayAboutBlock.owner_id == event.id,
        )
        .first()
    )
    if not block:
        raise HTTPException(status_code=404, detail="About block not found.")

    if body.media_asset_id is not None:
        asset = db.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id == body.media_asset_id,
            CreatorMediaAsset.space_id == space.id,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found in this space.")

    if body.resource_id is not None:
        linked = db.query(SpaceResource).filter(
            SpaceResource.id == body.resource_id,
            SpaceResource.space_id == space.id,
        ).first()
        if not linked:
            raise HTTPException(status_code=404, detail="Resource not found in this space.")

    patch = body.model_dump(exclude_unset=True)

    if block.block_type == StepBlockType.embed and patch.get("embed_url"):
        try:
            patch["embed_url"] = extract_and_validate_embed_url(patch["embed_url"])
        except EmbedValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    if block.block_type == StepBlockType.button:
        _normalise_button_fields(patch)

    for field, value in patch.items():
        setattr(block, field, value)

    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset", "resource"])
    return block


@router.delete(
    "/spaces/{slug}/events/{event_id}/about-blocks/{block_id}",
    status_code=204,
)
def delete_event_about_block(
    slug: str,
    event_id: str,
    block_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    event = _get_managed_event(space, event_id, db)

    block = (
        db.query(PathwayAboutBlock)
        .filter(
            PathwayAboutBlock.id == block_id,
            PathwayAboutBlock.owner_kind == _EVENT_OWNER_KIND,
            PathwayAboutBlock.owner_id == event.id,
        )
        .first()
    )
    if not block:
        raise HTTPException(status_code=404, detail="About block not found.")
    db.delete(block)
    db.commit()
