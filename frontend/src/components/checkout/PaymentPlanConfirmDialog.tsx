'use client'

/**
 * Pre-Stripe confirmation for a finite payment plan.
 *
 * Why this exists: the plan is set up through Stripe Checkout in
 * ``mode='setup'``, which has no line items — so Stripe's hosted page
 * shows no amount and labels its button "Save". A member could
 * reasonably read that as saving a card rather than committing to a
 * paid plan. This is the last screen before that redirect and the
 * place where the commitment can be stated plainly, so it does.
 *
 * Every figure is derived from the selected schedule. Nothing here is
 * hard-coded to any particular Payment Option.
 */

import { useEffect, useRef } from 'react'
import {
  planConfirmationCopy,
  type AnyPaymentSchedule,
} from '@/lib/paymentPlan'

const NAVY = '#0C1826'
const INK_BODY = 'rgba(12, 24, 38, 0.78)'
const INK_SOFT = 'rgba(12, 24, 38, 0.60)'

export default function PaymentPlanConfirmDialog({
  schedule,
  optionName,
  busy = false,
  accentHex = '#38A09E',
  onConfirm,
  onCancel,
}: {
  schedule: AnyPaymentSchedule
  /** Payment Option name, shown so the member knows what the plan buys. */
  optionName?: string | null
  busy?: boolean
  accentHex?: string
  onConfirm: () => void
  onCancel: () => void
}) {
  const confirmRef = useRef<HTMLButtonElement | null>(null)
  const copy = planConfirmationCopy(schedule)

  // Focus the primary action on open, and let Escape back out — this
  // is a commitment step, so it must be dismissible without a mouse.
  useEffect(() => {
    confirmRef.current?.focus()
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !busy) onCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onCancel])

  // Not a plan we can describe honestly — the caller should not have
  // opened this, but never show a half-filled commitment screen.
  if (!copy) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(12, 24, 38, 0.55)' }}
      onClick={() => { if (!busy) onCancel() }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="plan-confirm-heading"
        className="w-full max-w-[420px] rounded-2xl bg-white p-6 sm:p-7"
        style={{ boxShadow: '0 24px 60px rgba(12, 24, 38, 0.28)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="plan-confirm-heading"
          className="font-serif leading-tight"
          style={{ fontSize: '1.45rem', letterSpacing: '-0.02em', color: NAVY }}
        >
          Start your payment plan
        </h2>

        {optionName && (
          <p className="mt-1 text-[13px]" style={{ color: INK_SOFT }}>
            {optionName}
          </p>
        )}

        <div
          className="mt-5 rounded-xl px-4 py-4"
          style={{ background: '#F7F5F1' }}
        >
          <p
            className="text-[17px] font-semibold"
            style={{ color: NAVY }}
          >
            {copy.firstCharge}
          </p>
          <p className="mt-1 text-[14px]" style={{ color: INK_BODY }}>
            {copy.thenLine}
          </p>
          <p
            className="mt-3 border-t pt-3 text-[14px] font-semibold"
            style={{ borderColor: 'rgba(12, 24, 38, 0.10)', color: NAVY }}
          >
            {copy.totalLine}
          </p>
        </div>

        <p
          className="mt-4 text-[12.5px] leading-relaxed"
          style={{ color: INK_BODY }}
        >
          You&rsquo;ll enter your card details securely with Stripe. Your first
          payment will be charged immediately after setup, and your access
          will begin once that payment succeeds.
        </p>

        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-xl px-4 py-2.5 text-[13.5px] font-medium transition-colors disabled:opacity-60"
            style={{ color: INK_BODY, background: 'transparent' }}
          >
            Cancel
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="rounded-xl px-5 py-2.5 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
            style={{ background: accentHex }}
          >
            {busy ? 'Starting…' : 'Continue to payment details'}
          </button>
        </div>
      </div>
    </div>
  )
}
