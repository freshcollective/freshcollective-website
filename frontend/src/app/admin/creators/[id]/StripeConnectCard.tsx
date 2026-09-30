'use client'

/**
 * World Management — Creator Detail → Stripe Connect routing card.
 *
 * An operational control, not a payout surface. It exposes the one
 * deliberate administrative act that decides whether a creator's future
 * sales are routed through Stripe Connect:
 *
 *   GET  /api/admin/creators/{id}/stripe-connect          readiness
 *   POST /api/admin/creators/{id}/stripe-connect/enable
 *   POST /api/admin/creators/{id}/stripe-connect/disable
 *
 * Deliberate choices here
 * ───────────────────────
 *   - Nothing is enabled automatically. The fetch is a read; the only
 *     writes are behind a button and a confirmation. This matters more
 *     than it looks: ``connect_payouts_enabled_at`` has exactly one
 *     writer in the system and it is the endpoint below.
 *   - Both actions confirm first, and the confirmation says what does
 *     *not* change — the creator's money changing path is worth one
 *     extra click.
 *   - The enable/disable responses carry the refreshed readiness, so the
 *     card re-renders from the response rather than firing a second GET
 *     and briefly showing stale state in between.
 *   - Client-side fetch on mount, unlike the rest of this page. Routing
 *     state is operational and changes independently of the creator
 *     record, and the page's server data comes from a batched list
 *     endpoint that has no business carrying it.
 *   - All decisions and copy live in ``@/lib/adminConnectRouting`` so
 *     they are tested without JSX. This file renders.
 *
 * Does not touch the plan controls above it or anything about payout
 * architecture. Enabling changes where *future* sales go; purchases and
 * plans already created keep the payout model they were created with.
 */

import { useCallback, useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'
import {
  describeRouting,
  errorMessageFrom,
  type RoutingTone,
} from '@/lib/adminConnectRouting'
import type { AdminConnectReadiness } from '@/types/platform'

const INK        = '#0C1826'
const INK_MUTED  = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER = 'rgba(12, 24, 38, 0.42)'
const CARD_BG    = '#FFFFFF'
const CARD_BORDER = '1px solid #E7EEF0'
const CARD_SHADOW = '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'

const UNREACHABLE = 'Could not reach the server to read Connect routing state.'

const TONE: Record<RoutingTone, { dot: string; bg: string; fg: string }> = {
  live:    { dot: '#22a598', bg: 'rgba(34, 165, 152, 0.10)', fg: '#0F766E' },
  ready:   { dot: '#4c78d4', bg: 'rgba(76, 120, 212, 0.10)', fg: '#2B4E9B' },
  blocked: { dot: '#d4b048', bg: 'rgba(212, 176, 72, 0.12)', fg: '#7C5B10' },
}

export default function StripeConnectCard({ userId }: { userId: string }) {
  const [readiness, setReadiness] = useState<AdminConnectReadiness | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const base = `/api/admin/creators/${userId}/stripe-connect`

  const load = useCallback(async () => {
    try {
      const res = await fetch(apiUrl(base), { credentials: 'include' })
      if (!res.ok) {
        setLoadError(errorMessageFrom(res.status, await readBody(res)))
        return
      }
      setReadiness((await res.json()) as AdminConnectReadiness)
      setLoadError(null)
    } catch {
      setLoadError(UNREACHABLE)
    }
  }, [base])

  // The initial read is a promise chain rather than an awaited call, the
  // same shape ``DiscountCodesClient`` uses: setState reached
  // synchronously from an effect body triggers cascading renders, and
  // ``react-hooks/set-state-in-effect`` rightly objects.
  useEffect(() => {
    fetch(apiUrl(base), { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) throw new Error(errorMessageFrom(r.status, await readBody(r)))
        return (await r.json()) as AdminConnectReadiness
      })
      .then((next) => { setReadiness(next); setLoadError(null) })
      .catch((err: unknown) => setLoadError(
        err instanceof Error ? err.message : UNREACHABLE,
      ))
  }, [base])

  async function act(kind: 'enable' | 'disable') {
    setBusy(true)
    setActionError(null)
    try {
      const res = await fetch(apiUrl(`${base}/${kind}`), {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) {
        setActionError(errorMessageFrom(res.status, await readBody(res)))
        // The 409 means our picture of readiness was out of date, so
        // replace it rather than leaving a button the backend refuses.
        await load()
        return
      }
      // Both endpoints answer with the refreshed readiness.
      setReadiness((await res.json()) as AdminConnectReadiness)
      setConfirming(false)
    } catch {
      setActionError('Could not reach the server. Nothing was changed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className="rounded-2xl px-6 py-5 md:px-7 md:py-6"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <div className="mb-4 flex items-center justify-between gap-4">
        <h2 className="font-serif text-[20px] leading-tight" style={{ color: INK }}>
          Stripe Connect routing
        </h2>
        {readiness && <Badge readiness={readiness} />}
      </div>

      {!readiness && !loadError && (
        <p className="text-[13px]" style={{ color: INK_SOFTER }}>Reading routing state…</p>
      )}

      {loadError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-700">
          {loadError}{' '}
          <button
            type="button"
            onClick={() => void load()}
            className="font-semibold underline underline-offset-2"
          >
            Try again
          </button>
        </div>
      )}

      {readiness && <Body
        readiness={readiness}
        busy={busy}
        confirming={confirming}
        actionError={actionError}
        onAsk={() => { setConfirming(true); setActionError(null) }}
        onCancel={() => setConfirming(false)}
        onConfirm={act}
      />}
    </section>
  )
}

// ---------------------------------------------------------------------------

function Badge({ readiness }: { readiness: AdminConnectReadiness }) {
  const view = describeRouting(readiness)
  const tone = TONE[view.tone]
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-semibold"
      style={{ background: tone.bg, color: tone.fg }}
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: tone.dot }} aria-hidden />
      {view.badge}
    </span>
  )
}

