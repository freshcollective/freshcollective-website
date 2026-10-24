"""One place that answers "what artwork fills this brand role right now?".

    admin upload  →  approved bundled default  →  explicit missing

Every consumer goes through :func:`resolve` — the admin screen, the
public map, and (in a later phase) the email shell and the site chrome.
That is the entire point of the module: when the artwork changes, or a
vector master finally arrives, exactly one lookup has to change.

What this resolver will never do
--------------------------------

It will never substitute something that merely looks like a logo. The
teal rounded square that currently stands in for the brand across the
site and in both email shells is not reachable from here, and a role
with no artwork returns ``missing`` rather than a placeholder. A
caller that renders nothing is a visible gap someone fixes; a caller
that renders the wrong mark is a brand nobody notices is wrong.

Absolute URLs, and why two kinds of URL exist
---------------------------------------------

In-product callers want a same-origin path (``/brand/x.png``,
``/api/uploads/...``) so the browser fetches it from the origin it is
already on. Email clients and link-preview crawlers have no origin to
be relative to and no session to authenticate with, so they need a
fully-qualified ``https://`` URL that answers to an anonymous GET.

:attr:`BrandAssetResolution.public_url` is that second kind, and it is
``None`` unless the asset genuinely satisfies it. Uploaded brand
artwork is written under the ``platform-artwork/`` prefix, which
``app/core/storage.py::_bucket_for_key`` routes to the public R2
bucket and ``app/uploads/routes.py`` serves without a session — so in
R2 mode the public URL is the R2 origin directly, no redirect and no
backend hop. Anything not under that prefix is treated as private and
is deliberately withheld, so a misfiled asset cannot leak into an
email as a URL that 403s for every recipient.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.brand.roles import (
    BrandAssetRole,
    ROLE_ORDER,
    get_role,
    storage_key_for,
)
from app.core.config import settings
from app.core.public_url import public_app_url
from app.models.platform import PlatformArtwork


SOURCE_CUSTOM = "custom"
SOURCE_DEFAULT = "default"
SOURCE_MISSING = "missing"

# The upload prefix that is served without authentication. Kept here as
# a named constant so the email-safety check reads as a rule rather
# than as a string comparison.
PUBLIC_UPLOAD_PREFIX = "/api/uploads/platform-artwork/"


@dataclass(frozen=True)
class BrandAssetResolution:
    """The effective artwork for one role."""

    role: str
    source: str                      # custom | default | missing
    url: str | None                  # same-origin path for in-product use
    public_url: str | None           # absolute https URL, or None
    updated_at: datetime | None
    updated_by_user_id: str | None

    @property
    def is_missing(self) -> bool:
        return self.source == SOURCE_MISSING

    @property
    def definition(self) -> BrandAssetRole:
        return get_role(self.role)


def _app_origin() -> str:
    return public_app_url()


def _absolute_for_default(path: str) -> str:
    """Bundled defaults are static files on fc-web."""
    return f"{_app_origin()}{path}"


def _absolute_for_upload(url: str) -> str | None:
    """Absolute, anonymous-GET-able URL for an uploaded asset.

    Returns ``None`` for anything outside the public prefix. That is a
    refusal, not a failure: the caller asking for a public URL is about
    to put it somewhere a stranger's mail client will fetch it from.
    """
    if not url.startswith(PUBLIC_UPLOAD_PREFIX):
        return None
    key = url.removeprefix("/api/uploads/")
    base = (settings.r2_public_base_url or "").rstrip("/")
    if settings.is_r2_enabled and base:
        # Straight at the public bucket — no redirect, no fc-api hop,
        # which is what an inbox image load wants.
        return f"{base}/{key}"
    # Filesystem / local mode: fc-web proxies /api/* to fc-api and the
    # platform-artwork route needs no session.
    return f"{_app_origin()}{url}"


def _row_for(db: Session, role: str) -> PlatformArtwork | None:
    return (
        db.query(PlatformArtwork)
        .filter(PlatformArtwork.key == storage_key_for(role))
        .first()
    )


def resolve(db: Session, role: str) -> BrandAssetResolution:
    """Effective artwork for one role. Raises ``UnknownBrandRoleError``
    for a role that is not application-defined."""
    definition = get_role(role)

    row = _row_for(db, role)
    if row is not None and row.image_url:
        return BrandAssetResolution(
            role=role,
            source=SOURCE_CUSTOM,
            url=row.image_url,
            public_url=_absolute_for_upload(row.image_url),
            updated_at=row.updated_at,
            updated_by_user_id=row.updated_by_user_id,
        )

    if definition.default_path:
        return BrandAssetResolution(
            role=role,
            source=SOURCE_DEFAULT,
            url=definition.default_path,
            public_url=_absolute_for_default(definition.default_path),
            updated_at=None,
            updated_by_user_id=None,
        )

    return BrandAssetResolution(
        role=role,
        source=SOURCE_MISSING,
        url=None,
        public_url=None,
        updated_at=None,
        updated_by_user_id=None,
    )


def resolve_all(db: Session) -> list[BrandAssetResolution]:
    """Every role, in render order, in one query."""
    rows = {
        r.key: r
        for r in db.query(PlatformArtwork).filter(
            PlatformArtwork.key.in_([storage_key_for(r) for r in ROLE_ORDER]),
        ).all()
    }

    out: list[BrandAssetResolution] = []
    for role in ROLE_ORDER:
        definition = get_role(role)
        row = rows.get(storage_key_for(role))
        if row is not None and row.image_url:
            out.append(BrandAssetResolution(
                role=role, source=SOURCE_CUSTOM, url=row.image_url,
                public_url=_absolute_for_upload(row.image_url),
                updated_at=row.updated_at,
                updated_by_user_id=row.updated_by_user_id,
            ))
        elif definition.default_path:
            out.append(BrandAssetResolution(
                role=role, source=SOURCE_DEFAULT,
                url=definition.default_path,
                public_url=_absolute_for_default(definition.default_path),
                updated_at=None, updated_by_user_id=None,
            ))
        else:
            out.append(BrandAssetResolution(
                role=role, source=SOURCE_MISSING, url=None, public_url=None,
                updated_at=None, updated_by_user_id=None,
            ))
    return out


def bundled_default_public_url(role: str) -> str | None:
    """Absolute URL of a role's approved bundled artwork, with no
    database involved. The fallback an email uses when there is no
    admin upload — or when there is one and it is not safe to send."""
    default = get_role(role).default_path
    return _absolute_for_default(default) if default else None


def resolve_for_email(db: Session, role: str) -> str | None:
    """The URL to put in an ``<img src>`` in an email, or ``None``.

    ``None`` means "render no image" — the caller keeps its live text
    and the layout holds. It never means "fall back to something".
    """
    return resolve(db, role).public_url


def collective_artwork_for_email(db: Session, space_id: str | None) -> str | None:
    """The Collective's own artwork, as an ``<img src>`` an inbox can load.

    ``None`` means "render no image", exactly as in
    :func:`resolve_for_email` — never "fall back to something". That
    matters more here than it does for the brand logo, because the
    obvious fallback is wrong in a way that is invisible from the
    sending side.

    Where the artwork comes from
    ----------------------------

    A Collective does not own artwork. Under the Atlas it *chooses* a
    Location, and the Location carries the artwork — curated by Fresh
    Collective, reusable across Collectives. So the lookup is
    ``Space.location_id -> Location.hero_artwork_url``, and a
    Collective that has not chosen a Location simply has no artwork to
    send. Resolved per render rather than stored on the event, so a
    creator who changes their Location in Place & Feel changes the
    next welcome email too.

    Why not the two other artwork columns
    -------------------------------------

    ``Space.island_artwork_url`` is a stale column from migration 064
    that no form writes to; ``admin/schemas.py`` says in terms not to
    use it as a source anywhere new.

    ``Space.cover_image_url`` is the fallback rung every *in-product*
    call site uses, and it is the one thing that must not be used
    here. Covers are private uploads: ``/api/uploads/*`` authorises
    them against the signed-in user, so the URL works perfectly for
    the creator previewing the email and returns 403 for every actual
    recipient. A broken image in everyone's inbox except the person
    who checked it is precisely the bug this docstring exists to
    prevent.

    ``_absolute_for_upload`` is what enforces that: Location artwork
    is stored under ``platform-artwork/atlas-locations/...`` and so
    passes the public-prefix gate, while a cover would be refused.
    """
    if not space_id:
        return None
    from app.models.platform import Location, Space

    row = (
        db.query(Location.hero_artwork_url)
        .join(Space, Space.location_id == Location.id)
        .filter(Space.id == space_id)
        .first()
    )
    if row is None or not row[0]:
        return None
    return _absolute_for_upload(row[0])
