"""
Serving for stored uploads. Two flavours:

GET /api/uploads/platform-artwork/{file_path:path}
    Publicly readable. Platform artwork is rendered on unauthenticated
    marketing pages (e.g. /for-creators, homepage hero), so its files
    cannot be gated on a session. In R2 mode this returns a 302 to the
    public R2 origin (``R2_PUBLIC_BASE_URL``). In filesystem mode it
    serves the local file directly.

GET /api/uploads/place-artwork/{file_path:path}
    Also publicly readable, for the same reason: Discover Places is an
    unauthenticated surface and a Place's hero artwork is curated,
    member-facing imagery with nothing private in it.

    It differs from platform artwork in *where the bytes live*. These
    objects were written to the PRIVATE bucket and stay there — moving
    them would mean a data migration and would break every
    ``hero_artwork_url`` already stored. So this route reads publicly
    from a private object by issuing the same short-lived pre-signed
    redirect the auth-gated route uses. The grant is read-only and
    expires in minutes; writes (upload, delete, edit) remain behind
    the admin API and are untouched.

GET /api/uploads/{file_path:path}
    All other uploads (avatars, cover images, resources, atlas artwork,
    community images, etc.) require a signed-in user AND per-namespace
    authorization via ``app.uploads.authorization.authorize_upload``.
    Rules mirror the read APIs that surface the underlying rows:
    Space membership for Collective-scoped media, ``_check_pathway_access``
    for step resources, public-Space rules for covers/logos rendered on
    Explore surfaces, and default-deny for any prefix we don't recognise.
    In R2 mode this returns a 302 to a short-lived pre-signed R2 GET URL
    (5 minutes) for the private bucket. In filesystem mode it serves
    the local file directly.

    Two namespaces inside that catch-all behave differently, and
    both are Offerings. ``offering-files/*`` is a purchased download:
    authorised on *entitlement* rather than membership, and served as
    a forced attachment with a signed ``Content-Disposition`` so the
    bytes cannot render inline on a storage domain.
    ``offering-covers/*`` is ordinary imagery and follows the
    Collective's visibility like any other cover. They are separate
    prefixes precisely so a change to how covers are served can never
    reach the files people paid for. There is no public route for
    either, and there must never be one for the former.

Path traversal is blocked in filesystem mode by ``resolve()`` +
``is_relative_to(UPLOAD_DIR)``. In R2 mode any ``..`` segment in the
requested path is rejected outright — R2 keys are opaque strings, but
refusing traversal-shaped requests keeps the write and read layers
consistent and defends against future misuse.

The DB values are the same in both modes: ``/api/uploads/{key}``.
Storage backend swap requires zero DB migration.
"""

import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_optional_user
from app.core import storage as storage_module
from app.core.config import settings
from app.core.database import get_db
from app.core.storage import UPLOAD_DIR
from app.models.user import User
from app.services.offering_files import OFFERING_FILES_PREFIX
from app.uploads.authorization import authorize_upload, guide_image_is_published

uploads_router = APIRouter(prefix="/api/uploads", tags=["uploads"])


# Pre-signed URL lifetime for private-bucket redirects. Short by design
# — long enough for a page load to complete, short enough that a leaked
# URL (Slack paste, screenshot with URL bar, browser history export)
# stops working before it can be exploited.
_PRESIGNED_URL_EXPIRY_SECONDS = 300

# How long a browser may keep an anonymous public-cover response.
_PUBLIC_COVER_MAX_AGE_SECONDS = 86_400  # 24 hours

