/**
 * PROTOTYPE MOCK DATA — Ways to Connect
 * ============================================================
 *
 * TEMPORARY FIXTURE. Not production data. Not connected to any
 * introduction recommendation service (which does not exist yet).
 *
 * The three outgoing candidates below deliberately cover the three
 * intent types the real recommendation engine will produce:
 *
 *   right-now         — a timely shared moment (e.g. attending an
 *                       upcoming Gathering together, freshly-joined
 *                       Collective, just-started Pathway)
 *   shared-journey    — accumulated common ground (shared
 *                       Collective + Pathway + theme, or shared
 *                       Place, over time)
 *   thoughtful        — a curated introduction. Not the strongest
 *                       overlap; someone the member is likely to
 *                       enjoy knowing based on a considered blend
 *                       of shared experiences.
 *
 * The one incoming introduction request lets the demo show what
 * arriving on the receiving end feels like without needing a
 * second signed-in browser.
 *
 * Delete this whole `_prototype` folder when the real Ways to
 * Connect surface ships and the recommendation engine takes over.
 */

export type IntentType = 'right-now' | 'shared-journey' | 'thoughtful'

/** Kinds of shared common ground surfaced on introduction cards.
 *  The `emoji` lives here (not on the card layout) so the same
 *  mapping is reused between the card list and the conversation's
 *  intro panel. */
export type SharedKind =
  | 'collective'
  | 'pathway'
  | 'place'
  | 'gathering'
  | 'theme'

export interface SharedItem {
  kind: SharedKind
  label: string
}

export interface MockIntroduction {
  /** Stable id for React keys + mock URL slugs. */
  id: string
  /** The other person's display name. Given name only for warmth. */
  otherName: string
  /** Which intent bucket the recommendation engine would have
   *  placed this in. Not surfaced as a member-facing badge — the
   *  shared items themselves signal timeliness / accumulation /
   *  curation. */
  intent: IntentType
  sharedItems: SharedItem[]
}

/**
 * Semantic icon per shared-item kind. Used in the conversation's
 * permanent intro panel; the card list uses simple bullet dots.
 */
export const SHARED_ICON: Record<SharedKind, string> = {
  collective: '🌿',
  pathway:    '🧭',
  place:      '📍',
  gathering:  '🕯️',
  theme:      '✿',
}


// ---------------------------------------------------------------------------
// Outgoing candidates — three, deliberately one per intent type.
// ---------------------------------------------------------------------------

export const OUTGOING_INTRODUCTIONS: MockIntroduction[] = [
  {
    // Right now — a real, dated timely moment shared with the reader.
    id: 'intro-right-now-sarah',
    otherName: 'Sarah',
    intent: 'right-now',
    sharedItems: [
      { kind: 'collective', label: 'The Grove' },
      { kind: 'pathway',    label: 'Life in Alignment' },
      { kind: 'gathering',  label: "You're both attending Tuesday night's Gathering" },
    ],
  },
  {
    // Shared journey — accumulated overlap that has held over time.
    id: 'intro-shared-journey-emma',
    otherName: 'Emma',
    intent: 'shared-journey',
    sharedItems: [
      { kind: 'collective', label: 'The Grove' },
      { kind: 'collective', label: 'EMBODY' },
      { kind: 'pathway',    label: 'Life in Alignment' },
      { kind: 'place',      label: 'Melbourne' },
    ],
  },
  {
    // Thoughtful — not the strongest overlap, but a considered
    // introduction: shared theme + Place, no shared Collective yet.
    id: 'intro-thoughtful-anna',
    otherName: 'Anna',
    intent: 'thoughtful',
    sharedItems: [
      { kind: 'theme', label: 'Reflection' },
      { kind: 'theme', label: 'Creativity' },
      { kind: 'place', label: 'Byron Bay' },
    ],
  },
]


// ---------------------------------------------------------------------------
// One incoming request — lets the demo show what accepting an
// introduction on the receiving side feels like.
// ---------------------------------------------------------------------------

export const INCOMING_INTRODUCTION: MockIntroduction = {
  id: 'intro-incoming-james',
  otherName: 'James',
  intent: 'shared-journey',
  sharedItems: [
    { kind: 'collective', label: 'EMBODY' },
    { kind: 'pathway',    label: 'Life in Alignment' },
    { kind: 'place',      label: 'Melbourne' },
  ],
}
