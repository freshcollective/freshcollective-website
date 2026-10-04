/**
 * Ways to Connect — the shapes the API returns, and the language we
 * put around them.
 *
 * Everything here is pure. The phrasing rules are the part of this
 * feature most likely to read badly in a real member's account, so
 * they live in functions that can be tested against every awkward
 * combination without rendering anything.
 *
 * Two rules run through all of it.
 *
 * We only say what we know. Two people shared a Gathering; we do not
 * know that they met, spoke, noticed each other or would like to.
 * "You were there with Sarah" is true. "You connected with Sarah" is
 * an invention.
 *
 * And a person without a name is a person, not a blank. The API
 * returns ``display_name: null`` rather than a placeholder precisely
 * so that three unnamed members do not render as three strangers all
 * called Member. They are counted instead, which is both truthful and
 * the way someone would actually say it out loud — and they are never
 * offered as a card, because a card introduces somebody.
 */

import type { MemberImage } from '@/types/platform'

/** A Collective, as context on a shared experience. */
export interface CollectiveRef {
  id: string
  slug: string
  name: string
  /** IANA zone the Collective schedules in. A Gathering's `starts_at`
   *  is stored without one, so every date we render goes through
   *  this rather than the machine's own clock. */
  timezone: string
}

/** `upcoming` — everyone holds a confirmed booking for something that
 *  has not happened. `attended` — the roster was finalised and
 *  everyone was marked present. The difference decides the tense. */
export type GatheringBasis = 'upcoming' | 'attended'

export interface SharedGatheringRef {
  kind: 'gathering'
  id: string
  title: string
  starts_at: string
  basis: GatheringBasis
  collective_id: string
}

export interface SharedPathwayRef {
  kind: 'pathway'
  id: string
  slug: string
  title: string
  collective_id: string
  /** The earlier of the pair's two latest completed steps. Ordering
   *  only — never a threshold, never a score. */
  crossing_at: string | null
}

export type SharedThing = SharedGatheringRef | SharedPathwayRef

/**
 * Someone the viewer genuinely shares something with.
 *
 * `display_name` and `avatar_url` are both nullable and both being
 * null is ordinary — most members have set no name and have no public
 * creator profile. `shared` always has at least one entry; a person
 * with nothing shared is not recognisable and never appears.
 */
export interface PersonRef {
  id: string
  display_name: string | null
  /** Superseded by `image`; kept until every reader has moved over. */
  avatar_url: string | null
  /** The resolved picture — their photo, their alphabet card, or their
   *  letter. Decided server-side so this surface and the member
   *  directory cannot disagree about what somebody looks like. */
  image: MemberImage
  /** Where this pair stands, decided server-side from the two possible
   *  hello rows. The card renders what it is told: an optimistic click
   *  may run ahead of a refetch, but it never outranks this on
   *  re-render. Optional so a payload from before 5b still parses. */
  relationship?: HelloRelationship
  collectives: CollectiveRef[]
  shared: SharedThing[]
}

/** The four states a pair can be in. Mirrors
 *  ``ways_to_connect.hello_service.HelloState``. */
export type HelloRelationship = 'none' | 'outgoing' | 'incoming' | 'mutual'

export interface WaysToConnectPayload {
  /** Every recognisable person. The first `featured_count` are the
   *  ones the destination shows today; the tail exists so the
   *  in-context lines can count people the cards never name. */
  people: PersonRef[]
  featured_count: number
  truncated: boolean
}

/**
 * What happened when we asked.
 *
 * `empty` and `unavailable` are different states and must never
 * collapse into each other: one means "you have not crossed paths
 * with anyone yet", the other means "we could not ask". Telling a
 * member the first when the second is true is a lie the interface
 * would have no way to take back.
 */
export type WaysToConnectResult =
  | { status: 'ok'; data: WaysToConnectPayload }
  | { status: 'unavailable' }
  | { status: 'error' }

