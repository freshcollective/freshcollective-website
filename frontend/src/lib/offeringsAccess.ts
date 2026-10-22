import { notFound } from 'next/navigation'

import { getActiveCreatorSpace, getCreatorSpace } from '@/lib/serverApi'
import type { CreatorSpaceDetail } from '@/types/platform'

/**
 * Is Offerings available for the Collective this creator has selected?
 *
 * The answer comes from the backend — `SpaceDetail.offerings_available`,
 * which resolves the `OFFERINGS_ENABLED` master switch and the
 * `OFFERINGS_PILOT_COLLECTIVES` allow-list through the same predicate
 * `area_access` uses for the member side. Nothing in the frontend
 * knows which Collectives are in the pilot, and nothing here should
 * ever learn: adding a slug or an id to this file would create a second
 * source of truth that drifts the first time the pilot changes.
 *
 * Returns `false` rather than throwing when the fetch fails or there is
 * no active Collective. Hiding a surface a creator could have used is a
 * recoverable annoyance; showing one whose every write 404s is the
 * defect this exists to prevent.
 */
export async function offeringsAvailableForActiveSpace(): Promise<boolean> {
  const active = await getActiveCreatorSpace()
  if (!active) return false
  try {
    const detail = await getCreatorSpace(active.slug) as CreatorSpaceDetail | null
    return detail?.offerings_available === true
  } catch {
    return false
  }
}

/**
 * Guard a Creator Studio Offerings route.
 *
 * `notFound()` rather than a redirect or an upgrade notice, matching
 * what the backend already does: `require_pilot_space` answers 404 so a
 * refusal never confirms the feature exists for Collectives that cannot
 * see it. For a creator outside the pilot, Offerings should look exactly
 * as it does with the feature switched off — because for them, it is.
 *
 * This is a second line, not the only one. The sidebar hides the entry,
 * this stops a typed or bookmarked URL, and the backend refuses the
 * writes regardless. Removing any one of the three must not open the
 * other two.
 */
export async function requireOfferingsAvailable(): Promise<void> {
  if (!(await offeringsAvailableForActiveSpace())) notFound()
}
