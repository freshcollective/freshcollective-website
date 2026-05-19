'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface PaymentTransaction {
  id: string
  transaction_type: string
  status: string
  payment_provider: string
  payer_user_id: string | null
  creator_user_id: string | null
  space_id: string | null
  pathway_id: string | null
  currency: string
  gross_amount_cents: number
  platform_fee_basis_points: number
  platform_fee_cents: number
  net_creator_amount_cents: number | null
  net_platform_amount_cents: number | null
  provider_payment_intent_id: string | null
  notes: string | null
  created_at: string
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

export default function AdminPaymentsPage() {
  const [rows, setRows] = useState<PaymentTransaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(apiUrl('/api/admin/payments'), { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json()
      })
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

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

  const succeeded = rows.filter((r) => r.status === 'succeeded')
  const totalGross = succeeded.reduce((s, r) => s + r.gross_amount_cents, 0)
  const totalFee = succeeded.reduce((s, r) => s + r.platform_fee_cents, 0)
  const totalCreatorNet = succeeded.reduce((s, r) => s + (r.net_creator_amount_cents ?? 0), 0)
  const pendingCount = rows.filter((r) => r.status === 'pending').length
  const defaultCurrency = rows[0]?.currency ?? 'AUD'

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Payment Transactions</h1>
        <p className="mt-1 text-[14px] text-[#64748B]">
          Future payment activity, platform fees, refunds, and creator earnings will appear here.
        </p>
      </div>

      {/* Summary cards */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard
          label="Total Gross Sales"
          value={rows.length ? fmt(totalGross, defaultCurrency) : '—'}
          sub="succeeded only"
        />
        <MetricCard
          label="FC Fees"
          value={rows.length ? fmt(totalFee, defaultCurrency) : '—'}
          accent
        />
        <MetricCard
          label="Creator Net Earnings"
          value={rows.length ? fmt(totalCreatorNet, defaultCurrency) : '—'}
        />
        <MetricCard
          label="Pending"
          value={pendingCount}
          sub="transactions"
        />
      </div>

      {/* Transactions */}
      {rows.length === 0 ? (
        <div
          className="rounded-xl bg-white p-10 text-center"
          style={{ border: '1px solid #E2E8F0' }}
        >
          <p className="text-[15px] font-medium text-[#0F172A]">No payment transactions yet.</p>
          <p className="mt-2 text-[13px] text-[#94A3B8]">
            Stripe is not connected, so this ledger is ready but inactive.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
          {/* Desktop table */}
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full text-left">
              <thead>
                <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                  {['Date', 'Type', 'Status', 'Payer', 'Creator', 'Space / Pathway', 'Gross', 'FC Fee', 'Creator Net', 'Provider'].map((h) => (
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
                    <td className="px-4 py-3 text-[12px] capitalize text-[#94A3B8]">
                      {row.payment_provider}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="divide-y divide-[#F1F5F9] lg:hidden">
            {rows.map((row) => (
              <div key={row.id} className="p-4">
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
  )
}
