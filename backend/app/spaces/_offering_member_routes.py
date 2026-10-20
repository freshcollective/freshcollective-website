"""The member-facing Offering detail page — Phase B7.

One endpoint:

    GET /api/spaces/{slug}/offerings/{offering_slug}

It serves the page a member reads before deciding, and it is the **same**
page a creator sees when they press Preview. There is deliberately no
second renderer and no preview-only payload: the Pathway preview works
by redirecting into the real member URL, and this follows it exactly.
A duplicate renderer is how a creator comes to approve a page that is
not the page anybody else gets.

Who may see what
----------------

``status`` governs visibility, and only for people who do not manage the
Collective:

  * **published** — any authenticated caller who can see the Collective.
  * **draft** — managers only. A draft is private: a 404, not a 403, so
    the endpoint cannot be used to discover that a Collective is working
    on something.
  * **retired** — still readable, because people own it and a retired
    product that 404s looks deleted. It stops selling, not serving.

Acquisition is not here
-----------------------

The payload carries pricing so the page can *state* the price, and
carries no mechanism to pay it. ``can_acquire`` is absent by design
rather than present and false — a field that exists invites a button,
and the acquisition infrastructure (Phase D) does not exist. What the
payload does carry is ``viewer_owns``, because a member who already owns
an Offering should see their downloads rather than a price.

What a non-owner learns about the files
---------------------------------------

Names, types, sizes and descriptions — enough to judge what they would
be buying. **Never a storage key and never a URL.** Those appear only
for a caller with an active entitlement, and even then the download
route re-checks the entitlement itself, so this payload is a convenience
rather than the thing that authorises anything.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.creator._offering_about_routes import OFFERING_OWNER_KIND
from app.creator._offering_routes import require_offerings_enabled
from app.creator.schemas import AboutBlockResponse
from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingEntitlementStatus,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
    OfferingStatus,
)
from app.models.platform import PathwayAboutBlock, Space
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/spaces", tags=["offerings-member"])


def _file_type_label(content_type: str, filename: str) -> str:
    """A word a member understands, from the type we actually stored.

    Derived from the server-determined content type rather than the
    filename, so a file named ``notes.pdf`` that is really a ZIP is
    described as what it is.
    """
    ct = (content_type or "").lower()
    if ct == "application/pdf":
        return "PDF"
    if "wordprocessingml" in ct:
        return "Word document"
    if "spreadsheetml" in ct:
        return "Excel spreadsheet"
    if "presentationml" in ct:
        return "PowerPoint presentation"
    if ct in ("text/csv", "application/csv"):
        return "Spreadsheet (CSV)"
    if ct == "text/markdown":
        return "Markdown document"
    if ct == "text/plain":
        return "Text document"
    if ct.startswith("audio/"):
        return "Audio"
    if ct in ("application/zip", "application/x-zip-compressed"):
        return "ZIP bundle"
    ext = filename.rsplit(".", 1)[-1].upper() if "." in filename else ""
    return f"{ext} file" if ext else "File"


def _human_size(byte_size: int) -> str:
    """"2.4 MB", not "2516582 bytes"."""
    if byte_size < 1024:
        return f"{byte_size} bytes"
    if byte_size < 1024 * 1024:
        return f"{byte_size / 1024:.0f} KB"
    return f"{byte_size / (1024 * 1024):.1f} MB"


def _user_manages_space(user: User | None, space: Space, db: Session) -> bool:
    from app.spaces.routes import _user_manages_space as shared
    return shared(user, space, db)


@router.get(
    "/{slug}/offerings/{offering_slug}",
    # The *same* gate function the creator routes use, not a second
    # copy. One name, one behaviour, and the structural tests that
    # assert "every Offering route is gated" keep matching on it.
    #
    # This gates *presentation*. It deliberately does NOT gate
    # ``/api/uploads/offering-files/...``, which the entitlement alone
    # governs: turning the feature off closes the shopfront and must
    # never reach into what a member already owns.
    dependencies=[Depends(require_offerings_enabled)],
    summary="One Offering, as a member sees it",
)
def get_member_offering(
    slug: str,
    offering_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """The member detail page, and the creator's Preview target."""
    from app.spaces.routes import _get_space_visible_to

    space = _get_space_visible_to(slug, db, current_user)
    offering = (
        db.query(Offering)
        .filter(Offering.space_id == space.id, Offering.slug == offering_slug)
        .first()
    )
    if offering is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Offering not found.",
        )

    is_manager = _user_manages_space(current_user, space, db)

    # Draft privacy. 404 rather than 403: a stranger must not be able to
    # learn that a Collective has an unreleased product, or confirm a
    # slug they guessed.
    if offering.status == OfferingStatus.draft.value and not is_manager:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Offering not found.",
        )

    owns = (
        db.query(OfferingEntitlement.id)
        .filter(
            OfferingEntitlement.user_id == current_user.id,
            OfferingEntitlement.offering_id == offering.id,
            OfferingEntitlement.status == OfferingEntitlementStatus.active.value,
        )
        .first()
    ) is not None

    current_files = (
        db.query(OfferingFile)
        .filter(
            OfferingFile.offering_id == offering.id,
            OfferingFile.superseded_at.is_(None),
        )
        .order_by(OfferingFile.sort_order, OfferingFile.created_at)
        .all()
    )
    # Only approved files are described. A member must not be shown a
    # row for a file that is still being checked or was refused — it
    # would describe something they would then be unable to download.
    approved = [f for f in current_files if f.validation_status == FVS.passed.value]

    blocks = (
        db.query(PathwayAboutBlock)
        .filter(
            PathwayAboutBlock.owner_kind == OFFERING_OWNER_KIND,
            PathwayAboutBlock.owner_id == offering.id,
        )
        .order_by(PathwayAboutBlock.position)
        .all()
    )

    owner = (
        db.query(User).filter(User.id == space.creator_id).first()
        if space.creator_id
        else None
    )

    return {
        "id": offering.id,
        "slug": offering.slug,
        "title": offering.title,
        "summary": offering.summary,
        "description": offering.description,
        "cover_image_url": offering.cover_image_url,
        "status": offering.status,
        "pricing_kind": offering.pricing_kind,
        "price_cents": offering.price_cents,
        # Fixed for Phase 1 and sent explicitly rather than inferred by
        # the client, so the page's "Digital download" statement comes
        # from the record rather than from an assumption in the UI.
        "fulfilment_kind": offering.fulfilment_kind,
        "published_at": offering.published_at,
        "retired_at": offering.retired_at,
        "collective": {
            "slug": space.slug,
            "name": space.name,
            "logo_url": getattr(space, "logo_url", None),
            # The Collective's Colour Palette drives container styling
            # inside About blocks, exactly as it does on a Pathway About
            # page — so an Offering's rich content sits in the same
            # visual world as the rest of the Collective.
            "colour_palette": getattr(space, "colour_palette", None),
        },
        "creator": {"name": owner.name} if owner else None,
        "about_blocks": [
            AboutBlockResponse.model_validate(b, from_attributes=True).model_dump()
            for b in blocks
        ],
        "files": [
            {
                "id": f.id,
                "name": f.original_filename,
                "type_label": _file_type_label(f.content_type, f.original_filename),
                "size_label": _human_size(f.byte_size),
                "byte_size": f.byte_size,
                "description": f.description,
                # How many resources a bundle contains, so "1 ZIP bundle"
                # can honestly say what is inside it.
                "resource_count": f.resource_count or 1,
                # The download path, for owners only. A non-owner is told
                # what the file *is* and never where it lives — and the
                # download route re-checks the entitlement regardless, so
                # this is convenience, not authorisation.
                "download_url": (
                    f"/api/uploads/{f.storage_key}" if owns else None
                ),
            }
            for f in approved
        ],
        "file_count": len(approved),
        "total_resources": sum((f.resource_count or 1) for f in approved),
        "viewer_owns": owns,
        # So the preview banner can say "only you can see this".
        "viewer_manages": is_manager,
    }


__all__ = ["router"]
