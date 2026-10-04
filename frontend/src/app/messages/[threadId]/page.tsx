import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import { isWaysToConnectEnabled } from '@/lib/featureFlags'
import { getMe, getPeerThread } from '@/lib/serverApi'
import type { PeerThreadDetail } from '@/lib/peerMessages'
import PeerConversationClient from './PeerConversationClient'

export const metadata: Metadata = {
  title: 'Conversation · Fresh Collective',
  robots: { index: false, follow: false },
}

/**
 * One private conversation.
 *
 * The API answers 404 both for a thread that does not exist and for one
 * belonging to other people, so this cannot tell them apart either —
 * which is the point. ``notFound()`` for both.
 *
 * Loading the thread also marks the other person's messages as read:
 * opening a conversation is reading it, and that is the whole of the
 * read model in v1.
 */
export default async function ConversationPage({
  params,
}: {
  params: Promise<{ threadId: string }>
}) {
  if (!isWaysToConnectEnabled()) notFound()

  const { threadId } = await params
  const [thread, me] = await Promise.all([
    getPeerThread(threadId) as Promise<PeerThreadDetail | null>,
    getMe().catch(() => null),
  ])
  if (!thread || !me?.id) notFound()

  return (
    <SiteShell>
      <div className="mx-auto max-w-[680px] px-6 pb-24 pt-8 md:px-8">
        <Link
          href="/messages"
          className="text-[13px] font-medium transition-opacity hover:opacity-70"
          style={{ color: '#2F8F8D' }}
        >
          ← All messages
        </Link>
        <PeerConversationClient initialThread={thread} currentUserId={me.id} />
      </div>
    </SiteShell>
  )
}
