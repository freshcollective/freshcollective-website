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
  /** Optional slug for the shared entity. Used by the card layout
   *  as the deterministic seed for the atmospheric fallback
   *  artwork when no real cover image is available. When omitted
   *  the ``label`` is used as the seed instead. */
  slug?: string
  /** Optional URL to real cover artwork for the shared entity
   *  (e.g. a Collective's cover image, a Place's hero artwork).
   *  When present, this becomes the introduction card's hero
   *  image; otherwise the atmospheric fallback is used. The
   *  recommendation service will populate this from the real
   *  entity's stored artwork when it replaces this fixture. */
  artworkUrl?: string | null
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
      { kind: 'collective', label: 'The Grove',                          slug: 'the-grove' },
      { kind: 'gathering',  label: 'Life in Alignment Circle · Tuesday', slug: 'life-in-alignment-tuesday' },
      { kind: 'pathway',    label: 'Life in Alignment',                  slug: 'life-in-alignment' },
    ],
  },
  {
    // No prototype photo assigned right now — the card
    // demonstrates the serif-initial fallback state. To exercise
    // the photo state locally, drop an approved prototype JPG /
    // PNG into public/prototype/portraits/ and set avatarUrl to
    // "/prototype/portraits/<filename>". Pairing is deliberate,
    // not derived from the mock name.
    id: 'intro-shared-journey-emma',
    otherName: 'Emma',
    avatarUrl: null,
    intent: 'shared-journey',
    reasonSentence:
      "You're both part of The Grove, exploring Life in Alignment, and in Melbourne.",
    sharedItems: [
      { kind: 'collective', label: 'The Grove',          slug: 'the-grove' },
      { kind: 'pathway',    label: 'Life in Alignment',  slug: 'life-in-alignment' },
      { kind: 'place',      label: 'Melbourne',          slug: 'melbourne' },
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
      { kind: 'theme', label: 'Reflection',  slug: 'reflection' },
      { kind: 'theme', label: 'Creativity',  slug: 'creativity' },
      { kind: 'place', label: 'Byron Bay',   slug: 'byron-bay' },
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
  // No prototype photo assigned right now — the invitation and
  // (on accept) the conversation introduction panel render the
  // serif-initial fallback. To exercise the photo state locally,
  // drop an approved prototype JPG / PNG into
  // public/prototype/portraits/ and set avatarUrl to
  // "/prototype/portraits/<filename>". Pairing is deliberate,
  // not derived from the mock name.
  avatarUrl: null,
  intent: 'shared-journey',
  reasonSentence:
    "You're both part of EMBODY, exploring Life in Alignment, and in Melbourne.",
  sharedItems: [
    { kind: 'collective', label: 'EMBODY',             slug: 'embody' },
    { kind: 'pathway',    label: 'Life in Alignment',  slug: 'life-in-alignment' },
    { kind: 'place',      label: 'Melbourne',          slug: 'melbourne' },
  ],
}
