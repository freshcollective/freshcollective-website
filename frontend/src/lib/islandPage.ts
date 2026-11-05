/**
 * The member-facing island page: what to show, and in which colours.
 *
 * Every Collective sits in an Atlas Location, chosen by its creator
 * because the artwork, story and feeling of the place matched what
 * they wanted their community to have. Members saw almost none of
 * that — a name in the header and a small card on the About page.
 *
 * This is read-only. Every field comes from where it already lives:
 *
 *   name, tagline, story, artwork   `locations` (curated in /admin/atlas)
 *   atmosphere words                `spaces.atmosphere_keys` → names
 *   colours                         `spaces.colour_story_key` → palette
 *
 * Nothing here is a second copy, and nothing here writes. World
 * Artwork, Atlas curation and the creator's Location choice are
 * untouched — change the island in Place and Feel and this page says
 * something different on the next load, because it only ever read.
 *
 * The two concepts, kept apart
 * ----------------------------
 * The **Location** belongs to Fresh Collective's world. The **Colour
 * Palette** is the creator's, chosen separately, and is deliberately
 * what styles this page — so the same island looks like it belongs to
 * whichever Collective you reached it through. The palette itself is
 * never named or swatched to a member; it is only colour.
 */

import {
  darkenHex,
  isValidHex,
  paletteHex,
  readableOnWhite,
  type CollectivePaletteMeta,
} from './collectivePalette.ts'

/** Where a Collective's island page lives. Collective-scoped, so
 *  changing islands never breaks a link. */
export function islandHref(collectiveSlug: string): string {
  return `/spaces/${collectiveSlug}/island`
}

/** Where the back button and breadcrumb return to. */
export function collectiveAboutHref(collectiveSlug: string): string {
  return `/spaces/${collectiveSlug}/about`
}

/** The call to action on the About page's island card. */
export function exploreIslandLabel(islandName: string | null | undefined): string {
  const name = (islandName ?? '').trim()
  return name ? `Explore ${name}` : 'Explore this island'
}

// ---------------------------------------------------------------------------
// The island's story
// ---------------------------------------------------------------------------

/**
 * The island's story, as paragraphs.
 *
 * `atlas_entry` is the long-form page in the atlas — plain text with
 * its paragraph breaks preserved, authored in World Management. Blank
 * lines separate paragraphs; a single newline inside one is a soft
 * wrap and is folded, because that is how the field is written.
 *
 * Falls back to the short `description` when no atlas entry exists, so
 * an island with only a tagline still says something rather than
 * showing an empty section. Returns `[]` when there is nothing at all
 * and the caller should omit the section entirely.
 *
 * Plain text, deliberately. The field is plain text with newlines, and
 * these strings are rendered as text nodes — there is no second
 * rich-text system here and no markup is interpreted.
 */
export function islandStoryParagraphs(
  atlasEntry: string | null | undefined,
  description?: string | null,
): string[] {
  const source = (atlasEntry ?? '').trim() || (description ?? '').trim()
  if (!source) return []
  return source
    .split(/\n\s*\n+/)
    .map((block) => block.split('\n').map((l) => l.trim()).filter(Boolean).join(' '))
    .filter((block) => block.length > 0)
}

/**
 * The tagline under the island's name.
 *
 * The short `description`, unless it is already the whole story being
 * told below — which happens for an island with no atlas entry, where
 * showing the same sentences twice would read as a mistake.
 */
export function islandTagline(
  description: string | null | undefined,
  atlasEntry?: string | null,
): string | null {
  const tagline = (description ?? '').trim()
  if (!tagline) return null
  if (!(atlasEntry ?? '').trim()) return null
  return tagline
}

// ---------------------------------------------------------------------------
// The Collective's colours
// ---------------------------------------------------------------------------

export interface IslandPalette {
  /** "About this island", tinted and legible on the page background. */
  headingColor: string
  /** The feeling card's surface. */
  cardBackground: string
  /** Text on that surface. */
  cardText: string
  /** A pill on that surface. */
  pillBackground: string
  pillBorder: string
  pillText: string
  /** True when a palette was resolved rather than defaulted. */
  fromPalette: boolean
}

const LIGHT_INK = '#ffffff'
const DARK_INK = '#0f172a'

function _hexLuminance(hex: string): number | null {
  const match = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim())
  if (!match) return null
  const raw = match[1].length === 3
    ? match[1].split('').map((c) => c + c).join('')
    : match[1]
  const n = parseInt(raw, 16)
  const lin = (c: number) => {
    const v = c / 255
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
  }
  return 0.2126 * lin((n >> 16) & 255)
    + 0.7152 * lin((n >> 8) & 255)
    + 0.0722 * lin(n & 255)
}

