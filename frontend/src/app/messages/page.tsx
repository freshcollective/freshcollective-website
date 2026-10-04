import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import PageHero from '@/components/layout/PageHero'
import SiteShell from '@/components/layout/SiteShell'
import MemberImage from '@/components/ui/MemberImage'
import { isWaysToConnectEnabled } from '@/lib/featureFlags'
import { getPeerThreads } from '@/lib/serverApi'
import { participantName, type PeerThreadSummary } from '@/lib/peerMessages'

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
  if (!isWaysToConnectEnabled()) notFound()

  const threads = (await getPeerThreads()) as PeerThreadSummary[]

  return (
    <SiteShell>
      <PageHero
        title="Messages"
        supportingCopy="Private conversations with people you’ve both said hello to."
      />
      <div className="mx-auto max-w-[680px] px-6 pb-24 pt-2 md:px-8">
        {threads.length === 0 ? (
          <p
            className="rounded-2xl bg-white px-6 py-8 text-center text-[14px] italic"
            style={{
              color: 'rgba(12, 24, 38, 0.62)',
              fontFamily: 'Georgia, serif',
              border: '1px solid rgba(12,24,38,0.08)',
            }}
          >
            No conversations yet. When you and someone else have both
            said hello, you&rsquo;ll be able to talk here.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {threads.map((thread) => {
              const name = participantName(thread.other)
              const unread = thread.unread_count > 0
              return (
                <li key={thread.thread_id}>
                  <Link
                    href={`/messages/${thread.thread_id}`}
                    className="flex items-center gap-4 rounded-2xl bg-white px-4 py-3.5 transition-colors hover:bg-teal-50/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                    style={{ border: '1px solid rgba(12,24,38,0.08)' }}
                  >
                    <span className="h-12 w-12 shrink-0 overflow-hidden rounded-full">
                      <MemberImage image={thread.other.image} className="h-12 w-12" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span
                        className="block truncate text-[14.5px]"
                        style={{
                          color: '#0C1826',
                          fontWeight: unread ? 600 : 500,
                        }}
                      >
                        {name}
                      </span>
                      {/* A preview, not the conversation. Truncated by
                          CSS rather than sliced, so no partial word. */}
                      <span
                        className="block truncate text-[13px]"
                        style={{ color: 'rgba(12, 24, 38, 0.56)' }}
                      >
                        {thread.last_message ?? 'No messages yet'}
                      </span>
                    </span>
                    {unread && (
                      <span
                        aria-label={`${thread.unread_count} unread`}
                        className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold text-white"
                        style={{ background: '#38A09E' }}
                      >
                        {thread.unread_count}
                      </span>
                    )}
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </SiteShell>
  )
}
