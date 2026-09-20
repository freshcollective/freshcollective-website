import { notFound } from 'next/navigation'

import { canReachArea } from '@/lib/collectiveAreas'
import type { CollectiveArea, SpaceResponse } from '@/types/platform'

export { canReachArea }

/**
 * Guard a server-rendered Collective page.
 *
 * ``notFound()`` rather than a redirect to login, matching the API's
 * 404 and the platform's stance elsewhere: a refusal must not confirm
 * that an area exists to someone who may not see it. It is also a
 * server-side answer, so no protected page ever paints and then
 * disappears.
 */
export function requireArea(
  space: Pick<SpaceResponse, 'area_access'> | null | undefined,
  area: CollectiveArea,
): void {
  if (!canReachArea(space, area)) notFound()
}
