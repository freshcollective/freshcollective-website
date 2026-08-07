'use client'

import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

/**
 * Client wrapper around a full-row link on the notifications page.
 * Marks the notification as read *before* navigating so the badge
 * count and unread stripe update on return.
 */
interface Props {
  notificationId: string
  href: string
  markReadIfUnread: boolean
  className?: string
  style?: React.CSSProperties
  children: React.ReactNode
}

export default function NotificationRowLink({
  notificationId, href, markReadIfUnread, className, style, children,
}: Props) {
  const router = useRouter()

  async function handleClick(e: React.MouseEvent<HTMLAnchorElement>) {
    // Let the default happen for modifier-clicks (open in new tab, etc.)
    // — those don't warrant a mark-read side effect either.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
    e.preventDefault()
    if (markReadIfUnread) {
      try {
        await fetch(apiUrl(`/api/notifications/${notificationId}/read`), {
          method: 'POST',
          credentials: 'include',
        })
      } catch {
        // Non-critical — navigate anyway
      }
    }
    router.push(href)
    router.refresh()
  }

  return (
    <a
      href={href}
      onClick={handleClick}
      className={className}
      style={style}
    >
      {children}
    </a>
  )
}
