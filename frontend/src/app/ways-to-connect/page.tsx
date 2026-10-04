import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import PageHero from '@/components/layout/PageHero'
import SiteShell from '@/components/layout/SiteShell'
import { waysToConnectVisible } from '@/lib/waysToConnectPreview'
import {
  getWaysToConnect,
  getMyMemberships,
  getMe,
  getSpace,
  getSpaceEvents,
} from '@/lib/serverApi'
import { featuredPeople } from '@/lib/waysToConnect'
import PeopleYouveCrossed from '@/components/connections/PeopleYouveCrossed'
import WaysToConnectEmptyState, {
  buildDoorway,
} from '@/components/connections/WaysToConnectEmptyState'
import WaysToConnectUnavailable from '@/components/connections/WaysToConnectUnavailable'
import WaysToConnectOptIn from '@/components/connections/WaysToConnectOptIn'
import type { EventSummary, SpaceMembership } from '@/types/platform'

export const metadata: Metadata = {
  title: 'Ways to Connect · Fresh Collective',
  description:
    'The people you genuinely share Gatherings and Pathways with, alongside the thing you shared.',
}

/** How many Collectives we look inside for the empty state's doorway.
 *  Bounded so a member of many Collectives does not fan out a page
 *  that, by definition, has nothing on it. */
const DOORWAY_COLLECTIVE_LIMIT = 3

/**
 * The soonest upcoming Gathering in a Collective this member already
 * belongs to.
 *
 * Only reached when Recognition is empty. Built from getters the
 * dashboard already uses — no new endpoint — so the cost is a few
 * cached reads on a page that would otherwise be a dead end.
 *
 * Returns null freely: no doorway is a fine outcome, and a generic
 * Explore Collectives link is the honest fallback. Nothing here
 * invents an event to point at.
 */
async function findDoorway() {
  let memberships: SpaceMembership[] = []
  try {
    memberships = await getMyMemberships()
  } catch {
    return null
  }

  const active = memberships
    .filter((m) => m.status === 'active')
    .slice(0, DOORWAY_COLLECTIVE_LIMIT)
  if (active.length === 0) return null

  const now = Date.now()
  const candidates = await Promise.all(
    active.map(async (m) => {
      try {
        const [space, events] = await Promise.all([
          getSpace(m.space_slug),
          getSpaceEvents(m.space_slug) as Promise<EventSummary[]>,
        ])
        const timezone = space?.timezone ?? 'Australia/Melbourne'
        return (events ?? [])
          .filter(
            (e) =>
              e.status === 'active' &&
              new Date(e.starts_at).getTime() > now,
          )
          .map((e) => ({
            id: e.id,
            title: e.title,
            starts_at: e.starts_at,
            spaceSlug: m.space_slug,
            spaceName: m.space_name,
            timezone,
          }))
      } catch {
        return []
      }
    }),
  )

  const soonest = candidates
    .flat()
    .sort(
      (a, b) =>
        new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
    )[0]

  return buildDoorway(soonest ?? null)
}

/**
 * Ways to Connect — people first, with the shared experiences that
 * explain why each one is here.
 *
 * The page has four states and they are genuinely different things:
 * people to introduce, nobody shared yet, the surface is not open,
 * and we could not ask. The third and fourth must never be rendered as
 * the second — "you have not crossed paths with anyone" is a claim
 * about someone's life, and a failed request is not evidence for it.
 *
 * Gated by NEXT_PUBLIC_WAYS_TO_CONNECT_ENABLED; off, the route 404s.
 * The backend carries its own flag and is not mirrored here — if the
 * two disagree the API says so and this page renders the unavailable
 * state rather than guessing.
 *
 * See docs/foundations/discovery-connection-belonging-ways-to-connect.md.
 */
export default async function WaysToConnectPage() {
  if (!(await waysToConnectVisible())) notFound()

  // Participation is the member's own choice and is read before the
  // recommendations, because the two produce pages that mean opposite
  // things. The API answers "nothing" for an opted-out member — the
  // same answer as "nobody qualifies" — so without this the page would
  // tell somebody who switched the feature off that we simply had not
  // found anyone, and offer them no way back in.
  //
  // Read from the canonical profile endpoint rather than widening the
  // Ways to Connect response: it is the same field Settings writes, and
  // one source for it is the point.
  const me = await getMe().catch(() => null)
  const participating = me?.ways_to_connect_enabled === true

  const result = participating
    ? await getWaysToConnect()
    // Not fetched at all when opted out. The API would return an empty
    // list, which is correct and useless here, and asking for
    // recommendations on behalf of somebody who declined them is the
    // wrong instinct even when the answer is empty.
    : null

  let body: React.ReactNode
  if (!participating) {
    body = <WaysToConnectOptIn />
  } else if (result === null) {
    // Unreachable: ``participating`` and ``result === null`` are set
    // together. Present so the narrowing below is total rather than
    // asserted.
    body = <WaysToConnectUnavailable reason="error" />
  } else if (result.status === 'unavailable' || result.status === 'error') {
    body = <WaysToConnectUnavailable reason={result.status} />
  } else {
    // Featured people only. The payload's tail exists for the
    // in-context lines; the destination shows the few the server
    // chose and offers no way to reach past them.
    const featured = featuredPeople(result.data)
    body = featured.length > 0 ? (
      <PeopleYouveCrossed people={featured} />
    ) : (
      <WaysToConnectEmptyState doorway={await findDoorway()} />
    )
  }

  return (
    <SiteShell>
      <PageHero
        title="Ways to Connect"
        supportingCopy="Meaningful connection grows through shared experiences. Fresh Collective reveals the ones that already exist — nothing more."
      />
      {body}
    </SiteShell>
  )
}
