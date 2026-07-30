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
   *  placed this in. Not surfaced as a member-facing badge —
   *  turned into a gentle human eyebrow at the top of the card. */
  intent: IntentType
  /** A short natural-language sentence explaining the shared
   *  ground. Hand-authored per introduction so the card reads as
   *  a considered introduction rather than a database join. */
  reasonSentence: string
  sharedItems: SharedItem[]
}


// ---------------------------------------------------------------------------
// Human eyebrow per intent. The internal intent labels
// (right-now / shared-journey / thoughtful) never reach the
// member — they become quiet human framings.
// ---------------------------------------------------------------------------

export const INTENT_FRAMING: Record<IntentType, string> = {
  'right-now':      'Your paths are crossing this week',
  'shared-journey': "You've been walking similar paths",
  'thoughtful':     'We thought you might enjoy meeting',
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
    id: 'intro-right-now-sarah',
    otherName: 'Sarah',
    intent: 'right-now',
    reasonSentence:
      "You're both part of The Grove and heading to the same Gathering on Tuesday.",
    sharedItems: [
      { kind: 'collective', label: 'The Grove' },
      { kind: 'gathering',  label: "Tuesday's Gathering" },
      { kind: 'pathway',    label: 'Life in Alignment' },
    ],
  },
  {
    id: 'intro-shared-journey-emma',
    otherName: 'Emma',
    intent: 'shared-journey',
    reasonSentence:
      "You've spent time in the same Collectives, are exploring the same Pathway, and are both in Melbourne.",
    sharedItems: [
      { kind: 'collective', label: 'The Grove' },
      { kind: 'pathway',    label: 'Life in Alignment' },
      { kind: 'place',      label: 'Melbourne' },
    ],
  },
  {
    id: 'intro-thoughtful-anna',
    otherName: 'Anna',
    intent: 'thoughtful',
    reasonSentence:
      "You share a curiosity for reflection and creativity, and you're both circling Byron Bay.",
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
  reasonSentence:
    "You're both part of EMBODY, exploring Life in Alignment, and in Melbourne.",
  sharedItems: [
    { kind: 'collective', label: 'EMBODY' },
    { kind: 'pathway',    label: 'Life in Alignment' },
    { kind: 'place',      label: 'Melbourne' },
  ],
}
