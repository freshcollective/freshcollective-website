'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface AdminPaymentSummary {
  total_gross_amount_cents: number
  total_platform_fee_cents: number
  total_creator_net_amount_cents: number
  total_processing_fee_cents: number
  pending_payout_cents: number
  succeeded_count: number
  refunded_count: number
  disputed_count: number
  pending_count: number
  failed_count: number
}

interface PaymentTransaction {
  id: string
  transaction_type: string
  status: string
  payment_provider: string
  payer_user_id: string | null
  creator_user_id: string | null
  space_id: string | null
  pathway_id: string | null
  payment_option_id: string | null
  payment_option_schedule_id: string | null
  currency: string
  gross_amount_cents: number
  platform_fee_basis_points: number
  platform_fee_cents: number
  net_creator_amount_cents: number | null
  net_platform_amount_cents: number | null
  provider_checkout_session_id: string | null
  provider_payment_intent_id: string | null
  payout_status: string
  notes: string | null
  created_at: string
}

interface SimpleUser {
  id: string
  name: string | null
  email: string
}

interface SimplePaidPathway {
  id: string
  title: string
  space_id: string
  space_name: string
  space_slug: string
  access_type: string
  price_cents: number
  currency: string
  billing_interval: string | null
  creator_fee_basis_points: number
}

interface PurchaseResult {
  transaction_id: string
  entitlement_id: string
  entitlement_source: string
  payer_name: string | null
  payer_email: string
  pathway_title: string
  space_name: string
  currency: string
  gross_amount_cents: number
  platform_fee_basis_points: number
  platform_fee_cents: number
  net_creator_amount_cents: number
  net_platform_amount_cents: number
}

function fmt(cents: number, currency: string) {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 2,
  }).format(cents / 100)
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-AU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

function labelType(t: string) {
  return t.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    succeeded:          'bg-teal-50 text-teal-700 border-teal-200',
    pending:            'bg-amber-50 text-amber-700 border-amber-200',
    failed:             'bg-red-50 text-red-700 border-red-200',
    refunded:           'bg-slate-100 text-slate-600 border-slate-200',
    partially_refunded: 'bg-orange-50 text-orange-700 border-orange-200',
    disputed:           'bg-purple-50 text-purple-700 border-purple-200',
    cancelled:          'bg-slate-100 text-slate-500 border-slate-200',
  }
  const cls = styles[status] ?? 'bg-slate-100 text-slate-500 border-slate-200'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${cls}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

function ProviderBadge({ provider }: { provider: string }) {
  if (provider === 'manual') {
    return (
      <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-500">
        Manual
      </span>
    )
  }
  if (provider === 'stripe') {
    return (
      <span className="inline-flex items-center rounded-full border border-teal-200 bg-teal-50 px-2 py-0.5 text-[11px] font-semibold text-teal-700">
        Stripe
      </span>
    )
  }
  return <span className="text-[12px] capitalize text-[#94A3B8]">{provider}</span>
}

function PayoutBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending:        'bg-amber-50 text-amber-700 border-amber-200',
    paid:           'bg-teal-50 text-teal-700 border-teal-200',
    not_applicable: 'bg-slate-100 text-slate-400 border-slate-200',
    held:           'bg-purple-50 text-purple-700 border-purple-200',
  }
  const cls = styles[status] ?? 'bg-slate-100 text-slate-400 border-slate-200'
  const label = status === 'not_applicable' ? 'N/A' : status.replace(/_/g, ' ')
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${cls}`}>
      {label}
    </span>
  )
}

function MetricCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string | number
  sub?: string
  accent?: boolean
}) {
  return (
    <div className="rounded-xl bg-white p-4" style={{ border: '1px solid #E2E8F0' }}>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">{label}</p>
      <p className={`text-[1.4rem] font-bold leading-none ${accent ? 'text-teal-600' : 'text-[#0F172A]'}`}>
        {value}
      </p>
      {sub && <p className="mt-1 text-[12px] text-[#94A3B8]">{sub}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Manual purchase modal
// ---------------------------------------------------------------------------

function ManualPurchaseModal({
  onClose,
  onSuccess,
}: {
  onClose: () => void
  onSuccess: () => void
}) {
  const [users, setUsers] = useState<SimpleUser[]>([])
  const [pathways, setPathways] = useState<SimplePaidPathway[]>([])
  const [loadingOptions, setLoadingOptions] = useState(true)
  const [optionsError, setOptionsError] = useState<string | null>(null)

  const [payerUserId, setPayerUserId] = useState('')
  const [pathwayId, setPathwayId] = useState('')
  const [notes, setNotes] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [result, setResult] = useState<PurchaseResult | null>(null)

  useEffect(() => {
    Promise.all([
      fetch(apiUrl('/api/admin/users/simple'), { credentials: 'include' }).then((r) => r.json()),
      fetch(apiUrl('/api/admin/pathways/paid-simple'), { credentials: 'include' }).then((r) => r.json()),
    ])
      .then(([u, p]) => {
        setUsers(u as SimpleUser[])
        setPathways(p as SimplePaidPathway[])
      })
      .catch((e: Error) => setOptionsError(e.message))
      .finally(() => setLoadingOptions(false))
  }, [])

  const selectedPathway = pathways.find((p) => p.id === pathwayId) ?? null

  const preview = selectedPathway
    ? (() => {
        const gross = selectedPathway.price_cents
        const feeCents = Math.round((gross * selectedPathway.creator_fee_basis_points) / 10000)
        const netCreator = gross - feeCents
        return { gross, feeCents, netCreator, currency: selectedPathway.currency, bps: selectedPathway.creator_fee_basis_points }
      })()
    : null

  async function handleSubmit() {
    if (!payerUserId || !pathwayId) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const res = await fetch(apiUrl('/api/admin/payments/manual-pathway-purchase'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payer_user_id: payerUserId, pathway_id: pathwayId, notes: notes || null }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error((data as { detail?: string }).detail ?? `Error ${res.status}`)
      }
      const data = await res.json() as PurchaseResult
      setResult(data)
    } catch (e) {
      setSubmitError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-2xl bg-white"
        style={{ border: '1px solid #E2E8F0' }}
      >
        <div className="flex items-center justify-between border-b px-6 py-4" style={{ borderColor: '#E2E8F0' }}>
          <h2 className="font-serif text-[17px] text-[#0F172A]">Record manual pathway purchase</h2>
          <button
            onClick={onClose}
            className="text-[#94A3B8] transition-colors hover:text-[#475569]"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {result ? (
          /* Success state */
          <div className="px-6 py-8 text-center">
            <div
              className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
              style={{ background: 'rgba(56,160,158,0.10)' }}
            >
              <svg className="h-6 w-6 text-teal-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <p className="font-serif text-[17px] text-[#0F172A]">Purchase recorded</p>
            <p className="mt-1 text-[13px] text-[#64748B]">
              {result.payer_name ?? result.payer_email} now has access to{' '}
              <span className="font-semibold text-[#0F172A]">{result.pathway_title}</span>
            </p>
            <div className="mx-auto mt-4 max-w-xs rounded-xl p-4 text-left text-[13px]" style={{ background: '#F8FAFC', border: '1px solid #E2E8F0' }}>
              <div className="flex justify-between py-1">
                <span className="text-[#64748B]">Gross</span>
                <span className="font-semibold text-[#0F172A]">{fmt(result.gross_amount_cents, result.currency)}</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-[#64748B]">FC fee ({result.platform_fee_basis_points / 100}%)</span>
                <span className="text-teal-600">{fmt(result.platform_fee_cents, result.currency)}</span>
              </div>
              <div className="flex justify-between border-t py-1 font-semibold" style={{ borderColor: '#E2E8F0' }}>
                <span className="text-[#64748B]">Creator net</span>
                <span className="text-[#0F172A]">{fmt(result.net_creator_amount_cents, result.currency)}</span>
              </div>
            </div>
            <button
              onClick={() => { onSuccess(); onClose() }}
              className="mt-5 inline-block rounded-full px-6 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Done
            </button>
          </div>
        ) : loadingOptions ? (
          <div className="flex items-center justify-center gap-2 px-6 py-10 text-[14px] text-[#64748B]">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
            Loading…
          </div>
        ) : optionsError ? (
          <div className="px-6 py-6 text-[14px] text-red-600">{optionsError}</div>
        ) : (
          <div className="px-6 py-5 space-y-4">
            {/* Member select */}
            <div>
              <label className="mb-1.5 block text-[12px] font-semibold uppercase tracking-wide text-[#64748B]">
                Member
              </label>
              <select
                className="w-full rounded-lg border px-3 py-2 text-[14px] text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-teal-400"
                style={{ borderColor: '#E2E8F0' }}
                value={payerUserId}
                onChange={(e) => setPayerUserId(e.target.value)}
              >
                <option value="">Select a member…</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name ? `${u.name} (${u.email})` : u.email}
                  </option>
                ))}
              </select>
            </div>

            {/* Pathway select */}
            <div>
              <label className="mb-1.5 block text-[12px] font-semibold uppercase tracking-wide text-[#64748B]">
                Pathway
              </label>
              <select
                className="w-full rounded-lg border px-3 py-2 text-[14px] text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-teal-400"
                style={{ borderColor: '#E2E8F0' }}
                value={pathwayId}
                onChange={(e) => setPathwayId(e.target.value)}
              >
                <option value="">Select a paid pathway…</option>
                {pathways.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.space_name} — {p.title} ({p.access_type === 'subscription' ? 'sub' : 'one-off'})
                  </option>
                ))}
              </select>
              {pathways.length === 0 && (
                <p className="mt-1 text-[12px] text-[#94A3B8]">No paid pathways found.</p>
              )}
            </div>

            {/* Price preview */}
            {preview && (
              <div className="rounded-xl p-4 text-[13px]" style={{ background: '#F8FAFC', border: '1px solid #E2E8F0' }}>
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[#94A3B8]">
                  Preview · {selectedPathway?.space_name}
                </p>
                <div className="space-y-1">
                  <div className="flex justify-between">
                    <span className="text-[#64748B]">Pathway</span>
                    <span className="font-medium text-[#0F172A]">{selectedPathway?.title}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#64748B]">
                      {selectedPathway?.access_type === 'subscription' ? 'Monthly price' : 'Price'}
                    </span>
                    <span className="font-semibold text-[#0F172A]">{fmt(preview.gross, preview.currency)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#64748B]">FC fee ({preview.bps / 100}%)</span>
                    <span className="text-teal-600">{fmt(preview.feeCents, preview.currency)}</span>
                  </div>
                  <div className="flex justify-between border-t pt-1 font-semibold" style={{ borderColor: '#E2E8F0' }}>
                    <span className="text-[#64748B]">Creator net</span>
                    <span className="text-[#0F172A]">{fmt(preview.netCreator, preview.currency)}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Notes */}
            <div>
              <label className="mb-1.5 block text-[12px] font-semibold uppercase tracking-wide text-[#64748B]">
                Notes <span className="font-normal normal-case text-[#94A3B8]">(optional)</span>
              </label>
              <input
                type="text"
                className="w-full rounded-lg border px-3 py-2 text-[14px] text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-teal-400"
                style={{ borderColor: '#E2E8F0' }}
                placeholder="e.g. Admin test, beta access, etc."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>

            {submitError && (
              <div className="rounded-lg bg-red-50 px-4 py-3 text-[13px] text-red-600" style={{ border: '1px solid #FCA5A5' }}>
                {submitError}
              </div>
            )}

            <div className="flex items-center justify-end gap-3 border-t pt-4" style={{ borderColor: '#E2E8F0' }}>
              <button
                onClick={onClose}
                className="rounded-full px-4 py-1.5 text-[13px] text-[#64748B] transition-colors hover:text-[#0F172A]"
              >
                Cancel
              </button>
              <button
                disabled={!payerUserId || !pathwayId || submitting}
                onClick={handleSubmit}
                className="rounded-full px-5 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {submitting ? 'Recording…' : 'Record purchase'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

interface PlatformStatus {
  stripe_enabled: boolean
  stripe_test_mode: boolean
}

export default function AdminPaymentsPage() {
  const [rows, setRows] = useState<PaymentTransaction[]>([])
  const [summary, setSummary] = useState<AdminPaymentSummary | null>(null)
  const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)

  function loadPayments() {
    setLoading(true)
    Promise.all([
      fetch(apiUrl('/api/admin/payments'), { credentials: 'include' }).then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json() as Promise<PaymentTransaction[]>
      }),
      fetch(apiUrl('/api/admin/payments/summary'), { credentials: 'include' }).then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json() as Promise<AdminPaymentSummary>
      }),
      fetch(apiUrl('/api/checkout/status'), { credentials: 'include' }).then((r) =>
        r.ok ? r.json() as Promise<PlatformStatus> : null
      ),
    ])
      .then(([txns, sum, status]) => {
        setRows(txns)
        setSummary(sum)
        if (status) setPlatformStatus(status)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadPayments() }, [])

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[14px] text-[#64748B]">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
        Loading transactions…
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600" style={{ border: '1px solid #FCA5A5' }}>
        {error}
      </div>
    )
  }

  const defaultCurrency = rows[0]?.currency ?? 'AUD'

  return (
    <>
      {showModal && (
        <ManualPurchaseModal
          onClose={() => setShowModal(false)}
          onSuccess={loadPayments}
        />
      )}

      <div>
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Payment Transactions</h1>
            <p className="mt-1 text-[13px] text-[#64748B]">
              All platform transaction records — Stripe payments, manual entries, and test/admin-simulated purchases.
            </p>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="shrink-0 rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            + Manual purchase
          </button>
        </div>

        {/* Platform Stripe status */}
        <div className="mb-5 overflow-hidden rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
          <div className="border-b px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]" style={{ borderColor: '#E2E8F0' }}>
            Fresh Collective Stripe Account
          </div>
          <div className="grid grid-cols-2 divide-x divide-[#F1F5F9] sm:grid-cols-4">
            {[
              {
                label: 'Platform payments',
                value: platformStatus == null ? '…' : platformStatus.stripe_enabled ? 'Configured' : 'Not configured',
                ok: platformStatus?.stripe_enabled,
              },
              {
                label: 'Mode',
                value: platformStatus == null ? '…' : !platformStatus.stripe_enabled ? '—' : platformStatus.stripe_test_mode ? 'Test mode' : 'Live mode',
                ok: platformStatus?.stripe_enabled && !platformStatus?.stripe_test_mode,
                warn: platformStatus?.stripe_test_mode,
              },
              {
                label: 'Webhook',
                value: platformStatus?.stripe_enabled ? 'Configured' : '—',
                ok: platformStatus?.stripe_enabled,
              },
              {
                label: 'Paid pathway checkout',
                value: platformStatus?.stripe_enabled ? 'Active' : 'Inactive',
                ok: platformStatus?.stripe_enabled,
              },
            ].map(({ label, value, ok, warn }) => (
              <div key={label} className="px-4 py-3">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">{label}</p>
                <p className={`text-[13px] font-semibold ${ok ? 'text-teal-700' : warn ? 'text-amber-600' : 'text-[#94A3B8]'}`}>
                  {value}
                </p>
              </div>
            ))}
          </div>
          <div className="border-t px-4 py-2.5 text-[11px] text-[#94A3B8]" style={{ borderColor: '#F1F5F9' }}>
            <span className="font-semibold text-[#64748B]">Payouts:</span> Manual for now — pending payout tracked per transaction.&ensp;
            <span className="font-semibold text-[#64748B]">Stripe Connect:</span> Coming later (Phase 2+).&ensp;
            <span className="font-semibold text-[#64748B]">Creator subscription billing:</span> Coming later (Phase 3).
          </div>
        </div>

        {/* Summary cards */}
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricCard
            label="Gross Sales"
            value={summary ? fmt(summary.total_gross_amount_cents, 'AUD') : '—'}
            sub="succeeded only"
          />
          <MetricCard
            label="FC Fees"
            value={summary ? fmt(summary.total_platform_fee_cents, 'AUD') : '—'}
            accent
          />
          <MetricCard
            label="Creator Net Earnings"
            value={summary ? fmt(summary.total_creator_net_amount_cents, 'AUD') : '—'}
          />
          <MetricCard
            label="Pending Payouts"
            value={summary ? fmt(summary.pending_payout_cents, 'AUD') : '—'}
            sub="not yet disbursed"
          />
        </div>

        {/* Status notes */}
        <div
          className="mb-6 space-y-2 rounded-xl px-4 py-3 text-[12px] text-[#64748B]"
          style={{ background: '#F8FAFC', border: '1px solid #E2E8F0' }}
        >
          <p>
            <strong className="text-[#475569]">Summary totals:</strong>{' '}
            Gross sales, FC fees, and creator net figures only include <strong className="text-[#475569]">succeeded</strong> transactions.
            Pending, failed, and cancelled rows are shown in the table below but excluded from all totals.
          </p>
          <p>
            <strong className="text-[#475569]">Manual / test transactions:</strong>{' '}
            Transactions with provider <span className="font-mono text-[11px] text-[#475569]">manual</span> are
            admin-simulated or manually entered records — not Stripe-processed payments. These are useful for
            testing and beta access grants. All figures shown include these records.
          </p>
          <p>
            <strong className="text-[#475569]">Payouts:</strong>{' '}
            Creator payouts are manual for Phase 1 — Stripe Connect is not yet enabled. The pending payout figure
            shows creator net earnings not yet disbursed. Mark as paid functionality coming soon.
          </p>
        </div>

        {/* Transactions */}
        {rows.length === 0 ? (
          <div
            className="rounded-xl bg-white p-10 text-center"
            style={{ border: '1px solid #E2E8F0' }}
          >
            <p className="text-[15px] font-medium text-[#0F172A]">No payment transactions yet.</p>
            <p className="mt-2 text-[13px] text-[#94A3B8]">
              Use the button above to simulate a manual purchase, or wait for Stripe integration.
            </p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
            {/* Desktop table */}
            <div className="hidden overflow-x-auto lg:block">
              <table className="w-full text-left">
                <thead>
                  <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                    {['Date', 'Type', 'Status', 'Payer', 'Creator', 'Space / Pathway', 'Gross', 'FC Fee', 'Creator Net', 'Payout', 'Provider', 'Session'].map((h) => (
                      <th key={h} className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr
                      key={row.id}
                      className={row.status !== 'succeeded' ? 'opacity-50' : undefined}
                      style={{ borderBottom: i < rows.length - 1 ? '1px solid #F1F5F9' : undefined }}
                    >
                      <td className="px-4 py-3 text-[12px] text-[#475569] whitespace-nowrap">
                        {fmtDate(row.created_at)}
                      </td>
                      <td className="px-4 py-3 text-[12px] text-[#475569]">
                        {labelType(row.transaction_type)}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={row.status} />
                      </td>
                      <td className="px-4 py-3 text-[12px] text-[#475569] font-mono">
                        {row.payer_user_id ? row.payer_user_id.slice(0, 8) + '…' : '—'}
                      </td>
                      <td className="px-4 py-3 text-[12px] text-[#475569] font-mono">
                        {row.creator_user_id ? row.creator_user_id.slice(0, 8) + '…' : '—'}
                      </td>
                      <td className="px-4 py-3 text-[12px] text-[#475569]">
                        {row.space_id || row.pathway_id
                          ? [row.space_id?.slice(0, 6), row.pathway_id?.slice(0, 6)].filter(Boolean).join(' / ')
                          : '—'}
                        {row.payment_option_id && (
                          <span className="ml-1 rounded-full bg-teal-50 border border-teal-200 px-1.5 py-0.5 text-[10px] font-semibold text-teal-700">
                            opt:{row.payment_option_id.slice(0, 6)}
                          </span>
                        )}
                        {row.payment_option_schedule_id && (
                          <span className="ml-1 rounded-full bg-purple-50 border border-purple-200 px-1.5 py-0.5 text-[10px] font-semibold text-purple-700">
                            sched:{row.payment_option_schedule_id.slice(0, 6)}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-[12px] font-semibold text-[#0F172A] whitespace-nowrap">
                        {fmt(row.gross_amount_cents, row.currency)}
                      </td>
                      <td className="px-4 py-3 text-[12px] text-teal-700 whitespace-nowrap">
                        {fmt(row.platform_fee_cents, row.currency)}
                      </td>
                      <td className="px-4 py-3 text-[12px] text-[#475569] whitespace-nowrap">
                        {row.net_creator_amount_cents != null
                          ? fmt(row.net_creator_amount_cents, row.currency)
                          : '—'}
                      </td>
                      <td className="px-4 py-3">
                        <PayoutBadge status={row.payout_status} />
                      </td>
                      <td className="px-4 py-3">
                        <ProviderBadge provider={row.payment_provider} />
                      </td>
                      <td className="px-4 py-3 text-[11px] font-mono text-[#94A3B8]">
                        {row.provider_checkout_session_id
                          ? row.provider_checkout_session_id.slice(0, 16) + '…'
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile cards */}
            <div className="divide-y divide-[#F1F5F9] lg:hidden">
              {rows.map((row) => (
                <div key={row.id} className={`p-4${row.status !== 'succeeded' ? ' opacity-50' : ''}`}>
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <div>
                      <p className="text-[13px] font-medium text-[#0F172A]">{labelType(row.transaction_type)}</p>
                      <p className="text-[11px] text-[#94A3B8]">{fmtDate(row.created_at)}</p>
                    </div>
                    <StatusBadge status={row.status} />
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-[12px]">
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Gross</p>
                      <p className="font-semibold text-[#0F172A]">{fmt(row.gross_amount_cents, row.currency)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">FC Fee</p>
                      <p className="text-teal-700">{fmt(row.platform_fee_cents, row.currency)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Creator Net</p>
                      <p className="text-[#475569]">
                        {row.net_creator_amount_cents != null ? fmt(row.net_creator_amount_cents, row.currency) : '—'}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  )
}
