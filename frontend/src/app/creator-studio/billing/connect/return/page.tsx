'use client'

/**
 * Where Stripe sends a creator after hosted onboarding.
 *
 * Landing here does **not** mean setup succeeded. Stripe returns the
 * browser on completion *and* on abandonment, and the state it left behind
 * is whatever it is — a creator who skipped the bank-account step arrives
 * at exactly this URL. So the page asks Fresh Collective, which asks
 * Stripe, and reports what actually came back.
 *
 * ``POST /refresh`` rather than ``GET /status`` on purpose: this is the one
 * moment we know something just changed at Stripe, so it earns a live read.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import type { CreatorStripeConnectStatus } from '@/types/platform'
import { REFRESH_PATH } from '@/lib/stripeConnectActions'
import { describeConnect } from '@/lib/stripeConnectPanel'

export default function ConnectReturnPage() {
  const [status, setStatus] = useState<CreatorStripeConnectStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(true)
  const started = useRef(false)

  const check = useCallback(async () => {
    setChecking(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(REFRESH_PATH), {
        method: 'POST',
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
      setStatus((await res.json()) as CreatorStripeConnectStatus)
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : 'We couldn’t confirm your Stripe setup just now.',
      )
    } finally {
      setChecking(false)
    }
  }, [])

  // React may mount an effect twice in development; the guard keeps that
  // from firing two refreshes at Stripe.
  useEffect(() => {
    if (started.current) return
    started.current = true
    void check()
  }, [check])

  const view = status ? describeConnect(status) : null

  return (
    <div className="mx-auto max-w-xl px-6 py-16">
      <h1 className="text-[20px] font-semibold text-navy-900">
        {checking ? 'Checking with Stripe…' : view ? view.headline : 'Back from Stripe'}
      </h1>

      {checking && (
        <p className="mt-3 text-[14px] text-black">
          We’re confirming what Stripe recorded. This only takes a moment.
        </p>
      )}

      {!checking && view && (
        <>
          <p className="mt-3 text-[14px] text-black">{view.body}</p>
          {view.scheduleNote && (
            <p className="mt-2 text-[14px] text-black">{view.scheduleNote}</p>
          )}
          {view.routingNote && (
            <p className="mt-2 text-[14px] text-black">{view.routingNote}</p>
          )}
        </>
      )}

      {!checking && error && (
        <>
          <p className="mt-3 text-[14px] text-black">
            Your setup with Stripe may well have gone through — we just
            couldn’t confirm it from here.
          </p>
          <p className="mt-2 text-[13px] font-medium text-red-700">{error}</p>
          <button
            type="button"
            onClick={() => void check()}
            className="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 text-[13px] font-medium text-navy-900 hover:bg-slate-50"
          >
            Check again
          </button>
        </>
      )}

      <div className="mt-8">
        <Link
          href="/creator-studio/billing"
          className="rounded-lg bg-navy-900 px-4 py-2 text-[13px] font-medium text-white"
        >
          Back to Billing
        </Link>
      </div>
    </div>
  )
}
