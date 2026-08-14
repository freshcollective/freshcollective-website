'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'
import {
  paletteHex,
  type CollectivePaletteMeta,
} from '@/lib/collectivePalette'

/**
 * Kick off a unified Payment Option purchase for a Gathering Series.
 *
 * Calls ``POST /api/checkout`` with:
 *   payment_option_id, payment_option_schedule_id,
 *   success_url = current Series URL + ?checkout=success,
 *   cancel_url  = current Series URL + ?checkout=cancel.
 *
 * The backend handles both paths:
 *   * Paid options → returns a Stripe-hosted checkout URL; we
 *     redirect to it.
 *   * Free options → already fulfilled server-side; the backend
 *     returns our own success_url as the checkout_url and we
 *     redirect there (the query flag lets the page render a
 *     "You're in" confirmation).
 *
 * Duplicate guard: the backend refuses if the buyer already
 * actively holds the same Payment Option (409). We surface the
 * detail message inline rather than silently swallowing.
 */
export default function SeriesPurchaseButton({
  spaceSlug, seriesSlug, paymentOptionId, paymentOptionScheduleId, label,
  palette,
}: {
  spaceSlug: string
  seriesSlug: string
  paymentOptionId: string
  paymentOptionScheduleId: string
  label: string
  /** Optional Collective palette — button uses the primary hex
   *  so the CTA feels branded to the Collective. Falls back to
   *  the platform teal when the Space has no palette hydrated. */
  palette?: CollectivePaletteMeta | null
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleClick() {
    setBusy(true)
    setError(null)
    try {
      const origin = window.location.origin
      const base = `${origin}/spaces/${spaceSlug}/gathering-series/${seriesSlug}`
      const res = await fetch(apiUrl('/api/checkout'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          payment_option_id: paymentOptionId,
          payment_option_schedule_id: paymentOptionScheduleId,
          success_url: `${base}?checkout=success`,
          cancel_url: `${base}?checkout=cancel`,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : `Checkout failed (${res.status})`)
      }
      const data = await res.json() as { checkout_url: string }
      window.location.href = data.checkout_url
    } catch (err) {
      setError(String((err as Error)?.message ?? err))
      setBusy(false)
    }
  }

  const bg = paletteHex('primary', palette) ?? '#38A09E'
  return (
    <div className="flex w-full flex-col items-stretch gap-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="inline-flex w-full items-center justify-center rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
        style={{ background: bg }}
      >
        {busy ? 'Starting…' : label}
      </button>
      {error && (
        <p className="rounded-md bg-red-50 px-2 py-1 text-center text-[11px] text-red-700">
          {error}
        </p>
      )}
    </div>
  )
}
