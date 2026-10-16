/**
 * Project the platform-wide unseen counts onto one Collective.
 *
 * The counts endpoint is called **unscoped** — one request returns
 * every Collective the member belongs to — so the layout, the three
 * section pages and the Collective Home all share a single
 * ``cache()``'d response per page load. What each surface needs from
 * it is the same three numbers for the Collective it is rendering,
 * which is this function.
 *
 * Pure, and deliberately not inlined at the call sites. Two inline
 * copies of a badge rule is exactly how ``SpaceNav`` ended up capping
 * at ``9+`` on desktop and ``9`` on mobile. One definition.
 *
 * ``undefined`` — not a zeroed map — when the member has no row for
 * this Collective. The distinction matters to the caller: no row means
 * "nothing known", which renders no badges at all, whereas a zeroed
 * map would be a claim that every section is clear.
 */

import type { UnseenCountsResponse } from '@/types/platform'

export function unseenForCollective(
  counts: UnseenCountsResponse,
  collectiveId: string,
): Record<string, number> | undefined {
  const mine = counts.collectives.find((c) => c.collective_id === collectiveId)
  if (!mine) return undefined
  return {
    conversations: mine.conversations,
    pathways: mine.pathways,
    gatherings: mine.gatherings,
  }
}
