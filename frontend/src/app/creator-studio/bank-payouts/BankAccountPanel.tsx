'use client'

/**
 * Your bank account · Your payouts.
 *
 * Two sections that sit beneath the readiness panel. Both are deliberately
 * thin: the masked bank details come from the projection the status endpoint
 * already returns, and the payouts come from Fresh Collective's projection
 * of Stripe's own ``Payout`` records.
 *
 * "Update bank details" opens Stripe's Express Dashboard. That is not a
 * shortcut — Stripe refuses both alternatives for accounts shaped like
 * Fresh Collective's, and it means FC never handles a BSB or account number
 * at any point.
 */

import { useEffect, useState } from 'react'

import {
  bankAccountView,
  historyNote,
  payoutRowView,
  payoutsFreshness,
  payoutsHeadline,
} from '@/lib/bankPayouts'
import type {
  CreatorBankPayout,
  CreatorBankPayoutsResponse,
  CreatorStripeConnectStatus,
} from '@/types/platform'

const CARD = 'rounded-xl bg-white px-4 py-4'
const CARD_BORDER = { border: '1px solid #E2E8F0' } as const

export default function BankAccountPanel({
  status,
}: {
  status: CreatorStripeConnectStatus | null
}) {
  const bank = bankAccountView(status)
  const [payouts, setPayouts] = useState<CreatorBankPayout[]>([])
  const [syncedAt, setSyncedAt] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [historyComplete, setHistoryComplete] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const connected = Boolean(status?.stripe_account_id)
  // Derived rather than set in the effect: a creator with no connected
  // account has nothing to fetch, so "loaded" is already true on the first
  // render and no cascading re-render is needed to say so.
  const [loaded, setLoaded] = useState(!connected)

  useEffect(() => {
    if (!connected) return
    let active = true
    void (async () => {
      try {
        const res = await fetch('/api/creator/stripe-connect/payouts', {
          credentials: 'include',
        })
        if (!res.ok) throw new Error(String(res.status))
        const body = (await res.json()) as CreatorBankPayoutsResponse
        if (!active) return
        setPayouts(body.payouts ?? [])
        setSyncedAt(body.synced_at ?? null)
        setHasMore(Boolean(body.has_more))
        setHistoryComplete(Boolean(body.history_complete))
      } catch {
        // An unavailable list is not an error a creator can act on, and the
        // sections above it are still useful. Say nothing rather than
        // showing a scary empty state as though there were no payouts.
        if (active) setError('We couldn’t load your payouts just now.')
      } finally {
        if (active) setLoaded(true)
      }
    })()
    return () => { active = false }
  }, [connected])

  async function openDashboard() {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch('/api/creator/stripe-connect/dashboard-link', {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(String(res.status))
      const body = (await res.json()) as { url?: string }
      if (!body.url) throw new Error('no url')
      // Same tab: the link is single-use and a blocked popup would look
      // like a broken button.
      window.location.href = body.url
    } catch {
      setError(
        'We couldn’t open your Stripe settings just now. Please try again.',
      )
      setBusy(false)
    }
  }

  async function loadMore() {
    setLoadingMore(true)
    try {
      const res = await fetch(
        `/api/creator/stripe-connect/payouts?offset=${payouts.length}`,
        { credentials: 'include' },
      )
      if (!res.ok) throw new Error(String(res.status))
      const body = (await res.json()) as CreatorBankPayoutsResponse
      setPayouts((current) => [...current, ...(body.payouts ?? [])])
      setHasMore(Boolean(body.has_more))
    } catch {
      setError('We couldn’t load more payouts just now.')
    } finally {
      setLoadingMore(false)
    }
  }

  const headline = payoutsHeadline(payouts, status)
  const freshness = payoutsFreshness(syncedAt)
  const history = connected ? historyNote(historyComplete, payouts.length) : null

  return (
    <div className="mt-6 space-y-4">
      {/* ── Your bank account ───────────────────────────────────── */}
      <section className={CARD} style={CARD_BORDER} aria-labelledby="bank-account">
        <h2
          id="bank-account"
          className="text-[14px] font-semibold text-navy-900"
        >
          Your bank account
        </h2>
        <p
          className={`mt-2 text-[13px] ${
            bank.present ? 'font-medium text-navy-900' : 'text-black'
          }`}
        >
          {bank.label}
        </p>
        <p className="mt-1 max-w-[62ch] text-[12px] leading-relaxed text-black">
          {bank.note}
        </p>
        {connected && (
          <button
            type="button"
            onClick={() => void openDashboard()}
            disabled={busy}
            className="mt-3 rounded-lg px-3.5 py-2 text-[13px] font-semibold text-white disabled:opacity-60"
            style={{ background: '#38A09E' }}
          >
            {busy
              ? 'Opening…'
              : bank.present ? 'Update bank details' : 'Add bank details'}
          </button>
        )}
        {error && (
          <p className="mt-2 text-[12px] text-black" role="status">
            {error}
          </p>
        )}
      </section>

      {/* ── Your payouts ────────────────────────────────────────── */}
      <section className={CARD} style={CARD_BORDER} aria-labelledby="your-payouts">
        <h2 id="your-payouts" className="text-[14px] font-semibold text-navy-900">
          {headline.headline}
        </h2>
        <p className="mt-1 max-w-[62ch] text-[12px] leading-relaxed text-black">
          {headline.body}
        </p>

        {loaded && payouts.length > 0 && (
          <ul className="mt-3 divide-y" style={{ borderColor: '#EEF2F6' }}>
            {payouts.map((p, i) => {
              const row = payoutRowView(p)
              return (
                <li
                  key={`${p.initiated_at ?? 'p'}-${i}`}
                  className="flex flex-wrap items-baseline justify-between gap-2 py-2.5"
                >
                  <span
                    className={`text-[13px] ${
                      row.arrived
                        ? 'font-semibold text-navy-900'
                        : 'font-medium text-navy-900'
                    }`}
                  >
                    {row.amount}
                  </span>
                  <span className="text-[12px] text-black">
                    {row.status}
                    {row.when && <span className="ml-2">· {row.when}</span>}
                  </span>
                  {row.action && (
                    <p className="w-full text-[12px] leading-relaxed text-black">
                      {row.action}
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        )}

        {loaded && hasMore && (
          <button
            type="button"
            onClick={() => void loadMore()}
            disabled={loadingMore}
            className="mt-3 text-[13px] font-semibold text-teal-700 hover:underline disabled:opacity-60"
          >
            {loadingMore ? 'Loading…' : 'Show earlier payouts'}
          </button>
        )}

        {/* Said plainly while the import is still running. A creator who
            cannot see an older payout should know the list is incomplete
            rather than conclude it never happened. */}
        {history && (
          <p className="mt-3 text-[12px] leading-relaxed text-black">
            {history}
          </p>
        )}

        {freshness && (
          <p className="mt-3 text-[11.5px] italic text-black">{freshness}</p>
        )}
      </section>
    </div>
  )
}