/** How many names we read out before the rest become a count.
 *  Three is about where a spoken sentence stops being a sentence. */
export const MAX_NAMES = 3

// ---------------------------------------------------------------------------
// Naming people
// ---------------------------------------------------------------------------

/** Split a context's people into the names we can say and the number
 *  of people we cannot name. Anyone beyond `MAX_NAMES` joins the
 *  count — "other people" is true of them either way. */
export function splitPeople(
  people: PersonRef[],
): { names: string[]; others: number } {
  const named = people
    .map((p) => p.display_name)
    .filter((n): n is string => typeof n === 'string' && n.trim().length > 0)
  const unnamed = people.length - named.length
  const shown = named.slice(0, MAX_NAMES)
  return { names: shown, others: named.length - shown.length + unnamed }
}

/** Join a list the way a person would say it. */
function joinNaturally(parts: string[]): string {
  if (parts.length === 0) return ''
  if (parts.length === 1) return parts[0]
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
}

/**
 * Describe a group of people in plain English.
 *
 *   Sarah
 *   Sarah and James
 *   Sarah, James and Maya
 *   Sarah, James, Maya and 2 other people
 *   Sarah and someone else
 *   Sarah and 2 other people
 *   someone else
 *   3 people
 *
 * Returns an empty string for an empty group; callers render nothing
 * rather than a sentence about nobody.
 */
export function describePeople(people: PersonRef[]): string {
  const { names, others } = splitPeople(people)

  if (others === 0) return joinNaturally(names)

  // One unnamed person is "someone else" either way. Counting a
  // single person — "one other person" — is how a form describes a
  // headcount, not how anyone describes company; "someone else" is
  // the same fact said the way it would be said out loud.
  //
  // Past one, a number is the honest thing: nobody can picture "some
  // other people", and we have nothing truer to offer than how many.
  // "other" only earns its place once somebody has been named —
  // standing alone, unnamed people are simply the people who were
  // there.
  const othersPhrase =
    others === 1
      ? 'someone else'
      : names.length > 0
        ? `${others} other people`
        : `${others} people`

  return joinNaturally([...names, othersPhrase])
}

// ---------------------------------------------------------------------------
// Sentences about a group of people
// ---------------------------------------------------------------------------

/** `here` on the Gathering or Pathway's own page, `there` when we are
 *  pointing at it from somewhere else. */
export type Vantage = 'here' | 'there'

/**
 * The one line we put under a shared Gathering.
 *
 * Deliberately about presence and nothing else: who else will be in
 * the room, or who else was. No claim about meeting, knowing,
 * connecting or getting along.
 */
export function gatheringSentence(
  people: PersonRef[],
  basis: GatheringBasis,
  vantage: Vantage = 'there',
): string {
  const who = describePeople(people)
  if (!who) return ''
  const place = vantage === 'here' ? 'here' : 'there'
  return basis === 'upcoming'
    ? `You’ll be ${place} with ${who}.`
    : `You were ${place} with ${who}.`
}

/** The one line we put under a shared Pathway. Present tense: both
 *  people are still walking it. */
export function pathwaySentence(people: PersonRef[]): string {
  const who = describePeople(people)
  if (!who) return ''
  return `You’re moving through this with ${who}.`
}

// ---------------------------------------------------------------------------
// The person card
// ---------------------------------------------------------------------------

/** The Collective a person's shared things mostly belong to — the one
 *  the reason sentence names. Falls back to their first shared
 *  Collective when the evidence spans several. */
export function primaryCollective(person: PersonRef): CollectiveRef | null {
  if (person.collectives.length === 0) return null
  const tally = new Map<string, number>()
  for (const thing of person.shared) {
    tally.set(thing.collective_id, (tally.get(thing.collective_id) ?? 0) + 1)
  }
  let best = person.collectives[0]
  let bestCount = -1
  for (const c of person.collectives) {
    const n = tally.get(c.id) ?? 0
    if (n > bestCount) {
      best = c
      bestCount = n
    }
  }
  return best
}

