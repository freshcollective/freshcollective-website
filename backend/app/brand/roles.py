"""The Fresh Collective brand asset roles — what they are, what may fill them.

A *role* is a job the brand does somewhere in the product: the logo on
a light card, the mark small enough to sit in a 28px header, the square
that becomes a browser tab icon. Roles are fixed and defined by the
application. An admin chooses the artwork for a role; they never invent
a role, and they never see a storage key.

Three states, and the third one matters
---------------------------------------

Every role resolves to exactly one of:

* **custom**  — an admin uploaded artwork for it.
* **default** — no upload, and the role has approved artwork bundled in
  the repo, which is what ships.
* **missing** — no upload and no bundled default.

``missing`` is a real, reportable state rather than an accident. Four
roles are in it today: the two compact marks, the favicon and the
social share image. Fresh Collective has no compact artwork yet — only
the full stacked lockups, whose wordmark is 3% of the canvas height and
becomes an illegible smudge below about 120px wide. The tempting move
is to point those roles at the square lockup anyway and let CSS crop
it. That produces a logo nobody approved, drawn by a bounding box.
Saying "missing" is the honest answer and it keeps the gap visible in
World Management until proper derived artwork is supplied.

Why the defaults are paths, not rows
------------------------------------

The five approved PNGs live in ``frontend/public/brand/`` and are
served by fc-web as ordinary static files. A default is therefore a
URL path this module knows, not a database row seeded by a migration.
That means a fresh install is correctly branded with no data at all, a
reset is a DELETE rather than a re-seed, and replacing the artwork
later (a vector master, a new lockup) is a file swap plus one line
here — no migration, no re-upload, nothing to reconcile.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Admin-facing grouping. Order is render order in World Management.
GROUP_FULL_LOGOS = "full_logos"
GROUP_COMPACT_SYSTEM = "compact_system"

GROUP_LABELS: dict[str, dict[str, str]] = {
    GROUP_FULL_LOGOS: {
        "label": "Full logos",
        "description": (
            "The complete Fresh Collective lockup — the dragonfly and the "
            "wordmark together. Use these where the brand is the subject "
            "and there is room to read it."
        ),
    },
    GROUP_COMPACT_SYSTEM: {
        "label": "Compact / system assets",
        "description": (
            "Small and single-purpose. These sit in headers, browser tabs "
            "and link previews, where the full lockup is either too wide "
            "or too small to read."
        ),
    },
}


# Formats. PNG and WebP carry transparency, which every logo role needs.
# JPEG is offered only where a flat background is correct.
FORMATS_TRANSPARENT = ("image/png", "image/webp")
FORMATS_FLAT = ("image/png", "image/webp", "image/jpeg")

EXTENSION_BY_CONTENT_TYPE: dict[str, str] = {
    "image/png": "png",
    "image/webp": "webp",
    "image/jpeg": "jpg",
}

# A logo is a few tens of kilobytes. The platform-wide upload ceiling is
# 200 MB, which is the right number for a video resource and a useless
# one here: at that size the only thing it catches is a mistake nobody
# would make. 4 MB is generous for a 2x raster lockup and still refuses
# the "I dragged the print-resolution TIFF in" case.
MAX_BRAND_ASSET_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class AspectRule:
    """A target aspect ratio and how far from it we will still accept.

    ``tolerance`` is fractional, so 0.02 means "within 2% of the target".
    A square role wants a genuine square; a favicon that is 512x509 is a
    mistake worth catching at upload rather than discovering in a
    browser tab.
    """

    ratio: float
    tolerance: float
    description: str

    def accepts(self, width: int, height: int) -> bool:
        if height <= 0:
            return False
        return abs((width / height) - self.ratio) <= self.ratio * self.tolerance


SQUARE = AspectRule(1.0, 0.02, "square (1:1)")
SOCIAL_CARD = AspectRule(1200 / 630, 0.02, "1.91:1 — the OpenGraph card ratio")


@dataclass(frozen=True)
class BrandAssetRole:
    """One job the brand does, and the rules for the artwork that does it."""

    role: str
    title: str
    group: str
    # What this artwork is for, in the admin's language. Shown beside
    # the preview; it is the whole explanation of why the role exists.
    intended_use: str
    # Human-readable size guidance, rendered under the preview.
    recommended: str
    content_types: tuple[str, ...]
    min_width: int
    min_height: int
    aspect: AspectRule | None = None
    # Path to the approved bundled artwork, served by fc-web out of
    # ``frontend/public``. ``None`` means this role has no approved
    # artwork yet and resolves to ``missing``.
    default_path: str | None = None
    # Why a role is missing, when it is. Rendered in World Management so
    # the gap reads as a known piece of outstanding work rather than a
    # bug in the page.
    missing_note: str = ""
    # Roles whose artwork is embedded in email HTML or read by a
    # crawler must resolve to an absolute, publicly-fetchable URL.
    requires_public_url: bool = field(default=False)


_ROLES: tuple[BrandAssetRole, ...] = (
    # ── Full logos ───────────────────────────────────────────────────
    BrandAssetRole(
        role="primary_light_logo",
        title="Primary — light background",
        group=GROUP_FULL_LOGOS,
        intended_use=(
            "The default Fresh Collective logo. Navy dragonfly, gold "
            "wordmark. Use it anywhere the background is white or light "
            "— the auth cards, documents, anything printed."
        ),
        recommended="Square lockup · at least 500 × 500px · PNG or WebP with transparency",
        content_types=FORMATS_TRANSPARENT,
        min_width=400, min_height=400,
        default_path="/brand/fresh-collective-logo-navy-gold-white.png",
    ),
    BrandAssetRole(
        role="alternate_light_logo",
        title="Alternate — light background",
        group=GROUP_FULL_LOGOS,
        intended_use=(
            "The teal-dragonfly version of the same lockup, for light "
            "surfaces where the navy reads too heavy or sits beside "
            "other navy elements."
        ),
        recommended="Square lockup · at least 500 × 500px · PNG or WebP with transparency",
        content_types=FORMATS_TRANSPARENT,
        min_width=400, min_height=400,
        default_path="/brand/fresh-collective-logo-teal-gold-white.png",
    ),
    BrandAssetRole(
        role="logo_on_teal",
        title="Teal background",
        group=GROUP_FULL_LOGOS,
        intended_use=(
            "The lockup presented on its own teal gradient panel — white "
            "dragonfly, gold wordmark. Use it where the logo needs to "
            "carry its own background rather than borrow the page's."
        ),
        recommended="Square · at least 500 × 500px · PNG or WebP · background is part of the artwork",
        content_types=FORMATS_FLAT,
        min_width=400, min_height=400,
        aspect=SQUARE,
        default_path="/brand/fresh-collective-logo-square-teal.png",
    ),
    BrandAssetRole(
        role="logo_on_navy",
        title="Dark / navy background",
        group=GROUP_FULL_LOGOS,
        intended_use=(
            "White dragonfly, gold wordmark, transparent background — "
            "for deep navy and other dark surfaces. It is invisible on "
            "white, so never use it as a general-purpose logo."
        ),
        recommended="Square lockup · at least 500 × 500px · PNG or WebP with transparency",
        content_types=FORMATS_TRANSPARENT,
        min_width=400, min_height=400,
        default_path="/brand/fresh-collective-logo-transparent-gold.png",
    ),
    BrandAssetRole(
        role="marketing_hero_logo",
        title="Marketing / hero",
        group=GROUP_FULL_LOGOS,
        intended_use=(
            "White dragonfly with the teal wordmark, transparent "
            "background. The quieter of the two dark-surface lockups — "
            "for campaign artwork and hero imagery where gold would "
            "compete with the photograph behind it."
        ),
        recommended="Square lockup · at least 500 × 500px · PNG or WebP with transparency",
        content_types=FORMATS_TRANSPARENT,
        min_width=400, min_height=400,
        default_path="/brand/fresh-collective-logo-transparent-teal.png",
    ),

    # ── Compact / system assets ──────────────────────────────────────
    #
    # All four are missing. The note on each says so in the admin's own
    # terms rather than making them infer it from an empty preview.
    BrandAssetRole(
        role="compact_light_mark",
        title="Compact mark — light",
        group=GROUP_COMPACT_SYSTEM,
        intended_use=(
            "The dragonfly alone, drawn to read at 24–32px, for light "
            "backgrounds. This is what belongs in site headers, the "
            "footer, the Creator Studio and World Management sidebars, "
            "and the email header beside live “Fresh Collective” text."
        ),
        recommended="Square · at least 256 × 256px · PNG or WebP with transparency",
        content_types=FORMATS_TRANSPARENT,
        min_width=128, min_height=128,
        aspect=SQUARE,
        default_path=None,
        missing_note=(
            "Fresh Collective has no compact mark yet. The full lockups "
            "cannot stand in: their wordmark is 3% of the canvas height "
            "and disappears below about 120px wide, and cropping one "
            "down to the dragonfly would invent artwork nobody approved. "
            "A drawn-for-small-sizes mark is needed."
        ),
        requires_public_url=True,
    ),
    BrandAssetRole(
        role="compact_dark_mark",
        title="Compact mark — dark",
        group=GROUP_COMPACT_SYSTEM,
        intended_use=(
            "The same compact dragonfly in white, for navy and other "
            "dark chrome — the overlay header on the auth pages and the "
            "public footer."
        ),
        recommended="Square · at least 256 × 256px · PNG or WebP with transparency",
        content_types=FORMATS_TRANSPARENT,
        min_width=128, min_height=128,
        aspect=SQUARE,
        default_path=None,
        missing_note=(
            "Awaiting the same compact artwork as the light mark, in "
            "white."
        ),
        requires_public_url=True,
    ),
    BrandAssetRole(
        role="favicon_app_icon",
        title="Favicon / app icon",
        group=GROUP_COMPACT_SYSTEM,
        intended_use=(
            "The browser tab icon and the home-screen icon on iOS and "
            "Android. Rendered as small as 16px, and cropped to a circle "
            "or a rounded square by the operating system — so it needs "
            "its own background and generous margins, not a transparent "
            "lockup."
        ),
        recommended="Square · at least 512 × 512px · PNG or WebP · background included, safe margins",
        content_types=FORMATS_FLAT,
        min_width=256, min_height=256,
        aspect=SQUARE,
        default_path=None,
        missing_note=(
            "The teal square lockup is the closest existing asset, but "
            "at 16–32px its wordmark is noise rather than a word, and an "
            "app icon is the one place a smudge is most visible. Needs "
            "the compact mark on the teal panel, with margins. Until "
            "then the site still serves the default Next.js icon."
        ),
        requires_public_url=True,
    ),
    BrandAssetRole(
        role="social_share_image",
        title="Social share image",
        group=GROUP_COMPACT_SYSTEM,
        intended_use=(
            "The preview card shown when a Fresh Collective link is "
            "pasted into a message, a post or a chat. Read at thumbnail "
            "size by people who have never seen the site."
        ),
        recommended="1200 × 630px (1.91:1) · PNG, WebP or JPG · flat background",
        content_types=FORMATS_FLAT,
        min_width=600, min_height=315,
        aspect=SOCIAL_CARD,
        default_path=None,
        missing_note=(
            "No social card artwork exists. Pages currently share with "
            "title and description only and no image at all. This is a "
            "landscape composition rather than a logo, so none of the "
            "square lockups can fill it."
        ),
        requires_public_url=True,
    ),
)


BRAND_ASSET_ROLES: dict[str, BrandAssetRole] = {r.role: r for r in _ROLES}

# Render order for World Management, grouped.
ROLE_ORDER: tuple[str, ...] = tuple(r.role for r in _ROLES)


class UnknownBrandRoleError(KeyError):
    """The role id is not one of the application-defined roles.

    Roles are a closed vocabulary on purpose: an admin-invented key
    would be artwork nothing renders, and a typo would silently create
    one. Callers turn this into a 404.
    """


def get_role(role: str) -> BrandAssetRole:
    try:
        return BRAND_ASSET_ROLES[role]
    except KeyError as exc:
        raise UnknownBrandRoleError(role) from exc


def storage_key_for(role: str) -> str:
    """Database key for a role's ``platform_artwork`` row.

    Brand artwork lives in the same table, the same bucket and the same
    public URL prefix as the rest of World Artwork — one asset system,
    not two. The ``brand_`` prefix keeps the two vocabularies apart so
    neither list can accidentally render the other's rows.
    """
    return f"brand_{role}"


def storage_subdir_for(role: str) -> str:
    """Upload destination. The ``platform-artwork/`` prefix is what
    routes these objects to the PUBLIC R2 bucket and the unauthenticated
    serve route — which is what makes them usable in an email and in a
    link preview. See ``app/core/storage.py::_bucket_for_key``."""
    return f"platform-artwork/brand/{role}"
