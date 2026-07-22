'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { NotificationItem, NotificationsResponse } from '@/types/platform'

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

interface Props {
  initialCount: number
}

export default function NotificationBell({ initialCount }: Props) {
  const router = useRouter()
  const [unreadCount, setUnreadCount] = useState(initialCount)
  const [open, setOpen] = useState(false)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [loadingNotifs, setLoadingNotifs] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Poll unread count every 60 seconds
  const fetchUnreadCount = useCallback(async () => {
    try {
      const res = await fetch(apiUrl('/api/notifications/unread-count'), {
        credentials: 'include',
        cache: 'no-store',
      })
      if (res.ok) {
        const data = await res.json()
        setUnreadCount(data.count ?? 0)
      }
    } catch {
      // Silently ignore polling errors
    }
  }, [])

  useEffect(() => {
    const interval = setInterval(fetchUnreadCount, 60000)
    const onFocus = () => void fetchUnreadCount()
    window.addEventListener('focus', onFocus)
    return () => {
      clearInterval(interval)
      window.removeEventListener('focus', onFocus)
    }
  }, [fetchUnreadCount])

  // Fetch notifications when dropdown opens
  const fetchNotifications = useCallback(async () => {
    setLoadingNotifs(true)
    try {
      const res = await fetch(apiUrl('/api/notifications?limit=8'), {
        credentials: 'include',
        cache: 'no-store',
      })
      if (res.ok) {
        const data: NotificationsResponse = await res.json()
        setNotifications(data.notifications)
        setUnreadCount(data.unread_count)
      }
    } catch {
      // Silently ignore
    } finally {
      setLoadingNotifs(false)
    }
  }, [])

  const handleToggle = () => {
    if (!open) {
      void fetchNotifications()
    }
    setOpen((prev) => !prev)
  }

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handleMouseDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [open])

  const handleMarkAllRead = async () => {
    try {
      await fetch(apiUrl('/api/notifications/read-all'), {
        method: 'POST',
        credentials: 'include',
      })
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })))
      setUnreadCount(0)
    } catch {
      // Silently ignore
    }
  }

  const handleNotificationClick = async (notif: NotificationItem) => {
    if (!notif.is_read) {
      try {
        await fetch(apiUrl(`/api/notifications/${notif.id}/read`), {
          method: 'POST',
          credentials: 'include',
        })
        setNotifications((prev) =>
          prev.map((n) => (n.id === notif.id ? { ...n, is_read: true } : n))
        )
        setUnreadCount((prev) => Math.max(0, prev - 1))
      } catch {
        // Silently ignore
      }
    }
    setOpen(false)
    if (notif.url) {
      router.push(notif.url)
    }
  }

  return (
    <div ref={containerRef} className="relative">
      {/* Bell button */}
      <button
        onClick={handleToggle}
        aria-label="Notifications"
        className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-navy-100 text-navy-500 transition-all hover:border-navy-200 hover:bg-navy-50 hover:text-navy-900"
      >
        {/* Bell SVG */}
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>

        {/* Unread badge */}
        {unreadCount > 0 && (
          <span
            className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-[10px] font-bold text-white"
            style={{ background: '#38A09E' }}
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown panel */}
      {open && (
        <div
          className="absolute right-0 top-11 z-50 w-80 rounded-xl border border-navy-100 bg-white shadow-xl"
          style={{ boxShadow: '0 8px 32px rgba(13,27,42,0.12)' }}
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-navy-50 px-4 py-3">
            <span className="text-[13px] font-semibold text-navy-900">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAllRead}
                className="text-[12px] font-medium transition-colors"
                style={{ color: '#38A09E' }}
              >
                Mark all as read
              </button>
            )}
          </div>

          {/* Notification list */}
          <div className="max-h-80 overflow-y-auto">
            {loadingNotifs ? (
              <div className="px-4 py-6 text-center text-[13px] text-black">Loading…</div>
            ) : notifications.length === 0 ? (
              <div className="px-4 py-6 text-center text-[13px] text-black">
                No notifications yet.
              </div>
            ) : (
              notifications.map((notif) => (
                <button
                  key={notif.id}
                  onClick={() => void handleNotificationClick(notif)}
                  className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-navy-50"
                  style={
                    !notif.is_read
                      ? { borderLeft: '3px solid #38A09E', background: 'rgba(56,160,158,0.04)' }
                      : { borderLeft: '3px solid transparent' }
                  }
                >
                  {/* Unread dot */}
                  {!notif.is_read && (
                    <span
                      className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                      style={{ background: '#38A09E' }}
                    />
                  )}
                  {notif.is_read && <span className="mt-1.5 h-2 w-2 shrink-0" />}
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px] font-medium text-navy-900 leading-snug">
                      {notif.title}
                    </p>
                    <p className="mt-0.5 truncate text-[12px] text-black leading-snug">
                      {notif.message}
                    </p>
                    <p className="mt-1 text-[11px] text-black">
                      {relativeTime(notif.created_at)}
                    </p>
                  </div>
                </button>
              ))
            )}
          </div>

          {/* Footer */}
          <div className="border-t border-navy-50 px-4 py-2.5">
            <Link
              href="/notifications"
              onClick={() => setOpen(false)}
              className="block text-center text-[12px] font-medium transition-colors"
              style={{ color: '#38A09E' }}
            >
              View all notifications
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
