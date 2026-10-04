import type { PersonRef, SharedThing } from '@/lib/waysToConnect'
import type {
  PeerMessageItem,
  PeerThreadDetail,
  PeerThreadSummary,
} from '@/lib/peerMessages'
import type { MemberImage } from '@/types/platform'

/**
 * Fixtures for the admin visual-QA harness. Code only — nothing here
 * is ever written to the database, and the harness makes no API calls
 * that could create anything.
 *
 * The people are fictional. No email, phone or address appears
 * anywhere, and the ids are obviously synthetic so they can never be
 * mistaken for production users.
 *
 * Shared evidence follows the real 5a semantics rather than decorating
 * the cards: every eligible person carries **two** signals with at
 * least one **realised** (an attended Gathering, or a started
 * Pathway), and an upcoming Gathering only ever appears as the
 * *second*, supporting signal. No card is justified by Collective
 * membership, because membership is never a signal — it is the
 * boundary that makes Recognition permissible.
 */

const COLLECTIVE = {
  id: 'prev-collective-embody',
  slug: 'embody',
  name: 'EMBODY',
  timezone: 'Australia/Sydney',
}

function daysAgo(n: number): string {
  // Fixed offsets from a stable base so the harness looks the same on
  // every load. Not Date.now(): a preview that shifts under you is
  // harder to review than one that does not.
  const base = new Date('2027-03-02T09:30:00Z').getTime()
  return new Date(base - n * 86400000).toISOString()
}

function daysAhead(n: number): string {
  const base = new Date('2027-03-02T09:30:00Z').getTime()
  return new Date(base + n * 86400000).toISOString()
}

const attended = (title: string, days: number): SharedThing => ({
  kind: 'gathering',
  id: `prev-g-${title}-${days}`,
  title,
  starts_at: daysAgo(days),
  basis: 'attended',
  collective_id: COLLECTIVE.id,
})

const upcoming = (title: string, days: number): SharedThing => ({
  kind: 'gathering',
  id: `prev-u-${title}-${days}`,
  title,
  starts_at: daysAhead(days),
  basis: 'upcoming',
  collective_id: COLLECTIVE.id,
})

const pathway = (title: string, days: number): SharedThing => ({
  kind: 'pathway',
  id: `prev-p-${title}`,
  slug: title.toLowerCase().replace(/\s+/g, '-'),
  title,
  collective_id: COLLECTIVE.id,
  crossing_at: daysAgo(days),
})

/**
 * Pictures.
 *
 * ``alphabet`` entries carry the **real** uploaded member-card artwork:
 * the harness looks the URL up through the live Platform Artwork
 * payload and fills it in, so the monogram treatment under review is
 * the one members will actually see. The same ``MemberImage``
 * component renders it — no second avatar implementation.
 */
export type PreviewImageSpec =
  /**
   * A member's own photo.
   *
   * ``artworkKey`` rather than a URL, because the harness runs on
   * production and production's CSP allows images only from ``'self'``,
   * the API origin, R2 and ``data:``. The first version of these
   * fixtures pointed at ``images.unsplash.com``; the browser refused
   * both of them, and the two people with photos were the two that
   * looked broken under review. Pointing at a real uploaded asset
   * keeps the photo tier reviewable — real bytes, real media path,
   * same ``object-cover`` crop a member's photo gets.
   *
   * ``fallbackLetter`` is the card this photo degrades to, which is the
   * behaviour the plain-initial fallback is *not* supposed to reach.
   */
  | { kind: 'photo'; artworkKey: string; initial: string; fallbackLetter: string }
  /** Deliberately unresolvable, to review the end of the ladder. */
  | { kind: 'broken-photo'; initial: string; fallbackLetter: string }
  | { kind: 'alphabet'; letter: string }
  | { kind: 'neutral' }

export interface PreviewPerson {
  id: string
  name: string
  image: PreviewImageSpec
  shared: SharedThing[]
  relationship: 'none' | 'outgoing' | 'incoming' | 'mutual'
}

/**
 * The full cast the fixture sets draw from. Never rendered as one
 * list: the real page shows at most ``MAX_PREVIEW_CARDS`` people, and
 * a preview that shows more than the product does is not a preview of
 * the product. See ``PREVIEW_SETS``.
 */
