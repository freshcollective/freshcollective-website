'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'

/**
 * Revoke Access modal — used from Creator Studio → Payments received.
 *
 * Calls the platform-admin endpoint
 * ``POST /api/admin/payment-transactions/{txn_id}/revoke``, which
 * cancels every AccessPass created by the purchase, revokes every
 * reachable PathwayEntitlement, marks the linked AccessGrantRecords
 * revoked, releases every future confirmed EventBooking that was
 * consumed against those passes, and — only when no other active
 * grant keeps the buyer in the collective — removes the auto-joined
 * SpaceMembership.
 *
 * The endpoint is idempotent (``already_revoked=True`` on a second
 * call). It refuses (409) plan-anchored transactions; the frontend
 * already hides the button when ``purchase_plan_id`` is set.
 *
 * This modal does NOT refund the Stripe payment. Refund is a
 * separate operation performed in the Stripe Dashboard — the
 * ``PaymentTransaction.status`` on this ledger stays as it was.
 * Refund-status sync back into the ledger is a named follow-up
 * before the public payments launch.
 */

export interface RevokeResult {
  payment_transaction_id: string
  access_passes_revoked: number
  entitlements_revoked: number
  grant_records_revoked: number
  membership_removed: boolean
  future_bookings_released: number
  already_revoked: boolean
}

interface Props {
  txnId: string
  memberLabel: string
  purchaseLabel: string
  amountLabel: string
  onClose: () => void
  /** Called with the endpoint's response after a successful revoke.
   *  The parent should refresh the ledger so grant_state chips update
   *  and the button disappears. */
  onRevoked: (result: RevokeResult) => void
}

export default function RevokeAccessModal({
  txnId, memberLabel, purchaseLabel, amountLabel, onClose, onRevoked,
}: Props) {
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleRevoke() {
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/payment-transactions/${txnId}/revoke`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: reason.trim() || null }),
        },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(
          typeof body.detail === 'string'
            ? body.detail
            : `Could not revoke access (${res.status}).`,
        )
        return
      }
      const result = (await res.json()) as RevokeResult
      onRevoked(result)
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
      aria-labelledby="revoke-access-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
        style={{ border: '1px solid #E2E8F0' }}
      >
        <h2 id="revoke-access-title" className="text-[16px] font-semibold text-navy-900">
          Revoke access from this purchase
        </h2>

        <dl className="mt-4 grid grid-cols-3 gap-x-3 gap-y-1.5 text-[12.5px]">
          <dt className="col-span-1 text-slate-500">Member</dt>
          <dd className="col-span-2 text-navy-900">{memberLabel}</dd>
          <dt className="col-span-1 text-slate-500">Purchase</dt>
          <dd className="col-span-2 text-navy-900">{purchaseLabel}</dd>
          <dt className="col-span-1 text-slate-500">Amount paid</dt>
          <dd className="col-span-2 text-navy-900">{amountLabel}</dd>
        </dl>

        <div
          className="mt-4 rounded-xl px-4 py-3 text-[12.5px] leading-relaxed"
          style={{ background: '#FFFBEB', border: '1px solid #FDE68A', color: '#78350F' }}
        >
          <p className="font-semibold" style={{ color: '#92400E' }}>
            This removes the access granted by this purchase.
          </p>
          <p className="mt-1">
            It does <strong>not</strong> refund the Stripe payment. Refund
            money in Stripe separately.
          </p>
          <p className="mt-1">
            Fresh Collective does not yet sync Stripe refund status into
            this ledger — wiring <code>charge.refunded</code> is a named
            follow-up before the public payments launch.
          </p>
        </div>

        <label className="mt-4 block text-[12px] text-black">
          <span className="mb-1 block font-semibold uppercase tracking-[0.14em]">
            Reason (optional)
          </span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            placeholder="e.g. member requested refund"
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-[13px] text-navy-900 focus:border-red-300 focus:outline-none focus:ring-2 focus:ring-red-100"
          />
        </label>

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
            onClick={handleRevoke}
            disabled={submitting}
            className="rounded-full border border-red-300 px-4 py-2 text-[12.5px] font-semibold text-red-600 transition-colors hover:bg-red-50 disabled:opacity-60"
          >
            {submitting ? 'Revoking…' : 'Revoke access'}
          </button>
        </div>
      </div>
    </div>
  )
}
