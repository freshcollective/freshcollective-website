import Link from 'next/link'
import MemberImage from '@/components/ui/MemberImage'
import { participantName, type PeerThreadSummary } from '@/lib/peerMessages'

/**
 * The member's conversation list.
 *
 * Presentational and prop-driven: extracted from
 * ``app/messages/page.tsx`` so the admin preview harness can render the
 * real list against fixtures rather than a second implementation that
 * would drift from it. The page still owns the fetching.
 *
 * ``hrefFor`` exists only so the admin preview harness can point rows
 * at its own conversation view instead of real threads. Production
 * passes nothing. Safe as a function prop because both this component
 * and its callers are server components.
 */
export default function PeerThreadList({
  threads,
  hrefFor = (threadId: string) => `/messages/${threadId}`,
}: {
  threads: PeerThreadSummary[]
  hrefFor?: (threadId: string) => string
}) {
  return (
    <>
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
                href={hrefFor(thread.thread_id)}
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
    </>
  )
}
