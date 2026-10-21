"""Creator-side Offering **file** management — Phase B5.

Six endpoints behind the Files tab: list, upload, describe, reorder,
replace, remove. Everything about authorisation, flag-gating and
Offering resolution is inherited from ``_offering_routes`` rather than
restated — same ``require_offerings_enabled`` router dependency, same
owner-only ``_get_owned_space``, same resolve-through-the-Collective
``_get_offering``. A second copy of any of those is a second thing to
keep in step.

The ordering that makes this safe
---------------------------------

Every write path does the same five things in the same order, and the
order is the design:

  1. **Resolve and authorise** — owner-only, Offering through its
     Collective. A cross-Collective id is a 404, not a 403.
  2. **Take a concurrency slot** and stream the body to local disk,
     enforcing the per-file byte limit as the bytes arrive.
  3. **Transfer to R2** with no database lock held. A multipart upload
     of 50 MB can take tens of seconds, and holding a row lock across it
     would serialise an entire Collective's Creator Studio behind one
     upload.
  4. **Lock the Offering row, re-check the allowance, insert, commit.**
     Short and serialised. This is the authoritative limit check — the
     one in step 2 is a courtesy that fails fast without wasting a
     transfer.
  5. **On any failure after step 3, delete the R2 object.** The
     compensating action that keeps "no orphaned objects" true, rather
     than hoping step 4 never fails.

Nothing an upload produces is downloadable
------------------------------------------

A new row's ``validation_status`` defaults to ``pending`` in the column
itself, and ``app/uploads/authorization.py`` refuses anything that is not
``passed`` — for purchasers, for the creator who uploaded it, and for
admins alike. So "no upload may produce an immediately downloadable
file" is a property of the schema and the download route, not a rule
this module has to remember. There is deliberately no preview URL here.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import storage
from app.core.database import get_db
from app.creator._offering_routes import (
    _get_offering,
    _get_owned_space,
    require_offerings_enabled,
)
from app.creator.routes import get_creator_user
from app.creator.schemas_offerings import (
    OfferingFileListResponse,
    OfferingFileReorderRequest,
    OfferingFileResponse,
    OfferingFileUpdateRequest,
)
from app.models.offering import (
    Offering,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
)
from app.models.user import User
from app.services.offering_files import (
    OFFERING_COVERS_PREFIX,
    build_storage_key,
    sanitise_filename,
)
from app.services.offering_limits import (
    bundle_usage,
    guard_upload,
    limits_for_space,
)
from app.services.offering_upload import received, upload_slot

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/creator",
    tags=["creator-offering-files"],
    dependencies=[Depends(require_offerings_enabled)],
)

_BASE = "/spaces/{slug}/offerings/{offering_slug}/files"


# ---------------------------------------------------------------------------
# Creator-facing status
# ---------------------------------------------------------------------------

#: The approved four-word vocabulary. ``error`` and ``quarantined`` both
#: read as **On hold** on purpose: from the creator's side both mean "we
#: have not approved this and are not telling you more", and
#: distinguishing them would describe how the platform detects problems
#: to the person best placed to work around it. The machine-readable
#: ``validation_status`` still carries the difference for the UI and for
#: support.
_STATUS_LABELS = {
    FVS.pending.value: "Checking",
    FVS.passed.value: "Ready",
    FVS.rejected.value: "Not accepted",
    FVS.error.value: "On hold",
    FVS.quarantined.value: "On hold",
}

#: Shown when a file is on hold. Deliberately not the machine reason:
#: "inconclusive" means nothing to a creator, and a quarantine reason
#: could name a detection technique.
#
# It also deliberately avoids the words "safe", "clean" and "scanned".
# Nothing here scans for malware, and a reassuring adjective beside a
# file status is exactly how a creator would come to believe otherwise.
# A test asserts that none of this module's creator-facing prose uses
# them.
_ON_HOLD_MESSAGE = (
    "We haven't been able to finish checking this file yet. There's "
    "nothing you need to do — we'll keep trying. If it stays here, "
    "replace it or get in touch."
)


def _reason_for(row: OfferingFile) -> str | None:
    """The creator-facing explanation, or None when nothing is wrong."""
    if row.validation_status == FVS.rejected.value:
        # ``validation_reason`` is a machine code; the prose that went
        # with it was returned at upload. Map the codes a creator can act
        # on and fall back to a general sentence for the rest, so a new
        # reason code can never leak an internal detail into the UI.
        return _REJECTION_PROSE.get(
            row.validation_reason or "",
            "We couldn't accept this file. Please check the format and "
            "try again, or upload a different version.",
        )
    if row.validation_status in (FVS.error.value, FVS.quarantined.value):
        return _ON_HOLD_MESSAGE
    return None


_REJECTION_PROSE = {
    "file_too_large": "This file is larger than your plan allows.",
    "bundle_too_large": (
        "Adding this file would take the Offering over its total size "
        "allowance."
    ),
    "too_many_files": "This Offering already has as many files as your plan allows.",
    "zip_not_permitted": (
        "Your plan doesn't include ZIP bundles. Upload the files directly, "
        "or upgrade to Creator."
    ),
    "unsupported_type": "That file type isn't supported for Offerings.",
    "forbidden_type": "That file type can't be sold as a download.",
    "content_type_mismatch": "This file's type doesn't match its extension.",
    "signature_mismatch": "This file's contents don't match its file type.",
    "macro_document": (
        "This file includes macros, which we can't accept. Saving it as "
        ".docx, .xlsx or .pptx usually works."
    ),
    "legacy_office": (
        "This is an older Office format. Please save it as .docx, .xlsx or "
        ".pptx and upload again."
    ),
    "encrypted_archive": (
        "This ZIP is password-protected, so we can't check what's inside. "
        "Please upload an unprotected version."
    ),
    "unsafe_archive": (
        "This ZIP contains entries we can't accept. Please rebuild the "
        "archive from a plain folder."
    ),
    "zip_bomb": (
        "This archive expands to far more than we can accept. Please "
        "reduce its contents or split it into smaller downloads."
    ),
    "zip_contents": (
        "This ZIP contains files that can't be sold as downloads. Remove "
        "them and upload again."
    ),
    "formula_injection": (
        "This spreadsheet contains cells that start like a formula, which "
        "some apps run automatically. Please remove them and upload again."
    ),
    "inspection_budget_exceeded": (
        "This file is too complex for us to check fully. Please simplify "
        "it or split it into smaller downloads."
    ),
    "unreadable": (
        "We couldn't read this file — it may not have uploaded completely. "
        "Please try again."
    ),
    "empty_file": "That file is empty.",
    "no_extension": "That file needs a file extension so members know what it is.",
}


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _pending_replacement_targets(
    db: Session, offering: Offering,
) -> set[str]:
    """Ids of current files that have a replacement in flight."""
    rows = (
        db.query(OfferingFile.replaces_file_id)
        .filter(
            OfferingFile.offering_id == offering.id,
            OfferingFile.superseded_at.is_(None),
            OfferingFile.replaces_file_id.isnot(None),
            OfferingFile.validation_status.in_(
                (FVS.pending.value, FVS.error.value),
            ),
        )
        .all()
    )
    return {r[0] for r in rows if r[0]}


def _serialise(row: OfferingFile, *, being_replaced: bool) -> dict:
    return {
        "id": row.id,
        "filename": row.original_filename,
        "content_type": row.content_type,
        "byte_size": row.byte_size,
        "description": row.description,
        "sort_order": row.sort_order,
        "resource_count": row.resource_count or 1,
        "validation_status": row.validation_status,
        "status_label": _STATUS_LABELS.get(row.validation_status, "On hold"),
        "rejection_reason": _reason_for(row),
        # The same two conditions the download route enforces, read off
        # the model's own property rather than re-expressed here.
        "available_to_purchasers": row.is_downloadable,
        "replacement_pending": being_replaced,
        "replaces_file_id": row.replaces_file_id,
        "created_at": row.created_at,
        "validated_at": row.validated_at,
    }


def _current_files(db: Session, offering: Offering) -> list[OfferingFile]:
    return (
        db.query(OfferingFile)
        .filter(
            OfferingFile.offering_id == offering.id,
            OfferingFile.superseded_at.is_(None),
        )
        .order_by(OfferingFile.sort_order, OfferingFile.created_at)
        .all()
    )


def _list_payload(db: Session, *, space, offering: Offering) -> dict:
    limits = limits_for_space(space, db)
    usage = bundle_usage(db, offering=offering)
    being_replaced = _pending_replacement_targets(db, offering)
    return {
        "files": [
            _serialise(f, being_replaced=f.id in being_replaced)
            for f in _current_files(db, offering)
        ],
        "resources_used": usage.resources,
        "resources_allowed": limits.max_files,
        "bytes_used": usage.bytes_used,
        "bytes_allowed": limits.max_bundle_bytes,
        "max_file_bytes": limits.max_file_bytes,
        "zip_bundles_allowed": limits.zip_bundles_allowed,
        "plan_name": limits.plan_name,
    }


# ---------------------------------------------------------------------------
# Shared store-and-record
# ---------------------------------------------------------------------------


def _store_upload(
    db: Session,
    *,
    space,
    offering: Offering,
    upload: UploadFile,
    description: str | None,
    replacing: OfferingFile | None,
) -> OfferingFile:
    """The common body of upload and replace. See the module docstring.

    Returns the committed ``OfferingFile`` row, always ``pending``.
    """
    limits = limits_for_space(space, db)

    with upload_slot():
        with received(upload, max_bytes=limits.max_file_bytes) as got:
            # Courtesy pre-check: refuse an obviously over-allowance
            # upload before paying for an R2 transfer. Not authoritative
            # — the locked check below is — but it turns the common case
            # into a fast, cheap refusal.
            guard_upload(
                db,
                offering=offering,
                limits=limits,
                filename=got.filename,
                content_type=got.content_type,
                byte_size=got.byte_size,
                resource_count=got.resource_count,
                replacing_file_id=replacing.id if replacing else None,
            )

            key = build_storage_key(
                offering_id=offering.id, filename=got.filename,
            )

            # No lock held: a 50 MB multipart transfer must not serialise
            # the Collective's other writes behind it.
            with got.open() as fh:
                storage.upload_stream(key, fh, got.content_type)

            try:
                # Authoritative, serialised. Two uploads racing for the
                # last slot both arrive here; the lock makes the second
                # one see the first one's row.
                db.execute(
                    text("SELECT id FROM offerings WHERE id = :id FOR UPDATE"),
                    {"id": offering.id},
                )
                guard_upload(
                    db,
                    offering=offering,
                    limits=limits,
                    filename=got.filename,
                    content_type=got.content_type,
                    byte_size=got.byte_size,
                    resource_count=got.resource_count,
                    replacing_file_id=replacing.id if replacing else None,
                )

                if replacing is not None:
                    _assert_replaceable(db, offering, replacing)

                row = OfferingFile(
                    id=str(uuid4()),
                    offering_id=offering.id,
                    storage_key=key,
                    original_filename=sanitise_filename(got.filename),
                    content_type=got.content_type or "application/octet-stream",
                    byte_size=got.byte_size,
                    description=(description or "").strip() or None,
                    resource_count=got.resource_count,
                    sort_order=(
                        replacing.sort_order
                        if replacing is not None
                        else _next_sort_order(db, offering)
                    ),
                    replaces_file_id=replacing.id if replacing else None,
                    # Explicit, though the column defaults to it. An
                    # upload is never approved by the act of arriving.
                    validation_status=FVS.pending.value,
                )
                db.add(row)
                db.commit()
                db.refresh(row)
            except Exception:
                # The bytes are in R2 and no row references them. Remove
                # them rather than leaving an object nothing can reach.
                db.rollback()
                storage.delete_file(key)
                raise

    logger.info(
        "offering file uploaded: file=%s offering=%s bytes=%s resources=%s "
        "replacing=%s",
        row.id, offering.id, row.byte_size, row.resource_count,
        replacing.id if replacing else None,
    )
    return row


def _next_sort_order(db: Session, offering: Offering) -> int:
    top = (
        db.query(OfferingFile.sort_order)
        .filter(
            OfferingFile.offering_id == offering.id,
            OfferingFile.superseded_at.is_(None),
        )
        .order_by(OfferingFile.sort_order.desc())
        .first()
    )
    return (top[0] + 1) if top else 0


def _assert_replaceable(
    db: Session, offering: Offering, target: OfferingFile,
) -> None:
    """Refuse a second live replacement for the same file.

    The partial unique index ``ux_offering_files_pending_replacement``
    already makes this impossible; checking here turns what would be a
    500 from an integrity error into a 409 a creator can understand.
    """
    existing = (
        db.query(OfferingFile.id)
        .filter(
            OfferingFile.offering_id == offering.id,
            OfferingFile.replaces_file_id == target.id,
            OfferingFile.superseded_at.is_(None),
            OfferingFile.validation_status.in_(
                (FVS.pending.value, FVS.error.value),
            ),
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "replacement_in_flight",
                "message": (
                    "A replacement for this file is still being checked. "
                    "Wait for it to finish before uploading another."
                ),
            },
        )


def _get_file(
    db: Session, offering: Offering, file_id: str, *, current_only: bool = True,
) -> OfferingFile:
    """Resolve a file **through** its Offering.

    Scoped to the Offering the caller has already been authorised for, so
    a file id belonging to another Collective is a 404 rather than a
    leak — the same discipline ``_get_offering`` applies one level up.
    """
    q = db.query(OfferingFile).filter(
        OfferingFile.offering_id == offering.id,
        OfferingFile.id == file_id,
    )
    if current_only:
        q = q.filter(OfferingFile.superseded_at.is_(None))
    row = q.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found.",
        )
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Cover image
# ---------------------------------------------------------------------------

#: Covers are chrome, not product. 5 MB is generous for a 1200px image
#: and small enough that the upload is over before a creator wonders.
MAX_COVER_BYTES = 5 * 1024 * 1024

#: Raster formats only. No SVG: it is a document that can carry script,
#: and a cover is rendered on member-facing pages.
_COVER_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@router.post(
    "/spaces/{slug}/offerings/{offering_slug}/cover",
    response_model=OfferingFileResponse | dict,
    summary="Upload a custom cover image for this Offering",
)
def upload_offering_cover(
    slug: str,
    offering_slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Replace the Offering's cover with the creator's own image.

    Lives in this module rather than beside the other Details fields
    because it is an *upload*, and everything upload-shaped — the
    concurrency slot, the streaming receive, the bounded transfer — is
    already here. A second upload path written next to the PATCH handler
    would be a second place to get those wrong.

    Written into ``offering-covers/{offering_id}/…``, which is a
    different namespace from the downloadable files on purpose: a cover
    is shown to anyone who can see the Offering, a file only to someone
    who owns it. ``_authorise_offering_cover`` reads the Offering id out
    of the second path segment, so the shape matters.

    Choosing one of the five shared categories does **not** come through
    here — that is a PATCH storing the category *key*, with no bytes
    copied anywhere and no URL stored. The two live in separate columns,
    so an upload overrides the category without erasing it, and removing
    the upload falls back to it.
    """
    space = _get_owned_space(slug, current_user, db)
    offering = _get_offering(space, offering_slug, db)

    declared = (file.content_type or "").split(";")[0].strip().lower()
    if declared not in _COVER_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "reason": "unsupported_type",
                "message": "Cover images need to be a JPG, PNG or WebP.",
            },
        )

    previous = offering.cover_image_url

    with upload_slot():
        with received(file, max_bytes=MAX_COVER_BYTES) as got:
            # The extension comes from the *declared type we accepted*,
            # not from the filename, so a cover cannot be stored under a
            # suffix that disagrees with its content type.
            name = f"{sanitise_filename(got.filename).rsplit('.', 1)[0]}"
            key = (
                f"{OFFERING_COVERS_PREFIX}/{offering.id}/"
                f"{uuid4().hex}_{name}{_COVER_TYPES[declared]}"
            )
            with got.open() as fh:
                storage.upload_stream(key, fh, declared)
            try:
                offering.cover_image_url = f"/api/uploads/{key}"
                db.commit()
                db.refresh(offering)
            except Exception:
                db.rollback()
                storage.delete_file(key)
                raise

    # The previous custom cover is now unreferenced. The prefix check is
    # kept even though ``cover_image_url`` can now only hold a creator
    # upload: shared artwork lives in World Artwork under
    # ``platform-artwork/`` and is owned by administrators, so a delete
    # that ever reached it would remove an image every Collective uses.
    # Cheap, and the one guard standing between those two namespaces.
    if previous and previous.startswith(f"/api/uploads/{OFFERING_COVERS_PREFIX}/"):
        storage.delete_file(previous.removeprefix("/api/uploads/"))

    logger.info(
        "offering cover uploaded: offering=%s by=%s", offering.id, current_user.id,
    )
    return {"cover_image_url": offering.cover_image_url}


