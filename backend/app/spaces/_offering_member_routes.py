"""The member-facing Offerings surfaces — Phases B7 and C/D.

Four endpoints:

    GET  /api/spaces/{slug}/offerings                    the catalogue
    GET  /api/spaces/{slug}/offerings/{offering_slug}    one Offering
    POST /api/spaces/{slug}/offerings/{slug}/acquire     free, authed
    GET  /api/me/collection                              Your Collection

Anonymous visitors
------------------

The catalogue and the detail page answer **without a session**, which
is the whole point of Phase C: somebody finds a creator through a
resource, not the other way round. They are gated by
``area_policies.AREA_OFFERINGS``, which is fixed public for the same
reason About is — needing access in order to reach the page where you
buy access is a circle.

What stays private regardless of who is asking: draft Offerings (404,
not 403, so a slug cannot be confirmed), storage keys, download URLs,
and any file that has not passed validation.

It serves the page a member reads before deciding, and it is the **same**
page a creator sees when they press Preview. There is deliberately no
second renderer and no preview-only payload: the Pathway preview works
by redirecting into the real member URL, and this follows it exactly.
A duplicate renderer is how a creator comes to approve a page that is
not the page anybody else gets.

Who may see what
----------------

Three things govern who sees what here: the Offering's ``status``, the
Offerings pilot scope, and whether the caller already owns it.
**Ownership outranks the other two** — a member who has acquired an
Offering reaches this page from Your Collection whatever the pilot list
says, because that is where their downloads are.

``status`` governs visibility, and only for people who do not manage the
Collective:

  * **published** — any authenticated caller who can see the Collective.
  * **draft** — managers only. A draft is private: a 404, not a 403, so
    the endpoint cannot be used to discover that a Collective is working
    on something.
  * **retired** — still readable, because people own it and a retired
    product that 404s looks deleted. It stops selling, not serving.

Acquisition
-----------

Phase C/D fills in what B7 deliberately left out. The payload now
carries ``can_acquire`` and, when it is false, ``acquire_blocked`` /
``acquire_message`` saying why — resolved by
``services.offering_acquisition.check_acquirable``, the same function
the write paths guard with, so the page cannot offer a button the
endpoint would refuse.

``viewer_owns`` keeps its B7 meaning and still wins over everything:
somebody who owns an Offering sees their downloads, not a price.

The free path is a POST here. The paid path is
``POST /api/checkout/offering``, beside the Pathway and Series
wrappers, because it belongs with the thing that charges money rather
than with the thing that describes a product.

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    get_current_user,
    get_optional_user,
    get_verified_current_user,
)
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
from app.services import offering_acquisition as acq
from app.services import offering_covers as _covers
from app.services import offering_pilot as _pilot
from app.spaces import area_access, area_policies

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/spaces", tags=["offerings-member"])

#: Your Collection is not scoped to a Collective — it spans every
#: Offering this member has ever acquired, anywhere — so it lives in the
#: platform's existing per-person namespace rather than under
#: ``/api/spaces/{slug}``.
me_router = APIRouter(prefix="/api/me", tags=["offerings-member"])


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




#: Collapses a bundle's content types into one word a card can show.
#:
#: Derived from the **files**, never from the cover image. The covers are
#: illustrations — a photograph of headphones means "this is audio", not
#: "headphones are included" — so letting artwork name the category
#: would be the one place that distinction could quietly invert.
_CATEGORY_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("audio/", "Audio"),
    ("video/", "Video"),
)
_CATEGORY_BY_TYPE: dict[str, str] = {
    "application/pdf": "PDF",
    "text/csv": "Spreadsheet",
    "application/csv": "Spreadsheet",
    "application/zip": "Bundle",
    "application/x-zip-compressed": "Bundle",
    "text/markdown": "Document",
    "text/plain": "Document",
}


def _category_label(files: list[OfferingFile]) -> str:
    """One category for a card. ``Digital download`` when unknowable."""
    if not files:
        return "Digital download"
    found: set[str] = set()
    for f in files:
        ct = (f.content_type or "").lower()
        label = _CATEGORY_BY_TYPE.get(ct)
        if label is None:
            for prefix, lbl in _CATEGORY_BY_PREFIX:
                if ct.startswith(prefix):
                    label = lbl
                    break
        if label is None:
            if "spreadsheetml" in ct:
                label = "Spreadsheet"
            elif "wordprocessingml" in ct or "presentationml" in ct:
                label = "Document"
        found.add(label or "Digital download")
    if len(found) == 1:
        return found.pop()
    # A ZIP alongside anything else is still, usefully, a bundle.
    if "Bundle" in found:
        return "Bundle"
    return "Multiple formats"


def _current_approved(db: Session, offering_id: str) -> list[OfferingFile]:
    """The bundle a buyer would receive: current and passed.

    One predicate, used by the card, the detail payload and the
    acquisition gate, so a card cannot advertise a file the detail page
    hides or the gate counts differently.
    """
    return (
        db.query(OfferingFile)
        .filter(
            OfferingFile.offering_id == offering_id,
            OfferingFile.superseded_at.is_(None),
            OfferingFile.validation_status == FVS.passed.value,
        )
        .order_by(OfferingFile.sort_order, OfferingFile.created_at)
        .all()
    )


def _price_fields(offering: Offering) -> dict:
    """Pricing as a card or page states it. ``Free`` is a real answer,
    not a missing price, so the label is computed here rather than left
    to each client to infer from a null."""
    kind = offering.pricing_kind
    cents = offering.price_cents
    if kind == "free":
        label = "Free"
    elif kind == "one_time" and cents:
        dollars = cents / 100
        label = (
            f"${dollars:.0f}" if dollars == int(dollars) else f"${dollars:.2f}"
        )
    else:
        label = ""
    return {
        "pricing_kind": kind,
        "price_cents": cents,
        "price_label": label,
    }


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}/offerings",
    dependencies=[Depends(require_offerings_enabled)],
    summary="This Collective's published Offerings",
)
def list_member_offerings(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> list[dict]:
    """The Offerings doorway — the catalogue a visitor browses.

    **Published only, for everybody.** Managers see their drafts in
    Creator Studio, which is where unreleased work belongs; mixing
    drafts into this list is how a creator comes to share a URL that
    only works for them. Retired Offerings are also absent: the
    catalogue is what is on sale, and a retired Offering's page stays
    readable for the people who own it.

    An Offering with no currently-downloadable files is listed but
    reports ``can_acquire: false`` with a reason, rather than being
    hidden. Vanishing from the catalogue because a replacement file is
    mid-validation would look to its creator like deletion.
    """
    from app.spaces.routes import _get_space_visible_to

    space = _get_space_visible_to(slug, db, current_user)
    area_access.require_area(
        db, space, current_user, area_policies.AREA_OFFERINGS,
    )

    offerings = (
        db.query(Offering)
        .filter(
            Offering.space_id == space.id,
            Offering.status == OfferingStatus.published.value,
        )
        .order_by(Offering.published_at.desc(), Offering.created_at.desc())
        .all()
    )
    if not offerings:
        return []

    offering_ids = [o.id for o in offerings]

    # The shared cover artwork, once for the page rather than once per
    # card. Five rows, whatever the catalogue's size.
    shared_covers = _covers.artwork_urls(db)

    # Batch the two per-card questions rather than asking them per row:
    # "what files would a buyer get?" and "does this viewer own it?".
    files_by_offering: dict[str, list[OfferingFile]] = {
        o_id: [] for o_id in offering_ids
    }
    for f in (
        db.query(OfferingFile)
        .filter(
            OfferingFile.offering_id.in_(offering_ids),
            OfferingFile.superseded_at.is_(None),
            OfferingFile.validation_status == FVS.passed.value,
        )
        .order_by(OfferingFile.sort_order, OfferingFile.created_at)
        .all()
    ):
        files_by_offering[f.offering_id].append(f)

    owned: set[str] = set()
    if current_user is not None:
        owned = {
            o_id for (o_id,) in
            db.query(OfferingEntitlement.offering_id)
            .filter(
                OfferingEntitlement.user_id == current_user.id,
                OfferingEntitlement.offering_id.in_(offering_ids),
                OfferingEntitlement.status
                == OfferingEntitlementStatus.active.value,
            )
            .all()
        }

    cards: list[dict] = []
    for o in offerings:
        files = files_by_offering.get(o.id, [])
        card = {
            "id": o.id,
            "slug": o.slug,
            "title": o.title,
            "summary": o.summary,
            "cover_image_url": _covers.resolve_cover_url(
                db, o, shared=shared_covers,
            ),
            "category_label": _category_label(files),
            "file_count": len(files),
            "total_resources": sum((f.resource_count or 1) for f in files),
            "fulfilment_kind": o.fulfilment_kind,
            "viewer_owns": o.id in owned,
            # Cheap per-card availability. The full gate — plan
            # eligibility, commerce-row health — runs on the detail page
            # and again at the write, so a card never needs to resolve a
            # creator's plan and the list stays one query per question.
            "has_downloadable_files": len(files) > 0,
        }
        card.update(_price_fields(o))
        cards.append(card)
    return cards


# ---------------------------------------------------------------------------
# One Offering
# ---------------------------------------------------------------------------


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
    # Anonymous from Phase C. A visitor who has not signed in reads the
    # whole page — cover, description, price, what is included — and is
    # offered an account at the point of acquiring, which is the
    # established Pathway and Gathering journey.
    current_user: User | None = Depends(get_optional_user),
) -> dict:
    """The member detail page, and the creator's Preview target."""
    from app.spaces.routes import _get_space_visible_to

    space = _get_space_visible_to(slug, db, current_user)

    # The Offering is resolved **before** the area gate, because whether
    # the gate applies depends on whether this caller owns this
    # Offering. Resolving first leaks nothing: the lookup is scoped to
    # this Collective, and every refusal below is the same 404 as "no
    # such Offering".
    offering = (
        db.query(Offering)
        .filter(Offering.space_id == space.id, Offering.slug == offering_slug)
        .first()
    )
    if offering is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Offering not found.",
        )

    owns = current_user is not None and acq.already_owns(
        db, user_id=current_user.id, offering_id=offering.id,
    )

    # ── The area gate, which an owner is exempt from ───────────────
    #
    # Public visibility and new acquisitions stay pilot-gated: the
    # catalogue 404s, acquiring 404s, checkout 409s. But a member who
    # already owns this Offering reaches it from Your Collection, and
    # that link must not break because an operator edited a config
    # value. Their downloads are on this page.
    #
    # The exemption is as narrow as it can be:
    #
    #   * it requires an **active entitlement for this exact
    #     Offering** — not membership, not having owned something else,
    #     not being signed in. A non-owner is refused identically to
    #     before, so this is not a discovery route;
    #   * it changes nothing about what the page *offers*.
    #     ``can_acquire`` is false for an owner anyway, and the
    #     acquisition endpoints keep their own unexempted gate, so no
    #     new acquisition becomes possible in a Collective outside the
    #     pilot;
    #   * it does not touch download authorisation.
    #     ``_authorise_offering_file`` consults neither switch and is
    #     unchanged — it was already the thing protecting the file
    #     itself, and this only restores the page that links to it.
    #
    # ``require_area`` still runs for everybody else, so it continues to
    # enforce both the feature flag and the pilot list.
    if not owns:
        area_access.require_area(
            db, space, current_user, area_policies.AREA_OFFERINGS,
        )

    is_manager = _user_manages_space(current_user, space, db)

    # Draft privacy. 404 rather than 403: a stranger must not be able to
    # learn that a Collective has an unreleased product, or confirm a
    # slug they guessed.
    if offering.status == OfferingStatus.draft.value and not is_manager:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Offering not found.",
        )

    approved = _current_approved(db, offering.id)

    # What this viewer may do next, from the same function the write
    # paths guard with. Resolved once here so the page and the endpoint
    # cannot disagree about whether a button should exist.
    acquirability = acq.check_acquirable(
        db, offering=offering, space=space, user=current_user,
    )

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

    payload = {
        "id": offering.id,
        "slug": offering.slug,
        "title": offering.title,
        "summary": offering.summary,
        "description": offering.description,
        # Resolved: the creator's upload, else the chosen category's
        # current World Artwork, else null for the gradient.
        "cover_image_url": _covers.resolve_cover_url(db, offering),
        "status": offering.status,
        "category_label": _category_label(approved),
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
        # ── Acquisition (Phase C/D) ──────────────────────────────────
        "can_acquire": acquirability.can_acquire,
        "acquire_blocked": acquirability.refusal,
        "acquire_message": acquirability.message,
        # An anonymous visitor is shown the real action with an
        # account step in front of it, rather than a disabled button.
        # The established Pathway journey: sign up or log in with
        # ``?next=`` back to this page, then press it again.
        "requires_account": current_user is None,
        # The transparency notice. Answered from the same facts
        # fulfilment uses, so the page never promises a membership the
        # grant helper would decline — and says nothing at all to
        # somebody who is already a member.
        "will_join_collective": acq.will_join_collective(
            db, user=current_user, space=space,
        ),
    }
    payload.update(_price_fields(offering))
    return payload


