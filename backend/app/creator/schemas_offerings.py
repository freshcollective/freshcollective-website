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


__all__ = [
    "OfferingCreateRequest",
    "OfferingUpdateRequest",
    "OfferingSummaryResponse",
    "OfferingDetailResponse",
    "RequirementResponse",
    "OfferingReadinessResponse",
]