/**
 * Why this person is on the page, in one factual sentence.
 *
 * It names the Collective and the *shape* of the overlap; the card
 * lists the specific Gatherings and Pathways underneath, so repeating
 * their titles here would say the same thing twice. Nothing in it
 * claims a relationship — "you've both been showing up to EMBODY" is
 * an observation about attendance, not about how anyone feels.
 *
 * The sentence follows the same hierarchy the server used to choose
 * this person: what actually happened, then what is underway, then
 * what is merely planned. So a pair with real history is never
 * introduced by their diary — "you're both coming to EMBODY" would
 * lead with the weakest thing we know about them and quietly bury the
 * fact that they have already spent time together.
 *
 * A person reaching this function has at least two shared signals and
 * at least one of them realised, so every branch can speak in the
 * plural without stretching — and the "only plans" case at the bottom
 * is unreachable for a featured person. It stays as an honest fallback
 * rather than a throw, because a lie is worse than a sentence nobody
 * sees.
 */
export function reasonSentence(person: PersonRef): string {
  const collective = primaryCollective(person)
  if (!collective || person.shared.length === 0) return ''
  const where = collective.name

  const attended = person.shared.filter(
    (s): s is SharedGatheringRef => s.kind === 'gathering' && s.basis === 'attended',
  )
  const upcoming = person.shared.filter(
    (s): s is SharedGatheringRef => s.kind === 'gathering' && s.basis === 'upcoming',
  )
  const pathways = person.shared.filter(
    (s): s is SharedPathwayRef => s.kind === 'pathway',
  )

  // Strongest first: they have been in the same room.
  if (attended.length >= 2) {
    return `You’ve both been showing up to ${where}.`
  }
  if (attended.length === 1) {
    // One real shared room plus something else — still led by the
    // thing that happened, never by the thing that hasn't.
    return pathways.length > 0
      ? `You’ve been in the same room at ${where}, and you’re on the same path.`
      : `You’ve both been showing up to ${where}.`
  }

  // No shared history yet, but something is genuinely underway.
  if (pathways.length >= 2) {
    return `You’re both walking the same paths in ${where}.`
  }
  if (pathways.length === 1) {
    return upcoming.length > 0
      ? `You’re on the same path in ${where}, and you’ll be there together soon.`
      : `You’re both walking a pathway in ${where}.`
  }

  // Only plans — never a featured person, since a card requires one
  // realised signal. Kept truthful for any other caller.
  return upcoming.length >= 2
    ? `Your paths are about to cross at ${where}, more than once.`
    : `You’re both coming to ${where}.`
}

/** The people the destination features today. The API has already
 *  chosen them and put them first; this is the contract, in one place
 *  rather than a `.slice(0, 3)` scattered through components. */
export function featuredPeople(payload: WaysToConnectPayload): PersonRef[] {
  return payload.people.slice(0, Math.max(0, payload.featured_count))
}

// ---------------------------------------------------------------------------
// Derived context views
//
// The payload is person-shaped because the destination asks "who?".
// The quiet lines on a Gathering or Pathway page ask a different
// question — "who else is in this room?" — and the Collective page
// asks it of a whole Collective. Rather than a second endpoint, those
// views are derived here from the same people.
//
// Unnamed members are included on purpose. They never become a card,
// but "Sarah and 2 other people" is only true if they are counted.
// ---------------------------------------------------------------------------

export interface GatheringContext {
  kind: 'gathering'
  id: string
  title: string
  starts_at: string
  basis: GatheringBasis
  collective: CollectiveRef
  people: PersonRef[]
}

export interface PathwayContext {
  kind: 'pathway'
  id: string
  slug: string
  title: string
  collective: CollectiveRef
  people: PersonRef[]
}

export type SharedContext = GatheringContext | PathwayContext

/** Turn the person-keyed payload inside out: one entry per shared
 *  thing, carrying everyone who shares it. */
