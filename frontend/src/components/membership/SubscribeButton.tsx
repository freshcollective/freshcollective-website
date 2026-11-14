'use client'

/**
 * The one way a member opens membership checkout.
 *
 * Used by the Collective About page and by the conversion prompt an
 * existing member sees. Both need identical behaviour — the amount is
 * never sent, the server prices it — so there is one component rather
 * than two that drift.
 *
 * The flag being off is a *state*, not an error. When billing is not
 * switched on the backend refuses with a code, and this says so
 * plainly instead of implying a payment system that is not there.
 */

import { useState } from 'react'
import { apiUrl } from '@/lib/api'
import { subscribeRefusalMessage } from '@/lib/membership'

interface Props {
  slug: string
  label: string
  className?: string
  style?: React.CSSProperties
  /** Where Stripe returns to. Defaults to the shared return page. */
  returnTo?: string
}

export default function SubscribeButton({
  slug, label, className, style, returnTo,
}: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function start() {
    setBusy(true)
    setError(null)
    try {
      const origin = window.location.origin
      const back = returnTo ?? `${origin}/checkout/membership?collective=${slug}`
      const res = await fetch(
        apiUrl(`/api/spaces/${slug}/membership/checkout`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            // No amount, no interval, no currency. The server reads
            // those from the Collective and freezes them onto the
            // agreement; a price in this body would be a price a
            // client chose.
            success_url: `${back}&checkout=complete`,
            cancel_url: `${back}&checkout=cancelled`,
          }),
        },
      )
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        const detail = body?.detail
        const code = typeof detail === 'object' && detail
          ? (detail as { code?: string }).code ?? null
          : null
        const message = typeof detail === 'object' && detail
          ? (detail as { message?: string }).message
          : typeof detail === 'string' ? detail : undefined
        setError(subscribeRefusalMessage(code) ?? message
          ?? 'We couldn’t start checkout. Please try again.')
        setBusy(false)
        return
      }
      if (typeof body.checkout_url === 'string') {
        window.location.href = body.checkout_url
        return
      }
      setError('We couldn’t start checkout. Please try again.')
      setBusy(false)
    } catch {
      setError('We couldn’t reach the server. Please try again.')
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={start}
        disabled={busy}
        className={className}
        style={style}
      >
        {busy ? 'Opening checkout…' : label}
      </button>
      {error && (
        <p className="text-[12.5px] leading-relaxed text-[#B0503C]">
          {error}
        </p>
      )}
    </div>
  )
}
