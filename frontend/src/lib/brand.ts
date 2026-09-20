/**
 * Fresh Collective brand — semantic roles and resolution, no React.
 *
 * Every surface asks for a *role* ("the logo on a light card", "the
 * small mark for dark chrome") and this module answers with a URL or
 * with null. Nothing in the product names a brand file directly; that
 * is what let one placeholder survive in ten places and the real logo
 * appear in three, each with its own copy of the path.
 *
 * Resolution order matches the backend exactly:
 *
 *     admin override  →  approved bundled default  →  null
 *
 * ``null`` is a real answer and callers must handle it. The four
 * compact and system roles have no approved artwork yet, and the one
 * thing a caller may never do is invent a substitute — the old teal
 * rounded square, a cropped full lockup, a letter in a box. A brand
 * that renders nothing is a gap someone fixes; a brand that renders
 * the wrong mark is one nobody notices.
 *
 * BUNDLED_DEFAULTS mirrors ``backend/app/brand/roles.py``. The two are
 * held in agreement by a contract test
 * (``tests/test_brand_assets.py::TestFrontendContract``) which parses
 * this file, so drift fails the backend suite rather than shipping a
 * logo that exists on one side only.
 */

export const BRAND_ROLES = [
  'primary_light_logo',
  'alternate_light_logo',
  'logo_on_teal',
  'logo_on_navy',
  'marketing_hero_logo',
  'compact_light_mark',
  'compact_dark_mark',
  'favicon_app_icon',
  'social_share_image',
] as const

export type BrandRole = (typeof BRAND_ROLES)[number]

/** Approved artwork shipped in ``public/brand``. ``null`` = no approved
 *  artwork for this role yet. */
export const BUNDLED_DEFAULTS: Record<BrandRole, string | null> = {
  primary_light_logo: '/brand/fresh-collective-logo-navy-gold-on-white.png',
  alternate_light_logo: '/brand/fresh-collective-logo-teal-gold-on-white.png',
  logo_on_teal: '/brand/fresh-collective-logo-white-on-teal.png',
  logo_on_navy: '/brand/fresh-collective-logo-white-gold-on-navy.png',
  marketing_hero_logo: '/brand/fresh-collective-logo-white-gold-on-teal-gradient.png',
  compact_light_mark: null,
  compact_dark_mark: null,
  favicon_app_icon: null,
  social_share_image: null,
}

/** Admin uploads, keyed by role. Absent or null means "no override". */
export type BrandOverrides = Partial<Record<BrandRole, string | null>>

export function resolveBrandUrl(
  role: BrandRole,
  overrides?: BrandOverrides,
): string | null {
  const override = overrides?.[role]
  if (override) return override
  return BUNDLED_DEFAULTS[role] ?? null
}

/**
 * Surface tone: whether the brand is sitting on a light background or
 * a dark one. Chrome passes its own tone; the role follows.
 */
export type BrandTone = 'light' | 'dark'

/** The compact mark for a tone. Both are unfilled today, which is why
 *  chrome must cope with null rather than treat it as an error. */
export function compactRoleFor(tone: BrandTone): BrandRole {
  return tone === 'dark' ? 'compact_dark_mark' : 'compact_light_mark'
}

/**
 * Intrinsic artwork geometry, measured from the approved files rather
 * than assumed. All five full lockups are 500 × 500 with the same
 * composition, and these numbers are why the sizes elsewhere in the
 * product are what they are.
 */
export const FULL_LOGO_INTRINSIC = 500

/** Cap height of the FRESH COLLECTIVE wordmark as a fraction of the
 *  canvas: 15px in 500px. A lockup rendered at 44px therefore prints
 *  the wordmark at 1.3px, which is the defect this phase fixes. */
export const WORDMARK_CAP_RATIO = 15 / 500

/** Rendered wordmark cap height, in CSS pixels, for a given box. */
export function wordmarkCapHeight(renderedPx: number): number {
  return renderedPx * WORDMARK_CAP_RATIO
}

/**
 * Smallest box at which the wordmark is genuinely readable. Below
 * roughly 7px of cap height letterspaced caps stop resolving, and
 * 7 / (15/500) ≈ 233px. Sizes in the product are chosen against this,
 * and anything asked to be smaller should use a compact mark instead —
 * or, until one exists, live text.
 */
export const MIN_LEGIBLE_FULL_LOGO_PX = 233
