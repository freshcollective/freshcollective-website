import { cookies } from 'next/headers'
import { apiUrl } from '@/lib/api'
import { SESSION_COOKIE } from '@/lib/session'
import type { NotificationsResponse, NotificationItem } from '@/types/platform'
import {
  notificationDestination,
  notificationLabel,
  notificationRelativeTime,
  notificationTint,
} from '@/lib/notifications'
import NotificationsClient from './NotificationsClient'
import NotificationRowLink from './NotificationRowLink'

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

export default async function NotificationsPage() {
  const { notifications, unread_count } = await getNotifications(50, 0)

  return (
    <div
      className="min-h-screen"
      style={{
        background:
          'radial-gradient(90% 40% at 50% 0%, rgba(56, 160, 158, 0.05), transparent 65%),' +
          'linear-gradient(180deg, #FBFDFD 0%, #FFFFFF 100%)',
      }}
    >
      <div className="mx-auto max-w-2xl px-4 py-10">
        {/* Header */}
        <div className="mb-6 flex items-end justify-between">
          <div>
            <p
              className="mb-2 text-[11px] font-semibold uppercase"
              style={{ color: '#0f766e', letterSpacing: '0.24em' }}
            >
              Notifications
            </p>
            <h1
              className="font-serif text-[26px] leading-tight"
              style={{ color: '#0C1826', letterSpacing: '-0.01em' }}
            >
              {unread_count > 0
                ? `${unread_count} new ${unread_count === 1 ? 'note' : 'notes'} for you`
                : 'You\u2019re all caught up.'}
            </h1>
          </div>
          {unread_count > 0 && <NotificationsClient />}
        </div>

        {/* List */}
        <div
          className="overflow-hidden rounded-2xl bg-white"
          style={{ border: '1px solid rgba(12, 24, 38, 0.06)' }}
        >
          {notifications.length === 0 ? (
            <div className="px-6 py-16 text-center">
              <p
                className="font-serif text-[17px]"
                style={{ color: '#0C1826' }}
              >
                Nothing to note yet.
              </p>
              <p
                className="mx-auto mt-2 max-w-sm text-[13.5px] italic leading-relaxed"
                style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
              >
                Activity in your collectives will land here — only when it matters.
              </p>
            </div>
          ) : (
            <ul>
              {notifications.map((notif) => (
                <li key={notif.id}>
                  <NotificationRow notif={notif} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

function NotificationRow({ notif }: { notif: NotificationItem }) {
  const tint = notificationTint(notif.notification_type)
  const label = notificationLabel(notif.notification_type)
  const href = notificationDestination(notif)
  const unread = !notif.is_read

  return (
    <NotificationRowLink
      notificationId={notif.id}
      href={href}
      markReadIfUnread={unread}
      className="group flex items-start gap-4 px-5 py-4 transition-colors hover:bg-slate-50"
      style={{
        borderTop: '1px solid rgba(12, 24, 38, 0.05)',
        background: unread ? 'rgba(56, 160, 158, 0.03)' : '#FFFFFF',
        borderLeft: unread ? '3px solid #38A09E' : '3px solid transparent',
      }}
    >
      {/* Category icon disc — full colour when unread, muted greyscale
          when read. Same shape either way so rows still scan cleanly. */}
      <span
        aria-hidden="true"
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[15px]"
        style={
          unread
            ? { background: tint.bg, color: tint.fg }
            : { background: 'rgba(12, 24, 38, 0.05)', color: 'rgba(12, 24, 38, 0.40)' }
        }
      >
        {tint.icon}
      </span>

      {/* Content — when read, everything drops in weight + colour. */}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
            style={
              unread
                ? { background: tint.bg, color: tint.fg }
                : {
                    background: 'rgba(12, 24, 38, 0.05)',
                    color: 'rgba(12, 24, 38, 0.50)',
                  }
            }
          >
            {label}
          </span>
          <span
            className="text-[12px]"
            style={{ color: unread ? 'rgba(12, 24, 38, 0.50)' : 'rgba(12, 24, 38, 0.38)' }}
          >
            {notificationRelativeTime(notif.created_at)}
          </span>
        </div>
        <p
          className="mt-1.5 text-[14.5px] leading-snug"
          style={{
            color: unread ? '#0C1826' : 'rgba(12, 24, 38, 0.55)',
            fontWeight: unread ? 600 : 400,
          }}
        >
          {notif.title}
        </p>
        {notif.message && (
          <p
            className="mt-0.5 text-[13.5px] leading-snug"
            style={{ color: unread ? 'rgba(12, 24, 38, 0.72)' : 'rgba(12, 24, 38, 0.45)' }}
          >
            {notif.message}
          </p>
        )}
      </div>

      {/* Chevron only appears on hover — subtle affordance, never noisy. */}
      <span
        aria-hidden="true"
        className="mt-1.5 shrink-0 text-[13px] opacity-0 transition-opacity group-hover:opacity-100"
        style={{ color: '#38A09E' }}
      >
        →
      </span>
    </NotificationRowLink>
  )
}