# …and the signature behind it, which must outlive that cache entry.
#
# This is the whole reason the two numbers are different. A cached 302
# is a cached *pre-signed URL*: cache the redirect for a day while the
# signature lasts five minutes and every repeat visit for the next
# 23h55m follows a link that R2 rejects — strictly worse than minting
# a new one each time. An hour of headroom means a redirect served at
# the last moment of its cache lifetime still has an hour of signature
# left.
#
# A day-long signature is acceptable *for this subset and no other*.
# The 300-second default exists because a leaked private URL is a
# disclosure; these are cover images on a public, indexed page, already
# fetchable by anyone with no session at all. Nothing else gets this
# lifetime — the flag is set only by an anonymous public-cover grant.
_PUBLIC_COVER_URL_EXPIRY_SECONDS = _PUBLIC_COVER_MAX_AGE_SECONDS + 3_600


def _reject_traversal(file_path: str) -> None:
    """Refuse ``..`` in the requested key. R2 keys are literal, so a
    ``..`` segment is not a filesystem traversal — but it still smells
    wrong and lets us surface bugs early instead of silently 404ing
    against R2."""
    for part in file_path.split("/"):
        if part == "..":
            raise HTTPException(status_code=400, detail="Invalid path.")


def _serve_from_filesystem(
    file_path: str, *, force_download: bool = False, public_cache: bool = False,
) -> FileResponse:
    """Filesystem-mode serving — the pre-Stage-B behaviour, preserved
    for local dev and tests that write to UPLOAD_DIR."""
    target = (UPLOAD_DIR / file_path).resolve()
    root = UPLOAD_DIR.resolve()

    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    media_type, _ = mimetypes.guess_type(str(target))
    # ``Cross-Origin-Resource-Policy: cross-origin`` lets fc-web embed
    # these bytes as ``<img src>`` from a different origin.
    # ``X-Content-Type-Options: nosniff`` refuses browser MIME
    # sniffing — ``media_type`` is authoritative.
    headers = {
        "Cross-Origin-Resource-Policy": "cross-origin",
        "X-Content-Type-Options": "nosniff",
    }
    if force_download:
        headers["Content-Disposition"] = (
            f'attachment; filename="{_download_filename_from_key(file_path)}"'
        )
        headers["Cache-Control"] = "private, max-age=0, no-store"
    elif public_cache:
        # An anonymous public-cover response: the same bytes for every
        # visitor, for as long as the Collective stays public. No
        # signature to outlive here — these are the bytes themselves.
        headers["Cache-Control"] = f"public, max-age={_PUBLIC_COVER_MAX_AGE_SECONDS}"
        headers["Vary"] = "Cookie"
    return FileResponse(
        str(target),
        media_type=(
            "application/octet-stream" if force_download
            else (media_type or "application/octet-stream")
        ),
        headers=headers,
    )