# ---------------------------------------------------------------------------
# Free acquisition
# ---------------------------------------------------------------------------


@router.post(
    "/{slug}/offerings/{offering_slug}/acquire",
    dependencies=[Depends(require_offerings_enabled)],
    summary="Claim a free Offering",
)
def acquire_offering(
    slug: str,
    offering_slug: str,
    db: Session = Depends(get_db),
    # SEC-009, matching every other trust action on the platform: a
    # verified address. Acquiring creates a durable entitlement and a
    # Collective membership, and both are things an unverified signup
    # should not be able to mint.
    current_user: User = Depends(get_verified_current_user),
) -> dict:
    """Free Offerings only. Idempotent. One transaction.

    **Free is confirmed here, from the Offering row**, not taken from
    the request — there is nothing in the body to take it from. A paid
    Offering reaching this endpoint is refused rather than quietly
    given away, and the refusal is the same whichever way the two
    disagree (see ``REASON_WRONG_PRICING``).

    What a successful call produces, atomically:

      * one ``OfferingEntitlement`` (``source='free'``);
      * active membership of the Collective, via the shared
        ``membership_grant`` helper every paid path also uses.

    Pressing the button twice is a no-op that reports
    ``already_owned``. Three separate mechanisms make that true — see
    ``services.offering_acquisition``.
    """
    from app.spaces.routes import _get_space_visible_to

    space = _get_space_visible_to(slug, db, current_user)
    area_access.require_area(
        db, space, current_user, area_policies.AREA_OFFERINGS,
    )
    offering = (
        db.query(Offering)
        .filter(Offering.space_id == space.id, Offering.slug == offering_slug)
        .first()
    )
    # A draft is a 404 here for the same reason it is on the detail
    # endpoint, and managers get no exemption: previewing a draft must
    # not be able to create a real entitlement in real purchase history.
    if offering is None or offering.status == OfferingStatus.draft.value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Offering not found.",
        )

    try:
        outcome = acq.acquire_free(
            db, offering=offering, space=space, user=current_user,
        )
    except acq.AcquisitionRefused as exc:
        db.rollback()
        # 409, not 422: the request was well formed and would have
        # worked a moment ago. What changed is the Offering.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": exc.reason, "message": exc.message},
        ) from exc
    except IntegrityError:
        # Two requests from the same person interleaved, and
        # ``ux_offering_entitlements_active`` refused the loser's row —
        # exactly its job. This is the only place that can recover,
        # because rolling back is only safe for whoever owns the
        # transaction, and that is this function.
        #
        # Roll back and run it once more. The second attempt's own
        # already-owned read now finds the winning row and returns
        # ``created=False``, so a member who double-clicked gets
        # "already in Your Collection" rather than a 500.
        #
        # Deliberately not a loop: a second IntegrityError would mean
        # the index refused a row that the read says is not there,
        # which is a contradiction worth surfacing rather than
        # retrying around.
        db.rollback()
        logger.info(
            "offering acquire: lost a race for offering=%s user=%s — "
            "retrying once against the committed winner",
            offering.id, current_user.id,
        )
        offering = (
            db.query(Offering)
            .filter(Offering.id == offering.id)
            .one()
        )
        space = db.query(Space).filter(Space.id == space.id).one()
        try:
            outcome = acq.acquire_free(
                db, offering=offering, space=space, user=current_user,
            )
        except acq.AcquisitionRefused as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"reason": exc.reason, "message": exc.message},
            ) from exc

    db.commit()
    logger.info(
        "offering acquired (free): offering=%s user=%s created=%s joined=%s",
        offering.id, current_user.id, outcome.created,
        outcome.joined_collective,
    )
    return {
        "acquired": True,
        "already_owned": not outcome.created,
        "joined_collective": outcome.joined_collective,
        "collective_name": space.name,
        "offering_slug": offering.slug,
        "collective_slug": space.slug,
    }


