'use client'

import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

export default function LogoutButton({ className }: { className?: string }) {
  const router = useRouter()

  async function handleLogout() {
    await fetch(apiUrl('/api/auth/logout'), {
      method: 'POST',
      credentials: 'include',
    }).catch(() => {})

    router.push('/')
    router.refresh()
  }

  return (
    <button type="button" onClick={handleLogout} className={className}>
      Log out
    </button>
  )
}
