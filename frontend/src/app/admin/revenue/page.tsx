'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface RevenueSummary {
  total_fc_revenue_cents: number
  subscription_revenue_cents: number
  platform_fee_revenue_cents: number
  total_gross_sales_cents: number
  total_creator_net_cents: number
  paid_out_cents: number
  pending_payout_cents: number
  succeeded_transactions: number
  refunded_transactions: number
  failed_transactions: number
}

interface RevenueByCreatorRow {
  creator_user_id: string
  creator_name: string | null
  creator_email: string
  collective_count: number
  gross_sales_cents: number
  platform_fees_cents: number
  creator_net_cents: number
  subscription_revenue_cents: number
  total_fc_revenue_cents: number
  paid_out_cents: number
  pending_payout_cents: number
}

function fmt(cents: number) {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: 'AUD',
    minimumFractionDigits: 0,
  }).format(cents / 100)
}

function SummaryCard({
  label,
  value,
  sub,
  highlight,
  warn,
}: {
  label: string
  value: string
  sub?: string
  highlight?: boolean
  warn?: boolean
}) {
  return (
    <div
      className="rounded-xl bg-white p-4"
      style={{
        border: `1px solid ${highlight ? 'rgba(56,160,158,0.3)' : warn ? '#FCA5A5' : '#E2E8F0'}`,
        background: highlight ? 'rgba(56,160,158,0.03)' : undefined,
      }}
    >
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">{label}</p>
      <p className={`text-[1.5rem] font-bold leading-none ${highlight ? 'text-teal-700' : warn ? 'text-red-600' : 'text-[#0F172A]'}`}>
        {value}
      </p>
      {sub && <p className="mt-1 text-[11px] text-[#94A3B8]">{sub}</p>}
    </div>
  )
}

