"""Per-namespace authorization for ``GET /api/uploads/{file_path}``.

Every private-media key belongs to a specific model row (Space,
Pathway, Step, Event, CommunityPost, CreatorMediaAsset, avatar). This
module holds the auth helpers that decide, for each key namespace,
whether the caller is entitled to fetch it. The rules mirror the same
membership / entitlement predicates the read APIs use for the same
data (``_user_manages_space``, ``_check_pathway_access``), so a user
cannot fetch a private image if they wouldn't be allowed to see it
rendered on the page that references it.

Offerings are the one exception to the sentence above, and it is
deliberate. Every other namespace here grants on *membership* — if you
could see the page, you can fetch its image. A purchased Offering file
grants on *entitlement*: the member who bought it keeps it when they
leave the Collective, when the Collective closes, and when the product
is retired. Membership is neither necessary nor sufficient. See
``_authorise_offering_file``.

Not in this module:
  * Path traversal — enforced upstream in ``uploads/routes.py``.
  * R2 presigning / filesystem serving — the route handler still owns
    those; this module only decides allow / deny.
  * The public ``/api/uploads/platform-artwork/*`` route — it has its
    own handler that intentionally does not check auth.

Design:
  * Default-deny for any unknown prefix. New private namespaces must
    add an explicit branch.
  * 403 for known-owner-but-not-allowed, 404 for keys that don't
    resolve to any DB row (defence against enumeration).
  * Reverse-lookup resolvers query on the exact URL string
    (``/api/uploads/{file_path}``), the same value the write path
    persisted — so any key not present in the DB is a 404 regardless
    of whether the R2 object exists.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.platform import (
    CommunityPost,
    Event,
    Pathway,
    PathwayStep,
    PostComment,
    Space,
    SpaceMembership,
)
from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingEntitlementStatus,
    OfferingFile,
    OfferingFileValidationStatus,
)
from app.models.user import User


_DENIED_DETAIL = "Access denied."
_NOT_FOUND_DETAIL = "File not found."


# ---------------------------------------------------------------------------
# Shared membership predicates
# ---------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _is_space_owner(user: User, space: Space) -> bool:
    return space.creator_id is not None and space.creator_id == user.id


def _is_active_member(user: User, space: Space, db: Session) -> bool:
    """True when the user has an active membership of any role
    (learner / moderator / creator) on this Space. Mirrors the check
    used by ``_get_member_space`` in ``app/spaces/routes.py``."""
    return (
        db.query(SpaceMembership.id)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == "active",
        )
        .first()
    ) is not None


def _user_can_view_space_media(user: User, space: Space, db: Session) -> bool:
    """Full "may this user see media that belongs to this Space" check:
    admin, owner, or active member of any role. Explicitly does NOT
    trust ``user.role == 'creator'`` alone — per SEC-005-E platform
    creators must have an actual relationship to the Space."""
    return (
        _is_admin(user)
        or _is_space_owner(user, space)
        or _is_active_member(user, space, db)
    )


def _space_is_publicly_visible(space: Space) -> bool:
    """The public-visibility gate matches the Explore Collectives
    filter in ``spaces/routes.py:_public_space_query`` — status active
    AND is_public — but omits the ``auto_grant_role IS NULL`` bit
    because operational Spaces (World Builders) still render a public
    cover / logo image on their in-app surfaces to members / admins.
    A media request for such a Space's cover from an authenticated
    non-member still falls back to the member/admin branch below."""
    return bool(space.is_public) and str(space.status).endswith("active")


def _allow_if_publicly_visible_else_member(
    user: User, space: Space, db: Session,
) -> None:
    """Public + active Space → any authenticated user. Otherwise fall
    back to admin / owner / active member. Raises 403 on failure."""
    if _space_is_publicly_visible(space):
        return
    if _user_can_view_space_media(user, space, db):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_DENIED_DETAIL)


def _require_member_or_manager(
    user: User, space: Space, db: Session,
) -> None:
    """Membership-only rule (no public exception) — admin, owner, or
    active member of any role. Used for surfaces that never render to
    non-members (event thumbnails, community images, Media Library)."""
    if _user_can_view_space_media(user, space, db):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_DENIED_DETAIL)


# ---------------------------------------------------------------------------
# Per-namespace authorisers
# ---------------------------------------------------------------------------


def _authorise_avatar(user: User, file_path: str, db: Session) -> None:
    """avatars/{uuid}_{name} — any authenticated user. Avatars appear
    on member-profile surfaces that are visible to any signed-in
    caller; no per-owner check is needed here."""
    return  # get_current_user already ran; nothing more to check.


def _authorise_space_cover(user: User, file_path: str, db: Session) -> None:
    """covers/{uuid}_{name} — reverse-lookup Space.cover_image_url."""
    full_url = f"/api/uploads/{file_path}"
    space = (
        db.query(Space)
        .filter(Space.cover_image_url == full_url)
        .first()
    )
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    _allow_if_publicly_visible_else_member(user, space, db)


def _authorise_space_by_slug_prefix(
    user: User, file_path: str, db: Session,
) -> None:
    """logos/{slug}/{name} and island-artwork/{slug}/{name} — slug is
    the second path segment. Look up the Space by slug directly."""
    parts = file_path.split("/", 2)
    # parts[0] = 'logos' or 'island-artwork'; parts[1] = slug;
    # parts[2] = the stored filename.
    if len(parts) < 3 or not parts[1]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    slug = parts[1]
    space = db.query(Space).filter(Space.slug == slug).first()
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    _allow_if_publicly_visible_else_member(user, space, db)


def _authorise_pathway_cover(user: User, file_path: str, db: Session) -> None:
    """pathway-covers/{uuid}_{name} — reverse-lookup Pathway then its
    Space. Same public/private rule as Space covers, since pathway
    covers surface on the same Explore + About pages the cover does."""
    full_url = f"/api/uploads/{file_path}"
    pathway = (
        db.query(Pathway)
        .filter(Pathway.cover_image_url == full_url)
        .first()
    )
    if pathway is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    space = db.query(Space).filter(Space.id == pathway.space_id).first()
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    _allow_if_publicly_visible_else_member(user, space, db)


def _authorise_event_thumbnail(user: User, file_path: str, db: Session) -> None:
    """event-thumbnails/{uuid}_{name} — reverse-lookup Event → Space.
    Member-only (event thumbnails render on member gatherings surfaces,
    not on public Explore pages)."""
    full_url = f"/api/uploads/{file_path}"
    event = (
        db.query(Event)
        .filter(Event.thumbnail_url == full_url)
        .first()
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    space = db.query(Space).filter(Space.id == event.space_id).first()
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    _require_member_or_manager(user, space, db)


def _authorise_step_resource(user: User, file_path: str, db: Session) -> None:
    """steps/{step_id}/{uuid}_{name} — the second path segment is the
    step's DB id. Resolve Step → Pathway → Space and delegate to the
    canonical ``_check_pathway_access`` so paid / included / free /
    draft access matches the pathway surface exactly."""
    parts = file_path.split("/", 2)
    if len(parts) < 3 or not parts[1]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    step_id = parts[1]
    step = db.query(PathwayStep).filter(PathwayStep.id == step_id).first()
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    pathway = db.query(Pathway).filter(Pathway.id == step.pathway_id).first()
    if pathway is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    space = db.query(Space).filter(Space.id == pathway.space_id).first()
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    # ``_check_pathway_access`` raises HTTPException(403) on failure
    # and returns None on success. Lazy import so this module doesn't
    # pull ``app.spaces.routes`` at import time.
    from app.spaces.routes import _check_pathway_access
    _check_pathway_access(user, pathway, space, db)


def _authorise_media(user: User, file_path: str, db: Session) -> None:
    """media/… namespace — three sub-cases:

      * ``media/world-guide/…`` — editorial help content, any
        authenticated user.
      * ``media/{slug}/community/…`` — community post / comment images;
        require active membership in that Space.
      * ``media/{slug}/…`` (Media Library) — require active membership
        in that Space. Paid-pathway asset-reference analysis is
        deliberately NOT applied here; see the launch report §7 for
        the deferred tightening.

    The Collective is identified by a whole path segment and nothing
    else. There used to be a fallback that read a *trailing* substring:
    ``save_media_file`` once flattened "{slug}/community" into
    "{slug}_community", so historical Conversation images sat at
    ``media/{slug}_community/{file}``, and the authoriser learned to
    strip the suffix and retry when the segment matched no Collective.

    It is gone, because that shape no longer exists in production — the
    objects were migrated to the nested key and the database holds zero
    references to the old one — and because the fallback is what made a
    slug collision reachable at all: register a Collective named exactly
    ``{target}_community`` and the plain lookup matches it first, so its
    members could read the target's legacy Conversation images. With a
    whole segment and no suffix arithmetic, no Collective's *name* can
    be made to resolve to another Collective's media.

    Do not reintroduce a fallback here. ``media/{slug}_community/…`` is
    now simply a Media Library key belonging to a Collective whose slug
    happens to end that way, and a 404 if no such Collective exists.
    """
    parts = file_path.split("/", 3)
    # parts[0] = 'media'; parts[1] = slug (or 'world-guide'); parts[2]
    # = filename or 'community'; parts[3] present only for the
    # community sub-branch.
    if len(parts) < 3 or not parts[1]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    slug = parts[1]
    if slug == "world-guide":
        return  # any authenticated user allowed.

    # One lookup, on the whole segment. There is deliberately no
    # fallback here — see the note in the docstring above.
    space = db.query(Space).filter(Space.slug == slug).first()
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    _require_member_or_manager(user, space, db)


# ---------------------------------------------------------------------------
# Offerings
# ---------------------------------------------------------------------------


def _offering_manager(user: User, offering: Offering, db: Session) -> bool:
    """May this user manage the Offering's Collective?

    Admin, or the Collective's owner. Deliberately **not**
    ``_user_can_view_space_media`` — that accepts any active member,
    and a member of a Collective has no business reading a paid file
    they did not buy.
    """
    if _is_admin(user):
        return True
    space = db.query(Space).filter(Space.id == offering.space_id).first()
    return space is not None and _is_space_owner(user, space)


def _has_active_entitlement(user: User, offering_id: str, db: Session) -> bool:
    """Does this user own this Offering right now?

    One question, one row. No membership join, no Offering-status
    check, no look at whether the payment was later refunded — those
    are all deliberately absent, and their absence is what implements
    the approved ownership decisions.
    """
    return (
        db.query(OfferingEntitlement.id)
        .filter(
            OfferingEntitlement.user_id == user.id,
            OfferingEntitlement.offering_id == offering_id,
            OfferingEntitlement.status == OfferingEntitlementStatus.active.value,
        )
        .first()
    ) is not None


def _authorise_offering_file(user: User, file_path: str, db: Session) -> None:
    """``offering-files/{offering_id}/{uuid}_{name}`` — paid downloads.

    Four things must hold, and the order matters because no earlier
    answer may leak information the caller has not earned:

      1. The key's shape resolves an Offering that exists. A key that
         does not is **404**, matching every other resolver here, so
         the route cannot be used to probe which ids are real.
      2. The caller is entitled, or manages the Collective, or is an
         admin. Anyone else is 403.
      3. The file has **passed validation**. This applies to
         *everyone*, managers included — see below.
      4. The file belongs to *this* Offering and, for a purchaser, is
         the current version.

    Step 1/4 is why the Offering id is a whole path segment: an
    entitled buyer of Offering A must not be able to read Offering B's
    file by pasting its key, and that is checked here rather than
    assumed from the fact that the caller is entitled to something.

    No feature flag here, deliberately
    ----------------------------------

    Phase A gated this on ``settings.offerings_enabled`` and flagged it
    for revisiting. It is revisited now, because the gate was wrong in
    a way that only becomes dangerous once files are owned: a release
    switch must never be able to take away a file somebody paid for.

    The required separation, stated so it is not re-litigated:

      * **Feature availability** — whether Offerings can be browsed,
        created or acquired — is the flag's job. It gates the
        creator surfaces, the member surfaces and (later) acquisition.
        It also still gates ``offering-covers``, which are
        presentation rather than property.
      * **Existing download entitlements** are the entitlement row's
        job, and nothing else's. Turning Offerings off stops new
        activity; it does not reach back into what members already own.

    So this resolver asks "do you own it, and has it passed?" and
    never "is the feature switched on?".

    Unvalidated files are not downloadable by anyone
    -----------------------------------------------

    Managers may read a *superseded* file — Phase A's recovery and
    audit access, preserved — but they may **not** read one that is
    ``pending``, ``rejected``, ``error`` or ``quarantined`` through
    this route. The reason is narrow and worth stating: this route
    mints a pre-signed URL that behaves exactly like an approved
    download and can be pasted anywhere. Letting a manager obtain one
    for an unchecked file would be precisely the bypass that
    distributes unvalidated content as though it were approved.

    A creator previewing their own pending upload is a legitimate need
    and belongs in a controlled Creator Studio surface that is clearly
    labelled and does not hand out a durable URL. That is Phase B
    editor work, not a relaxation here.
    """
    # 1. Resolve the Offering from the key's own structure.
    from app.services.offering_files import offering_id_from_storage_key
    offering_id = offering_id_from_storage_key(file_path)
    if offering_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL,
        )
    offering = db.query(Offering).filter(Offering.id == offering_id).first()
    if offering is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL,
        )

    # 2. Who is asking.
    is_manager = _offering_manager(user, offering, db)
    if not is_manager and not _has_active_entitlement(user, offering.id, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_DENIED_DETAIL,
        )

    # 3/4. Which file. Matched on the key, scoped to this Offering, so
    #      a key belonging to another Offering is a 404 even for a
    #      caller legitimately entitled to this one.
    row = (
        db.query(OfferingFile)
        .filter(
            OfferingFile.storage_key == file_path,
            OfferingFile.offering_id == offering.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL,
        )

    # Validation gate — applies to everyone, including managers.
    #
    # One line, in the single place that already decides what may be
    # fetched, so there is no second gate to keep in step. A file that
    # has not passed is not downloadable: not for a purchaser, not for
    # the creator who uploaded it, not for an admin.
    if row.validation_status != OfferingFileValidationStatus.passed.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_DENIED_DETAIL,
        )

    if row.superseded_at is not None and not is_manager:
        # Owned, but not this version. 403 rather than 404: the file
        # genuinely exists and the caller may legitimately know of it,
        # having downloaded it before it was replaced.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_DENIED_DETAIL,
        )


def _authorise_offering_cover(user: User, file_path: str, db: Session) -> None:
    """``offering-covers/{offering_id}/{uuid}_{name}`` — cover artwork.

    A separate namespace from the files, and a separate rule: a cover
    is part of how an Offering is presented, so it follows the
    Collective's ordinary visibility — public Collective, or member /
    owner / admin — exactly as a Pathway cover does.

    It is emphatically **not** a download grant. Keeping covers in
    their own namespace is what guarantees that a future change making
    covers cheaper to serve cannot widen access to the paid assets.

    This resolver **does** check the feature flag, where
    ``_authorise_offering_file`` deliberately does not. A cover is
    presentation — part of whether the feature is available — while a
    purchased file is property. Turning Offerings off should hide the
    shopfront and must not reach into what members already own.
    """
    from app.core.config import settings
    if not settings.offerings_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_DENIED_DETAIL,
        )

    parts = file_path.split("/", 2)
    if len(parts) < 3 or not parts[1]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL,
        )
    offering = db.query(Offering).filter(Offering.id == parts[1]).first()
    if offering is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL,
        )
    space = db.query(Space).filter(Space.id == offering.space_id).first()
    if space is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL,
        )
    _allow_if_publicly_visible_else_member(user, space, db)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


# Prefix → resolver. Order doesn't matter — we match on the exact first
# path segment. Anything not in this table is default-deny.
#
# Two namespaces are deliberately absent because they never reach this
# function: ``platform-artwork`` and ``place-artwork`` are matched by
# their own public routes in ``app/uploads/routes.py``, declared ahead
# of the catch-all. Adding either here would have no effect; removing
# their routes would silently default-deny them, which is the bug that
# made Place artwork unrenderable before those routes existed.
_DISPATCH = {
    "avatars":          _authorise_avatar,
    "covers":           _authorise_space_cover,
    "logos":            _authorise_space_by_slug_prefix,
    "island-artwork":   _authorise_space_by_slug_prefix,
    "pathway-covers":   _authorise_pathway_cover,
    "event-thumbnails": _authorise_event_thumbnail,
    "steps":            _authorise_step_resource,
    "media":            _authorise_media,
    # Offerings. Two namespaces on purpose — see the resolvers above.
    "offering-files":   _authorise_offering_file,
    "offering-covers":  _authorise_offering_cover,
}


def authorize_upload(file_path: str, user: User, db: Session) -> None:
    """Route entry point. Dispatch on the first path segment, run the
    matching authoriser, or raise 403 for anything not in the
    dispatch table. Called by ``serve_upload`` after the path-traversal
    guard and before the R2 / filesystem branch."""
    if not file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    prefix = file_path.split("/", 1)[0]
    resolver = _DISPATCH.get(prefix)
    if resolver is None:
        # Default-deny for any private namespace we don't recognise.
        # New namespaces must add an explicit branch above.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_DENIED_DETAIL)
    resolver(user, file_path, db)


__all__ = ["authorize_upload"]
