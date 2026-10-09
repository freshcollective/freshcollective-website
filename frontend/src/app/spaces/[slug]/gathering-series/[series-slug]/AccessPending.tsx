'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import {
  paletteHex,
  rgbaFromHex,
  type CollectivePaletteMeta,
} from '@/lib/collectivePalette'
import {
  ACCESS_POLL_INTERVAL_MS,
  ACCESS_POLL_MAX_ATTEMPTS,
  accessWaitCopy,
  accessWaitPhase,
} from '@/lib/regularSessions'

/**
 * The gap between paying and having access.
 *
 * The AccessPass is written by webhook-driven fulfilment
 * (``purchase_fulfilment``), not by the redirect back from Stripe. So a
 * member can arrive here with ``?checkout=success`` a second or two
 * before their pass exists — and in the weekly-payment setup flow,
 * where activation waits on the first payment event, the gap can be
 * longer.
 *
 * Before this component, that window fell through to "Ways to join",
 * which offered to sell them the term they had just bought. That is the
 * worst possible thing to show someone who has paid: it reads as a
 * failed payment, and the obvious response to it is to pay twice.
 *
 * So the window has its own state. It waits, it says the payment has
 * gone through, and when access appears it refreshes the page — at
 * which point the server component renders the real access card and
 * "Reserve your regular sessions" opens itself, exactly as it would
 * have if the webhook had won the race.
 *
 * Polling the Series detail endpoint rather than something new: it is
 * the endpoint that already answers "do I have access", and it is the
 * one this page was rendered from, so there is no second definition of
 * the answer.
 */
export default function AccessPending({
  spaceSlug, seriesSlug, palette,
}: {
  spaceSlug: string
  seriesSlug: string
  palette: CollectivePaletteMeta | null
}) {
  const router = useRouter()
  const primary = paletteHex('primary', palette) ?? '#0f766e'
  const [attempt, setAttempt] = useState(1)

  useEffect(() => {
    if (attempt >= ACCESS_POLL_MAX_ATTEMPTS) return
    let cancelled = false

    const timer = setTimeout(async () => {
      try {
        const res = await fetch(
          apiUrl(`/api/spaces/${spaceSlug}/gathering-series/${seriesSlug}`),
          { credentials: 'include', cache: 'no-store' },
        )
        if (!cancelled && res.ok) {
          const body = await res.json().catch(() => null)
          if (body?.access?.has_access) {
            // Re-render the server component. ``?checkout=success`` is
            // still in the URL, so the reserve card opens expanded.
            router.refresh()
            return
          }
        }
      } catch {
        // A failed poll is not news — the next one is due in three
        // seconds, and the member is told nothing alarming meanwhile.
      }
      if (!cancelled) setAttempt((n) => n + 1)
    }, ACCESS_POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [attempt, router, spaceSlug, seriesSlug])

  const copy = accessWaitCopy(accessWaitPhase(attempt))

  return (
    <div
      className="rounded-2xl border px-5 py-5"
      style={{
        borderColor: rgbaFromHex(primary, 0.24),
        background: rgbaFromHex(primary, 0.05),
      }}
      aria-live="polite"
    >
      <p className="font-serif text-lg text-navy-900">{copy.heading}</p>
      <p className="mt-2 text-[13px]" style={{ color: 'rgba(12,24,38,0.70)' }}>
        {copy.body}
      </p>
      {copy.showReload ? (
        <button
          type="button"
          onClick={() => router.refresh()}
          className="mt-4 rounded-lg px-4 py-2 text-[13px] font-semibold"
          style={{ background: primary, color: '#FFFFFF' }}
        >
          Reload
        </button>
      ) : (
        <p className="mt-3 text-[11.5px] text-slate-600">
          You can leave this page — your access will be here when you
          come back.
        </p>
      )}
    </div>
  )
}
