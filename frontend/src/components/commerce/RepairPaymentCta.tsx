'use client'

/**
 * FIP4B2 — interactive "Update payment details" CTA for the
 * plan-recovery banner. Kept in its own client component so the
 * parent `PlanRecoveryBanner` can stay server-rendered.
 *
 * On click: POST /api/finite-plan/repair-session with the plan id,
 * then window.location = returned Stripe URL. The backend
 * re-validates ownership + recoverable status before opening the
 * Session — see `backend/app/commerce/finite_plan_repair_routes.py`.
 *
 * A basic error state is shown inline if the request fails (network
 * outage, 502 from Stripe, plan no longer recoverable). No polling,
 * no retry loops — the member just clicks again or refreshes.
 */

import { useState } from 'react'
import { apiUrl } from '@/lib/api'

interface Props {
  planId: string
  accent: string
  /** Compact layout used by the in-Pathway notice. Drops the outer
   *  mt-3 (parent controls spacing) and uses smaller padding + text
   *  so the CTA fits on a single-line strip without overwhelming
   *  the reading content. */
  compact?: boolean
}

interface RepairSessionResponse {
  checkout_url: string
  session_id: string
}

export function RepairPaymentCta({ planId, accent, compact = false }: Props) {
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle')

  const handleClick = async () => {
    setStatus('loading')
    try {
      const res = await fetch(apiUrl('/api/finite-plan/repair-session'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: planId }),
      })
      if (!res.ok) {
        setStatus('error')
        return
      }
      const body: RepairSessionResponse = await res.json()
      if (!body.checkout_url) {
        setStatus('error')
        return
      }
      window.location.href = body.checkout_url
    } catch {
      setStatus('error')
    }
  }

  const disabled = status === 'loading'

  const buttonClass = compact
    ? 'inline-flex items-center rounded-full px-3 py-1 text-[11.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-wait disabled:opacity-60'
    : 'inline-flex items-center rounded-full px-4 py-2 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-wait disabled:opacity-60'

  return (
    <div className={compact ? '' : 'mt-3'}>
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled}
        aria-busy={disabled ? 'true' : 'false'}
        className={buttonClass}
        style={{ background: accent }}
      >
        {status === 'loading' ? 'Opening secure form…' : 'Update payment details'}
      </button>
      {status === 'error' && (
        <p className={compact ? 'mt-1 text-[11px] text-slate-500' : 'mt-2 text-[11px] text-slate-500'}>
          We couldn&rsquo;t open the payment form. Please try again in a
          moment or refresh the page.
        </p>
      )}
    </div>
  )
}
