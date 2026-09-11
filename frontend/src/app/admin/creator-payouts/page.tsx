'use client'

/**
 * Admin — Creator Payouts.
 *
 * Records manual bank/SEPA payouts to external creators. Fresh
 * Collective owes the creator until an admin marks a payout with a
 * bank reference; this UI is the entry point.
 *
 * Payable balance is derived server-side from retained creator amounts
 * (net_creator_amount_cents - refunded_creator_amount_cents) across
 * transactions whose refunds are fully resolved and whose payout_status
 * is still ``pending``. A ``NOT EXISTS`` clause on unresolved
 * RefundOperations means in-flight refunds are automatically excluded.
 *
 * Cancellation is a correction of Fresh Collective's INTERNAL record.
 * It does NOT reverse a bank transfer. UI copy states this
 * unambiguously.
 */

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface BatchRow {
  id: string
  creator_user_id: string
  currency: string
  total_amount_cents: number
  transaction_count: number
  reference: string
  note: string | null
  status: 'paid' | 'cancelled'
  created_at: string
  paid_at: string
  cancelled_at: string | null
  cancellation_reason: string | null
}

interface PayableSummary {
  creator_user_id: string
  currency: string
  payable_cents: number
  transaction_count: number
}

function fmtMoney(cents: number, currency: string): string {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 2,
  }).format(cents / 100)
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-AU', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

