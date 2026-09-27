/**
 * Recognition where the shared thing already is.
 *
 * A server component that asks Ways to Connect what the viewer
 * shares, finds this Gathering or this Pathway in the answer, and
 * renders one quiet line — or nothing at all, which is the usual
 * case and must cost the page nothing visually.
 *
 * Every failure mode is silence. On a Gathering page, Recognition is
 * a grace note; a member who came to read the details should never
 * see an error about a sentence they did not ask for. The
 * destination is where failure is worth reporting, because there the
 * failure *is* the page.
 *
 * Gated on the same frontend flag as the destination, so nothing
 * leaks onto existing pages before the surface opens.
 */

import { isWaysToConnectEnabled } from '@/lib/featureFlags'
import { getWaysToConnect } from '@/lib/serverApi'
import {
  findGatheringContext,
  findPathwayContext,
  type PersonRef,
  type SharedContext,
} from '@/lib/waysToConnect'
import RecognitionNote from './RecognitionNote'

async function resolve(
  find: (people: PersonRef[]) => SharedContext | null,
): Promise<SharedContext | null> {
  if (!isWaysToConnectEnabled()) return null
  const result = await getWaysToConnect()
  if (result.status !== 'ok') return null
  // Derived from the same people the destination features, so the
  // line here and the card there can never disagree about who is in
  // the room.
  return find(result.data.people)
}

/** "You'll be here with Sarah and 2 other people." */
export async function GatheringRecognition({
  gatheringId,
}: {
  gatheringId: string
}) {
  const context = await resolve((people) => findGatheringContext(people, gatheringId))
  if (!context) return null
  return <RecognitionNote context={context} vantage="here" />
}

/** "You're moving through this with Emma." */
export async function PathwayRecognition({
  pathwayId,
}: {
  pathwayId: string
}) {
  const context = await resolve((people) => findPathwayContext(people, pathwayId))
  if (!context) return null
  return <RecognitionNote context={context} vantage="here" />
}
