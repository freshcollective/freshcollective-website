'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface CreatorPaymentSummary {
  total_gross_amount_cents: number
  total_platform_fee_cents: number
  total_creator_net_amount_cents: number
  pending_payout_cents: number
  succeeded_count: number
  refunded_count: number
  disputed_count: number
  pending_count: number
}

interface CreatorPaymentTransaction {
  id: string
  transaction_type: string
  status: string
  payer_user_id: string | null
  space_id: string | null
  pathway_id: string | null
  payment_option_id: string | null
  payment_option_schedule_id: string | null
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

function SummaryCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub?: string
  accent?: boolean
}) {
  return (
    <div className="rounded-xl bg-white p-4" style={{ border: '1px solid #E2E8F0' }}>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">{label}</p>
      <p className={`text-[1.35rem] font-bold leading-none ${accent ? 'text-teal-600' : 'text-[#0F172A]'}`}>
        {value}
      </p>
      {sub && <p className="mt-1 text-[11px] text-[#94A3B8]">{sub}</p>}
    </div>
  )
}

const PRICING_OPTIONS = [
  {
    title: 'Free collective',
    description: 'Members join at no cost. Great for community-led spaces.',
  },
  {
    title: 'Paid collective',
    description: 'Charge a one-time or recurring fee for full Space access.',
  },
  {
    title: 'Paid pathway',
    description: 'Offer individual pathways for purchase within a free or paid Space.',
  },
  {
    title: 'Paid gathering',
    description: 'Sell tickets or charge for individual live events.',
  },
  {
    title: 'Included with membership',
    description: 'Bundle Space access into a platform-wide membership subscription.',
  },
]

