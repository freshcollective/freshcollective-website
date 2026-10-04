import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import PageHero from '@/components/layout/PageHero'
import SiteShell from '@/components/layout/SiteShell'
import { waysToConnectVisible } from '@/lib/waysToConnectPreview'
import { getPeerThreads } from '@/lib/serverApi'
import PeerThreadList from '@/components/messages/PeerThreadList'
import type { PeerThreadSummary } from '@/lib/peerMessages'

export const metadata: Metadata = {
  title: 'Messages · Fresh Collective',
  robots: { index: false, follow: false },
}

/**
 * Never prerendered.
 *
 * Without this the page is static at build time, when
 * ``isWaysToConnectEnabled()`` is false — so Next bakes in the
 * ``notFound()`` result and keeps serving that 404 after the flag is
 * turned on. The conversations are also per-member, so a shared
 * snapshot would be wrong even with the flag on.
 */
export const dynamic = 'force-dynamic'

/**
 * /messages — the member's private conversations.
 *
 * A deliberately separate destination from
 * ``/spaces/[slug]/messages``, which is a Collective's creator talking
 * to its members. This is the peer surface: conversations that exist
 * because two people said hello to each other, belonging to no
 * Collective. Keeping them apart is the same decision as the two
 * database tables — see ``app/models/peer_messages.py``.
 *
 * Gated on the Ways to Connect flag, because that is the only way a
 * conversation can come to exist. There is no second flag: a member
 * with no connections would see an empty page, and nothing here is
 * reachable while the surface that creates connections is off.
 */
export default async function MessagesPage() {
  if (!(await waysToConnectVisible())) notFound()

  const threads = (await getPeerThreads()) as PeerThreadSummary[]

  return (
    <SiteShell>
      <PageHero
        title="Messages"
        supportingCopy="Private conversations with people you’ve both said hello to."
      />
      <div className="mx-auto max-w-[680px] px-6 pb-24 pt-2 md:px-8">
        <PeerThreadList threads={threads} />
      </div>
    </SiteShell>
  )
}