export default function AdminCreatorPayoutsPage() {
  const [batches, setBatches] = useState<BatchRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [cancelling, setCancelling] = useState<BatchRow | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl('/api/admin/creator-payout-batches?limit=200'),
        { credentials: 'include' },
      )
      if (!res.ok) throw new Error(`Error ${res.status}`)
      const data = (await res.json()) as BatchRow[]
      setBatches(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load batches.')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { refresh() }, [])

  return (
    <div className="mx-auto max-w-[1200px] px-5 py-6 md:px-8 md:py-10">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-[1.8rem] leading-tight text-navy-900">
            Creator Payouts
          </h1>
          <p className="mt-1 text-[13px] text-black">
            Record manual bank / SEPA payouts to creators. Cancellation
            corrects Fresh Collective&apos;s internal record only —{' '}
            <span className="font-semibold">it does not reverse a bank transfer.</span>
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="rounded-full bg-teal-600 px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
        >
          Record payout
        </button>
      </div>

      {loading && (
        <p className="text-[13px] text-slate-500">Loading…</p>
      )}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">
          {error}
        </div>
      )}

      {!loading && !error && batches.length === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-6 py-10 text-center">
          <p className="text-[14px] text-navy-900">No payouts recorded yet.</p>
        </div>
      )}

      {!loading && !error && batches.length > 0 && (
        <div className="overflow-hidden rounded-2xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
          <table className="w-full text-left">
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                {['Creator', 'Currency', 'Amount', 'Txns', 'Reference', 'Paid at', 'Status', 'Action'].map((h) => (
                  <th key={h} className="px-3 py-3 text-[11px] font-semibold uppercase tracking-wider text-black">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {batches.map((b, i) => (
                <tr key={b.id} style={{ borderBottom: i < batches.length - 1 ? '1px solid #F1F5F9' : undefined }}>
                  <td className="px-3 py-3 text-[12.5px] text-navy-900 font-mono">{b.creator_user_id}</td>
                  <td className="px-3 py-3 text-[12.5px] text-navy-900">{b.currency}</td>
                  <td className="px-3 py-3 text-[12.5px] font-semibold text-navy-900 whitespace-nowrap">
                    {fmtMoney(b.total_amount_cents, b.currency)}
                  </td>
                  <td className="px-3 py-3 text-[12.5px] text-navy-900">{b.transaction_count}</td>
                  <td className="px-3 py-3 text-[12.5px] text-navy-900">{b.reference}</td>
                  <td className="px-3 py-3 text-[11.5px] whitespace-nowrap text-slate-500">
                    {fmtDate(b.paid_at)}
                  </td>
                  <td className="px-3 py-3 text-[11.5px] whitespace-nowrap">
                    {b.status === 'cancelled' ? (
                      <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
                        Cancelled
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded-full border border-teal-200 bg-teal-50 px-2 py-0.5 text-[11px] font-semibold text-teal-700">
                        Paid
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap">
                    {b.status === 'paid' && (
                      <button
                        type="button"
                        onClick={() => setCancelling(b)}
                        className="rounded-full border border-red-200 bg-white px-3 py-1 text-[11px] font-medium text-red-700 transition-colors hover:bg-red-50"
                      >
                        Correct record
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {creating && (
        <RecordPayoutModal
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false)
            setToast('Payout recorded.')
            refresh()
          }}
        />
      )}
      {cancelling && (
        <CorrectRecordModal
          batch={cancelling}
          onClose={() => setCancelling(null)}
          onDone={(msg: string) => {
            setCancelling(null)
            setToast(msg)
            refresh()
          }}
        />
      )}
      {toast && (
        <div
          className="fixed bottom-6 left-1/2 z-40 -translate-x-1/2 rounded-full px-4 py-2 text-[12.5px] font-medium text-white shadow-lg"
          style={{ background: '#0F172A' }}
          onClick={() => setToast(null)}
          role="status"
        >
          {toast}
        </div>
      )}
    </div>
  )
}

function RecordPayoutModal({
  onClose, onCreated,
}: { onClose: () => void; onCreated: () => void }) {
  const [creatorUserId, setCreatorUserId] = useState('')
  const [currency, setCurrency] = useState('AUD')
  const [reference, setReference] = useState('')
  const [note, setNote] = useState('')
  const [paidAt, setPaidAt] = useState(new Date().toISOString().slice(0, 10))
  const [payable, setPayable] = useState<PayableSummary | null>(null)
  const [loadingPayable, setLoadingPayable] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function loadPayable() {
    if (!creatorUserId.trim() || !currency.trim()) return
    setLoadingPayable(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        creator_user_id: creatorUserId.trim(),
        currency: currency.trim().toUpperCase(),
      })
      const res = await fetch(
        apiUrl(`/api/admin/creator-payout-batches/payable?${params}`),
        { credentials: 'include' },
      )
      if (!res.ok) throw new Error(`Error ${res.status}`)
      setPayable((await res.json()) as PayableSummary)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to compute payable.')
      setPayable(null)
    } finally {
      setLoadingPayable(false)
    }
  }

  async function submit() {
    if (!payable) return
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl('/api/admin/creator-payout-batches'),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            creator_user_id: creatorUserId.trim(),
            currency: currency.trim().toUpperCase(),
            reference: reference.trim(),
            submitted_total_cents: payable.payable_cents,
            paid_at: new Date(paidAt).toISOString(),
            note: note.trim() || null,
          }),
        },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(
          typeof body.detail === 'string' ? body.detail : `Error ${res.status}`,
        )
      }
      onCreated()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to record payout.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl">
        <h2 className="font-serif text-[1.25rem] leading-tight text-navy-900">Record a manual payout</h2>
        <p className="mt-2 text-[12.5px] text-black">
          Record a bank/SEPA transfer you have already sent to a creator.
          This marks the eligible transactions paid and snapshots the
          creator amount at payout time. Refunds landing after this
          batch is created will NOT change the recorded total.
        </p>
        <div className="mt-4 space-y-3 text-[13px]">
          <label className="block text-[12px] font-medium text-navy-900">
            Creator user id
            <input
              type="text"
              value={creatorUserId}
              onChange={(e) => { setCreatorUserId(e.target.value); setPayable(null) }}
              className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-[12.5px]"
              placeholder="u_..."
            />
          </label>
          <label className="block text-[12px] font-medium text-navy-900">
            Currency
            <input
              type="text"
              value={currency}
              maxLength={3}
              onChange={(e) => { setCurrency(e.target.value.toUpperCase()); setPayable(null) }}
              className="mt-1 w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-[12.5px]"
            />
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={loadPayable}
              disabled={loadingPayable || !creatorUserId.trim()}
              className="rounded-full border border-teal-300 px-4 py-1.5 text-[12px] font-semibold text-teal-700 hover:bg-teal-50 disabled:opacity-50"
            >
              {loadingPayable ? 'Loading…' : 'Compute payable'}
            </button>
            {payable && (
              <p className="text-[12.5px] text-navy-900">
                <span className="font-semibold">{fmtMoney(payable.payable_cents, payable.currency)}</span>
                {' '}across {payable.transaction_count} transaction{payable.transaction_count === 1 ? '' : 's'}
              </p>
            )}
          </div>
          <label className="block text-[12px] font-medium text-navy-900">
            Bank reference
            <input
              type="text"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              maxLength={200}
              className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-[13px]"
              placeholder="SEPA / bank reference"
            />
          </label>
          <label className="block text-[12px] font-medium text-navy-900">
            Paid at
            <input
              type="date"
              value={paidAt}
              onChange={(e) => setPaidAt(e.target.value)}
              className="mt-1 w-56 rounded-xl border border-slate-200 bg-white px-3 py-2 text-[13px]"
            />
          </label>
          <label className="block text-[12px] font-medium text-navy-900">
            Note (optional)
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              maxLength={1000}
              className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-[13px]"
            />
          </label>
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
            onClick={submit}
            disabled={submitting || !payable || payable.payable_cents === 0 || !reference.trim()}
            className="rounded-full bg-teal-600 px-4 py-2 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Recording…' : 'Record payout'}
          </button>
        </div>
      </div>
    </div>
  )
}

function CorrectRecordModal({
  batch, onClose, onDone,
}: {
  batch: BatchRow
  onClose: () => void
  onDone: (message: string) => void
}) {
  const [reason, setReason] = useState('')
  const [revert, setRevert] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/creator-payout-batches/${batch.id}/cancel`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            cancellation_reason: reason.trim(),
            revert_transactions: revert,
          }),
        },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(
          typeof body.detail === 'string' ? body.detail : `Error ${res.status}`,
        )
      }
      const body = await res.json() as {
        already_cancelled: boolean
        reverted_transaction_ids: string[]
      }
      if (body.already_cancelled) {
        onDone('Batch was already cancelled.')
      } else if (revert) {
        onDone(`Batch cancelled. ${body.reverted_transaction_ids.length} transaction(s) reverted to pending.`)
      } else {
        onDone('Batch cancelled (record only; transactions still marked paid).')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
        <h2 className="font-serif text-[1.25rem] leading-tight text-navy-900">
          Correct this payout record
        </h2>
        <div
          className="mt-3 rounded-xl px-4 py-3 text-[12px] leading-relaxed"
          style={{ background: '#FEF3C7', border: '1px solid #FDE68A', color: '#78350F' }}
        >
          Cancelling only corrects the Fresh Collective record of this
          payout. It does <strong>not</strong> reverse the bank transfer.
          If money left your account and reached the creator, resolve
          that through your bank or by adjusting future payouts. If you
          are correcting an incorrectly-recorded payout that never
          happened, tick the box below so the linked transactions
          become unpaid again and can be included in a corrected batch.
        </div>
        <dl className="mt-4 grid grid-cols-3 gap-x-3 gap-y-1.5 text-[12.5px]">
          <dt className="col-span-1 text-slate-500">Creator</dt>
          <dd className="col-span-2 font-mono text-navy-900">{batch.creator_user_id}</dd>
          <dt className="col-span-1 text-slate-500">Amount</dt>
          <dd className="col-span-2 font-semibold text-navy-900">
            {fmtMoney(batch.total_amount_cents, batch.currency)}
          </dd>
          <dt className="col-span-1 text-slate-500">Reference</dt>
          <dd className="col-span-2 text-navy-900">{batch.reference}</dd>
        </dl>
        <label className="mt-4 block text-[12px] font-medium text-navy-900">
          Reason (required)
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            maxLength={500}
            className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-[13px]"
            placeholder="Why is this record being corrected?"
          />
        </label>
        <label className="mt-3 flex items-start gap-2 text-[12.5px] text-navy-900">
          <input
            type="checkbox"
            checked={revert}
            onChange={(e) => setRevert(e.target.checked)}
            className="mt-1"
          />
          <span>
            Also revert the linked transactions to <span className="font-semibold">pending</span>{' '}
            (only tick if the bank transfer never happened).
          </span>
        </label>
        {error && (
          <p className="mt-3 text-[12.5px] text-red-600">{error}</p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-full px-4 py-2 text-[12.5px] font-medium text-black hover:text-slate-600 disabled:opacity-50"
          >
            Keep record
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting || !reason.trim()}
            className="rounded-full bg-red-600 px-4 py-2 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Submitting…' : 'Cancel this record'}
          </button>
        </div>
      </div>
    </div>
  )
}
