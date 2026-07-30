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
  /** Always the most specific shared name available — the actual
   *  Collective, Pathway, Gathering, Place or Theme name. Never a
   *  generic category label like "same Gathering" or "the same
   *  Pathway". Members should recognise the common ground at a
   *  glance without having to interpret an abstract phrase.
   *
   *  When two members are booked into the same Gathering, use the
   *  Gathering's actual title (optionally suffixed with a day for
   *  readability, e.g. "Life in Alignment Circle · Tuesday"),
   *  not the day alone. The recommendation service is responsible
   *  for populating labels from the real entity names when it
   *  replaces this fixture. */
  label: string
}

export interface MockIntroduction {
  /** Stable id for React keys + mock URL slugs. */
  id: string
  /** The other person's display name. Given name only for warmth. */
  otherName: string
  /** The other person's profile photo URL, or null when either
   *  no photo is set OR the member's profile visibility settings
   *  do not permit showing it in this context.
   *
   *  Server-side is authoritative on visibility: the introduction
   *  recommendation service must never populate this field for a
   *  member who has kept their photo private. The client trusts
   *  that "null means fall back" — it does not perform its own
   *  visibility check.
   *
   *  When null (or the image fails to load), PortraitCircle
   *  renders the serif-initial fallback at the same size, in the
   *  same frame, on the same warm gradient.
   */
  avatarUrl: string | null
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
    // No photo set — renders the serif-initial fallback.
    id: 'intro-right-now-sarah',
    otherName: 'Sarah',
    avatarUrl: null,
    intent: 'right-now',
    reasonSentence:
      "You're both part of The Grove and booked into Tuesday's Life in Alignment Circle.",
    sharedItems: [
      { kind: 'collective', label: 'The Grove' },
      { kind: 'gathering',  label: 'Life in Alignment Circle · Tuesday' },
      { kind: 'pathway',    label: 'Life in Alignment' },
    ],
  },
  {
    // Has a photo set AND profile visibility permits sharing —
    // the server has populated avatarUrl and the card renders the
    // image. Uses a local abstract SVG portrait
    // (public/prototype/portraits/) so the prototype does not
    // depend on any external avatar service, and so no external
    // service can infer identity from the mock name. The pairing
    // Emma ↔ portrait-01 is deliberate and stable across every
    // render state.
    id: 'intro-shared-journey-emma',
    otherName: 'Emma',
    avatarUrl: '/prototype/portraits/portrait-01.svg',
    intent: 'shared-journey',
    reasonSentence:
      "You're both part of The Grove, exploring Life in Alignment, and in Melbourne.",
    sharedItems: [
      { kind: 'collective', label: 'The Grove' },
      { kind: 'pathway',    label: 'Life in Alignment' },
      { kind: 'place',      label: 'Melbourne' },
    ],
  },
  {
    // No photo set — fallback.
    id: 'intro-thoughtful-anna',
    otherName: 'Anna',
    avatarUrl: null,
    intent: 'thoughtful',
    reasonSentence:
      "You share Reflection and Creativity, and you're both drawn to Byron Bay.",
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
  // Photo set and visibility permits sharing — demonstrates the
  // photo state on the invitation card and (after accept) the
  // conversation introduction panel. Local SVG portrait, paired
  // deliberately with James and stable across every render state.
  avatarUrl: '/prototype/portraits/portrait-02.svg',
  intent: 'shared-journey',
  reasonSentence:
    "You're both part of EMBODY, exploring Life in Alignment, and in Melbourne.",
  sharedItems: [
    { kind: 'collective', label: 'EMBODY' },
    { kind: 'pathway',    label: 'Life in Alignment' },
    { kind: 'place',      label: 'Melbourne' },
  ],
}
