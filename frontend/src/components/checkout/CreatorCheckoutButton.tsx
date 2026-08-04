'use client'

/**
 * CreatorCheckoutButton — Stage 2.
 *
 * The real replacement for the /checkout/creator "Preview the next
 * step" placeholder. Behaviour:
 *
 *   1. Click → POST /api/purchases/creator-subscription { plan_slug }
 *   2. On 200 (Stripe configured) — redirect the browser to the
 *      Stripe-hosted Checkout URL.
 *   3. On 503 (Stripe not configured / Price ID not configured for
 *      this plan) — render a calm, fixed environment-limit message.
 *      In development builds, add a small secondary line naming the
 *      missing env var so operators can act on it. Production
 *      builds never show that line.
 *   4. On any other error — render a plain error message so the
 *      visitor can retry.
 *
 * The human-facing copy is owned by ``checkoutUnavailable.ts`` (a
 * pure module) so no operator-authored backend text ever renders as
 * the visible message.
 *
 * This component does not consume PurchaseIntents, does not create
 * accounts, does not grant entitlements. Those belong to later stages.
 */

import { useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { CreatorPlanSlug } from '@/lib/plans'
import {
  getDevOnlyDetail,
  getUnavailableCopy,
  type UnavailableDetail,
} from './checkoutUnavailable'

const TEAL = '#38A09E'
const TEAL_DEEP = '#246B6A'
const NAVY = '#0C1826'

interface Props {
  planSlug: Extract<CreatorPlanSlug, 'creator' | 'pro'>
  /** Rendered above the button when Stripe rejects the request (bad
   *  plan, Stripe SDK failure, network etc). */
  errorId?: string
}

export default function CreatorCheckoutButton({ planSlug, errorId }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState<UnavailableDetail | null>(null)

  async function handleClick() {
    setBusy(true)
    setError(null)
    setUnavailable(null)
    try {
      const res = await fetch(apiUrl('/api/purchases/creator-subscription'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ plan_slug: planSlug }),
      })

      if (res.status === 503) {
        const body = await res.json().catch(() => null)
        const detail = body?.detail
        if (
          detail &&
          typeof detail === 'object' &&
          typeof (detail as UnavailableDetail).reason === 'string'
        ) {
          setUnavailable(detail as UnavailableDetail)
          return
        }
        // Malformed 503 body — fall through to a generic error, still
        // without rendering backend prose.
        setError('Payments are not available right now. Please try again later.')
        return
      }

      if (!res.ok) {
        setError('Could not start checkout. Please try again.')
        return
      }

      const body = await res.json()
      if (typeof body?.checkout_url === 'string') {
        // Full-page navigation to Stripe. `assign` (not `replace`) so
        // the buyer can use browser Back to return to /checkout/creator.
        window.location.assign(body.checkout_url)
        return
      }
      setError('Server response did not include a checkout URL.')
    } catch {
      setError('Could not reach the server. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        aria-describedby={errorId}
        className="inline-flex w-fit items-center rounded-full px-7 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
        style={{
          background: `linear-gradient(135deg, ${TEAL} 0%, #55B8B6 100%)`,
          letterSpacing: '0.04em',
          boxShadow: '0 6px 24px rgba(56, 160, 158, 0.30)',
        }}
      >
        {busy ? 'Redirecting to secure payment…' : 'Continue to secure payment →'}
      </button>

      {unavailable && <UnavailableCard detail={unavailable} />}

      {error && (
        <p
          id={errorId}
          role="alert"
          className="text-[13px]"
          style={{ color: '#B32424' }}
        >
          {error}
        </p>
      )}
    </div>
  )
}

function UnavailableCard({ detail }: { detail: UnavailableDetail }) {
  const { heading, body } = getUnavailableCopy()
  const devDetail = getDevOnlyDetail(detail.missing_env_var)

  return (
    <div
      role="status"
      className="rounded-2xl border px-5 py-4 text-[14px] leading-relaxed"
      style={{
        borderColor: 'rgba(12, 24, 38, 0.10)',
        background: '#F7F5F1',
        color: NAVY,
        fontFamily: 'Georgia, serif',
      }}
    >
      <p className="font-semibold">{heading}</p>
      <p className="mt-2 italic" style={{ color: 'rgba(12, 24, 38, 0.80)' }}>
        {body}
      </p>
      {devDetail && (
        <p
          className="mt-3 font-mono text-[12px]"
          style={{ color: TEAL_DEEP }}
        >
          {devDetail}
        </p>
      )}
    </div>
  )
}