function Body({
  readiness, busy, confirming, actionError, onAsk, onCancel, onConfirm,
}: {
  readiness: AdminConnectReadiness
  busy: boolean
  confirming: boolean
  actionError: string | null
  onAsk: () => void
  onCancel: () => void
  onConfirm: (kind: 'enable' | 'disable') => void
}) {
  const view = describeRouting(readiness)
  const destructive = view.action === 'disable'

  return (
    <>
      <p className="text-[13.5px] leading-relaxed" style={{ color: INK_MUTED }}>
        {view.summary}
      </p>

      {view.blockers.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {view.blockers.map((b) => (
            <li key={b} className="flex gap-2 text-[12.5px] leading-relaxed" style={{ color: '#7C5B10' }}>
              <span aria-hidden style={{ color: '#d4b048' }}>•</span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}

      <dl className="mt-4 divide-y" style={{ borderColor: 'rgba(12, 24, 38, 0.06)' }}>
        {view.facts.map((f) => (
          <div key={f.label} className="flex items-center justify-between gap-4 py-2.5 first:pt-0 last:pb-0">
            <dt className="text-[12px] font-semibold uppercase tracking-[0.14em]" style={{ color: INK_SOFTER }}>
              {f.label}
            </dt>
            <dd className="text-right text-[13.5px]" style={{ color: INK }}>{f.value}</dd>
          </div>
        ))}
      </dl>

      {actionError && (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-700">
          {actionError}
        </div>
      )}

      {view.action !== 'none' && (
        <div className="mt-4">
          {!confirming ? (
            <button
              type="button"
              onClick={onAsk}
              className="rounded-full border px-4 py-1.5 text-[12.5px] font-semibold transition-colors"
              style={{ borderColor: '#E7EEF0', color: destructive ? '#B3261E' : INK, background: '#FFFFFF' }}
            >
              {view.actionLabel}
            </button>
          ) : (
            <div
              className="rounded-xl px-4 py-3.5"
              style={{ background: '#F7FAFB', border: '1px solid #E7EEF0' }}
            >
              <p className="text-[12.5px] leading-relaxed" style={{ color: INK }}>
                {view.confirmPrompt}
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={onCancel}
                  disabled={busy}
                  className="rounded-full border px-4 py-1.5 text-[12.5px] font-medium transition-colors disabled:opacity-50"
                  style={{ borderColor: '#E7EEF0', color: INK }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => onConfirm(destructive ? 'disable' : 'enable')}
                  disabled={busy}
                  className="rounded-full px-4 py-1.5 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                  style={{ background: destructive ? '#B3261E' : '#0F766E' }}
                >
                  {busy ? 'Applying…' : view.actionLabel}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}

async function readBody(res: Response): Promise<unknown> {
  try {
    return await res.json()
  } catch {
    return null
  }
}