@router.get(
    _BASE,
    response_model=OfferingFileListResponse,
    summary="The current bundle, with validation status and remaining allowance",
)
def list_offering_files(
    slug: str,
    offering_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """What the Files tab polls.

    Polling rather than websockets, per the approved design: validation
    finishes in seconds to minutes, and a creator who navigates away and
    returns gets the same answer from the same endpoint. There is no
    in-memory progress state to lose.
    """
    space = _get_owned_space(slug, current_user, db)
    offering = _get_offering(space, offering_slug, db)
    return _list_payload(db, space=space, offering=offering)


@router.post(
    _BASE,
    response_model=OfferingFileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file into the current bundle",
)
def upload_offering_file(
    slug: str,
    offering_slug: str,
    file: UploadFile = File(...),
    description: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Add one file. It arrives ``pending`` and is not downloadable.

    201 with the row rather than 202: the file genuinely has been
    created and stored, and the creator can see it in the list
    immediately. What has *not* happened is approval, which the
    ``Checking`` status and ``available_to_purchasers: false`` say
    plainly.
    """
    space = _get_owned_space(slug, current_user, db)
    offering = _get_offering(space, offering_slug, db)
    row = _store_upload(
        db,
        space=space,
        offering=offering,
        upload=file,
        description=description,
        replacing=None,
    )
    return _serialise(row, being_replaced=False)


@router.post(
    _BASE + "/{file_id}/replace",
    response_model=OfferingFileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a replacement — the original stays available until it passes",
)
def replace_offering_file(
    slug: str,
    offering_slug: str,
    file_id: str,
    file: UploadFile = File(...),
    description: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Replace a file's contents, without a gap in purchaser access.

    The approved promise, and the mechanism that keeps it: this endpoint
    writes a **new** row pointing at the old one via
    ``replaces_file_id``. The old row is untouched — still current, still
    ``passed``, still downloadable. Only when the replacement passes
    validation does the worker supersede the original, and a purchaser's
    next download silently becomes the new version at no extra cost.

    If validation fails, nothing is superseded and the original simply
    remains the current file. There is no window in which a purchaser has
    neither version.
    """
    space = _get_owned_space(slug, current_user, db)
    offering = _get_offering(space, offering_slug, db)
    target = _get_file(db, offering, file_id)

    if target.replaces_file_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "target_is_replacement",
                "message": (
                    "This file is itself a replacement that hasn't finished "
                    "checking. Wait for it to settle, then replace it."
                ),
            },
        )

    _assert_replaceable(db, offering, target)
    row = _store_upload(
        db,
        space=space,
        offering=offering,
        upload=file,
        description=description if description is not None else target.description,
        replacing=target,
    )
    return _serialise(row, being_replaced=False)