def _redirect_to_public_r2(key: str) -> RedirectResponse:
    """Public-bucket redirect. ``R2_PUBLIC_BASE_URL`` is the origin
    (R2.dev subdomain initially, custom domain later); the key is
    URL-encoded per component so path segments with reserved chars
    still resolve correctly."""
    assert settings.r2_public_base_url is not None
    base = settings.r2_public_base_url.rstrip("/")
    # ``quote`` with ``safe='/'`` preserves the path structure while
    # escaping anything else; keys are UUID-prefixed so this rarely
    # matters, but it is the safe encoding either way.
    encoded = quote(key, safe="/")
    return RedirectResponse(
        url=f"{base}/{encoded}",
        status_code=302,
        headers={
            "Cross-Origin-Resource-Policy": "cross-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _download_filename_from_key(key: str) -> str:
    """A human-readable filename for a forced download.

    Keys are ``{prefix}/{id}/{uuid}_{sanitised-name}``, so the basename
    with its uuid prefix removed is the name the creator uploaded. No
    database read: the key already carries it, and a download path
    should not pay for a second query to label a file.
    """
    base = key.rsplit("/", 1)[-1]
    name = base.split("_", 1)[1] if "_" in base else base
    return name or "download"


def _redirect_to_presigned_r2(
    key: str, *, force_download: bool = False, public_cache: bool = False,
) -> RedirectResponse:
    """Private-bucket redirect via a short-lived pre-signed URL.

    ``force_download`` adds ``ResponseContentDisposition`` to the
    signed parameters. That matters because the bytes are served by R2,
    not by this app: a header set on *this* 302 says nothing about what
    the browser does with the response it is redirected to. Signing the
    disposition is the only way to guarantee a purchased file arrives as
    a download rather than rendering inline on a storage domain.

    Two callers, and the difference matters. ``serve_upload`` calls it
    after verifying the session and the per-namespace rule, so the
    grant follows an authorisation decision. ``serve_public_place_artwork``
    calls it with no session at all, because Place artwork is public
    content that happens to be stored privately — the namespace itself
    is the authorisation decision, made once, here in the route table
    rather than per request.

    Either way the URL is read-only and expires in minutes."""
    assert settings.r2_bucket_private is not None
    # Attribute lookup at call time (via the module reference) so tests
    # that monkeypatch ``storage_module._r2_client`` are observed here.
    params: dict[str, str] = {
        "Bucket": settings.r2_bucket_private,
        "Key": key,
    }
    if force_download:
        filename = _download_filename_from_key(key)
        params["ResponseContentDisposition"] = (
            f'attachment; filename="{filename}"'
        )
        # Signed alongside the disposition so the storage layer cannot be
        # talked into serving a purchased document as, say, HTML.
        params["ResponseContentType"] = "application/octet-stream"
    url = storage_module._r2_client().generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=(
            _PUBLIC_COVER_URL_EXPIRY_SECONDS
            if public_cache
            else _PRESIGNED_URL_EXPIRY_SECONDS
        ),
    )
    if public_cache:
        # Anonymous public cover. The signature is deliberately longer
        # than the cache lifetime — see the constants above — so a
        # redirect served from cache always has time left on it.
        #
        # ``Vary: Cookie`` because this same URL answers differently
        # for a signed-in caller, whose response is ``no-store``. A
        # shared cache must key on the session cookie rather than
        # handing one caller's answer to another. It costs shared-cache
        # hit rate and keeps the browser caching that this is for.
        cache_control = f"public, max-age={_PUBLIC_COVER_MAX_AGE_SECONDS}"
    else:
        # A pre-signed URL is caller-specific and time-bounded; any
        # shared cache that stored the 302 would hand the same URL
        # to other users well past its usefulness. Force no-store
        # so intermediaries do not stash it.
        cache_control = "private, max-age=0, no-store"
    headers = {
        "Cross-Origin-Resource-Policy": "cross-origin",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": cache_control,
    }
    if public_cache:
        headers["Vary"] = "Cookie"
    return RedirectResponse(url=url, status_code=302, headers=headers)


# Public route — declared first so FastAPI's specificity ordering picks
# it before the catch-all below.
@uploads_router.get("/platform-artwork/{file_path:path}")
def serve_public_upload(file_path: str):
    _reject_traversal(file_path)
    key = f"platform-artwork/{file_path}"
    if settings.is_r2_enabled:
        return _redirect_to_public_r2(key)
    return _serve_from_filesystem(key)


@uploads_router.get("/guide-images/{file_path:path}")
def serve_guide_image(
    file_path: str,
    current_user: "User | None" = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Public read for images that belong to a published Guide.

    Guides are free, public articles meant to be found through search,
    so their hero and inline images must render for a logged-out
    reader. They get their own namespace rather than riding on the
    Asset Library, for three reasons that all bit at once:

      * ``media/guides/…`` sent every Guide image through
        ``_authorise_media``, which reads the segment after ``media/``
        as a *Collective slug*, found no Collective called "guides",
        and answered 404 — to everyone, administrators in the preview
        included;
      * even once resolved, that namespace is member-gated, so an
        anonymous reader could never have been served;
      * and if a creator ever registered a Collective slugged
        ``guides``, every Guide image would silently fall under that
        Collective's membership rules. A namespace of its own makes
        that collision unreachable rather than unlikely.

    **Published only, plus administrators.** A key is readable when
    some *published* Guide points at it — as its hero, or from inside
    its sanitised body. A draft's artwork is not public yet, and
    neither is an image uploaded and then never used. Administrators
    are allowed either way, which is what makes the draft preview
    work.

    Refusals are a flat 404, the same answer a key that was never
    uploaded gets, so the route cannot be used to learn that a draft
    exists.

    Only reads are opened up. Uploading and replacing still go through
    ``app/admin/guides/routes.py`` behind ``get_admin_user``.
    """
    _reject_traversal(file_path)
    key = f"guide-images/{file_path}"
    is_admin = current_user is not None and current_user.role == "admin"
    if not is_admin and not guide_image_is_published(key, db):
        raise HTTPException(status_code=404, detail="File not found.")
    if settings.is_r2_enabled:
        # Presigned rather than a public-origin redirect: the bytes
        # are in the private bucket and stay there. Cached the same
        # way an anonymous public cover is — see the constants above
        # for why the signature outlives the cache window.
        return _redirect_to_presigned_r2(key, public_cache=not is_admin)
    return _serve_from_filesystem(key, public_cache=not is_admin)


@uploads_router.get("/place-artwork/{file_path:path}")
def serve_public_place_artwork(file_path: str):
    """Public read for curated Place hero artwork.

    Declared before the catch-all so it wins the route match; without
    it these keys fall through to ``serve_upload``, where
    ``place-artwork`` is not in the dispatch table and is therefore
    default-denied — which is exactly what happened before this route
    existed: 401 for anonymous visitors and 403 for everyone else,
    including administrators, so the artwork rendered nowhere at all.

    Only reads are opened up. Uploading, replacing and deleting Place
    artwork still go through the admin API in
    ``app/admin/physical_locations.py`` behind ``get_admin_user``.
    """
    _reject_traversal(file_path)
    key = f"place-artwork/{file_path}"
    if settings.is_r2_enabled:
        # Presigned rather than a public-origin redirect: the bytes are
        # in the private bucket and stay there.
        return _redirect_to_presigned_r2(key)
    return _serve_from_filesystem(key)


@uploads_router.get("/{file_path:path}")
def serve_upload(
    file_path: str,
    current_user: "User | None" = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Serve a private upload to whoever is entitled to see it.

    ``get_optional_user`` rather than ``get_current_user``: three
    pages are reachable without an account and render images from
    this route — Explore, a Collective's About page and a Pathway's
    About page — and while the dependency refused anonymous callers,
    every one of those covers was a broken image. Authorisation moved
    into ``authorize_upload``, which answers anonymous requests from a
    deliberately small matrix and refuses everything else with the
    same 401 the dependency used to raise.
    """
    _reject_traversal(file_path)
    # Per-namespace authorization. Raises 403 (or 404 for keys that
    # don't resolve to a DB row; a flat 401 for anything anonymous).
    # See ``app.uploads.authorization`` for the full rule matrix. Runs
    # BEFORE the R2 / filesystem branch so both modes are equally
    # gated. Returns whether the answer may be cached publicly, which
    # only an anonymous public-cover grant ever is.
    public_cache = authorize_upload(file_path, current_user, db)
    # Purchased Offering files are the one namespace served as a forced
    # download. Everything else here is imagery the app renders inline
    # (covers, avatars, artwork, step resources), and attaching those
    # would break the pages that display them. Offering *covers* are
    # imagery too, and deliberately not in this set.
    force_download = file_path.startswith(f"{OFFERING_FILES_PREFIX}/")
    if settings.is_r2_enabled:
        return _redirect_to_presigned_r2(
            file_path, force_download=force_download, public_cache=public_cache,
        )
    return _serve_from_filesystem(
        file_path, force_download=force_download, public_cache=public_cache,
    )
