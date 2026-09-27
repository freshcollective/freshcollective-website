import { notFound } from 'next/navigation'
import Link from 'next/link'
import { failureError } from '@/lib/fetchOutcome'
import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'
import { getSpaceMessageThread } from '@/lib/serverApi'
import MessageThreadClient from './MessageThreadClient'

interface Props {
  params: Promise<{ slug: string; threadId: string }>
}

export default async function MessageThreadPage({ params }: Props) {
  const { slug, threadId } = await params
  // The established guard, rather than reading ``getMe()`` and treating a
  // null as a missing thread — which is what this page used to do, so a
  // failing ``/api/auth/me`` reported someone else's conversation as
  // nonexistent.
  const me = await requireAuthenticatedUser()

  const outcome = await getSpaceMessageThread(slug, threadId)
  // Three states, kept apart. A thread that is gone or was never yours is
  // genuinely not found; a server that could not answer is an error, and
  // saying "not found" about it sends the reader looking for a thread that
  // is sitting right there.
  if (outcome.kind === 'missing') notFound()
  if (outcome.kind === 'failure') {
    throw failureError(outcome, 'Loading this conversation')
  }
  const thread = outcome.data

  const otherName = me.id === thread.member_id ? thread.creator_name : thread.member_name

  return (
    <div className="max-w-2xl">
      <Link
        href={`/spaces/${slug}/messages`}
        className="mb-5 inline-block text-sm text-black hover:text-navy-700"
      >
        ← Messages
      </Link>

      <div className="mb-4 flex items-center gap-3">
        <div
          className="flex h-10 w-10 items-center justify-center rounded-full text-[12px] font-semibold"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.13))',
            color: 'var(--fc-accent, #0f766e)',
          }}
        >
          {otherName.split(' ').map((p: string) => p[0]).join('').toUpperCase().slice(0, 2)}
        </div>
        <div>
          <p className="font-semibold text-navy-900">{otherName}</p>
          <p className="text-[12px] text-black">Direct message</p>
        </div>
      </div>

      <MessageThreadClient
        initialThread={thread}
        currentUserId={me.id}
        spaceSlug={slug}
      />
    </div>
  )
}
