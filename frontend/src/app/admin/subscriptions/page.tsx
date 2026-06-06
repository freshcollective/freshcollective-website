'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface CreatorSubscriptionRow {
  id: string
  user_id: string
  user_name: string | null
  user_email: string
  plan_id: string
  plan_name: string
  plan_slug: string
  monthly_price_cents: number
  currency: string
  transaction_fee_basis_points: number
  status: string
  starts_at: string
  ends_at: string | null
  stripe_subscription_id: string | null
  stripe_customer_id: string | null
  created_at: string
  updated_at: string
}

function fmt(cents: number, currency: string) {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 0,
  }).format(cents / 100)
}

function fmtDate(s: string | null) {
  if (!s) return '—'
  return new Date(s).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: 'bg-teal-50 text-teal-700 border-teal-200',
    trialing: 'bg-blue-50 text-blue-700 border-blue-200',
    past_due: 'bg-amber-50 text-amber-700 border-amber-200',
    cancelled: 'bg-slate-100 text-slate-500 border-slate-200',
    unpaid: 'bg-red-50 text-red-700 border-red-200',
  }
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${map[status] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

export default function AdminSubscriptionsPage() {
  const [rows, setRows] = useState<CreatorSubscriptionRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('')

  useEffect(() => {
    fetch(apiUrl('/api/admin/creator-subscriptions'), { credentials: 'include' })
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
        Loading…
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

  const filtered = statusFilter
    ? rows.filter((r) => r.status === statusFilter)
    : rows

  const activeCount = rows.filter((r) => r.status === 'active').length
  const pastDueCount = rows.filter((r) => r.status === 'past_due' || r.status === 'unpaid').length

  return (
    <div>
      <h1 className="mb-1 text-[1.5rem] font-bold text-[#0F172A]">Creator Subscriptions</h1>
      <p className="mb-4 text-[13px] text-[#64748B]">
        Each creator on Fresh Collective subscribes to a plan that determines their monthly fee,
        transaction fee rate, and collective limits.
      </p>

      {pastDueCount > 0 && (
        <div
          className="mb-4 flex items-center gap-2 rounded-xl bg-amber-50 px-4 py-3"
          style={{ border: '1px solid #FCD34D' }}
        >
          <span>⚠</span>
          <p className="text-[13px] font-medium text-amber-800">
            {pastDueCount} subscription{pastDueCount !== 1 ? 's' : ''} past due or unpaid — review and follow up.
          </p>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-lg border border-[#E2E8F0] bg-white px-3 py-1.5 text-[13px] outline-none"
        >
          <option value="">All statuses ({rows.length})</option>
          <option value="active">Active ({activeCount})</option>
          <option value="trialing">Trialing</option>
          <option value="past_due">Past Due</option>
          <option value="unpaid">Unpaid</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      <div className="overflow-hidden rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
        {/* Desktop */}
        <div className="hidden overflow-x-auto lg:block">
          <table className="w-full text-left">
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                {['Creator', 'Plan', 'Price', 'Fee', 'Status', 'Started', 'Ends', 'Stripe'].map((h) => (
                  <th key={h} className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, i) => (
                <tr
                  key={row.id}
                  style={{
                    borderBottom: i < filtered.length - 1 ? '1px solid #F1F5F9' : undefined,
                    background: row.status === 'past_due' || row.status === 'unpaid' ? '#FFFBEB' : undefined,
                  }}
                >
                  <td className="px-4 py-3">
                    <p className="text-[13px] font-medium text-[#0F172A]">{row.user_name ?? '—'}</p>
                    <p className="text-[11px] text-[#94A3B8]">{row.user_email}</p>
                  </td>
                  <td className="px-4 py-3">
                    <p className="text-[13px] text-[#0F172A]">{row.plan_name}</p>
                    <p className="font-mono text-[10px] text-[#CBD5E1]">{row.plan_slug}</p>
                  </td>
                  <td className="px-4 py-3 text-[13px] text-[#0F172A]">
                    {fmt(row.monthly_price_cents, row.currency)}/mo
                  </td>
                  <td className="px-4 py-3 text-[13px] text-[#475569]">
                    {(row.transaction_fee_basis_points / 100).toFixed(0)}%
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={row.status} /></td>
                  <td className="px-4 py-3 text-[12px] text-[#94A3B8]">{fmtDate(row.starts_at)}</td>
                  <td className="px-4 py-3 text-[12px] text-[#94A3B8]">{fmtDate(row.ends_at)}</td>
                  <td className="px-4 py-3">
                    {row.stripe_subscription_id ? (
                      <span className="font-mono text-[11px] text-[#64748B]">
                        {row.stripe_subscription_id.slice(0, 16)}…
                      </span>
                    ) : (
                      <span className="text-[11px] text-[#CBD5E1]">Not connected</span>
                    )}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-[13px] text-[#94A3B8]">
                    No subscriptions found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Mobile cards */}
        <div className="divide-y divide-[#F1F5F9] lg:hidden">
          {filtered.map((row) => (
            <div
              key={row.id}
              className="p-4"
              style={{ background: row.status === 'past_due' || row.status === 'unpaid' ? '#FFFBEB' : undefined }}
            >
              <div className="mb-1 flex items-start justify-between gap-2">
                <div>
                  <p className="text-[14px] font-semibold text-[#0F172A]">{row.user_name ?? row.user_email}</p>
                  <p className="text-[12px] text-[#64748B]">{row.user_email}</p>
                </div>
                <StatusBadge status={row.status} />
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-[12px]">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Plan</p>
                  <p className="font-medium text-[#0F172A]">{row.plan_name}</p>
                  <p className="text-[#94A3B8]">{fmt(row.monthly_price_cents, row.currency)}/mo</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Fee</p>
                  <p className="font-medium text-[#0F172A]">{(row.transaction_fee_basis_points / 100).toFixed(0)}%</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Started</p>
                  <p className="font-medium text-[#0F172A]">{fmtDate(row.starts_at)}</p>
                </div>
              </div>
            </div>
          ))}
          {filtered.length === 0 && (
            <p className="p-6 text-center text-[13px] text-[#94A3B8]">No subscriptions found.</p>
          )}
        </div>
      </div>

      <div
        className="mt-4 rounded-xl bg-slate-50 px-4 py-3 text-[12px] text-[#64748B]"
        style={{ border: '1px solid #E2E8F0' }}
      >
        <strong className="text-[#475569]">Stripe:</strong> Subscription billing is not yet connected to Stripe.
        Stripe subscription IDs will appear here once live billing is enabled. Subscription status changes
        must currently be made manually via Creator Billing.
      </div>
    </div>
  )
}
