import type { CollectiveArea, SpaceResponse } from '@/types/platform'

/**
 * Whether this viewer may reach an area of a Collective.
 *
 * The answer is the server's, carried on ``SpaceResponse.area_access``
 * and resolved once per request by ``app/spaces/area_access.py``.
 * Nothing here decides anything — it reads a set and reports.
 *
 * That restraint is the point. The Members tab and the Members Home
 * tile once disagreed because each worked the rule out for itself, and
 * Explore and the dashboard disagreed about membership for the same
 * reason. One resolution, threaded down, read everywhere.
 *
 * ``area_access`` absent means an older payload; every area is then
 * treated as reachable and the page behaves as it did before this
 * existed. The API guards independently, so a stale client cannot see
 * protected data either way — it would render an empty page rather
 * than a leak.
 *
 * Kept free of ``next/navigation`` so the rule can be tested as
 * behaviour; the ``notFound()`` guard that uses it lives in
 * ``areaAccess.ts``.
 */
export function canReachArea(
  space: Pick<SpaceResponse, 'area_access'> | null | undefined,
  area: CollectiveArea,
): boolean {
  const areas = space?.area_access
  if (areas === undefined) return true
  return areas.includes(area)
}
