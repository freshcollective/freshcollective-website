/**
 * Artwork for a Collective Home tile.
 *
 * Phase 1 used the Collective's cover for every tile, which made five
 * doorways look like five copies of the same card, and a Collective
 * with no cover got the same teal gradient five times over. The fix is
 * that each tile should look like the place it leads to, before any
 * creator has configured anything.
 *
 * Three steps, in order:
 *
 *   1. the creator's own image for that tile;
 *   2. Fresh Collective's existing platform artwork for that member
 *      area — real, art-directed photography that is already uploaded
 *      and already public;
 *   3. a gradient derived from the Collective's own palette, varied
 *      per tile.
 *
 * Step 2 is reuse, not new assets. ``homepage_gatherings``,
 * ``homepage_pathways`` and ``homepage_conversations`` were authored
 * for exactly these areas — the platform-artwork registry describes
 * each as "also used as the hero image on the dedicated … page when
 * built". This is that page. Nothing is copied or regenerated; the
 * tiles point at the same public URLs the homepage already serves.
 */

import { darkenHex, rgbaFromHex } from './collectivePalette.ts'
import type { CollectivePaletteMeta } from './collectivePalette.ts'
import { getCollectiveCoverStyle } from './coverArt.ts'

/**
 * Tile → platform artwork key.
 *
 * Chosen from what each asset actually depicts, per its description in
 * the artwork registry, not from a name that happens to match:
 * ``homepage_friction_conversation`` is specified as "genuine human
 * connection — a circle, a shared moment, people talking. NOT an
 * interface, NOT a landscape", which is what a Members doorway wants;
 * ``member_onboarding_welcome`` is "the first moment of arrival — a
 * horizon, an opening in the world", which suits About.
 *
 * A key that has no artwork uploaded simply falls through to the
 * themed gradient, so this map can never leave a tile blank.
 */
export const TILE_PLATFORM_ARTWORK: Record<string, string> = {
  gatherings: 'homepage_gatherings',
  pathways: 'homepage_pathways',
  conversations: 'homepage_conversations',
  messages: 'homepage_ways_to_connect',
  members: 'homepage_friction_conversation',
  about: 'member_onboarding_welcome',
}

/**
 * Deterministic per-tile variation, so the five gradients on one Home
 * differ from each other while every one of them is unmistakably this
 * Collective's colours. The numbers are an angle and two mixing
 * weights — arbitrary but fixed, which is the point: the same tile in
 * the same Collective looks the same on every render and every device.
 */
const TILE_VARIANT: Record<string, { angle: number; from: number; to: number }> = {
  gatherings:    { angle: 145, from: 0.00, to: 0.28 },
  pathways:      { angle: 165, from: 0.16, to: 0.04 },
  conversations: { angle: 125, from: 0.08, to: 0.34 },
  messages:      { angle: 185, from: 0.22, to: 0.10 },
  members:       { angle: 205, from: 0.04, to: 0.22 },
  about:         { angle: 115, from: 0.30, to: 0.12 },
}

const FALLBACK_VARIANT = { angle: 150, from: 0.05, to: 0.25 }

/**
 * A CSS ``background`` for a tile with no photograph behind it.
 *
 * Built from the Collective's own palette, so The Grove's warm orange
 * Home never looks like EMBODY's. Two palette slots are blended at
 * per-tile weights and a soft highlight is laid over the top, which
 * keeps the result from reading as a flat colour swatch.
 *
 * Falls back to the platform's per-slug gradient when a Collective has
 * chosen no palette — still deterministic, still distinct between
 * Collectives, just not palette-derived because there is no palette.
 */
export function tileFallbackBackground(
  tileKey: string,
  palette: CollectivePaletteMeta | null | undefined,
  slug: string,
): string {
  const hexes = palette?.palette
  const variant = TILE_VARIANT[tileKey] ?? FALLBACK_VARIANT

  if (!hexes?.primary || !hexes?.secondary) {
    return getCollectiveCoverStyle(slug).background
  }

  const from = darkenHex(hexes.primary, variant.from)
  const to = darkenHex(hexes.secondary || hexes.primary, variant.to)
  const highlight = rgbaFromHex(hexes.accent || hexes.secondary, 0.22)

  return [
    // A soft off-centre highlight first (topmost layer) so the panel
    // has depth rather than reading as a flat two-stop wash.
    `radial-gradient(ellipse at 24% 18%, ${highlight}, transparent 62%)`,
    `linear-gradient(${variant.angle}deg, ${from}, ${to})`,
  ].join(', ')
}

/**
 * The image a tile should show, or ``null`` to use the themed
 * gradient. ``platformArtwork`` maps an artwork key to a resolved URL
 * — the caller supplies it from the public platform-artwork map it
 * already fetches.
 */
export function tileImageUrl(
  tileKey: string,
  creatorImageUrl: string | null | undefined,
  platformArtwork: (key: string) => string | null,
): string | null {
  if (creatorImageUrl) return creatorImageUrl
  const artworkKey = TILE_PLATFORM_ARTWORK[tileKey]
  return artworkKey ? platformArtwork(artworkKey) : null
}
