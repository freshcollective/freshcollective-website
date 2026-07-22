'use client'

import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

export default function NotificationsClient() {
  const router = useRouter()

  const handleMarkAllRead = async () => {
    try {
      await fetch(apiUrl('/api/notifications/read-all'), {
        method: 'POST',
        credentials: 'include',
      })
      router.refresh()
    } catch {
      // Silently ignore
    }
  }

  return (
    <button
      onClick={handleMarkAllRead}
      className="rounded-xl border border-navy-100 px-4 py-2 text-[13px] font-medium text-black transition-all hover:border-navy-200 hover:bg-navy-50"
    >
      Mark all as read
    </button>
  )
}
