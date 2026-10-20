"""Request and response shapes for creator Offering management.

A separate module rather than more lines in ``creator/schemas.py``,
which is already 2,900 lines carrying every other creator surface.
Offerings is self-contained enough to keep its own file, and a reader
looking for the Offering contract should not have to search for it.

The creator never sees Payment Option vocabulary here: the only pricing
input is a kind and a price in cents.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.services.offering_files import MAX_OFFERING_FILE_COUNT


class OfferingCreateRequest(BaseModel):
    """Create a draft. Title only — everything else is set by editing.

    Deliberately minimal: a creator should be able to start an Offering
    from a title and fill the rest in, which is how Pathway creation
    already behaves.
    """

    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)


class OfferingUpdateRequest(BaseModel):
    """Partial update. Only fields present are applied.

    ``pricing_kind`` and ``price_cents`` travel together: setting a
    price without a kind is refused rather than guessed at, because
    inventing ``one_time`` would be the server making a pricing
    decision on the creator's behalf.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    #: Rich-text/long-form body. The About *blocks* editor is separate
    #: and arrives in a later stage; this is the plain detail field on
    #: the Offering row itself.
    description: str | None = None
    #: Either a curated platform default or a file this platform stored
    #: — validated against an allow-list of shapes, not a URL validator.
    cover_image_url: str | None = Field(default=None, max_length=500)
    #: ``free`` or ``one_time``.
    pricing_kind: str | None = None
    #: Minor units. Must be positive when ``pricing_kind='one_time'``.
    price_cents: int | None = Field(default=None, ge=0, le=100_000_00)


class OfferingSummaryResponse(BaseModel):
    """One card's worth of Offering."""

    id: str
    slug: str
    title: str
    summary: str | None = None
    cover_image_url: str | None = None
    status: str
    pricing_kind: str | None = None
    price_cents: int | None = None
    #: Files in the current bundle, and how many have passed validation.
    #: Surfaced together so a creator card can say "3 files, 1 still
    #: being checked" without a second request.
    file_count: int = 0
    files_passed: int = 0
    published_at: datetime | None = None
    retired_at: datetime | None = None
    updated_at: datetime | None = None


class OfferingDetailResponse(OfferingSummaryResponse):
    description: str | None = None
    fulfilment_kind: str | None = None
    created_at: datetime | None = None
    #: Active entitlements. Revoked ones are excluded — they are not
    #: holdings anyone still has.
    acquisition_count: int = 0


class RequirementResponse(BaseModel):
    id: str
    met: bool
    #: Creator-facing and safe to show as-is. Never names a detection
    #: technique, and never implies files were scanned for malware.
    message: str


class OfferingReadinessResponse(BaseModel):
    """The publication checklist.

    Every requirement is returned, met or not, so the editor can show a
    complete list rather than revealing problems one publish attempt at
    a time. The About section is absent because rich content is
    optional — including it even as a passing row would imply it had
    been assessed.
    """

    ready: bool
    requirements: list[RequirementResponse]
    #: The plan's Offering cap, or null for uncapped. Here so the
    #: editor shows the same number the guard enforces.
    offering_limit: int | None = None


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


class OfferingFileUpdateRequest(BaseModel):
    """Edit the one editable property of a stored file.

    Not the filename, not the type, not the bytes. Replacing content is a
    separate endpoint because it starts a validation cycle, and letting
    a PATCH do it quietly would be how an unvalidated file inherits an
    approved row's status.
    """

    model_config = ConfigDict(extra="forbid")

    #: One sentence explaining this resource. ``None`` clears it.
    description: str | None = Field(default=None, max_length=300)


class OfferingFileReorderRequest(BaseModel):
    """The current bundle's ids, in the order the creator wants them.

    The ceiling is the platform file ceiling rather than a second copy of
    the number 50 — the one rule this phase holds to is that a limit is
    written down once. The *plan's* allowance is enforced at upload; this
    only bounds the request body.
    """

    model_config = ConfigDict(extra="forbid")

    file_ids: list[str] = Field(
        min_length=1, max_length=MAX_OFFERING_FILE_COUNT,
    )


class OfferingFileResponse(BaseModel):
    """One file, as the Files tab needs to render it.

    Shaped for the approved creator experience: a name, a size, a status
    word a person understands, and — when something is wrong — a reason
    they can act on. Deliberately says nothing about *how* a file was
    checked: no check names, no detection techniques, and never a word
    implying a malware scan, because none was performed.
    """

    id: str
    filename: str
    content_type: str
    byte_size: int
    description: str | None = None
    sort_order: int = 0

    #: Downloadable resources this file contributes to the plan's file
    #: allowance: 1 for a plain file or an Office document, the member
    #: count for a ZIP bundle. Surfaced so the creator can see why a
    #: three-row bundle is using twelve of their fifty files.
    resource_count: int = 1

    #: Machine-readable: ``pending`` | ``passed`` | ``rejected`` |
    #: ``error`` | ``quarantined``. For the UI to branch on.
    validation_status: str

    #: Human-readable, and the only one to put on screen:
    #: **Checking** → **Ready** / **Not accepted** / **On hold**.
    status_label: str

    #: Why it was not accepted, in words a creator can act on. Null
    #: unless something is actually wrong.
    rejection_reason: str | None = None

    #: Can a purchaser download this right now? The same two conditions
    #: the download route enforces — current version, passed validation
    #: — so the creator sees the truth rather than an approximation.
    available_to_purchasers: bool = False

    #: A replacement for this file is uploaded and still being checked.
    #: Until it passes, this file stays the one purchasers receive.
    replacement_pending: bool = False

    #: Set on a replacement: the file it will supersede once it passes.
    replaces_file_id: str | None = None

    created_at: datetime | None = None
    validated_at: datetime | None = None


class OfferingFileListResponse(BaseModel):
    """The Files tab's whole payload: the files, and the room left.

    The allowance travels with the list so the tab can say "3 of 50
    files, 12 MB of 75 MB" without a second request and without
    computing it from a copy of the plan table held in the frontend.
    """

    files: list[OfferingFileResponse]

    #: Resources used and allowed, under the approved counting rules —
    #: ZIP members counted individually, a pending replacement sharing
    #: its target's slot.
    resources_used: int
    resources_allowed: int
    bytes_used: int
    bytes_allowed: int
    #: The largest single upload this plan accepts.
    max_file_bytes: int
    zip_bundles_allowed: bool
    #: Customer-facing plan name, so a refusal and the tab agree.
    plan_name: str


__all__ = [
    "OfferingCreateRequest",
    "OfferingUpdateRequest",
    "OfferingSummaryResponse",
    "OfferingDetailResponse",
    "RequirementResponse",
    "OfferingReadinessResponse",
    "OfferingFileUpdateRequest",
    "OfferingFileReorderRequest",
    "OfferingFileResponse",
    "OfferingFileListResponse",
]
