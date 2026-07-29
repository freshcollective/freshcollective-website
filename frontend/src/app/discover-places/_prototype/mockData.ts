/**
 * PROTOTYPE MOCK DATA — Discover Places (iteration 2)
 * ============================================================
 *
 * TEMPORARY FIXTURE. Not production data. Not connected to the
 * database or /api/places. This file exists so we can prototype
 * the Discover Places page in the browser and evaluate the
 * feeling / hierarchy / scale behaviour before Phase 1 design.
 *
 * Delete this whole `_prototype` folder when the real page ships.
 *
 * Records are deterministic — the same three sets render every
 * refresh so we can compare treatments across a review session.
 *
 * Iteration 2 changes:
 *   * Not-yet-active Places have been removed. Discover Places
 *     celebrates where community is already alive; it should not
 *     name absence.
 *   * `activeCollectives` and `upcomingGatherings` remain on each
 *     record so the component can derive an activity tier
 *     (flourishing / growing / emerging) and a warm character
 *     line — but the raw numbers are no longer surfaced on the
 *     card.
 */

export type PlaceActivity = 'active' | 'emerging'

export interface PlaceMock {
  slug: string
  name: string
  /** The state / territory the Place sits in (e.g. "Victoria"). */
  region: string
  /** ISO-ish state code, kept for possible future grouping. */
  stateCode:
    | 'VIC' | 'NSW' | 'QLD' | 'TAS' | 'SA' | 'WA' | 'NT' | 'ACT'
  /** Poetic descriptor — what the Place FEELS like. */
  livingIdentity: string
  /** Top 3 themes for active; 1–2 for emerging. */
  themes: string[]
  /** Retained for tier + character-line derivation. Not shown as a
   *  raw metric on the card. */
  activeCollectives: number
  upcomingGatherings: number
  activity: PlaceActivity
}

// ---------------------------------------------------------------------------
// Early world — a handful of Places. Enough to show what community-first
// framing feels like at the smallest scale.
// ---------------------------------------------------------------------------
export const EARLY_WORLD: PlaceMock[] = [
  {
    slug: 'byron-bay',
    name: 'Byron Bay',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity:
      'A coastal community grounded in wellbeing, movement and reflection.',
    themes: ['Wellbeing', 'Movement', 'Reflection'],
    activeCollectives: 5,
    upcomingGatherings: 14,
    activity: 'active',
  },
  {
    slug: 'melbourne',
    name: 'Melbourne',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity:
      'A place where creativity, wellbeing and leadership are flourishing.',
    themes: ['Wellbeing', 'Creativity', 'Leadership'],
    activeCollectives: 8,
    upcomingGatherings: 23,
    activity: 'active',
  },
  {
    slug: 'sunshine-coast',
    name: 'Sunshine Coast',
    region: 'Queensland',
    stateCode: 'QLD',
    livingIdentity:
      'Movement, wellbeing and spirituality by the sea.',
    themes: ['Movement', 'Wellbeing', 'Spirituality'],
    activeCollectives: 4,
    upcomingGatherings: 10,
    activity: 'active',
  },
  {
    slug: 'blue-mountains',
    name: 'Blue Mountains',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity:
      'A quiet mountain refuge for reflection and inner work.',
    themes: ['Reflection', 'Inner Work'],
    activeCollectives: 2,
    upcomingGatherings: 3,
    activity: 'emerging',
  },
]