export default function CreatorPaymentsClient({
  feeBasisPoints,
  currency,
  stripeEnabled,
  stripeTestMode,
}: {
  feeBasisPoints: number
  currency: string
  stripeEnabled: boolean
  stripeTestMode: boolean
}) {
  const [summary, setSummary] = useState<CreatorPaymentSummary | null>(null)
  const [rows, setRows] = useState<CreatorPaymentTransaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      fetch(apiUrl('/api/creator/payments/summary'), { credentials: 'include' }).then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json() as Promise<CreatorPaymentSummary>
      }),
      fetch(apiUrl('/api/creator/payments'), { credentials: 'include' }).then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json() as Promise<CreatorPaymentTransaction[]>
      }),
    ])
      .then(([sum, txns]) => { setSummary(sum); setRows(txns) })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const feeDisplay = `${(feeBasisPoints / 100).toFixed(0)}%`
  const displayCurrency = rows[0]?.currency ?? currency

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
          Track member purchases, fees, and estimated payouts for your collectives.
        </p>
      </div>

      {/* Platform payment status */}
      {stripeEnabled ? (
        <div
          className="mb-6 rounded-2xl p-5"
          style={{ background: '#F0FDFB', border: '1px solid #99E6E4' }}
        >
          <div className="flex items-start gap-3">
            <div
              className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
              style={{ background: '#38A09E' }}
            >
              ✓
            </div>
            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[14px] font-semibold" style={{ color: '#0F766E' }}>
                  Paid pathway checkout is available
                </p>
                {stripeTestMode && (
                  <span
                    className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                    style={{ background: '#FDE68A', color: '#78350F' }}
                  >
                    Test mode
                  </span>
                )}
              </div>
              <p className="mt-1 text-[13px] leading-relaxed" style={{ color: '#0F766E' }}>
                Payments are processed through Fresh Collective during this phase. Members can
                purchase paid pathways now. You do not need to connect your own Stripe account.
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div
          className="mb-6 rounded-2xl p-5"
          style={{ background: '#FFFBEB', border: '1px solid #FDE68A' }}
        >
          <div className="flex items-start gap-3">
            <div
              className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
              style={{ background: '#FEF3C7', color: '#92400E' }}
            >
              !
            </div>
            <div className="flex-1">
              <p className="text-[14px] font-semibold" style={{ color: '#92400E' }}>
                Payments are not configured yet
              </p>
              <p className="mt-1 text-[13px] leading-relaxed" style={{ color: '#78350F' }}>
                The Fresh Collective platform Stripe account has not been set up. Members cannot
                purchase paid pathways until this is resolved. Contact Fresh Collective support.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Creator plan */}
      <div
        className="mb-6 rounded-2xl p-5"
        style={{ background: '#F0FDFB', border: '1px solid #99E6E4' }}
      >
        <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-wider" style={{ color: '#38A09E' }}>
          Your creator plan
        </p>
        <p className="font-serif text-[1.1rem] font-semibold text-[#0F172A]">
          Founding Creator Access
        </p>
        <div className="mt-3 flex flex-wrap gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">Trial</p>
            {/* TODO: wire to Stripe trial_period_days: 14 when payment setup is enabled */}
            <p className="text-[14px] font-semibold text-[#0F172A]">14 days free</p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">Then</p>
            <p className="text-[14px] font-semibold text-[#0F172A]">$19 / month</p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">Transaction fee</p>
            <p className="text-[14px] font-semibold text-[#0F172A]">{feeDisplay} per sale</p>
          </div>
        </div>
        <p className="mt-3 text-[12px]" style={{ color: '#64748B' }}>
          No hidden fees. The transaction fee covers payment processing and platform infrastructure.
        </p>
      </div>

      {/* Access and pricing options */}
      <div className="mb-8">
        <div className="mb-3 flex items-baseline gap-2">
          <h2 className="text-[15px] font-semibold text-[#0F172A]">Access and pricing options</h2>
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
            style={{ background: '#E2E8F0', color: '#64748B' }}
          >
            Coming soon
          </span>
        </div>
        <p className="mb-4 text-[13px]" style={{ color: '#64748B' }}>
          Choose how members access your collective. Pricing configuration will be available in a
          future update.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {PRICING_OPTIONS.map((opt) => (
            <div
              key={opt.title}
              className="rounded-xl p-4 opacity-60"
              style={{ background: '#F8FAFC', border: '1px dashed #CBD5E1' }}
            >
              <p className="text-[13px] font-semibold text-[#0F172A]">{opt.title}</p>
              <p className="mt-1 text-[12px] leading-relaxed text-[#64748B]">{opt.description}</p>
              <p className="mt-2 text-[11px] font-semibold uppercase tracking-wide" style={{ color: '#94A3B8' }}>
                Coming soon
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Divider */}
      <div className="mb-6" style={{ borderTop: '1px solid #E2E8F0' }} />

      {/* Transaction history heading */}
      <div className="mb-4">
        <h2 className="text-[15px] font-semibold text-[#0F172A]">Transaction history</h2>
        <p className="mt-0.5 text-[13px]" style={{ color: '#64748B' }}>
          Payments recorded when member purchases are processed through Stripe.
        </p>
      </div>

      {stripeTestMode && (
        <div
          className="mb-4 flex items-center gap-2 rounded-xl px-4 py-2.5 text-[12px]"
          style={{ background: '#FFFBEB', border: '1px solid #FDE68A' }}
        >
          <span className="font-semibold" style={{ color: '#92400E' }}>Test mode — sandbox data only.</span>
          <span style={{ color: '#78350F' }}>These transactions were made using Stripe test cards and are not real payments.</span>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-2 text-[14px] text-[#64748B]">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
          Loading payments…
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600" style={{ border: '1px solid #FCA5A5' }}>
          {error}
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Summary cards */}
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <SummaryCard
              label="Gross Sales"
              value={summary ? fmt(summary.total_gross_amount_cents, displayCurrency) : '—'}
              sub="succeeded only"
            />
            <SummaryCard
              label="FC Fee"
              value={summary ? fmt(summary.total_platform_fee_cents, displayCurrency) : '—'}
              sub="platform fee retained"
              accent
            />
            <SummaryCard
              label="Est. Creator Earnings"
              value={summary ? fmt(summary.total_creator_net_amount_cents, displayCurrency) : '—'}
              sub={`after ${feeDisplay} fee`}
            />
            <SummaryCard
              label="Pending Payout"
              value={summary ? fmt(summary.pending_payout_cents, displayCurrency) : '—'}
              sub="not yet disbursed"
            />
          </div>

          {/* Payout note */}
          <div
            className="mb-6 flex items-start gap-2 rounded-xl px-4 py-3 text-[12px] text-[#64748B]"
            style={{ background: '#F8FAFC', border: '1px solid #E2E8F0' }}
          >
            <span className="mt-0.5 shrink-0 text-[#94A3B8]">ℹ</span>
            <span>
              Your creator earnings are tracked as pending payout. Automatic payouts via Stripe
              Connect are coming in a future update — for now, payouts are handled manually by
              Fresh Collective. Your transaction fee is{' '}
              <span className="font-semibold text-[#0F172A]">{feeDisplay}</span>{' '}
              per sale.
            </span>
          </div>

          {/* Empty state */}
          {rows.length === 0 ? (
            <div
              className="rounded-2xl p-10 text-center"
              style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
            >
              <p className="text-[15px] font-medium text-[#0F172A]">No member payments yet.</p>
              <p className="mt-2 text-[13px] text-[#94A3B8]">
                When members purchase paid pathways, transactions will appear here.
              </p>
            </div>
          ) : (
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
                        className={row.status !== 'succeeded' ? 'opacity-50' : undefined}
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
        </>
      )}
    </div>
  )
}