export const PREVIEW_PEOPLE: PreviewPerson[] = [
  {
    // D — incoming, prioritised
    id: 'prev-maya',
    name: 'Maya Fuller',
    image: { kind: 'alphabet', letter: 'M' },
    relationship: 'incoming',
    shared: [attended('EMBODY — Monday', 9), pathway('Life in Alignment', 21)],
  },
  {
    // E — mutual
    id: 'prev-anna',
    name: 'Anna Byrne',
    image: {
      kind: 'photo',
      artworkKey: 'homepage_conversations',
      initial: 'A',
      fallbackLetter: 'A',
    },
    relationship: 'mutual',
    shared: [attended('EMBODY — Monday', 9), upcoming('EMBODY — Thursday', 4)],
  },
  {
    // F — a second mutual, to judge repetition
    id: 'prev-rose',
    name: 'Rosemary Ngata',
    image: { kind: 'alphabet', letter: 'R' },
    relationship: 'mutual',
    shared: [pathway('Life in Alignment', 30), attended('EMBODY — Monday', 9)],
  },
  {
    // C — outgoing
    id: 'prev-tess',
    name: 'Tess Okafor',
    image: { kind: 'alphabet', letter: 'T' },
    relationship: 'outgoing',
    shared: [attended('Winter Gathering', 44), upcoming('EMBODY — Thursday', 4)],
  },
  {
    // B — eligible, with a photo
    id: 'prev-jo',
    name: 'Jo Marsden',
    image: {
      kind: 'photo',
      artworkKey: 'homepage_ways_to_connect',
      initial: 'J',
      fallbackLetter: 'J',
    },
    relationship: 'none',
    shared: [pathway('Life in Alignment', 12), upcoming('EMBODY — Thursday', 4)],
  },
  {
    // A — eligible, two realised signals
    id: 'prev-dee',
    name: 'Dee Whitlock',
    image: { kind: 'alphabet', letter: 'D' },
    relationship: 'none',
    shared: [attended('EMBODY — Monday', 9), attended('Winter Gathering', 44)],
  },
  {
    // G — no usable A–Z letter, so the neutral card
    id: 'prev-neutral',
    name: '左 Lin',
    image: { kind: 'neutral' },
    relationship: 'none',
    shared: [pathway('Life in Alignment', 18), attended('EMBODY — Monday', 9)],
  },
  {
    // The end of the ladder: a photo that cannot be loaded. Must show
    // this member's own card, never a bare glyph.
    id: 'prev-wren',
    name: 'Wren Adeyemi',
    image: { kind: 'broken-photo', initial: 'W', fallbackLetter: 'W' },
    relationship: 'none',
    shared: [pathway('Life in Alignment', 16), attended('Winter Gathering', 44)],
  },
]

// ---------------------------------------------------------------------------
// Fixture sets
// ---------------------------------------------------------------------------

/**
 * The product's own limit, mirrored.
 *
 * ``selection.MAX_PEOPLE`` on the backend is the authority; this is the
 * number the harness is held to so the preview cannot quietly show a
 * page the product would never render. Reviewing seven cards at once is
 * what made the destination read as a directory.
 */
export const MAX_PREVIEW_CARDS = 3

export type PreviewSetKey = 'discovery' | 'hello' | 'connected'

export interface PreviewSet {
  key: PreviewSetKey
  label: string
  /** What this set is for, shown beside the control. */
  note: string
  people: PreviewPerson[]
}

const byId = (id: string): PreviewPerson => {
  const found = PREVIEW_PEOPLE.find((p) => p.id === id)
  if (!found) throw new Error(`unknown preview person: ${id}`)
  return found
}

/**
 * Three sets of three, instead of one page of seven.
 *
 * Every state still gets reviewed — they are just not all on screen at
 * once, because the product never puts them there. Each set is a page
 * the real product could actually produce.
 */
export const PREVIEW_SETS: PreviewSet[] = [
  {
    key: 'discovery',
    label: 'Discovery',
    note: 'Nobody has said hello yet. Photo, monogram and the broken-photo fallback.',
    people: [byId('prev-jo'), byId('prev-dee'), byId('prev-wren')],
  },
  {
    key: 'hello',
    label: 'Hello states',
    note: 'An incoming hello first, then one sent and one not yet acted on.',
    people: [byId('prev-maya'), byId('prev-tess'), byId('prev-neutral')],
  },
  {
    key: 'connected',
    label: 'Connected',
    note: 'Two mutual connections side by side, to judge repetition.',
    people: [byId('prev-anna'), byId('prev-rose'), byId('prev-dee')],
  },
]

export function previewSet(key: string | undefined): PreviewSet {
  return PREVIEW_SETS.find((s) => s.key === key) ?? PREVIEW_SETS[0]
}

/** Turn a spec into the payload ``MemberImage`` expects. */
export function resolvePreviewImage(
  spec: PreviewImageSpec,
  artworkByKey: Map<string, string | null>,
): MemberImage {
  if (spec.kind === 'photo' || spec.kind === 'broken-photo') {
    return {
      kind: 'photo',
      url: spec.kind === 'photo'
        ? artworkByKey.get(spec.artworkKey) ?? null
        // A path that resolves to nothing, so the ladder is exercised
        // rather than described.
        : '/api/uploads/preview/this-photo-is-gone.webp',
      initial: spec.initial,
      // The rung below, exactly as the real resolver now sends it: a
      // photo that fails falls to the member's card, never straight to
      // a bare glyph.
      fallback_url:
        artworkByKey.get(`member_card_${spec.fallbackLetter.toLowerCase()}`)
        ?? artworkByKey.get('member_card_neutral')
        ?? null,
    }
  }
  if (spec.kind === 'neutral') {
    return {
      kind: 'neutral',
      url: artworkByKey.get('member_card_neutral') ?? null,
      initial: null,
    }
  }
  const url = artworkByKey.get(`member_card_${spec.letter.toLowerCase()}`) ?? null
  // Falls back to the plain initial exactly as the real resolver does
  // when a letter's card has not been uploaded.
  return {
    kind: url ? 'alphabet' : 'initial',
    url,
    initial: spec.letter,
  }
}

