import { cookies } from 'next/headers'
import { notFound, redirect } from 'next/navigation'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import { SESSION_COOKIE } from '@/lib/session'
import { getMe } from '@/lib/serverApi'
import type { MessageThreadDetail } from '@/types/platform'
import MessageThreadClient from './MessageThreadClient'

interface Props {
  params: Promise<{ slug: string; threadId: string }>
}

async function getThread(slug: string, threadId: string): Promise<MessageThreadDetail | null> {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value ?? ''
  if (!token) return null
  try {
    const res = await fetch(apiUrl(`/api/spaces/${slug}/messages/${threadId}`), {
      headers: { Cookie: `${SESSION_COOKIE}=${token}` },
      cache: 'no-store',
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export default async function MessageThreadPage({ params }: Props) {
  const { slug, threadId } = await params
  const [thread, me] = await Promise.all([getThread(slug, threadId), getMe()])
  if (!thread || !me) notFound()

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
          style={{ background: 'rgba(56,160,158,0.13)', color: '#0f766e' }}
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