export default function AdminRevenuePage() {
  const [summary, setSummary] = useState<RevenueSummary | null>(null)
  const [byCreator, setByCreator] = useState<RevenueByCreatorRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      fetch(apiUrl('/api/admin/revenue/summary'), { credentials: 'include' }).then((r) => {
        if (!r.ok) throw new Error(`Summary: Error ${r.status}`)
        return r.json() as Promise<RevenueSummary>
      }),
      fetch(apiUrl('/api/admin/revenue/by-creator'), { credentials: 'include' }).then((r) => {
        if (!r.ok) throw new Error(`By-creator: Error ${r.status}`)
        return r.json() as Promise<RevenueByCreatorRow[]>
      }),
    ])
      .then(([s, c]) => { setSummary(s); setByCreator(c) })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[14px] text-[#64748B]">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
        Loading…
      </div>
    )
  }

  if (error || !summary) {
    return (
      <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600" style={{ border: '1px solid #FCA5A5' }}>
        {error ?? 'No data'}
      </div>
    )
  }

  const noTransactions = summary.succeeded_transactions === 0

  return (
    <div>
      <h1 className="mb-1 text-[1.5rem] font-bold text-[#0F172A]">Revenue</h1>
      <p className="mb-6 text-[13px] text-[#64748B]">
        Fresh Collective revenue from creator subscriptions and platform fees on member purchases.
        Gross creator sales are shown separately — they belong to creators, not Fresh Collective.
      </p>

      <div
        className="mb-6 rounded-xl bg-slate-50 px-4 py-3 text-[12px] text-[#64748B]"
        style={{ border: '1px solid #E2E8F0' }}
      >
        <strong className="text-[#475569]">Note:</strong>{' '}
        {noTransactions
          ? 'No payment transactions recorded yet. Revenue will appear here once creator subscriptions and member purchases are processed.'
          : 'Current figures may include manually entered and admin-simulated (test) transactions until Stripe processing is connected. Manual transactions have provider = "manual".'}
      </div>

      {/* Fresh Collective Revenue */}
      <div className="mb-6">
        <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-[#94A3B8]">
          Fresh Collective Revenue
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <SummaryCard
            label="Total FC Revenue"
            value={fmt(summary.total_fc_revenue_cents)}
            sub="subscriptions + platform fees"
            highlight
          />
          <SummaryCard
            label="Creator Subscription Fees"
            value={fmt(summary.subscription_revenue_cents)}
            sub="monthly plan revenue"
          />
          <SummaryCard
            label="Platform Fees from Sales"
            value={fmt(summary.platform_fee_revenue_cents)}
            sub="% retained from member purchases"
          />
        </div>
      </div>

      {/* Creator Sales (pass-through) */}
      <div className="mb-6">
        <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-[#94A3B8]">
          Creator Sales (Gross / Pass-Through)
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <SummaryCard
            label="Gross Member Sales"
            value={fmt(summary.total_gross_sales_cents)}
            sub="total paid by members"
          />
          <SummaryCard
            label="Creator Net Earnings"
            value={fmt(summary.total_creator_net_cents)}
            sub="owed to creators after fees"
          />
          <SummaryCard
            label="Paid Out"
            value={fmt(summary.paid_out_cents)}
            sub="transferred to creators"
          />
          <SummaryCard
            label="Pending Payout"
            value={fmt(summary.pending_payout_cents)}
            sub="awaiting payout"
            warn={summary.pending_payout_cents > 0}
          />
        </div>
      </div>

      {/* Transaction counts */}
      <div className="mb-8">
        <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-[#94A3B8]">Transactions</h2>
        <div className="grid grid-cols-3 gap-3">
          <SummaryCard label="Succeeded" value={String(summary.succeeded_transactions)} />
          <SummaryCard label="Refunded" value={String(summary.refunded_transactions)} warn={summary.refunded_transactions > 0} />
          <SummaryCard label="Failed" value={String(summary.failed_transactions)} warn={summary.failed_transactions > 0} />
        </div>
      </div>

      {/* Per-creator breakdown */}
      <div>
        <h2 className="mb-3 text-[18px] font-bold text-[#0F172A]">Revenue by Creator</h2>

        {byCreator.length === 0 ? (
          <div className="rounded-xl bg-white p-8 text-center text-[14px] text-[#94A3B8]" style={{ border: '1px solid #E2E8F0' }}>
            No creator revenue data yet.
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
            {/* Desktop */}
            <div className="hidden overflow-x-auto lg:block">
              <table className="w-full text-left">
                <thead>
                  <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                    {[
                      'Creator',
                      'Collectives',
                      'Gross Sales',
                      'FC Platform Fee',
                      'Creator Net',
                      'Sub Revenue',
                      'Total FC Revenue',
                      'Paid Out',
                      'Pending Payout',
                    ].map((h) => (
                      <th key={h} className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {byCreator.map((row, i) => (
                    <tr
                      key={row.creator_user_id}
                      style={{ borderBottom: i < byCreator.length - 1 ? '1px solid #F1F5F9' : undefined }}
                    >
                      <td className="px-4 py-3">
                        <p className="text-[13px] font-medium text-[#0F172A]">{row.creator_name ?? '—'}</p>
                        <p className="text-[11px] text-[#94A3B8]">{row.creator_email}</p>
                      </td>
                      <td className="px-4 py-3 text-[13px] text-[#475569]">{row.collective_count}</td>
                      <td className="px-4 py-3 text-[13px] text-[#475569]">{fmt(row.gross_sales_cents)}</td>
                      <td className="px-4 py-3 text-[13px] font-medium text-teal-700">{fmt(row.platform_fees_cents)}</td>
                      <td className="px-4 py-3 text-[13px] text-[#475569]">{fmt(row.creator_net_cents)}</td>
                      <td className="px-4 py-3 text-[13px] font-medium text-teal-700">{fmt(row.subscription_revenue_cents)}</td>
                      <td className="px-4 py-3">
                        <p className="text-[14px] font-bold text-teal-700">{fmt(row.total_fc_revenue_cents)}</p>
                      </td>
                      <td className="px-4 py-3 text-[13px] text-[#475569]">{fmt(row.paid_out_cents)}</td>
                      <td className="px-4 py-3">
                        {row.pending_payout_cents > 0 ? (
                          <span className="text-[13px] font-medium text-amber-600">{fmt(row.pending_payout_cents)}</span>
                        ) : (
                          <span className="text-[13px] text-[#94A3B8]">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile cards */}
            <div className="divide-y divide-[#F1F5F9] lg:hidden">
              {byCreator.map((row) => (
                <div key={row.creator_user_id} className="p-4">
                  <div className="mb-2">
                    <p className="text-[14px] font-semibold text-[#0F172A]">{row.creator_name ?? row.creator_email}</p>
                    <p className="text-[12px] text-[#64748B]">{row.creator_email}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[12px]">
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Total FC Revenue</p>
                      <p className="font-bold text-teal-700">{fmt(row.total_fc_revenue_cents)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Gross Sales</p>
                      <p className="font-medium text-[#0F172A]">{fmt(row.gross_sales_cents)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Platform Fee</p>
                      <p className="font-medium text-teal-700">{fmt(row.platform_fees_cents)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Sub Revenue</p>
                      <p className="font-medium text-teal-700">{fmt(row.subscription_revenue_cents)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Creator Net</p>
                      <p className="font-medium text-[#475569]">{fmt(row.creator_net_cents)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Pending Payout</p>
                      <p className={row.pending_payout_cents > 0 ? 'font-medium text-amber-600' : 'text-[#94A3B8]'}>
                        {row.pending_payout_cents > 0 ? fmt(row.pending_payout_cents) : '—'}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div
        className="mt-6 rounded-xl bg-slate-50 px-4 py-3 text-[12px] text-[#64748B]"
        style={{ border: '1px solid #E2E8F0' }}
      >
        <strong className="text-[#475569]">What is tracked vs. pending:</strong>{' '}
        Gross sales, platform fees, and creator net figures are calculated from PaymentTransaction records.
        Creator subscription revenue requires manual PaymentTransaction records of type{' '}
        <code className="rounded bg-slate-200 px-1 font-mono text-[11px]">creator_subscription_payment</code>.
        Processing fees (Stripe charges) and Stripe payout tracking will populate once Stripe Connect is connected.
        Payout status must currently be updated manually via the Payments page.
      </div>
    </div>
  )
}
