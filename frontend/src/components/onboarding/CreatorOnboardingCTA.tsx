'use client'

/**
 * CreatorOnboardingCTA — the single button that ends the short
 * Creator welcome and forwards the visitor into Build Your Collective.
 *
 * POSTs to /api/auth/me/complete-creator-onboarding to set the
 * ``creator_onboarded_at`` timestamp (idempotent server-side), then
 * navigates to /build-your-collective and refreshes so future page
 * loads see the flag as true.
 *
 * No skip option — the welcome is intentionally short enough that
 * reading it once is the price of entry.
 */

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Button from '@/components/ui/Button'
import { apiUrl } from '@/lib/api'

export default function CreatorOnboardingCTA() {
  const router = useRouter()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleClick() {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl('/api/auth/me/complete-creator-onboarding'),
        { method: 'POST', credentials: 'include' },
      )
      if (!res.ok) {
        setError('Could not save your progress. Please try again.')
        return
      }
      router.push('/build-your-collective')
      router.refresh()
    } catch {
      setError('Could not reach the server. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col items-start gap-3">
      <Button
        type="button"
        variant="primary"
        size="md"
        onClick={handleClick}
        disabled={busy}
      >
        {busy ? 'Opening…' : 'Build your first Collective →'}
      </Button>
      {error && (
        <p role="alert" className="text-[13px]" style={{ color: '#B32424' }}>
          {error}
        </p>
      )}
    </div>
  )
}
