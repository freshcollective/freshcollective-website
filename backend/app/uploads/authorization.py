"""Per-namespace authorization for ``GET /api/uploads/{file_path}``.

Every private-media key belongs to a specific model row (Space,
Pathway, Step, Event, CommunityPost, CreatorMediaAsset, avatar). This
module holds the auth helpers that decide, for each key namespace,
whether the caller is entitled to fetch it. The rules mirror the same
membership / entitlement predicates the read APIs use for the same
data (``_user_manages_space``, ``_check_pathway_access``), so a user
cannot fetch a private image if they wouldn't be allowed to see it
rendered on the page that references it.

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

    space = db.query(Space).filter(Space.slug == slug).first()
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    _require_member_or_manager(user, space, db)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


# Prefix → resolver. Order doesn't matter — we match on the exact first
# path segment. Anything not in this table is default-deny.
_DISPATCH = {
    "avatars":          _authorise_avatar,
    "covers":           _authorise_space_cover,
    "logos":            _authorise_space_by_slug_prefix,
    "island-artwork":   _authorise_space_by_slug_prefix,
    "pathway-covers":   _authorise_pathway_cover,
    "event-thumbnails": _authorise_event_thumbnail,
    "steps":            _authorise_step_resource,
    "media":            _authorise_media,
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
