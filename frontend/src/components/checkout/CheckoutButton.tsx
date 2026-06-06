'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'

interface CheckoutButtonProps {
  pathwayId: string
  label?: string
}

export function CheckoutButton({ pathwayId, label = 'Unlock pathway' }: CheckoutButtonProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleClick() {
    setLoading(true)
    setError(null)
    try {
      const base = window.location.origin + window.location.pathname
      // {CHECKOUT_SESSION_ID} is a Stripe template variable — replaced at redirect time
      const successUrl = `${base}?success=true&session_id={CHECKOUT_SESSION_ID}`
      const cancelUrl = `${base}?cancelled=true`

      const res = await fetch(apiUrl('/api/checkout/pathway'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pathway_id: pathwayId,
          success_url: successUrl,
          cancel_url: cancelUrl,
        }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        const detail = (data as { detail?: string }).detail
        if (res.status === 409) {
          // Already purchased — reload so the server component shows the access-granted state
          window.location.reload()
          return
        }
        setError(detail ?? 'Something went wrong. Please try again.')
        return
      }

      const { checkout_url } = await res.json() as { checkout_url: string }
      window.location.href = checkout_url
    } catch {
      setError('Could not start checkout. Please check your connection and try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        className="w-full rounded-full px-5 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
      >
        {loading ? 'Redirecting to checkout…' : label}
      </button>
      {error && (
        <p className="text-center text-[12px] text-red-500">{error}</p>
      )}
    </div>
  )
}