// ---------------------------------------------------------------------------
// Growing world — enough to justify search + theme filters. All Places
// have active community life; the mix leans towards flourishing / growing
// tiers, with a handful of emerging ones for texture.
// ---------------------------------------------------------------------------
export const GROWING_WORLD: PlaceMock[] = [
  {
    slug: 'melbourne',
    name: 'Melbourne',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity:
      'A place where creativity, wellbeing and leadership are flourishing.',
    themes: ['Wellbeing', 'Creativity', 'Leadership'],
    activeCollectives: 8,
    upcomingGatherings: 23,
    activity: 'active',
  },
  {
    slug: 'sydney',
    name: 'Sydney',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity:
      'Where business and inner work meet on the harbour.',
    themes: ['Business', 'Inner Work', 'Leadership'],
    activeCollectives: 7,
    upcomingGatherings: 19,
    activity: 'active',
  },
  {
    slug: 'brisbane',
    name: 'Brisbane',
    region: 'Queensland',
    stateCode: 'QLD',
    livingIdentity:
      'A warm subtropical community exploring creativity and relationships.',
    themes: ['Creativity', 'Relationships', 'Wellbeing'],
    activeCollectives: 6,
    upcomingGatherings: 15,
    activity: 'active',
  },
  {
    slug: 'byron-bay',
    name: 'Byron Bay',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity:
      'A coastal community grounded in wellbeing, movement and reflection.',
    themes: ['Wellbeing', 'Movement', 'Reflection'],
    activeCollectives: 5,
    upcomingGatherings: 14,
    activity: 'active',
  },
  {
    slug: 'sunshine-coast',
    name: 'Sunshine Coast',
    region: 'Queensland',
    stateCode: 'QLD',
    livingIdentity:
      'Movement, wellbeing and spirituality by the sea.',
    themes: ['Movement', 'Wellbeing', 'Spirituality'],
    activeCollectives: 4,
    upcomingGatherings: 10,
    activity: 'active',
  },
  {
    slug: 'blue-mountains',
    name: 'Blue Mountains',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity:
      'A quiet mountain refuge for reflection and inner work.',
    themes: ['Reflection', 'Inner Work', 'Creativity'],
    activeCollectives: 3,
    upcomingGatherings: 6,
    activity: 'active',
  },
  {
    slug: 'perth',
    name: 'Perth',
    region: 'Western Australia',
    stateCode: 'WA',
    livingIdentity:
      'Leadership and wellbeing on the western edge.',
    themes: ['Leadership', 'Wellbeing', 'Business'],
    activeCollectives: 3,
    upcomingGatherings: 7,
    activity: 'active',
  },
  {
    slug: 'northern-rivers',
    name: 'Northern Rivers',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity:
      'Spirituality, wellbeing and movement across the hinterland.',
    themes: ['Spirituality', 'Wellbeing', 'Movement'],
    activeCollectives: 4,
    upcomingGatherings: 9,
    activity: 'active',
  },
  {
    slug: 'yarra-valley',
    name: 'Yarra Valley',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity:
      'Wellbeing and creativity among the vineyards.',
    themes: ['Wellbeing', 'Creativity', 'Relationships'],
    activeCollectives: 3,
    upcomingGatherings: 8,
    activity: 'active',
  },
  {
    slug: 'hobart',
    name: 'Hobart',
    region: 'Tasmania',
    stateCode: 'TAS',
    livingIdentity:
      'Inner work and creativity at the edge of the world.',
    themes: ['Inner Work', 'Creativity'],
    activeCollectives: 2,
    upcomingGatherings: 4,
    activity: 'emerging',
  },
  {
    slug: 'adelaide',
    name: 'Adelaide',
    region: 'South Australia',
    stateCode: 'SA',
    livingIdentity:
      'A calm city exploring wellbeing, reflection and creativity.',
    themes: ['Wellbeing', 'Reflection'],
    activeCollectives: 2,
    upcomingGatherings: 3,
    activity: 'emerging',
  },
  {
    slug: 'fremantle',
    name: 'Fremantle',
    region: 'Western Australia',
    stateCode: 'WA',
    livingIdentity:
      'Creativity and relationships by the port.',
    themes: ['Creativity', 'Relationships'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },
  {
    slug: 'newcastle',
    name: 'Newcastle',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity:
      'Movement and wellbeing on the coast.',
    themes: ['Movement', 'Wellbeing'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },
  {
    slug: 'mornington-peninsula',
    name: 'Mornington Peninsula',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity:
      'Coastal reflection and quiet wellbeing.',
    themes: ['Reflection', 'Wellbeing'],
    activeCollectives: 1,
    upcomingGatherings: 1,
    activity: 'emerging',
  },
  {
    slug: 'illawarra',
    name: 'Illawarra',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity:
      'Movement, wellbeing and creativity along the coast.',
    themes: ['Movement', 'Wellbeing', 'Creativity'],
    activeCollectives: 3,
    upcomingGatherings: 6,
    activity: 'active',
  },
]

// ---------------------------------------------------------------------------
// Established world — the stress-test for search, filters and grouping.
// Only Places with real community life. Tier grouping (Flourishing /
// Growing / Emerging) is derived at render time from activeCollectives.
// ---------------------------------------------------------------------------
export const ESTABLISHED_WORLD: PlaceMock[] = [
  // ── Victoria ──────────────────────────────────────────────────────
  {
    slug: 'melbourne',
    name: 'Melbourne',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity: 'A place where creativity, wellbeing and leadership are flourishing.',
    themes: ['Wellbeing', 'Creativity', 'Leadership'],
    activeCollectives: 12,
    upcomingGatherings: 34,
    activity: 'active',
  },
  {
    slug: 'geelong',
    name: 'Geelong',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity: 'A community exploring creativity and inner work.',
    themes: ['Creativity', 'Inner Work', 'Wellbeing'],
    activeCollectives: 4,
    upcomingGatherings: 9,
    activity: 'active',
  },
  {
    slug: 'mornington-peninsula',
    name: 'Mornington Peninsula',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity: 'Coastal reflection, movement and quiet leadership.',
    themes: ['Reflection', 'Movement', 'Leadership'],
    activeCollectives: 5,
    upcomingGatherings: 11,
    activity: 'active',
  },
  {
    slug: 'ballarat',
    name: 'Ballarat',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity: 'Inner work and reflection in the goldfields.',
    themes: ['Inner Work', 'Reflection', 'Creativity'],
    activeCollectives: 3,
    upcomingGatherings: 6,
    activity: 'active',
  },
  {
    slug: 'bendigo',
    name: 'Bendigo',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity: 'A small community, gathering into rhythm.',
    themes: ['Reflection', 'Wellbeing'],
    activeCollectives: 2,
    upcomingGatherings: 4,
    activity: 'emerging',
  },
  {
    slug: 'yarra-valley',
    name: 'Yarra Valley',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity: 'Wellbeing and creativity among the vineyards.',
    themes: ['Wellbeing', 'Creativity', 'Relationships'],
    activeCollectives: 3,
    upcomingGatherings: 8,
    activity: 'active',
  },
  {
    slug: 'daylesford',
    name: 'Daylesford',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity: 'Springs country — wellbeing, spirituality and reflection.',
    themes: ['Wellbeing', 'Spirituality', 'Reflection'],
    activeCollectives: 4,
    upcomingGatherings: 10,
    activity: 'active',
  },
  {
    slug: 'bellarine-peninsula',
    name: 'Bellarine Peninsula',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity: 'A small community exploring wellbeing and reflection.',
    themes: ['Wellbeing', 'Reflection'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },
  {
    slug: 'great-ocean-road',
    name: 'Great Ocean Road',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity: 'Movement and reflection along the coast.',
    themes: ['Movement', 'Reflection'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },
  {
    slug: 'warrnambool',
    name: 'Warrnambool',
    region: 'Victoria',
    stateCode: 'VIC',
    livingIdentity: 'A small coastal community grounded in wellbeing.',
    themes: ['Wellbeing', 'Reflection'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },

  // ── New South Wales ───────────────────────────────────────────────
  {
    slug: 'sydney',
    name: 'Sydney',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'Where business and inner work meet on the harbour.',
    themes: ['Business', 'Inner Work', 'Leadership'],
    activeCollectives: 11,
    upcomingGatherings: 28,
    activity: 'active',
  },
  {
    slug: 'byron-bay',
    name: 'Byron Bay',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'A coastal community grounded in wellbeing, movement and reflection.',
    themes: ['Wellbeing', 'Movement', 'Reflection'],
    activeCollectives: 9,
    upcomingGatherings: 26,
    activity: 'active',
  },
  {
    slug: 'blue-mountains',
    name: 'Blue Mountains',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'A quiet mountain refuge for reflection and inner work.',
    themes: ['Reflection', 'Inner Work', 'Creativity'],
    activeCollectives: 5,
    upcomingGatherings: 12,
    activity: 'active',
  },
  {
    slug: 'newcastle',
    name: 'Newcastle',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'Movement, wellbeing and creativity by the coast.',
    themes: ['Movement', 'Wellbeing', 'Creativity'],
    activeCollectives: 4,
    upcomingGatherings: 9,
    activity: 'active',
  },
  {
    slug: 'wollongong',
    name: 'Wollongong',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'A small community exploring wellbeing and movement.',
    themes: ['Wellbeing', 'Movement'],
    activeCollectives: 2,
    upcomingGatherings: 3,
    activity: 'emerging',
  },
  {
    slug: 'central-coast',
    name: 'Central Coast',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'Coastal wellbeing and parenting communities finding each other.',
    themes: ['Wellbeing', 'Parenting', 'Relationships'],
    activeCollectives: 3,
    upcomingGatherings: 7,
    activity: 'active',
  },
  {
    slug: 'southern-highlands',
    name: 'Southern Highlands',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'Reflection and inner work in the highlands.',
    themes: ['Reflection', 'Inner Work'],
    activeCollectives: 2,
    upcomingGatherings: 5,
    activity: 'emerging',
  },
  {
    slug: 'northern-rivers',
    name: 'Northern Rivers',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'Spirituality, wellbeing and movement across the hinterland.',
    themes: ['Spirituality', 'Wellbeing', 'Movement'],
    activeCollectives: 4,
    upcomingGatherings: 11,
    activity: 'active',
  },
  {
    slug: 'hunter-valley',
    name: 'Hunter Valley',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'A small community exploring reflection and relationships.',
    themes: ['Reflection', 'Relationships'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },
  {
    slug: 'coffs-harbour',
    name: 'Coffs Harbour',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'A small community exploring wellbeing and movement.',
    themes: ['Wellbeing', 'Movement'],
    activeCollectives: 1,
    upcomingGatherings: 1,
    activity: 'emerging',
  },
  {
    slug: 'illawarra',
    name: 'Illawarra',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'Movement, wellbeing and creativity along the coast.',
    themes: ['Movement', 'Wellbeing', 'Creativity'],
    activeCollectives: 3,
    upcomingGatherings: 6,
    activity: 'active',
  },
  {
    slug: 'ballina',
    name: 'Ballina',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'A small community exploring wellbeing and movement.',
    themes: ['Wellbeing', 'Movement'],
    activeCollectives: 2,
    upcomingGatherings: 3,
    activity: 'emerging',
  },
  {
    slug: 'lismore',
    name: 'Lismore',
    region: 'New South Wales',
    stateCode: 'NSW',
    livingIdentity: 'A small community exploring spirituality and reflection.',
    themes: ['Spirituality', 'Reflection'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },

  // ── Queensland ────────────────────────────────────────────────────
  {
    slug: 'brisbane',
    name: 'Brisbane',
    region: 'Queensland',
    stateCode: 'QLD',
    livingIdentity: 'A warm subtropical community exploring creativity and relationships.',
    themes: ['Creativity', 'Relationships', 'Wellbeing'],
    activeCollectives: 8,
    upcomingGatherings: 18,
    activity: 'active',
  },
  {
    slug: 'sunshine-coast',
    name: 'Sunshine Coast',
    region: 'Queensland',
    stateCode: 'QLD',
    livingIdentity: 'Movement, wellbeing and spirituality by the sea.',
    themes: ['Movement', 'Wellbeing', 'Spirituality'],
    activeCollectives: 7,
    upcomingGatherings: 17,
    activity: 'active',
  },
  {
    slug: 'gold-coast',
    name: 'Gold Coast',
    region: 'Queensland',
    stateCode: 'QLD',
    livingIdentity: 'Business, leadership and movement in the sun.',
    themes: ['Business', 'Leadership', 'Movement'],
    activeCollectives: 5,
    upcomingGatherings: 12,
    activity: 'active',
  },
  {
    slug: 'noosa',
    name: 'Noosa',
    region: 'Queensland',
    stateCode: 'QLD',
    livingIdentity: 'Reflection and wellbeing on the northern beaches.',
    themes: ['Reflection', 'Wellbeing', 'Spirituality'],
    activeCollectives: 3,
    upcomingGatherings: 8,
    activity: 'active',
  },
  {
    slug: 'cairns',
    name: 'Cairns',
    region: 'Queensland',
    stateCode: 'QLD',
    livingIdentity: 'A small community exploring movement and spirituality.',
    themes: ['Movement', 'Spirituality'],
    activeCollectives: 2,
    upcomingGatherings: 3,
    activity: 'emerging',
  },
  {
    slug: 'toowoomba',
    name: 'Toowoomba',
    region: 'Queensland',
    stateCode: 'QLD',
    livingIdentity: 'A small community exploring reflection and parenting.',
    themes: ['Reflection', 'Parenting'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },
  {
    slug: 'sunshine-hinterland',
    name: 'Sunshine Hinterland',
    region: 'Queensland',
    stateCode: 'QLD',
    livingIdentity: 'A small community exploring spirituality and reflection.',
    themes: ['Spirituality', 'Reflection'],
    activeCollectives: 2,
    upcomingGatherings: 3,
    activity: 'emerging',
  },
  {
    slug: 'scenic-rim',
    name: 'Scenic Rim',
    region: 'Queensland',
    stateCode: 'QLD',
    livingIdentity: 'A small community exploring reflection and wellbeing.',
    themes: ['Reflection', 'Wellbeing'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },

  // ── Tasmania ──────────────────────────────────────────────────────
  {
    slug: 'hobart',
    name: 'Hobart',
    region: 'Tasmania',
    stateCode: 'TAS',
    livingIdentity: 'Inner work and creativity at the edge of the world.',
    themes: ['Inner Work', 'Creativity', 'Reflection'],
    activeCollectives: 4,
    upcomingGatherings: 9,
    activity: 'active',
  },
  {
    slug: 'launceston',
    name: 'Launceston',
    region: 'Tasmania',
    stateCode: 'TAS',
    livingIdentity: 'A small community exploring reflection and inner work.',
    themes: ['Reflection', 'Inner Work'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },

  // ── South Australia ───────────────────────────────────────────────
  {
    slug: 'adelaide',
    name: 'Adelaide',
    region: 'South Australia',
    stateCode: 'SA',
    livingIdentity: 'A calm city exploring wellbeing, reflection and creativity.',
    themes: ['Wellbeing', 'Reflection', 'Creativity'],
    activeCollectives: 5,
    upcomingGatherings: 13,
    activity: 'active',
  },
  {
    slug: 'adelaide-hills',
    name: 'Adelaide Hills',
    region: 'South Australia',
    stateCode: 'SA',
    livingIdentity: 'Reflection and spirituality in the hills.',
    themes: ['Reflection', 'Spirituality', 'Wellbeing'],
    activeCollectives: 3,
    upcomingGatherings: 7,
    activity: 'active',
  },
  {
    slug: 'barossa-valley',
    name: 'Barossa Valley',
    region: 'South Australia',
    stateCode: 'SA',
    livingIdentity: 'A small community exploring relationships and reflection.',
    themes: ['Relationships', 'Reflection'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },
  {
    slug: 'fleurieu-peninsula',
    name: 'Fleurieu Peninsula',
    region: 'South Australia',
    stateCode: 'SA',
    livingIdentity: 'A small community exploring movement and wellbeing.',
    themes: ['Movement', 'Wellbeing'],
    activeCollectives: 1,
    upcomingGatherings: 1,
    activity: 'emerging',
  },

  // ── Western Australia ─────────────────────────────────────────────
  {
    slug: 'perth',
    name: 'Perth',
    region: 'Western Australia',
    stateCode: 'WA',
    livingIdentity: 'Leadership and wellbeing on the western edge.',
    themes: ['Leadership', 'Wellbeing', 'Business'],
    activeCollectives: 6,
    upcomingGatherings: 14,
    activity: 'active',
  },
  {
    slug: 'fremantle',
    name: 'Fremantle',
    region: 'Western Australia',
    stateCode: 'WA',
    livingIdentity: 'Creativity, relationships and community by the port.',
    themes: ['Creativity', 'Relationships', 'Wellbeing'],
    activeCollectives: 4,
    upcomingGatherings: 10,
    activity: 'active',
  },
  {
    slug: 'margaret-river',
    name: 'Margaret River',
    region: 'Western Australia',
    stateCode: 'WA',
    livingIdentity: 'Reflection, spirituality and movement in the south-west.',
    themes: ['Reflection', 'Spirituality', 'Movement'],
    activeCollectives: 3,
    upcomingGatherings: 7,
    activity: 'active',
  },
  {
    slug: 'albany',
    name: 'Albany',
    region: 'Western Australia',
    stateCode: 'WA',
    livingIdentity: 'A small community exploring reflection and wellbeing.',
    themes: ['Reflection', 'Wellbeing'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },

  // ── Northern Territory ────────────────────────────────────────────
  {
    slug: 'darwin',
    name: 'Darwin',
    region: 'Northern Territory',
    stateCode: 'NT',
    livingIdentity: 'A small community exploring spirituality and relationships.',
    themes: ['Spirituality', 'Relationships'],
    activeCollectives: 2,
    upcomingGatherings: 4,
    activity: 'emerging',
  },
  {
    slug: 'alice-springs',
    name: 'Alice Springs',
    region: 'Northern Territory',
    stateCode: 'NT',
    livingIdentity: 'A small community exploring reflection and spirituality.',
    themes: ['Reflection', 'Spirituality'],
    activeCollectives: 1,
    upcomingGatherings: 2,
    activity: 'emerging',
  },

  // ── Australian Capital Territory ──────────────────────────────────
  {
    slug: 'canberra',
    name: 'Canberra',
    region: 'Australian Capital Territory',
    stateCode: 'ACT',
    livingIdentity: 'Leadership, inner work and reflection in the capital.',
    themes: ['Leadership', 'Inner Work', 'Reflection'],
    activeCollectives: 4,
    upcomingGatherings: 9,
    activity: 'active',
  },
]
