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
  compact_light_mark: '/brand/fresh-collective-mark-navy-on-transparent.png',
  compact_dark_mark: '/brand/fresh-collective-mark-white-on-transparent.png',
  favicon_app_icon: '/brand/fresh-collective-app-icon.png',
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
 * The compact marks are the approved dragonfly with the wordmark
 * cropped away — a fine-line drawing whose stroke is 1.34% of its
 * width. At a 24px box that stroke lands at 0.32 CSS pixels and the
 * browser averages it into a grey haze; the mark stops reading as a
 * dragonfly at all. Measured on screen, 32px is the floor and 36px is
 * where the wing detail separates cleanly. CHROME_MARK_PX is that
 * finding, written down.
 */
export const CHROME_MARK_PX = 36

/** The smallest box at which the compact mark still resolves. Below
 *  this the honest options are live text or a heavier-stroke mark
 *  drawn for the size — not a smaller copy of this one. */
export const MIN_LEGIBLE_MARK_PX = 32

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
 * Smallest box at which the wordmark is genuinely readable.
 *
 * This started as a rule of thumb — 7px of cap height, so 233px — and
 * was then checked by rendering the real email shell at 140, 168, 200
 * and 240 and looking at all four. 140 loses the wordmark. 200 reads
 * cleanly at 6px of cap height, which is 12 device pixels on the
 * retina displays most of this is read on. The measured answer is
 * therefore 200, not 233, and it is the measured one that belongs
 * here. Anything smaller should use a compact mark instead.
 */
export const MIN_LEGIBLE_FULL_LOGO_PX = 200
