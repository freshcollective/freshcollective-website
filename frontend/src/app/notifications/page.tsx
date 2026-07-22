import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import { SESSION_COOKIE } from '@/lib/session'
import type { NotificationsResponse, NotificationItem } from '@/types/platform'
import NotificationsClient from './NotificationsClient'

async function getNotifications(limit = 50, offset = 0): Promise<NotificationsResponse> {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value ?? ''
  if (!token) return { notifications: [], unread_count: 0 }
  try {
    const res = await fetch(
      apiUrl(`/api/notifications?limit=${limit}&offset=${offset}`),
      {
        headers: { Cookie: `${SESSION_COOKIE}=${token}` },
        cache: 'no-store',
      }
    )
    if (res.status === 401) return { notifications: [], unread_count: 0 }
    if (!res.ok) return { notifications: [], unread_count: 0 }
    return res.json() as Promise<NotificationsResponse>
  } catch {
    return { notifications: [], unread_count: 0 }
  }
}

function typeBadgeLabel(type: string): string {
  const map: Record<string, string> = {
    comment_reply: 'Reply',
    new_post: 'Conversation',
    event_reminder: 'Event',
    new_pathway: 'Pathway',
    new_pathway_step: 'New Step',
    admin_broadcast: 'Announcement',
    new_member: 'Member',
    event_registration: 'Booking',
    pathway_completed: 'Completed',
    direct_message: 'Message',
    // Community Phase 1
    mention: 'Mention',
    caretaker_answer: 'Answered',
  }
  return map[type] ?? type
}

function typeBadgeColor(type: string): string {
  const map: Record<string, string> = {
    comment_reply: '#38A09E',
    new_post: '#6B7280',
    event_reminder: '#F59E0B',
    new_pathway: '#8B5CF6',
    new_pathway_step: '#8B5CF6',
    admin_broadcast: '#EF4444',
    new_member: '#10B981',
    event_registration: '#3B82F6',
    pathway_completed: '#38A09E',
    direct_message: '#0f766e',
    // Community Phase 1
    mention: '#5C4577',
    caretaker_answer: '#0f766e',
  }
  return map[type] ?? '#9CA3AF'
}

function relativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  const diffHr = Math.floor(diffMs / 3600000)
  const diffDay = Math.floor(diffMs / 86400000)
  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${diffMin} min ago`
  if (diffHr < 24) return `${diffHr}h ago`
  if (diffDay === 1) return 'Yesterday'
  return `${diffDay}d ago`
}

export default async function NotificationsPage() {
  const data = await getNotifications(50, 0)
  const { notifications, unread_count } = data

  return (
    <div className="min-h-screen" style={{ background: '#F5F5F2' }}>
      <div className="mx-auto max-w-2xl px-4 py-10">
        {/* Page header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-[22px] font-bold tracking-[-0.02em] text-navy-950">
              Notifications
            </h1>
            {unread_count > 0 && (
              <p className="mt-0.5 text-[13px] text-black">
                {unread_count} unread
              </p>
            )}
          </div>
          {unread_count > 0 && <NotificationsClient />}
        </div>

        {/* List */}
        <div className="overflow-hidden rounded-xl border border-navy-100 bg-white">
          {notifications.length === 0 ? (
            <div className="px-6 py-16 text-center">
              <p className="text-[15px] text-black">No notifications yet.</p>
              <p className="mt-1 text-[13px] text-black">
                We&apos;ll notify you about activity in your collectives.
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-navy-50">
              {notifications.map((notif: NotificationItem) => (
                <li
                  key={notif.id}
                  className="flex items-start gap-4 px-5 py-4"
                  style={
                    !notif.is_read
                      ? { background: 'rgba(56,160,158,0.03)', borderLeft: '3px solid #38A09E' }
                      : { borderLeft: '3px solid transparent' }
                  }
                >
                  {/* Unread indicator */}
                  <div className="mt-1.5 flex-shrink-0">
                    {!notif.is_read ? (
                      <span
                        className="block h-2 w-2 rounded-full"
                        style={{ background: '#38A09E' }}
                      />
                    ) : (
                      <span className="block h-2 w-2" />
                    )}
                  </div>

                  {/* Content */}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      {/* Type badge */}
                      <span
                        className="rounded-full px-2 py-0.5 text-[11px] font-semibold text-white"
                        style={{ background: typeBadgeColor(notif.notification_type) }}
                      >
                        {typeBadgeLabel(notif.notification_type)}
                      </span>
                      <span className="text-[12px] text-black">
                        {relativeTime(notif.created_at)}
                      </span>
                    </div>
                    <p className="mt-1 text-[14px] font-semibold text-navy-900 leading-snug">
                      {notif.title}
                    </p>
                    <p className="mt-0.5 text-[13px] text-black leading-snug">
                      {notif.message}
                    </p>
                    {notif.url && (
                      <a
                        href={notif.url}
                        className="mt-1.5 inline-block text-[12px] font-medium transition-colors"
                        style={{ color: '#38A09E' }}
                      >
                        View &rarr;
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