export function previewPersonRef(
  person: PreviewPerson,
  artworkByKey: Map<string, string | null>,
): PersonRef {
  return {
    id: person.id,
    display_name: person.name,
    avatar_url: null,
    image: resolvePreviewImage(person.image, artworkByKey),
    relationship: person.relationship,
    collectives: [COLLECTIVE],
    shared: person.shared,
  }
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

const VIEWER_ID = 'prev-viewer'
export const PREVIEW_VIEWER_ID = VIEWER_ID

interface PreviewThreadSpec {
  threadId: string
  person: PreviewPerson
  lastMessage: string
  lastAt: string
  unread: number
}

const THREAD_SPECS: PreviewThreadSpec[] = [
  {
    threadId: 'maya',
    person: PREVIEW_PEOPLE[0],
    lastMessage: 'That sounds lovely — I’d be keen.',
    lastAt: daysAgo(0),
    unread: 2,
  },
  {
    threadId: 'anna',
    person: PREVIEW_PEOPLE[1],
    lastMessage: 'I was thinking the same thing after Monday.',
    lastAt: daysAgo(1),
    unread: 0,
  },
  {
    threadId: 'rose',
    person: PREVIEW_PEOPLE[2],
    lastMessage: 'Next month suits me better, if that’s alright.',
    lastAt: daysAgo(11),
    unread: 0,
  },
  {
    threadId: 'tess',
    person: PREVIEW_PEOPLE[3],
    lastMessage: 'Thanks for saying hello.',
    lastAt: daysAgo(26),
    unread: 0,
  },
]

export function previewThreadSummaries(
  artworkByKey: Map<string, string | null>,
): PeerThreadSummary[] {
  return THREAD_SPECS.map((spec) => ({
    thread_id: spec.threadId,
    other: {
      id: spec.person.id,
      display_name: spec.person.name,
      image: resolvePreviewImage(spec.person.image, artworkByKey),
    },
    last_message: spec.lastMessage,
    last_message_at: spec.lastAt,
    unread_count: spec.unread,
  }))
}

/**
 * One conversation — two women who recognised each other from a
 * Gathering, starting easily. Short turns, alternating, so spacing and
 * the run of consecutive messages can both be judged.
 */
const CONVERSATION: { from: 'them' | 'me'; body: string; days: number }[] = [
  { from: 'them', body: 'Hello! You were at EMBODY on Monday, weren’t you?', days: 3 },
  { from: 'me', body: 'I was — back row, trying to keep up.', days: 3 },
  { from: 'them', body: 'Ha, same. I nearly fell over in the last sequence.', days: 3 },
  { from: 'me', body: 'You looked far more composed than I felt.', days: 2 },
  { from: 'them', body: 'Kind of you. Are you going again Thursday?', days: 2 },
  { from: 'me', body: 'Planning to. It’s become the steadiest hour of my week.', days: 2 },
  { from: 'them', body: 'That’s exactly how I’d put it.', days: 1 },
  { from: 'them', body: 'A few of us get a coffee afterwards, if you ever fancy it.', days: 1 },
  { from: 'me', body: 'I’d like that, thank you.', days: 1 },
  { from: 'them', body: 'That sounds lovely — I’d be keen.', days: 0 },
]

/** Conversation states the harness can show. */
export type ConversationState = 'normal' | 'blocked' | 'report'

export function previewConversation(
  artworkByKey: Map<string, string | null>,
  state: ConversationState = 'normal',
): PeerThreadDetail {
  const person = PREVIEW_PEOPLE[0]
  const messages: PeerMessageItem[] = CONVERSATION.map((turn, i) => ({
    id: `prev-m-${i + 1}`,
    sender_user_id: turn.from === 'me' ? VIEWER_ID : person.id,
    body: turn.body,
    created_at: daysAgo(turn.days),
    // The two most recent from the other person are still unread, so
    // the inbox badge and the thread agree.
    is_read: !(turn.from === 'them' && turn.days <= 0),
  }))

  const blocked = state === 'blocked'
  return {
    thread_id: 'maya',
    other: {
      id: person.id,
      display_name: person.name,
      image: resolvePreviewImage(person.image, artworkByKey),
    },
    messages,
    // Driven by the same two fields the real payload carries, so the
    // blocked state under review is the real one rather than a
    // preview-only branch.
    blocked_by_me: blocked,
    can_send: !blocked,
  }
}
