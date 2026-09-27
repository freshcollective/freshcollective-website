/**
 * Recognition on a Collective's own page.
 *
 * A Collective never produces Recognition by itself — sharing a
 * Collective with two hundred people says nothing about any of them,
 * which is the whole reason co-membership is the privacy boundary
 * and not the evidence. What this section shows is strictly the
 * Gatherings and Pathways *inside* this Collective that the member
 * genuinely shares with someone. Nothing is derived at the
 * Collective level; this is a filter, not a new kind of evidence.
 *
 * Renders nothing when there is nothing, which will be most
 * Collectives for most members.
 *
 * The heading names the shared things rather than the people, even
 * though the people are the reason it is interesting. A section
 * headed "people" above a list of Gatherings sets up the wrong
 * expectation and starts the slide toward a directory.
 */

import { isWaysToConnectEnabled } from '@/lib/featureFlags'
import { getWaysToConnect } from '@/lib/serverApi'
import { contextsInCollective } from '@/lib/waysToConnect'
import SharedContextCard from './SharedContextCard'

export default async function CollectiveRecognition({
  collectiveId,
  collectiveName,
}: {
  collectiveId: string
  collectiveName: string
}) {
  if (!isWaysToConnectEnabled()) return null

  const result = await getWaysToConnect()
  // Silent on failure: this is a grace note on somebody else's page.
  if (result.status !== 'ok') return null

  const contexts = contextsInCollective(result.data.people, collectiveId)
  if (contexts.length === 0) return null

  return (
    <section className="mt-12">
      <h2 className="font-serif text-[15px]" style={{ color: '#0C1826' }}>
        Where your paths have crossed
      </h2>
      <p className="mt-1 text-[12.5px]" style={{ color: 'rgba(12, 24, 38, 0.5)' }}>
        Gatherings and pathways in {collectiveName} you’ve shared with
        other people.
      </p>
      <ul className="mt-4 flex flex-col gap-3">
        {contexts.map((c) => (
          <SharedContextCard key={`${c.kind}-${c.id}`} context={c} />
        ))}
      </ul>
    </section>
  )
}
