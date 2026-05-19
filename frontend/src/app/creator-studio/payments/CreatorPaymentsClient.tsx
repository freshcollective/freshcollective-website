'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface CreatorPaymentTransaction {
  id: string
  transaction_type: string
  status: string
  payer_user_id: string | null
  space_id: string | null
  pathway_id: string | null
  currency: string
  gross_amount_cents: number
  platform_fee_basis_points: number
  platform_fee_cents: number
  net_creator_amount_cents: number | null
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
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${cls}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

export default function CreatorPaymentsClient({
  feeBasisPoints,
  currency,
}: {
  feeBasisPoints: number
  currency: string
}) {
  const [rows, setRows] = useState<CreatorPaymentTransaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(apiUrl('/api/creator/payments'), { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json()
      })
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const feeDisplay = `${(feeBasisPoints / 100).toFixed(0)}%`

  return (
    <div className="w-full max-w-[1100px] px-6 py-8 md:px-10 md:py-10">

      {/* Header */}
      <div className="mb-6">
        <p
          className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Payments</h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
          Track member purchases, fees, and future payouts for your collectives.
        </p>
      </div>

      {/* Plan fee callout */}
      <div
        className="mb-6 flex items-center gap-3 rounded-xl p-4"
        style={{ background: '#F0FAFA', border: '1px solid #C5E8E7' }}
      >
        <div
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[13px] font-bold"
          style={{ background: '#38A09E', color: '#fff' }}
        >
          %
        </div>
        <div>
          <p className="text-[13px] font-semibold text-[#0F172A]">
            Your current plan transaction fee: {feeDisplay}
          </p>
          <p className="text-[12px] text-[#64748B]">
            Fresh Collective deducts {feeDisplay} from each member sale. The remainder is your estimated payout (before Stripe fees).
          </p>
        </div>
      </div>

      {/* State: loading */}
      {loading && (
        <div className="flex items-center gap-2 text-[14px] text-[#64748B]">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
          Loading payments…
        </div>
      )}

      {/* State: error */}
      {!loading && error && (
        <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600" style={{ border: '1px solid #FCA5A5' }}>
          {error}
        </div>
      )}

      {/* State: empty */}
      {!loading && !error && rows.length === 0 && (
        <div
          className="rounded-2xl p-10 text-center"
          style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
        >
          <p className="text-[15px] font-medium text-[#0F172A]">No member payments yet.</p>
          <p className="mt-2 text-[13px] text-[#94A3B8]">
            Checkout is not connected yet.
          </p>
        </div>
      )}

      {/* State: data */}
      {!loading && !error && rows.length > 0 && (
        <div className="overflow-hidden rounded-2xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
          {/* Desktop table */}
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full text-left">
              <thead>
                <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                  {['Date', 'Member / Payer', 'Collective / Pathway', 'Gross Sale', 'FC Fee', 'Est. Creator Amount', 'Status'].map((h) => (
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
                    <td className="px-4 py-3 text-[12px] text-[#475569] font-mono">
                      {row.payer_user_id ? row.payer_user_id.slice(0, 8) + '…' : '—'}
                    </td>
                    <td className="px-4 py-3 text-[12px] text-[#475569]">
                      {row.space_id || row.pathway_id
                        ? [row.space_id?.slice(0, 6), row.pathway_id?.slice(0, 6)].filter(Boolean).join(' / ')
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-[12px] font-semibold text-[#0F172A] whitespace-nowrap">
                      {fmt(row.gross_amount_cents, row.currency)}
                    </td>
                    <td className="px-4 py-3 text-[12px] text-[#64748B] whitespace-nowrap">
                      {fmt(row.platform_fee_cents, row.currency)}
                    </td>
                    <td className="px-4 py-3 text-[12px] font-semibold whitespace-nowrap" style={{ color: '#38A09E' }}>
                      {row.net_creator_amount_cents != null
                        ? fmt(row.net_creator_amount_cents, row.currency)
                        : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={row.status} />
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
                    <p className="text-[#64748B]">{fmt(row.platform_fee_cents, row.currency)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Creator Net</p>
                    <p style={{ color: '#38A09E' }}>
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
