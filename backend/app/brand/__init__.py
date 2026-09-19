"""Fresh Collective brand assets — roles, approved defaults, resolution.

``roles`` defines what the brand is asked to do and what artwork may
fill each job; ``resolver`` answers which artwork currently does.
Import from here rather than reaching into either module.
"""

from app.brand.resolver import (
    SOURCE_CUSTOM,
    SOURCE_DEFAULT,
    SOURCE_MISSING,
    BrandAssetResolution,
    resolve,
    resolve_all,
    resolve_for_email,
)
from app.brand.roles import (
    BRAND_ASSET_ROLES,
    GROUP_COMPACT_SYSTEM,
    GROUP_FULL_LOGOS,
    GROUP_LABELS,
    MAX_BRAND_ASSET_BYTES,
    ROLE_ORDER,
    BrandAssetRole,
    UnknownBrandRoleError,
    get_role,
    storage_key_for,
    storage_subdir_for,
)

__all__ = [
    "BRAND_ASSET_ROLES",
    "GROUP_COMPACT_SYSTEM",
    "GROUP_FULL_LOGOS",
    "GROUP_LABELS",
    "MAX_BRAND_ASSET_BYTES",
    "ROLE_ORDER",
    "SOURCE_CUSTOM",
    "SOURCE_DEFAULT",
    "SOURCE_MISSING",
    "BrandAssetResolution",
    "BrandAssetRole",
    "UnknownBrandRoleError",
    "get_role",
    "resolve",
    "resolve_all",
    "resolve_for_email",
    "storage_key_for",
    "storage_subdir_for",
]
