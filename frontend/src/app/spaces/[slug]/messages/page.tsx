import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import { SESSION_COOKIE } from '@/lib/session'
import type { MessageThreadSummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

async function getThreads(slug: string): Promise<MessageThreadSummary[]> {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value ?? ''
  if (!token) return []
  try {
    const res = await fetch(apiUrl(`/api/spaces/${slug}/messages`), {
      headers: { Cookie: `${SESSION_COOKIE}=${token}` },
      cache: 'no-store',
    })
    if (!res.ok) return []
    return res.json()
  } catch {
    return []
  }
}

function relativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMin = Math.floor((now.getTime() - date.getTime()) / 60000)
  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay === 1) return 'Yesterday'
  if (diffDay < 7) return `${diffDay}d ago`
  return date.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}

function initials(name: string): string {
  return name.split(' ').map(p => p[0]).join('').toUpperCase().slice(0, 2)
}

export default async function MessagesPage({ params }: Props) {
  const { slug } = await params
  const threads = await getThreads(slug)

  return (
    <div className="max-w-2xl">
      <div className="mb-6">
        <h1 className="font-serif text-2xl text-navy-900">Messages</h1>
        <p className="mt-1 text-[14px] text-black">
          Private conversations with members and caretakers.
        </p>
      </div>

      {threads.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-8 py-12 text-center">
          <p className="text-[15px] font-medium text-navy-900">No messages yet</p>
          <p className="mt-1 text-[13px] text-black">
            When a team member messages you, their message will appear here.
          </p>
        </div>
      ) : (
        <div className="rounded-2xl border border-border bg-white">
          {threads.map((t, i) => (
            <Link
              key={t.thread_id}
              href={`/spaces/${slug}/messages/${t.thread_id}`}
              className={[
                'flex items-start gap-4 px-5 py-4 transition-colors hover:bg-slate-50/60',
                i < threads.length - 1 ? 'border-b border-border' : '',
              ].join(' ')}
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold"
                style={{
                  background: 'var(--fc-accent-soft, rgba(56,160,158,0.13))',
                  color: 'var(--fc-accent, #0f766e)',
                }}>
                {initials(t.other_user_name)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <p className={`text-[14px] ${t.unread_count > 0 ? 'font-semibold text-navy-900' : 'font-medium text-navy-800'}`}>
                    {t.other_user_name}
                  </p>
                  {t.last_message_at && (
                    <span className="shrink-0 text-[11px] text-black">
                      {relativeTime(t.last_message_at)}
                    </span>
                  )}
                </div>
                <p className={`mt-0.5 truncate text-[13px] ${t.unread_count > 0 ? 'text-navy-700' : 'text-black'}`}>
                  {t.last_message ?? 'No messages yet'}
                </p>
              </div>
              {t.unread_count > 0 && (
                <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white"
                  style={{ background: 'var(--fc-accent, #38A09E)' }}>
                  {t.unread_count > 9 ? '9+' : t.unread_count}
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
