'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'

/**
 * Refund Payment modal — used from Creator Studio → Payments received.
 *
 * Calls the creator refund endpoint
 * ``POST /api/creator/payments/{txn_id}/refund``. Fresh Collective
 * makes the Stripe API call server-side with platform credentials;
 * the creator never touches Stripe.
 *
 * The refund LEDGER (refunded_amount_cents, refunded_platform_fee_cents,
 * refunded_creator_amount_cents, status, last_refunded_at) is not
 * updated by this endpoint — that stays webhook-authoritative via
 * ``charge.refunded``. This modal therefore says "Refund initiated —
 * awaiting confirmation from Stripe" on the successful path; the row
 * updates when the webhook arrives (usually within seconds).
 *
 * Refund does NOT change the member's access. If access should also
 * be revoked, use the separate Revoke access action.
 */

export interface RefundResult {
  refund_operation_id: string
  payment_transaction_id: string
  requested_amount_cents: number
  stripe_refund_id: string | null
  terminal_status: string
  message: string
  refundable_before_cents: number
  refundable_after_cents: number
  payout_advisory: string | null
}

interface Props {
  txnId: string
  memberLabel: string
  purchaseLabel: string
  currency: string
  grossAmountCents: number
  alreadyRefundedCents: number
  /** Current payout state — determines whether a pre-submit
   *  manual-recovery warning is shown. For non-admin creators the
   *  UI hides the button entirely when this is ``paid``/``held``;
   *  for the platform-owner override case, the warning + explicit
   *  acknowledgement gate the confirm button. */
  payoutStatus: 'pending' | 'paid' | 'held' | 'cancelled' | 'not_applicable'
  onClose: () => void
  onRefunded: (result: RefundResult) => void
}

const REASONS: Array<{ value: string; label: string }> = [
  { value: 'member_request', label: 'Member requested' },
  { value: 'duplicate', label: 'Duplicate payment' },
  { value: 'fraudulent', label: 'Fraudulent' },
  { value: 'goodwill', label: 'Goodwill' },
  { value: 'error_correction', label: 'Error correction' },
  { value: 'other', label: 'Other' },
]

function fmtMoney(cents: number, currency: string): string {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 2,
  }).format(cents / 100)
}

