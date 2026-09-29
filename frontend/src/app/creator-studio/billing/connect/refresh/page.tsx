'use client'

/**
 * Where Stripe sends a creator when their setup link has expired.
 *
 * Account links last five minutes from creation, so this is not an error
 * path — it is the ordinary consequence of opening the page and pausing to
 * find a document. Stripe's contract for ``refresh_url`` is that it mints a
 * new link with the same parameters and sends the creator onward, which is
 * all this page does.
 *
 * It always asks the backend for a new link. Reusing the expired one is the
 * one thing that cannot work here.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import { LINK_PATH, type AccountLinkResponse } from '@/lib/stripeConnectActions'

export default function ConnectRefreshPage() {
  const [error, setError] = useState<string | null>(null)
  const started = useRef(false)

  const mintAndGo = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch(apiUrl(LINK_PATH), {
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
      const { url } = (await res.json()) as AccountLinkResponse
      if (!url) throw new Error('Stripe did not return a setup link.')
      window.location.href = url
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : 'We couldn’t start your Stripe setup again.',
      )
    }
  }, [])

  useEffect(() => {
    if (started.current) return
    started.current = true
    void mintAndGo()
  }, [mintAndGo])

  return (
    <div className="mx-auto max-w-xl px-6 py-16">
      <h1 className="text-[20px] font-semibold text-navy-900">
        Taking you back to Stripe…
      </h1>
      {!error ? (
        <p className="mt-3 text-[14px] text-black">
          Your last setup link had expired, so we’re opening a fresh one.
        </p>
      ) : (
        <>
          <p className="mt-3 text-[14px] text-black">
            We couldn’t open Stripe just now. Nothing about your setup has
            changed — you can try again from Billing.
          </p>
          <p className="mt-2 text-[13px] font-medium text-red-700">{error}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void mintAndGo()}
              className="rounded-lg bg-navy-900 px-4 py-2 text-[13px] font-medium text-white"
            >
              Try again
            </button>
            <Link
              href="/creator-studio/billing"
              className="rounded-lg border border-slate-300 px-4 py-2 text-[13px] font-medium text-navy-900 hover:bg-slate-50"
            >
              Back to Billing
            </Link>
          </div>
        </>
      )}
    </div>
  )
}
