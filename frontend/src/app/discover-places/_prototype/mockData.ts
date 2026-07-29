/**
 * PROTOTYPE MOCK DATA — Discover Places (iteration 3)
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
 * Iteration 3 changes (see also DiscoverPlacesPrototype.tsx):
 *   * Records now carry a `country` field. Every card renders
 *     "Region, Country" consistently — no special-case suppression
 *     for a hand-picked list of Australian capitals — so the page
 *     works for an international audience.
 *   * The Established set gains a handful of international
 *     examples (Auckland, Bali, Edinburgh, Portland, Vancouver)
 *     to stress-test the design outside Australia.
 *   * Fixture order is no longer meaningful — the component sorts
 *     every visible group alphabetically at render time.
 */

export type PlaceActivity = 'active' | 'emerging'

export interface PlaceMock {
  slug: string
  name: string
  /** The state, region or province the Place sits in
   *  (e.g. "Victoria", "British Columbia", "Scotland"). */
  region: string
  /** The country the Place sits in
   *  (e.g. "Australia", "Canada", "United Kingdom"). */
  country: string
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
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
    country: 'Australia',
    livingIdentity: 'Leadership, inner work and reflection in the capital.',
    themes: ['Leadership', 'Inner Work', 'Reflection'],
    activeCollectives: 4,
    upcomingGatherings: 9,
    activity: 'active',
  },

  // ── International — a small stress-test set for global readiness ─
  // Not exhaustive by design. Enough international examples for the
  // layout, labels and grouping to be evaluated outside Australia.
  {
    slug: 'auckland',
    name: 'Auckland',
    region: 'Auckland',
    country: 'New Zealand',
    livingIdentity: 'A harbour city exploring wellbeing, creativity and leadership.',
    themes: ['Wellbeing', 'Creativity', 'Leadership'],
    activeCollectives: 6,
    upcomingGatherings: 15,
    activity: 'active',
  },
  {
    slug: 'bali',
    name: 'Bali',
    region: 'Bali',
    country: 'Indonesia',
    livingIdentity: 'Spirituality, wellbeing and movement across the island.',
    themes: ['Spirituality', 'Wellbeing', 'Movement'],
    activeCollectives: 7,
    upcomingGatherings: 18,
    activity: 'active',
  },
  {
    slug: 'edinburgh',
    name: 'Edinburgh',
    region: 'Scotland',
    country: 'United Kingdom',
    livingIdentity: 'Inner work, reflection and creativity in the old town.',
    themes: ['Inner Work', 'Reflection', 'Creativity'],
    activeCollectives: 4,
    upcomingGatherings: 10,
    activity: 'active',
  },
  {
    slug: 'portland',
    name: 'Portland',
    region: 'Oregon',
    country: 'United States',
    livingIdentity: 'Creativity, movement and reflection in the Pacific Northwest.',
    themes: ['Creativity', 'Movement', 'Reflection'],
    activeCollectives: 5,
    upcomingGatherings: 12,
    activity: 'active',
  },
  {
    slug: 'vancouver',
    name: 'Vancouver',
    region: 'British Columbia',
    country: 'Canada',
    livingIdentity: 'A coastal city grounded in movement, wellbeing and leadership.',
    themes: ['Movement', 'Wellbeing', 'Leadership'],
    activeCollectives: 6,
    upcomingGatherings: 14,
    activity: 'active',
  },
]