export default function RefundPaymentModal({
  txnId, memberLabel, purchaseLabel, currency,
  grossAmountCents, alreadyRefundedCents, payoutStatus,
  onClose, onRefunded,
}: Props) {
  const refundable = Math.max(0, grossAmountCents - alreadyRefundedCents)

  // Post-payout override — the platform owner is refunding a
  // transaction whose creator funds have already been paid out
  // (or are on hold). Fresh Collective cannot automatically recover
  // that money from the creator's bank account; the pre-submit
  // warning + explicit acknowledgement are required so this is
  // never a surprise.
  const postPayoutOverride = payoutStatus === 'paid' || payoutStatus === 'held'

  // Amount mode: 'full' | 'partial'. Default to full for the common case.
  const [mode, setMode] = useState<'full' | 'partial'>('full')
  const [partialInput, setPartialInput] = useState<string>('')
  const [reason, setReason] = useState<string>('member_request')
  const [note, setNote] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ackPostPayout, setAckPostPayout] = useState<boolean>(false)

  function parsePartialCents(): number | null {
    const cleaned = partialInput.trim().replace(/[^0-9.]/g, '')
    if (!cleaned) return null
    const dollars = Number(cleaned)
    if (!Number.isFinite(dollars) || dollars <= 0) return null
    return Math.round(dollars * 100)
  }

  const resolvedAmountCents =
    mode === 'full' ? refundable : (parsePartialCents() ?? 0)
  const canSubmit =
    !submitting
    && resolvedAmountCents > 0
    && resolvedAmountCents <= refundable
    && (!postPayoutOverride || ackPostPayout)

  async function handleRefund() {
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/payments/${txnId}/refund`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            amount_cents: resolvedAmountCents,
            reason,
            note: note.trim() || null,
          }),
        },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(
          typeof body.detail === 'string'
            ? body.detail
            : `Could not process refund (${res.status}).`,
        )
        return
      }
      const result = (await res.json()) as RefundResult
      onRefunded(result)
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="refund-payment-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
        style={{ border: '1px solid #E2E8F0' }}
      >
        <h2 id="refund-payment-title" className="text-[16px] font-semibold text-navy-900">
          Refund this payment
        </h2>

        <dl className="mt-4 grid grid-cols-3 gap-x-3 gap-y-1.5 text-[12.5px]">
          <dt className="col-span-1 text-slate-500">Member</dt>
          <dd className="col-span-2 text-navy-900">{memberLabel}</dd>
          <dt className="col-span-1 text-slate-500">Purchase</dt>
          <dd className="col-span-2 text-navy-900">{purchaseLabel}</dd>
          <dt className="col-span-1 text-slate-500">Original amount</dt>
          <dd className="col-span-2 text-navy-900">{fmtMoney(grossAmountCents, currency)}</dd>
          <dt className="col-span-1 text-slate-500">Already refunded</dt>
          <dd className="col-span-2 text-navy-900">{fmtMoney(alreadyRefundedCents, currency)}</dd>
          <dt className="col-span-1 text-slate-500">Refundable now</dt>
          <dd className="col-span-2 font-semibold text-navy-900">{fmtMoney(refundable, currency)}</dd>
        </dl>

        <div className="mt-4">
          <span className="mb-2 block text-[12px] font-semibold uppercase tracking-[0.14em] text-black">
            Refund amount
          </span>
          <div className="flex gap-2">
            <label className="flex items-center gap-2 text-[13px] text-navy-900">
              <input
                type="radio"
                name="refund-amount-mode"
                value="full"
                checked={mode === 'full'}
                onChange={() => setMode('full')}
                disabled={submitting}
              />
              <span>Full ({fmtMoney(refundable, currency)})</span>
            </label>
            <label className="flex items-center gap-2 text-[13px] text-navy-900">
              <input
                type="radio"
                name="refund-amount-mode"
                value="partial"
                checked={mode === 'partial'}
                onChange={() => setMode('partial')}
                disabled={submitting}
              />
              <span>Partial</span>
            </label>
          </div>
          {mode === 'partial' && (
            <input
              type="text"
              inputMode="decimal"
              placeholder="e.g. 15.00"
              value={partialInput}
              onChange={(e) => setPartialInput(e.target.value)}
              disabled={submitting}
              className="mt-2 w-40 rounded-lg border border-border bg-white px-3 py-2 text-[13px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
              aria-label="Partial refund amount"
            />
          )}
        </div>

        <label className="mt-4 block text-[12px] text-black">
          <span className="mb-1 block font-semibold uppercase tracking-[0.14em]">Reason</span>
          <select
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            disabled={submitting}
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-[13px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
          >
            {REASONS.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
        </label>

        <label className="mt-3 block text-[12px] text-black">
          <span className="mb-1 block font-semibold uppercase tracking-[0.14em]">
            Note (optional)
          </span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            maxLength={250}
            placeholder="Any internal detail worth keeping in the audit trail"
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-[13px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
          />
        </label>

        {postPayoutOverride && (
          <div
            className="mt-4 rounded-xl px-4 py-3 text-[12.5px] leading-relaxed"
            style={{ background: '#FEF3C7', border: '1px solid #F59E0B', color: '#78350F' }}
            role="alert"
            data-testid="post-payout-warning"
          >
            <p className="font-semibold" style={{ color: '#92400E' }}>
              Creator funds already {payoutStatus === 'paid' ? 'paid out' : 'held'}
            </p>
            <p className="mt-1">
              This transaction&apos;s creator earnings have already been
              {payoutStatus === 'paid' ? ' paid to the creator' : ' placed on hold'}.
              Fresh Collective <strong>will not automatically recover</strong>
              those funds when you refund the member. Proceeding will refund
              the member through Stripe; recovering the creator amount is a
              manual follow-up (adjust a future payout, ask the creator to
              return the amount, or absorb it — your call).
            </p>
            <label className="mt-3 flex items-start gap-2">
              <input
                type="checkbox"
                checked={ackPostPayout}
                onChange={(e) => setAckPostPayout(e.target.checked)}
                disabled={submitting}
                className="mt-0.5"
              />
              <span>
                I understand this refund will require manual creator-fund
                recovery.
              </span>
            </label>
          </div>
        )}

        <div
          className="mt-4 rounded-xl px-4 py-3 text-[12.5px] leading-relaxed"
          style={{ background: '#F0F9FF', border: '1px solid #BAE6FD', color: '#075985' }}
        >
          <p>
            Refunding this payment does not automatically change the
            member&apos;s access. Use the separate Revoke access action
            if access should also be removed.
          </p>
        </div>

        {error && (
          <p className="mt-3 text-[12.5px] text-red-600">{error}</p>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-full px-4 py-2 text-[12.5px] font-medium text-black hover:text-slate-600 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleRefund}
            disabled={!canSubmit}
            className="rounded-full bg-red-600 px-4 py-2 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {submitting
              ? 'Submitting…'
              : `Refund ${resolvedAmountCents > 0 ? fmtMoney(resolvedAmountCents, currency) : ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}