export function deriveContexts(people: PersonRef[]): SharedContext[] {
  const collectives = new Map<string, CollectiveRef>()
  for (const person of people) {
    for (const c of person.collectives) {
      if (!collectives.has(c.id)) collectives.set(c.id, c)
    }
  }

  const gatherings = new Map<string, GatheringContext>()
  const pathways = new Map<string, PathwayContext>()

  for (const person of people) {
    for (const thing of person.shared) {
      const collective = collectives.get(thing.collective_id)
      if (!collective) continue

      if (thing.kind === 'gathering') {
        const existing = gatherings.get(thing.id)
        if (existing) {
          existing.people.push(person)
        } else {
          gatherings.set(thing.id, {
            kind: 'gathering',
            id: thing.id,
            title: thing.title,
            starts_at: thing.starts_at,
            basis: thing.basis,
            collective,
            people: [person],
          })
        }
      } else {
        const existing = pathways.get(thing.id)
        if (existing) {
          existing.people.push(person)
        } else {
          pathways.set(thing.id, {
            kind: 'pathway',
            id: thing.id,
            slug: thing.slug,
            title: thing.title,
            collective,
            people: [person],
          })
        }
      }
    }
  }

  const sortPeople = (c: SharedContext) => {
    c.people.sort((a, b) => {
      // Named first, so a sentence can lead with somebody recognisable.
      if (!a.display_name !== !b.display_name) return a.display_name ? -1 : 1
      return (a.display_name ?? '').localeCompare(b.display_name ?? '')
        || a.id.localeCompare(b.id)
    })
    return c
  }

  return [
    ...[...gatherings.values()].map(sortPeople),
    ...[...pathways.values()].map(sortPeople),
  ]
}

/** The Gathering context for this Event, if the viewer shares it. */
export function findGatheringContext(
  people: PersonRef[],
  gatheringId: string,
): GatheringContext | null {
  for (const c of deriveContexts(people)) {
    if (c.kind === 'gathering' && c.id === gatheringId && c.people.length > 0) {
      return c
    }
  }
  return null
}

/** The Pathway context for this Pathway, if the viewer shares it. */
export function findPathwayContext(
  people: PersonRef[],
  pathwayId: string,
): PathwayContext | null {
  for (const c of deriveContexts(people)) {
    if (c.kind === 'pathway' && c.id === pathwayId && c.people.length > 0) {
      return c
    }
  }
  return null
}

/** Every shared thing belonging to one Collective. Used by the
 *  Collective page, which has no evidence of its own and shows only
 *  what its Gatherings and Pathways produced. */
export function contextsInCollective(
  people: PersonRef[],
  collectiveId: string,
): SharedContext[] {
  return deriveContexts(people).filter(
    (c) => c.collective.id === collectiveId && c.people.length > 0,
  )
}

/** Whichever sentence fits a derived context. */
export function contextSentence(
  context: SharedContext,
  vantage: Vantage = 'there',
): string {
  return context.kind === 'gathering'
    ? gatheringSentence(context.people, context.basis, vantage)
    : pathwaySentence(context.people)
}

/**
 * Say hello to someone on the Ways to Connect page.
 *
 * Throws on anything other than a 2xx so the card can show its own
 * retry copy. A duplicate send is *not* an error — the endpoint
 * answers a repeat click with the same body as the first, so an
 * optimistic card and a double-tap both converge on the server's view
 * rather than on a failure state.
 *
 * The resulting relationship is returned but the card currently only
 * needs to know the call succeeded; the authoritative state arrives on
 * the next payload.
 */
export async function sayHello(
  personId: string,
): Promise<{ relationship: HelloRelationship; became_mutual: boolean }> {
  const res = await fetch(
    `/api/ways-to-connect/${encodeURIComponent(personId)}/hello`,
    { method: 'POST', credentials: 'include' },
  )
  if (!res.ok) throw new Error(`say hello failed: ${res.status}`)
  return res.json()
}