@router.patch(
    _BASE + "/{file_id}",
    response_model=OfferingFileResponse,
    summary="Add or change a file's description",
)
def update_offering_file(
    slug: str,
    offering_slug: str,
    file_id: str,
    body: OfferingFileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Edit the description. Nothing here can change validation state.

    Deliberately narrow: the only mutable property of a stored file is
    the sentence shown beside it. Content changes go through
    ``/replace``, which starts a validation cycle — if a PATCH could
    swap the bytes, an unvalidated file would inherit an approved row's
    ``passed`` status and become downloadable without being checked.
    """
    space = _get_owned_space(slug, current_user, db)
    offering = _get_offering(space, offering_slug, db)
    row = _get_file(db, offering, file_id)

    data = body.model_dump(exclude_unset=True)
    if "description" in data:
        row.description = (data["description"] or "").strip() or None
    db.commit()
    db.refresh(row)

    being_replaced = row.id in _pending_replacement_targets(db, offering)
    return _serialise(row, being_replaced=being_replaced)


@router.post(
    _BASE + "/reorder",
    response_model=OfferingFileListResponse,
    summary="Set the display order of the current bundle",
)
def reorder_offering_files(
    slug: str,
    offering_slug: str,
    body: OfferingFileReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Reorder, by sending every current file's id in the wanted order.

    The whole list rather than a move-this-one delta, because a partial
    reorder has to invent positions for the files it was not told about
    and two concurrent deltas can produce an order neither client asked
    for. A complete list is idempotent and cannot be ambiguous.

    Pending replacements are not reorderable: they inherit their target's
    position when they are promoted, so a creator never has to place a
    file twice.
    """
    space = _get_owned_space(slug, current_user, db)
    offering = _get_offering(space, offering_slug, db)

    rows = {
        f.id: f for f in _current_files(db, offering)
        if f.replaces_file_id is None
    }
    wanted = list(dict.fromkeys(body.file_ids))   # de-duplicate, keep order

    if set(wanted) != set(rows):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "reason": "incomplete_order",
                "message": (
                    "Send every file in the Offering, in the order you want "
                    "them."
                ),
            },
        )

    for position, fid in enumerate(wanted):
        rows[fid].sort_order = position
    db.commit()
    return _list_payload(db, space=space, offering=offering)