# ---------------------------------------------------------------------------
# Your Collection
# ---------------------------------------------------------------------------


@me_router.get(
    "/collection",
    # Gated like every other Offerings *presentation* surface. The
    # entitlements it lists are untouched by the flag, and the download
    # route that serves them is deliberately not gated — turning the
    # feature off hides this page and still lets a member who has a
    # direct link fetch a file they own.
    dependencies=[Depends(require_offerings_enabled)],
    summary="Every Offering this member has acquired",
)
def get_your_collection(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Your Collection — one list, across every Collective.

    Deliberately **not** separated into "my Offerings" and "my files":
    an acquired Offering is one thing a person owns, and splitting it
    would make them learn a distinction that exists only in the schema.

    Everything legitimately acquired appears, and keeps appearing:

      * free and paid alike, with no visible difference — what you own
        is what you own;
      * Offerings from Collectives the member has since **left**;
      * Offerings the creator has since **retired**;
      * Offerings whose Collective has been archived.

    The only row that does not appear is one that was explicitly
    revoked, which is a deliberate administrative act recorded with a
    reason.

    Newest first, using ``ix_offering_entitlements_user_acquired`` —
    the index that exists for exactly this query.

    Visibility during the pilot
    ---------------------------

    While the pilot is scoped to named Collectives, this page is shown
    to **members who have acquired something**, and to nobody else. A
    member with nothing gets a 404, so Your World does not grow a
    Your Collection band for every account on the platform while the
    feature is still being trialled.

    What this deliberately does **not** do is filter the list by pilot
    scope. Two reasons, and they are the same reason:

      * a Collective leaving the pilot would otherwise hide a purchase
        somebody had already made, which is the mistake the feature
        flag and the download route both exist to avoid;
      * ownership is ownership. Once the row exists, this page's job is
        to show it.

    So the gate is "do you own anything at all", which cannot drift out
    of step with the pilot list and cannot hide a legitimate
    acquisition. When the pilot opens to everything (``*``), the gate
    lifts and an empty Collection renders its invitation as normal.
    """
    rows = (
        db.query(OfferingEntitlement, Offering, Space)
        .join(Offering, Offering.id == OfferingEntitlement.offering_id)
        # Outer join on Space: an archived or deleted Collective must
        # not make a member's own collection disappear. The card then
        # shows the Offering without a Collective link rather than 500.
        .outerjoin(Space, Space.id == OfferingEntitlement.space_id)
        .filter(
            OfferingEntitlement.user_id == current_user.id,
            OfferingEntitlement.status
            == OfferingEntitlementStatus.active.value,
        )
        .order_by(OfferingEntitlement.acquired_at.desc())
        .all()
    )
    if not rows:
        # Nothing acquired. While the pilot is scoped, that means this
        # page is not for this member yet — 404, consistent with every
        # other out-of-scope Offerings surface. Once the pilot opens to
        # all Collectives, an empty Collection is a legitimate state and
        # renders its invitation.
        if _pilot.current_scope().is_restricted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Not found.",
            )
        return {"items": [], "count": 0}

    offering_ids = [o.id for (_e, o, _s) in rows]
    creator_ids = {s.creator_id for (_e, _o, s) in rows if s and s.creator_id}

    files_by_offering: dict[str, list[OfferingFile]] = {
        o_id: [] for o_id in offering_ids
    }
    for f in (
        db.query(OfferingFile)
        .filter(
            OfferingFile.offering_id.in_(offering_ids),
            OfferingFile.superseded_at.is_(None),
            OfferingFile.validation_status == FVS.passed.value,
        )
        .order_by(OfferingFile.sort_order, OfferingFile.created_at)
        .all()
    ):
        files_by_offering[f.offering_id].append(f)

    shared_covers = _covers.artwork_urls(db)

    creators: dict[str, str] = {}
    if creator_ids:
        for u_id, name in (
            db.query(User.id, User.name).filter(User.id.in_(creator_ids)).all()
        ):
            creators[u_id] = name

    items: list[dict] = []
    for ent, offering, space in rows:
        files = files_by_offering.get(offering.id, [])
        item = {
            "entitlement_id": ent.id,
            "offering_id": offering.id,
            "slug": offering.slug,
            "title": offering.title,
            "summary": offering.summary,
            "cover_image_url": _covers.resolve_cover_url(
                db, offering, shared=shared_covers,
            ),
            "category_label": _category_label(files),
            "acquired_at": ent.acquired_at,
            # Shown nowhere by default. Present so the page can
            # distinguish a retired Offering with a quiet note, which is
            # kinder than silence when a member wonders why they cannot
            # find it in the catalogue any more.
            "offering_status": offering.status,
            "collective": (
                {"slug": space.slug, "name": space.name}
                if space is not None else None
            ),
            "creator_name": (
                creators.get(space.creator_id)
                if space is not None and space.creator_id else None
            ),
            "file_count": len(files),
            "total_resources": sum((f.resource_count or 1) for f in files),
            # The honest answer when a creator has replaced a file and
            # the replacement is still being checked, or an operator has
            # quarantined one. The page says so rather than offering a
            # download that would refuse them.
            "files_available": len(files) > 0,
            # Where to go to read it and download it. The detail page is
            # the one renderer; Your Collection links into it rather
            # than growing a second copy of the download list.
            "href": (
                f"/spaces/{space.slug}/offerings/{offering.slug}"
                if space is not None else None
            ),
        }
        items.append(item)

    return {"items": items, "count": len(items)}


__all__ = ["router", "me_router"]
