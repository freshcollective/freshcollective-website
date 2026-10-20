"""The Offering About page — Phase B6.

Five endpoints, each a thin shell over
:mod:`app.creator._about_block_ops`. The blocks are the *same* rows, in
the same table, rendered by the same ``AboutBlockRenderer`` the Pathway
and Gathering Series About pages use. Nothing about rich content is
reimplemented here: an Offering simply becomes a fourth ``owner_kind``.

Why no migration was needed
---------------------------

``pathway_about_blocks.owner_kind`` is ``String(20)`` with no CHECK
constraint, and migration 113's own docstring anticipated this: *"New
owner kinds slot in without a further migration."* Adding ``'offering'``
is a value, not a schema change.

Optional, and it stays optional
-------------------------------

An Offering with no About blocks is complete. ``offering_readiness``
deliberately has no ``about`` requirement — including one even as a
passing row would imply the section had been assessed — so a creator who
wants to sell a worksheet with a title and a cover is never nagged to
write a page about it.

Owner-only, like the rest of Offerings
--------------------------------------

Reuses ``_get_owned_space`` rather than ``_get_managed_space``. The
Pathway About page accepts any manager; this one does not, for the same
reason the rest of Offering management does not — a moderator helping
run a community should not be editing the sales page of a product sold
under someone else's payout account.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.creator import _about_block_ops as ops
from app.creator._offering_routes import (
    _get_offering,
    _get_owned_space,
    require_offerings_enabled,
)
from app.creator.routes import get_creator_user
from app.creator.schemas import (
    AboutBlockCreateRequest,
    AboutBlockReorderRequest,
    AboutBlockResponse,
    AboutBlockUpdateRequest,
)
from app.models.platform import PathwayAboutBlock
from app.models.user import User

#: The fourth owner kind. Singular and lower-case, matching
#: ``'pathway'`` and ``'event_series'``.
OFFERING_OWNER_KIND = "offering"

router = APIRouter(
    prefix="/api/creator",
    tags=["creator-offering-about"],
    dependencies=[Depends(require_offerings_enabled)],
)

_BASE = "/spaces/{slug}/offerings/{offering_slug}/about-blocks"


def _resolve(slug: str, offering_slug: str, user: User, db: Session):
    """Collective, then Offering through it. Owner-only at both levels."""
    space = _get_owned_space(slug, user, db)
    offering = _get_offering(space, offering_slug, db)
    return space, offering


@router.get(_BASE, response_model=list[AboutBlockResponse])
def list_offering_about_blocks(
    slug: str,
    offering_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayAboutBlock]:
    _space, offering = _resolve(slug, offering_slug, current_user, db)
    return ops.blocks_query(
        db, owner_kind=OFFERING_OWNER_KIND, owner_id=offering.id,
    ).all()


@router.post(
    _BASE, response_model=AboutBlockResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_offering_about_block(
    slug: str,
    offering_slug: str,
    body: AboutBlockCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayAboutBlock:
    space, offering = _resolve(slug, offering_slug, current_user, db)
    return ops.create_block(
        db, space=space, owner_kind=OFFERING_OWNER_KIND,
        owner_id=offering.id, body=body,
    )


# ``/reorder`` must be registered BEFORE ``/{block_id}`` or FastAPI
# matches the literal path as a block id. The same note sits above the
# Pathway and Series versions for the same reason.
@router.patch(_BASE + "/reorder", response_model=list[AboutBlockResponse])
def reorder_offering_about_blocks(
    slug: str,
    offering_slug: str,
    body: AboutBlockReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayAboutBlock]:
    _space, offering = _resolve(slug, offering_slug, current_user, db)
    return ops.reorder_blocks(
        db, owner_kind=OFFERING_OWNER_KIND, owner_id=offering.id,
        ids=body.ids,
    )


@router.patch(_BASE + "/{block_id}", response_model=AboutBlockResponse)
def update_offering_about_block(
    slug: str,
    offering_slug: str,
    block_id: str,
    body: AboutBlockUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayAboutBlock:
    space, offering = _resolve(slug, offering_slug, current_user, db)
    return ops.update_block(
        db, space=space, owner_kind=OFFERING_OWNER_KIND,
        owner_id=offering.id, block_id=block_id, body=body,
    )


@router.delete(_BASE + "/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_offering_about_block(
    slug: str,
    offering_slug: str,
    block_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    _space, offering = _resolve(slug, offering_slug, current_user, db)
    ops.delete_block(
        db, owner_kind=OFFERING_OWNER_KIND, owner_id=offering.id,
        block_id=block_id,
    )


__all__ = ["router", "OFFERING_OWNER_KIND"]
