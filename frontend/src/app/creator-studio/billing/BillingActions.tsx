'use client'

/**
 * Client-side buttons for the Creator Studio Billing page.
 *
 *   * Start Subscription — POST /api/creator/billing/subscribe, then
 *     redirect the browser to the returned Stripe Checkout URL.
 *   * Manage Billing — POST /api/creator/billing/portal-session, then
 *     redirect to Stripe Customer Portal.
 *   * Cancel / Reactivate — POST /api/creator/billing/{cancel,reactivate},
 *     then hard-reload so the page re-fetches the server-rendered
 *     billing state.
 *
 * All request errors surface inline; the buttons never leave the
 * user in a silent "clicked and nothing happened" state.
 */

import { useState } from 'react'
import { apiUrl } from '@/lib/api'

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const b = (await res.json()) as { detail?: string }
      if (b?.detail) detail = b.detail
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return (await res.json()) as T
}

export function StartSubscriptionButton({ planSlug, label }: {
  planSlug: 'creator' | 'pro'
  label: string
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onClick() {
    setBusy(true)
    setError(null)
    try {
      const { checkout_url } = await postJson<{ checkout_url: string }>(
        '/api/creator/billing/subscribe',
        { plan_slug: planSlug },
      )
      window.location.href = checkout_url
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start checkout.')
      setBusy(false)
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className="w-full rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
        style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
      >
        {busy ? 'Redirecting…' : label}
      </button>
      {error && (
        <p className="mt-2 text-[12px] text-red-700">{error}</p>
      )}
    </div>
  )
}

export function ManageBillingButton() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function onClick() {
    setBusy(true)
    setError(null)
    try {
      const { portal_url } = await postJson<{ portal_url: string }>(
        '/api/creator/billing/portal-session',
      )
      window.location.href = portal_url
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not open billing portal.')
      setBusy(false)
    }
  }
  return (
    <div>
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-[13px] font-semibold text-navy-900 transition-colors hover:bg-slate-50 disabled:opacity-60"
      >
        {busy ? 'Opening…' : 'Manage billing'}
      </button>
      {error && (
        <p className="mt-2 text-[12px] text-red-700">{error}</p>
      )}
    </div>
  )
}

export function CancelSubscriptionButton() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function onClick() {
    if (!confirm(
      "Cancel your subscription at the end of the current billing period? " +
      "You'll retain commercial capability until then. Existing member " +
      "purchases and payments continue after cancellation.",
    )) return
    setBusy(true)
    setError(null)
    try {
      await postJson<{ queued: boolean }>('/api/creator/billing/cancel')
      window.location.reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not cancel.')
      setBusy(false)
    }
  }
  return (
    <div>
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-[13px] font-medium text-navy-900 hover:bg-slate-50 disabled:opacity-60"
      >
        {busy ? 'Cancelling…' : 'Cancel at period end'}
      </button>
      {error && (
        <p className="mt-2 text-[12px] text-red-700">{error}</p>
      )}
    </div>
  )
}

export function ReactivateSubscriptionButton() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function onClick() {
    setBusy(true)
    setError(null)
    try {
      await postJson<{ queued: boolean }>('/api/creator/billing/reactivate')
      window.location.reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reactivate.')
      setBusy(false)
    }
  }
  return (
    <div>
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className="rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
        style={{ background: '#38A09E' }}
      >
        {busy ? 'Reactivating…' : 'Resume subscription'}
      </button>
      {error && (
        <p className="mt-2 text-[12px] text-red-700">{error}</p>
      )}
    </div>
  )
}
