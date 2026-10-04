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
  | { kind: 'photo'; url: string; initial: string }
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
 * Seven people covering every card state, in the order the real page
 * would produce: an incoming hello is lifted to the front, because
 * somebody waiting on you should not sit behind a recommendation.
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
      url: 'https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=400&q=70',
      initial: 'A',
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
      url: 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400&q=70',
      initial: 'J',
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
]

/** Turn a spec into the payload ``MemberImage`` expects. */
export function resolvePreviewImage(
  spec: PreviewImageSpec,
  artworkByKey: Map<string, string | null>,
): MemberImage {
  if (spec.kind === 'photo') {
    return { kind: 'photo', url: spec.url, initial: spec.initial }
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
    avatar_url: person.image.kind === 'photo' ? person.image.url : null,
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
