/**
 * Fallback atmospheric colour system for real-world Places.
 *
 * Rendered on Discover Places location cards when a Place does NOT
 * yet have curated artwork configured in World Management. When
 * real artwork exists it always takes precedence — this palette
 * exists so an unconfigured Place still reads as considered rather
 * than empty.
 *
 * The palette is deliberately atmospheric — deep, monochromatic
 * gradients drawn from broad landscape families (ocean, mountain,
 * forest, coast, urban stone). It is NOT symbolic: assignment is
 * deterministic per Place slug, not derived from the Place's real
 * geography or climate. The goal is a rich, varied fallback that
 * makes each location easy to distinguish visually — not to claim
 * that "coastal locations should feel like ocean." That kind of
 * per-Place identity comes from real artwork later.
 *
 * Kept in ``lib/`` (not inside a prototype folder) so the module
 * outlives the current Discover Places prototype and can be used
 * by the production Discover Places surface when it ships.
 */

export interface Atmosphere {
  /** Top-left of the header gradient — the lighter tone. */
  from: string
  /** Bottom-right — the deeper tone. */
  to:   string
}

/**
 * Eight richer atmospheres, each a plausible watercolour-evening
 * variation on a single hue family. Enough variety to avoid
 * obvious repetition across a page of ~15–50 Places while staying
 * within one shared visual vocabulary. All read comfortably beneath
 * the shared PageHero navy.
 */
export const PLACE_ATMOSPHERES: readonly Atmosphere[] = [
  { from: '#7DBEB7', to: '#3F7F7C' },   // deep coastal teal
  { from: '#8AA2C0', to: '#4A6688' },   // dusk harbour blue
  { from: '#9EA9B8', to: '#5A6577' },   // slate mist (mountain / stone)
  { from: '#8FA88A', to: '#4F6B4E' },   // forest sage
  { from: '#CFA482', to: '#8B5837' },   // warm coast (sand + coral)
  { from: '#C5A876', to: '#7E5A20' },   // amber inland
  { from: '#94A190', to: '#4F5F52' },   // eucalyptus urban
  { from: '#B9856F', to: '#7C4230' },   // terracotta / rose clay
] as const

/**
 * Softer palette used for "not-yet-active-here" or otherwise
 * intentionally quiet Places. In the current prototype we surface
 * this by mixing each atmosphere towards white; a Place with a
 * hidden or emerging status can carry it. Retained separately so
 * we can adjust it independently later.
 */
const EMERGING_WHITE_MIX = 0.25

/**
 * Deterministic assignment: same slug → same atmosphere across
 * every render. Uses a simple char-code sum modulo palette size —
 * no cryptographic quality needed, just stability.
 */
export function atmosphereForSlug(slug: string, emerging: boolean = false): Atmosphere {
  let hash = 0
  for (let i = 0; i < slug.length; i++) hash += slug.charCodeAt(i)
  const pick = PLACE_ATMOSPHERES[hash % PLACE_ATMOSPHERES.length]
  return emerging
    ? { from: mixWithWhite(pick.from, EMERGING_WHITE_MIX), to: mixWithWhite(pick.to, EMERGING_WHITE_MIX) }
    : pick
}

/**
 * The CSS ``background`` value for the atmospheric card header.
 * Composes three layers, front to back:
 *   1. Morning-light radial highlight in the top-left — adds
 *      dimension without changing the underlying hue.
 *   2. Bottom-edge shadow gradient — subtle depth so the header
 *      doesn't read flat next to the darker PageHero navy above.
 *   3. The atmospheric linear gradient itself.
 */
export function atmosphereBackground(atmosphere: Atmosphere): string {
  return [
    'linear-gradient(180deg, transparent 55%, rgba(0,0,0,0.16) 100%)',
    'radial-gradient(ellipse at 22% 22%, rgba(255,255,255,0.28), transparent 60%)',
    `linear-gradient(150deg, ${atmosphere.from}, ${atmosphere.to})`,
  ].join(', ')
}


// ---------------------------------------------------------------------------
// internals
// ---------------------------------------------------------------------------

function mixWithWhite(hex: string, ratio: number): string {
  const n = parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 0xff
  const g = (n >> 8) & 0xff
  const b = n & 0xff
  const mix = (c: number) => Math.round(c + (255 - c) * ratio)
  return `#${((1 << 24) + (mix(r) << 16) + (mix(g) << 8) + mix(b)).toString(16).slice(1)}`
}
