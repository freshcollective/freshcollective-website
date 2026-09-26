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
 * the way someone would actually say it out loud.
 */

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

/** Someone the viewer genuinely shares a context with.
 *
 *  Both `display_name` and `avatar_url` are nullable and both being
 *  null is ordinary — most members have set no name and have no
 *  public creator profile. Nothing here is a score, a rank or a
 *  reason; the shared context is the reason. */
export interface PersonRef {
  id: string
  display_name: string | null
  avatar_url: string | null
}

/** `upcoming` — everyone holds a confirmed booking for something that
 *  has not happened. `attended` — the roster was finalised and
 *  everyone was marked present. The difference decides the tense. */
export type GatheringBasis = 'upcoming' | 'attended'

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

export interface WaysToConnectPayload {
  contexts: SharedContext[]
  /** The response reached its safety bound. Not a page count, and
   *  deliberately not a number — there is nothing to page to. */
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
// Sentences
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
  context: GatheringContext,
  vantage: Vantage = 'there',
): string {
  const who = describePeople(context.people)
  if (!who) return ''
  const place = vantage === 'here' ? 'here' : 'there'
  return context.basis === 'upcoming'
    ? `You’ll be ${place} with ${who}.`
    : `You were ${place} with ${who}.`
}

/** The one line we put under a shared Pathway. Present tense: both
 *  people are still walking it. */
export function pathwaySentence(
  context: PathwayContext,
  vantage: Vantage = 'there',
): string {
  const who = describePeople(context.people)
  if (!who) return ''
  return vantage === 'here'
    ? `You’re moving through this with ${who}.`
    : `You’re moving through this with ${who}.`
}

/** Whichever sentence fits the context. */
export function contextSentence(
  context: SharedContext,
  vantage: Vantage = 'there',
): string {
  return context.kind === 'gathering'
    ? gatheringSentence(context, vantage)
    : pathwaySentence(context, vantage)
}

// ---------------------------------------------------------------------------
// Finding and grouping
// ---------------------------------------------------------------------------

/** The Gathering context for this Event, if the viewer shares it. */
export function findGatheringContext(
  contexts: SharedContext[],
  gatheringId: string,
): GatheringContext | null {
  for (const c of contexts) {
    if (c.kind === 'gathering' && c.id === gatheringId && c.people.length > 0) {
      return c
    }
  }
  return null
}

/** The Pathway context for this Pathway, if the viewer shares it. */
export function findPathwayContext(
  contexts: SharedContext[],
  pathwayId: string,
): PathwayContext | null {
  for (const c of contexts) {
    if (c.kind === 'pathway' && c.id === pathwayId && c.people.length > 0) {
      return c
    }
  }
  return null
}

/** Every context belonging to one Collective, in the order the API
 *  gave them. Used by the Collective page, which has no evidence of
 *  its own and shows only what its Gatherings and Pathways produced. */
export function contextsInCollective(
  contexts: SharedContext[],
  collectiveId: string,
): SharedContext[] {
  return contexts.filter(
    (c) => c.collective.id === collectiveId && c.people.length > 0,
  )
}

export interface GroupedContexts {
  comingUp: GatheringContext[]
  pathways: PathwayContext[]
  recent: GatheringContext[]
}

/**
 * The destination's three groups, ordered by what a member is most
 * likely to act on: what is about to happen, what they are in the
 * middle of, what already happened.
 *
 * Grouped by the shared thing, never by person. A person who shows up
 * at the same circle and on the same Pathway appears in both, because
 * those are two different things they share and collapsing them would
 * lose the one worth saying.
 *
 * The API already returns contexts in order; this only partitions.
 * Empty groups stay empty so callers can drop the heading rather than
 * render a section about nothing.
 */
export function groupContexts(contexts: SharedContext[]): GroupedContexts {
  const comingUp: GatheringContext[] = []
  const pathways: PathwayContext[] = []
  const recent: GatheringContext[] = []

  for (const c of contexts) {
    if (c.people.length === 0) continue
    if (c.kind === 'pathway') pathways.push(c)
    else if (c.basis === 'upcoming') comingUp.push(c)
    else recent.push(c)
  }

  return { comingUp, pathways, recent }
}

/** Whether there is anything at all to show. */
export function hasAnyContext(grouped: GroupedContexts): boolean {
  return (
    grouped.comingUp.length > 0 ||
    grouped.pathways.length > 0 ||
    grouped.recent.length > 0
  )
}