@router.delete(
    _BASE + "/{file_id}",
    response_model=OfferingFileListResponse,
    summary="Remove a file from the current bundle",
)
def remove_offering_file(
    slug: str,
    offering_slug: str,
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Take a file out of the bundle. The row and the object both stay.

    ``superseded_at`` set with ``superseded_by_id`` left NULL — the
    model's existing encoding for "removed with nothing standing in for
    it". Three consequences, all of them the approved behaviour:

      * It stops being part of what a purchaser receives immediately,
        because download authorisation only serves current rows.
      * A purchaser who downloaded it before keeps the copy they have;
        nothing reaches onto their machine.
      * The stored object is **not** deleted. Superseded approved files
        are retained for now by an explicit decision, and the retention
        sweep only ever removes the contents of *rejected* files.

    Removing the last file does not unpublish the Offering, which would
    be a surprising side effect of a file action. The published Offering
    will simply fail its readiness check the next time it is evaluated,
    and the Files tab says so.
    """
    space = _get_owned_space(slug, current_user, db)
    offering = _get_offering(space, offering_slug, db)
    row = _get_file(db, offering, file_id)

    # Removing a file that has a replacement in flight would leave the
    # replacement pointing at a superseded target. The worker tolerates
    # that (it declines to promote and leaves the replacement standing on
    # its own), but telling the creator is better than silently changing
    # what their replacement means.
    if row.id in _pending_replacement_targets(db, offering):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "replacement_in_flight",
                "message": (
                    "A replacement for this file is still being checked. "
                    "Wait for it to finish, then remove the file."
                ),
            },
        )

    row.superseded_at = datetime.utcnow()
    row.superseded_by_id = None
    db.commit()
    logger.info(
        "offering file removed from bundle: file=%s offering=%s by=%s",
        row.id, offering.id, current_user.id,
    )
    return _list_payload(db, space=space, offering=offering)


__all__ = ["router"]
