/**
 * Collective Palette — shared token / override model.
 *
 * A collective's colour palette (Earth & Moss, Ocean & Sand, Deep
 * Ocean, Sunrise, …) is defined server-side in the ``colour_stories``
 * table (seeded from Alembic migration 063). Every space stores the
 * selected palette as a slug key (``colour_story_key``); the space
 * detail endpoint hydrates it into ``colour_palette`` with four hex
 * slots — ``primary``, ``secondary``, ``accent``, ``background``.
 *
 * This module owns the *storage encoding* for creator-authored block
 * colour choices — callout tint, container tint, button colour, etc.
 * A single stored string can hold three flavours of colour, and this
 * module owns parse + resolve for all three so callers never inline
 * the encoding:
 *
 *   1. ``palette:primary`` (or secondary/accent/background)
 *      A palette-linked *role* token. The stored value carries no
 *      hex — it resolves at render time against the currently active
 *      collective palette. Changing the collective's palette flows
 *      through automatically.
 *
 *   2. ``custom:#3A6B7A``
 *      A literal hex override. Preserved as-is, ignored by future
 *      palette changes.
 *
 *   3. Any other string (``teal``, ``gold``, ``blue``, ``rose``,
 *      ``sage``, ``grey``, ``lilac``, ``orange``)
 *      A legacy fixed key. Callers keep resolving these through the
 *      existing ``CALLOUT_COLOURS`` palette for byte-identical output
 *      on pre-migration content. No silent migration is performed.
 *
 * Server-safe (no ``use client``, no React imports) so both Server
 * Components (member step + About pages) and Client Components
 * (creator editors) can share the same encode/decode helpers.
 */


// ---------------------------------------------------------------------------
// Palette shape
// ---------------------------------------------------------------------------

/** The four semantic slots present on every seeded colour story. */
export const PALETTE_ROLES = ['primary', 'secondary', 'accent', 'background'] as const
export type PaletteRole = typeof PALETTE_ROLES[number]

/** Human-readable role labels for use in the picker UI. */
export const PALETTE_ROLE_LABEL: Record<PaletteRole, string> = {
  primary:    'Primary',
  secondary:  'Secondary',
  accent:     'Accent',
  background: 'Background',
}

/**
 * The full palette metadata returned by the space detail endpoint.
 * Kept structurally identical to the API payload — do not rename.
 */
export interface CollectivePaletteMeta {
  key: string
  name: string
  palette: { primary: string; secondary: string; accent: string; background: string }
}


// ---------------------------------------------------------------------------
// Storage encoding
// ---------------------------------------------------------------------------

const PALETTE_PREFIX = 'palette:'
const CUSTOM_PREFIX  = 'custom:'


/** Discriminated union produced by ``parseStoredColour``. */
export type ParsedStoredColour =
  | { kind: 'palette'; role: PaletteRole }
  | { kind: 'custom';  hex: string }
  | { kind: 'legacy';  key: string }
  | { kind: 'none' }


/** Only accept #rgb or #rrggbb — reject anything else (rgb(), url(), …). */
export function isValidHex(v: string): boolean {
  return /^#[0-9A-Fa-f]{3}([0-9A-Fa-f]{3})?$/.test(v.trim())
}


/**
 * Parse a stored colour value into its typed form. Unrecognised
 * prefixes fall through to ``legacy`` so old rows keep resolving via
 * the existing CALLOUT_COLOURS map without a data migration.
 */
export function parseStoredColour(value: string | null | undefined): ParsedStoredColour {
  if (!value) return { kind: 'none' }
  if (value.startsWith(PALETTE_PREFIX)) {
    const raw = value.slice(PALETTE_PREFIX.length)
    if ((PALETTE_ROLES as readonly string[]).includes(raw)) {
      return { kind: 'palette', role: raw as PaletteRole }
    }
    return { kind: 'none' }
  }
  if (value.startsWith(CUSTOM_PREFIX)) {
    const hex = value.slice(CUSTOM_PREFIX.length).trim()
    if (isValidHex(hex)) return { kind: 'custom', hex }
    return { kind: 'none' }
  }
  return { kind: 'legacy', key: value }
}


/** Encode a palette role as a stored value. */
export function encodePaletteRole(role: PaletteRole): string {
  return `${PALETTE_PREFIX}${role}`
}


/** Encode a custom hex as a stored value. Throws on bad hex. */
export function encodeCustomHex(hex: string): string {
  if (!isValidHex(hex)) throw new Error(`Invalid hex value: ${hex}`)
  return `${CUSTOM_PREFIX}${hex}`
}


// ---------------------------------------------------------------------------
// Colour resolution
// ---------------------------------------------------------------------------


/** Return the hex colour for a role from a palette, or null. */
export function paletteHex(role: PaletteRole, palette: CollectivePaletteMeta | null | undefined): string | null {
  if (!palette) return null
  return palette.palette[role] ?? null
}


/**
 * Derive a soft-tint ``{ bg, border }`` pair from a solid hex, so a
 * palette-linked or custom-hex block colour can render as a callout /
 * container background without the writer having to pick both surfaces.
 *
 * Values chosen to match the visual weight of the legacy CALLOUT_COLOURS
 * (soft pastel bg + slightly darker border).
 */
export function deriveSoftTint(hex: string): { bg: string; border: string } {
  return {
    bg:     rgbaFromHex(hex, 0.10),
    border: rgbaFromHex(hex, 0.32),
  }
}


/**
 * Resolve a stored colour value into a hex string, using the active
 * collective palette for role tokens. Returns null when the value is
 * ``none`` (empty) or when a palette role is stored but no active
 * palette is available — the caller falls back to its own default.
 *
 * Legacy string keys (teal, gold, …) are *not* resolved here — the
 * caller passes the value on to ``resolveCalloutPalette`` /
 * ``resolveContainerPalette`` for byte-identical rendering on
 * pre-migration blocks.
 */
export function resolveHex(
  value: string | null | undefined,
  palette: CollectivePaletteMeta | null | undefined,
): string | null {
  const parsed = parseStoredColour(value)
  if (parsed.kind === 'palette') return paletteHex(parsed.role, palette)
  if (parsed.kind === 'custom')  return parsed.hex
  return null
}


// Small #RRGGBB → rgba() helper — silently returns the source on bad input.
function rgbaFromHex(hex: string, alpha: number): string {
  const trimmed = hex.trim().replace(/^#/, '')
  let full = trimmed
  if (trimmed.length === 3) {
    // Expand shorthand #abc → #aabbcc
    full = trimmed.split('').map((c) => c + c).join('')
  }
  if (!/^[0-9a-f]{6}$/i.test(full)) return hex
  const n = parseInt(full, 16)
  const r = (n >> 16) & 0xff
  const g = (n >> 8) & 0xff
  const b = n & 0xff
  return `rgba(${r},${g},${b},${alpha})`
}


/** Exposed for tests + advanced callers. */
export { rgbaFromHex }
