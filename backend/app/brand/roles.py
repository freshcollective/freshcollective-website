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

``missing`` is a real, reportable state rather than an accident, and
one role is in it today: the social share image. It needs a landscape
composition rather than a logo, and no square lockup can be made into
one by resizing.

The app icon is filled, and like the compact marks it is composed from
approved parts rather than designed: the white dragonfly on the teal
that the approved white-on-teal lockup already puts behind it, squared
up, wordmark gone. ``scripts/compose_app_icon.py`` builds it, along
with the static ``favicon.ico``, ``icon.png`` and ``apple-icon.png``
that Next.js resolves at build time — all from that one composition,
so the browser tab and this role cannot disagree.

The two compact marks are filled, and by derivation rather than by
drawing. ``scripts/derive_compact_marks.py`` recovers the dragonfly
from the approved lockups by un-compositing their flat background,
crops away the FRESH COLLECTIVE wordmark and pads the result to a
square, with no resampling at any point. It is the same symbol, the
same pixels; only the wordmark and the background are gone. A test
re-runs the derivation and compares, so the marks cannot drift from
the artwork they came from.

All five full-logo roles are filled by artwork supplied directly by
Lindsey. Every one of the defaults below was identified by reading its
pixels rather than its filename — background kind, dragonfly colour,
wordmark colour — and that identification is pinned as a test, not a
comment: see ``tests/test_brand_assets.py::TestApprovedArtworkContent``.
It is pinned because trusting a filename is exactly how an earlier
pass mapped the marketing lockup to a file whose wordmark is the wrong
colour.

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
            "— the auth cards, documents, anything printed. The current "
            "artwork carries a flat white background rather than "
            "transparency, so it sits on white and near-white only; a "
            "transparent replacement would widen where it can be used."
        ),
        recommended="Square lockup · at least 500 × 500px · PNG or WebP · transparency welcome",
        content_types=FORMATS_TRANSPARENT,
        min_width=400, min_height=400,
        default_path="/brand/fresh-collective-logo-navy-gold-on-white.png",
    ),
    BrandAssetRole(
        role="alternate_light_logo",
        title="Alternate — light background",
        group=GROUP_FULL_LOGOS,
        intended_use=(
            "The teal-dragonfly version of the same lockup, for light "
            "surfaces where the navy reads too heavy or sits beside "
            "other navy elements. Like the primary, the current artwork "
            "has a flat white background rather than transparency."
        ),
        recommended="Square lockup · at least 500 × 500px · PNG or WebP · transparency welcome",
        content_types=FORMATS_TRANSPARENT,
        min_width=400, min_height=400,
        default_path="/brand/fresh-collective-logo-teal-gold-on-white.png",
    ),
    BrandAssetRole(
        role="logo_on_teal",
        title="Teal background",
        group=GROUP_FULL_LOGOS,
        intended_use=(
            "The lockup on a teal panel with the wordmark in white — the "
            "flatter, quieter of the two teal treatments. Use it where "
            "the logo needs to carry its own background and gold would "
            "be too much, such as a solid teal band or a partner "
            "placement."
        ),
        recommended="Square · at least 500 × 500px · PNG or WebP · flat teal background, WHITE wordmark",
        content_types=FORMATS_FLAT,
        min_width=400, min_height=400,
        aspect=SQUARE,
        default_path="/brand/fresh-collective-logo-white-on-teal.png",
    ),
    BrandAssetRole(
        role="logo_on_navy",
        title="Dark / navy background",
        group=GROUP_FULL_LOGOS,
        intended_use=(
            "The lockup on its own flat navy panel — white dragonfly, "
            "gold wordmark. The dressier of the two single-colour "
            "backgrounds; use it where the brand should feel formal "
            "and self-contained rather than borrowing the page's dark "
            "surface."
        ),
        recommended="Square · at least 500 × 500px · PNG or WebP · flat navy background",
        content_types=FORMATS_FLAT,
        min_width=400, min_height=400,
        aspect=SQUARE,
        default_path="/brand/fresh-collective-logo-white-gold-on-navy.png",
    ),
    BrandAssetRole(
        role="marketing_hero_logo",
        title="Marketing / hero",
        group=GROUP_FULL_LOGOS,
        intended_use=(
            "The full lockup on its own deep teal gradient — white "
            "dragonfly, gold wordmark, the background running from teal "
            "at the top to near-navy at the foot. The most complete "
            "statement of the brand, for campaign artwork, hero "
            "placements and anywhere the logo needs to hold a space by "
            "itself."
        ),
        recommended="Square · at least 500 × 500px · PNG or WebP · gradient background is part of the artwork",
        content_types=FORMATS_FLAT,
        min_width=400, min_height=400,
        aspect=SQUARE,
        default_path="/brand/fresh-collective-logo-white-gold-on-teal-gradient.png",
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
        default_path="/brand/fresh-collective-mark-navy-on-transparent.png",
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
        default_path="/brand/fresh-collective-mark-white-on-transparent.png",
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
        default_path="/brand/fresh-collective-app-icon.png",
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