/**
 * White or near-black on a surface, whichever actually reads better.
 *
 * `contrastText` is used elsewhere for the same job and decides by a
 * luminance threshold, which is right for the surfaces it was tuned
 * on — but on a mid-tone palette primary like Sunrise it chose white
 * at 3.6:1, under the 4.5:1 that small uppercase heading text needs.
 * Measuring both candidates and taking the better one cannot do worse
 * for any hue, and it is a local decision here rather than a change to
 * a helper several other surfaces already depend on.
 */
function bestTextOn(surface: string): string {
  const l = _hexLuminance(surface)
  if (l === null) return DARK_INK
  const againstLight = 1.05 / (l + 0.05)
  const againstDark = (l + 0.05) / (_hexLuminance(DARK_INK)! + 0.05)
  return againstLight >= againstDark ? LIGHT_INK : DARK_INK
}

/** Fresh Collective's own teal, for a Collective with no palette. */
const FALLBACK_PRIMARY = '#38A09E'

/**
 * The page's colours, from the Collective's chosen palette.
 *
 * Two different contrast problems, so two different helpers:
 *
 * The **heading** is small text on a near-white page, where several
 * seeded primaries — Sunrise, Snow & Sky — sit at 2–3:1 and would be
 * quietly unreadable. `readableOnWhite` deepens the hue until it
 * clears AA rather than abandoning the tint for grey, so a pale
 * palette still looks like itself.
 *
 * The **feeling card** is the primary used as a surface, which is what
 * palette primaries are chosen for. `contrastText` then picks white or
 * near-black for the text on it by luminance, so a dark teal and a
 * pale sand both come out readable.
 *
 * Pills are the same surface lightened by a translucent white wash
 * rather than a second stored colour — one palette slot, two depths.
 */
export function islandPalette(
  palette: CollectivePaletteMeta | null | undefined,
): IslandPalette {
  // Validated, not merely read. ``paletteHex`` returns the stored
  // value as it is, and a junk value would reach CSS as an invalid
  // colour — which renders as nothing at all, so the feeling card
  // would lose its background rather than look slightly wrong.
  const stored = paletteHex('primary', palette)
  const primary = stored && isValidHex(stored) ? stored : FALLBACK_PRIMARY
  // A touch deeper than the raw primary: a large field of a bright
  // palette hue is louder than the same hue on a small card.
  const surface = darkenHex(primary, 0.08)
  const onSurface = bestTextOn(surface)
  const lightText = onSurface === LIGHT_INK

  return {
    headingColor: readableOnWhite(primary),
    // A touch deeper than the raw primary: a large field of a bright
    // palette hue is louder than the same hue on a small card.
    cardBackground: surface,
    cardText: onSurface,
    // Lifted off the card with white on a dark surface and with
    // near-black on a light one, so the pill reads as raised either
    // way without a second palette slot.
    pillBackground: lightText ? 'rgba(255,255,255,0.14)' : 'rgba(15,23,42,0.08)',
    pillBorder: lightText ? 'rgba(255,255,255,0.28)' : 'rgba(15,23,42,0.16)',
    pillText: onSurface,
    fromPalette: Boolean(stored && isValidHex(stored)),
  }
}

// ---------------------------------------------------------------------------
// Atmosphere
// ---------------------------------------------------------------------------

/**
 * The feeling words for this place.
 *
 * `atmosphere_labels` — the Collective's own atmosphere, resolved from
 * `atmosphere_keys` — is what the Collective header already shows a
 * member, so it is what a member recognises as the feeling of their
 * place.
 *
 * An island's `preferred_atmospheres` is a *recommendation* list used
 * to match creators to Locations during Build Your Collective, not a
 * description of the island, and it is not member-facing anywhere
 * today. It is used only as a fallback, so a Collective whose creator
 * never chose an atmosphere still gets a meaningful card rather than
 * an empty one.
 *
 * Empty means the caller omits the card.
 */
export function atmosphereWords(
  collectiveLabels: readonly string[] | null | undefined,
  islandFallback?: readonly string[] | null,
): string[] {
  const own = (collectiveLabels ?? []).map((l) => l.trim()).filter(Boolean)
  if (own.length > 0) return own
  return (islandFallback ?? []).map((l) => l.trim()).filter(Boolean)
}
