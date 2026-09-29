'use client'

/**
 * Creator Studio → Billing → what Stripe has paid, sale by sale.
 *
 * Shown only when the creator has Connect-routed sales. Kept separate from the
 * manual payout figures above it, because for these sales Fresh Collective owes
 * nothing by hand — Stripe does — and folding the two together would tell a
 * creator FC is holding money it is not.
 *
 * Self-loading on demand rather than with the page: a creator without Connect
 * sales should not pay for a query that returns nothing, and this sits below
 * the fold.
 */

import { useCallback, useRef, useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { ConnectEarningsResponse } from '@/types/platform'
import {
  earningLines,
  earningsHeadline,
  formatMoney,
  instalmentCaption,
  isReturned,
} from '@/lib/connectEarnings'

const EARNINGS_PATH = '/api/creator/stripe-connect/earnings'

export default function ConnectEarnings() {
  const [data, setData] = useState<ConnectEarningsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false)

  const load = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(EARNINGS_PATH), {
        method: 'GET',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      })
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`
        try {
          const body = (await res.json()) as { detail?: string }
          if (body?.detail) detail = body.detail
        } catch { /* keep the status line */ }
        throw new Error(detail)
      }
      setData((await res.json()) as ConnectEarningsResponse)
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'We couldn’t load your Stripe payouts.',
      )
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }, [])

  if (data === null) {
    return (
      <div className="mt-3 rounded-xl bg-slate-50 p-4">
        <p className="text-[13px] font-medium text-navy-900">
          Your Stripe payouts
        </p>
        <p className="mt-1 max-w-prose text-[12px] text-black">
          See each sale Stripe has paid you for, with the fees broken down.
        </p>
        <button
          type="button"
          onClick={() => void load()}
          disabled={busy}
          className="mt-2 rounded-lg border border-slate-300 px-3 py-1.5 text-[12px] font-medium text-navy-900 hover:bg-white disabled:opacity-60"
        >
          {busy ? 'Loading…' : 'Show my Stripe payouts'}
        </button>
        {error && (
          <p className="mt-2 text-[12px] font-medium text-red-700">{error}</p>
        )}
      </div>
    )
  }

  const summary = earningsHeadline(data)

  return (
    <div className="mt-3 rounded-xl bg-slate-50 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-[13px] font-medium text-navy-900">
            {summary.headline}
          </p>
          <p className="mt-1 max-w-prose text-[12px] text-black">
            {summary.body}
          </p>
        </div>
        {summary.sentTotal && (
          <p className="text-[12px] text-black">
            <span className="font-medium text-navy-900">
              {summary.sentTotal}
            </span>{' '}
            sent to Stripe
            {summary.awaitingTotal && (
              <>
                {' · '}
                {summary.awaitingTotal} on its way
              </>
            )}
          </p>
        )}
      </div>

      {data.rows.length > 0 && (
        <ul className="mt-3 space-y-2">
          {data.rows.map((row) => {
            const caption = instalmentCaption(row)
            return (
              <li
                key={row.payment_transaction_id}
                className="rounded-lg bg-white p-3"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-[12px] font-medium text-navy-900">
                    {formatMoney(row.sale_amount_cents, row.currency)} sale
                    {caption && (
                      <span className="ml-1 font-normal text-black">
                        · {caption}
                      </span>
                    )}
                  </p>
                  <span className="text-[11px] font-semibold text-black">
                    {row.status_label}
                  </span>
                </div>

                <dl className="mt-2 space-y-0.5">
                  {earningLines(row).map((line) => (
                    <div
                      key={line.label}
                      className="flex justify-between gap-4 text-[12px]"
                    >
                      <dt className="text-black">{line.label}</dt>
                      <dd
                        className={
                          line.pending
                            ? 'text-black italic'
                            : line.isDeduction
                              ? 'text-black'
                              : 'font-medium text-navy-900'
                        }
                      >
                        {line.value}
                      </dd>
                    </div>
                  ))}
                </dl>

                {isReturned(row) && (
                  <p className="mt-1 text-[12px] text-black">
                    {formatMoney(row.refunded_amount_cents, row.currency)} of
                    this sale was refunded to the member.
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <button
        type="button"
        onClick={() => void load()}
        disabled={busy}
        className="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 text-[12px] font-medium text-navy-900 hover:bg-white disabled:opacity-60"
      >
        {busy ? 'Refreshing…' : 'Refresh'}
      </button>
      {error && (
        <p className="mt-2 text-[12px] font-medium text-red-700">{error}</p>
      )}
    </div>
  )
}
