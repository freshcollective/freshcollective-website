/**
 * World / collective mapping layer.
 *
 * Defines the three founding constellations (The Grove, EMBODY, Life in
 * Alignment) and the symbolic elements each one adds to a member's personal
 * world. Slugs match the intended member-facing space route (`/spaces/{slug}`).
 * If a space has not been seeded yet, its constellation still renders in the
 * sky — the link just falls through to the standard 404 until the space
 * exists. This is intentional: the sky is the map, and the map is allowed
 * to describe territory that is still being made.
 *
 * Structure is deliberately data-only so future collectives, pathways, and
 * activity signals can plug in without touching component code.
 */

export type WorldElementType =
  | 'trees'
  | 'garden'
  | 'water'
  | 'path'
  | 'sunrise'
  | 'mountain'
  | 'fire'

export interface ConstellationPoint {
  /** 0..1 within the sky container (left → right). */
  x: number
  /** 0..1 within the sky container (top → bottom). */
  y: number
}

export interface ConstellationDef {
  /**
   * Symbolic id — used to match a member's memberships to the constellation
   * for the "isMember" glow and for element contribution. Independent of
   * the space slug so the visual identity doesn't churn if a space is
   * renamed or reslugged.
   */
  id: string
  name: string
  tagline: string
  /**
   * The route this constellation links to, or `null` if the collective is
   * still forming and has no member-facing home yet. Non-null constellations
   * become clickable in the sky; null constellations render as a soft
   * "forming" whisper instead.
   */
  href: string | null
  /**
   * Space slugs that count as membership in this collective. Multiple
   * slugs are supported so a rename doesn't break world-element mapping.
   */
  memberSlugs: ReadonlyArray<string>
  /** Core star + connective-line colour. */
  accent: string
  /** rgba glow used behind the constellation name label. */
  glow: string
  points: ReadonlyArray<ConstellationPoint>
  /** Pairs of point indices to draw a line between. */
  lines: ReadonlyArray<[number, number]>
  worldElements: ReadonlyArray<WorldElementType>
}

export const COLLECTIVES: ReadonlyArray<ConstellationDef> = [
  {
    id: 'grove',
    name: 'The Grove',
    tagline: 'Roots, ground, and how you meet the world.',
    href: '/spaces/the-natural-leader-hub',
    memberSlugs: ['the-natural-leader-hub', 'grove', 'the-grove'],
    accent: '#8DE8E6',
    glow: 'rgba(141, 232, 230, 0.55)',
    points: [
      { x: 0.08, y: 0.28 },
      { x: 0.16, y: 0.38 },
      { x: 0.13, y: 0.52 },
      { x: 0.24, y: 0.46 },
      { x: 0.27, y: 0.60 },
    ],
    lines: [[0, 1], [1, 2], [1, 3], [3, 4]],
    worldElements: ['trees', 'garden'],
  },
  {
    id: 'embody',
    name: 'EMBODY',
    tagline: 'The intelligence of the body — movement, breath, presence.',
    href: '/spaces/embody',
    memberSlugs: ['embody'],
    accent: '#55D7D2',
    glow: 'rgba(85, 215, 210, 0.55)',
    points: [
      { x: 0.42, y: 0.22 },
      { x: 0.48, y: 0.34 },
      { x: 0.55, y: 0.28 },
      { x: 0.52, y: 0.48 },
      { x: 0.60, y: 0.42 },
      { x: 0.58, y: 0.58 },
    ],
    lines: [[0, 1], [1, 2], [1, 3], [2, 4], [3, 5], [4, 5]],
    worldElements: ['water', 'path'],
  },
  {
    id: 'life-in-alignment',
    name: 'Life in Alignment',
    tagline: 'Bringing values, work, and rest into rhythm.',
    // No space seeded yet — rendered as a "forming" constellation. When
    // the space is created, set href + memberSlugs and this becomes live.
    href: null,
    memberSlugs: ['life-in-alignment', 'lia'],
    accent: '#E7C65A',
    glow: 'rgba(231, 198, 90, 0.55)',
    points: [
      { x: 0.73, y: 0.26 },
      { x: 0.80, y: 0.36 },
      { x: 0.87, y: 0.30 },
      { x: 0.78, y: 0.50 },
      { x: 0.88, y: 0.54 },
    ],
    lines: [[0, 1], [1, 2], [1, 3], [3, 4]],
    worldElements: ['sunrise', 'mountain', 'fire'],
  },
]

/**
 * True when the member belongs to any of the collective's known slugs.
 * Handles renames by accepting the set of slugs a collective claims.
 */
export function isMemberOf(
  def: ConstellationDef,
  memberSlugs: ReadonlyArray<string>,
): boolean {
  return def.memberSlugs.some((s) => memberSlugs.includes(s))
}

/**
 * Union of every WorldElementType contributed by the collectives the member
 * belongs to. Order is preserved by COLLECTIVES declaration + within-array
 * declaration, so the personal island composes deterministically.
 */
export function collectWorldElementsFor(
  memberSlugs: ReadonlyArray<string>,
): WorldElementType[] {
  const seen = new Set<WorldElementType>()
  const out: WorldElementType[] = []
  for (const c of COLLECTIVES) {
    if (!isMemberOf(c, memberSlugs)) continue
    for (const el of c.worldElements) {
      if (!seen.has(el)) {
        seen.add(el)
        out.push(el)
      }
    }
  }
  return out
}
