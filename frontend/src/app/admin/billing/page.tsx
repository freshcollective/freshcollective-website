'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiUrl } from '@/lib/api'

interface CreatorBillingRow {
  user_id: string
  name: string | null
  email: string
  current_plan_name: string
  current_plan_slug: string
  monthly_price_cents: number
  currency: string
  transaction_fee_basis_points: number
  collective_limit: number
  subscription_status: string
  collectives_used: number
  pathways_used: number
  joined_at: string
}

function fmt(cents: number, currency: string) {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 0,
  }).format(cents / 100)
}

function fmtFee(basisPoints: number) {
  return `${(basisPoints / 100).toFixed(0)}%`
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    active: 'bg-teal-50 text-teal-700 border-teal-200',
    trialing: 'bg-blue-50 text-blue-700 border-blue-200',
    past_due: 'bg-amber-50 text-amber-700 border-amber-200',
    cancelled: 'bg-slate-100 text-slate-500 border-slate-200',
    unpaid: 'bg-red-50 text-red-700 border-red-200',
    none: 'bg-slate-100 text-slate-500 border-slate-200',
  }
  const cls = styles[status] ?? 'bg-slate-100 text-slate-500 border-slate-200'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${cls}`}>
      {status}
    </span>
  )
}

function MetricCard({
  label,
  value,
  warn,
}: {
  label: string
  value: string | number
  warn?: boolean
}) {
  return (
    <div
      className="rounded-xl bg-white p-4"
      style={{ border: `1px solid ${warn ? '#FCA5A5' : '#E2E8F0'}` }}
    >
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
        {label}
      </p>
      <p className={`text-[1.5rem] font-bold leading-none ${warn ? 'text-red-600' : 'text-[#0F172A]'}`}>
        {value}
      </p>
    </div>
  )
}

function PlanDropdown({
  row,
  onSaved,
}: {
  row: CreatorBillingRow
  onSaved: (updated: CreatorBillingRow) => void
}) {
  const [selected, setSelected] = useState(row.current_plan_slug)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dirty = selected !== row.current_plan_slug
  const downgradingWithOverLimit =
    selected === 'creator-basic' && row.collectives_used > 1

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/creator-billing/${row.user_id}/plan`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ creator_plan_slug: selected }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail ?? `Error ${res.status}`)
      }
      const updated: CreatorBillingRow = await res.json()
      onSaved(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <select
          value={selected}
          onChange={(e) => { setSelected(e.target.value); setSaved(false); setError(null) }}
          className="rounded-lg border border-[#E2E8F0] bg-white px-2.5 py-1.5 text-[12px] text-[#0F172A] focus:border-teal-500 focus:outline-none"
        >
          <option value="creator-basic">Basic</option>
          <option value="creator-plus">Plus</option>
        </select>
        {dirty && (
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-teal-500 px-3 py-1.5 text-[12px] font-semibold text-white transition-colors hover:bg-teal-600 disabled:opacity-60"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        )}
        {saved && !dirty && (
          <span className="text-[12px] font-medium text-teal-600">Saved ✓</span>
        )}
      </div>
      {downgradingWithOverLimit && dirty && (
        <p className="text-[11px] text-amber-600">
          Warning: creator has {row.collectives_used} collectives but Basic allows 1.
        </p>
      )}
      {error && (
        <p className="text-[11px] text-red-600">{error}</p>
      )}
    </div>
  )
}

export default function AdminBillingPage() {
  const [rows, setRows] = useState<CreatorBillingRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(apiUrl('/api/admin/creator-billing'), { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json()
      })
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const handleSaved = useCallback((updated: CreatorBillingRow) => {
    setRows((prev) => prev.map((r) => (r.user_id === updated.user_id ? updated : r)))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[14px] text-[#64748B]">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
        Loading billing data…
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

  const basicCount = rows.filter((r) => r.current_plan_slug === 'creator-basic').length
  const plusCount = rows.filter((r) => r.current_plan_slug === 'creator-plus').length
  const overLimitCount = rows.filter((r) => r.collectives_used > r.collective_limit).length

  return (
    <div>
      <h1 className="mb-6 text-[1.5rem] font-bold text-[#0F172A]">Creator Billing</h1>

      {/* Summary cards */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard label="Total Creators" value={rows.length} />
        <MetricCard label="Basic Plan" value={basicCount} />
        <MetricCard label="Plus Plan" value={plusCount} />
        <MetricCard label="Over Limit" value={overLimitCount} warn={overLimitCount > 0} />
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
        {/* Desktop table */}
        <div className="hidden overflow-x-auto lg:block">
          <table className="w-full text-left">
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                {['Creator', 'Email', 'Current Plan', 'Collectives', 'Transaction Fee', 'Status', 'Change Plan'].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const overLimit = row.collectives_used > row.collective_limit
                return (
                  <tr
                    key={row.user_id}
                    style={{
                      borderBottom: i < rows.length - 1 ? '1px solid #F1F5F9' : undefined,
                      background: overLimit ? '#FFF7ED' : undefined,
                    }}
                  >
                    <td className="px-4 py-3">
                      <p className="text-[13px] font-medium text-[#0F172A]">
                        {row.name ?? '—'}
                      </p>
                      {overLimit && (
                        <p className="text-[11px] text-amber-600">Over limit</p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[13px] text-[#475569]">{row.email}</td>
                    <td className="px-4 py-3">
                      <p className="text-[13px] font-medium text-[#0F172A]">{row.current_plan_name}</p>
                      <p className="text-[11px] text-[#94A3B8]">
                        {fmt(row.monthly_price_cents, row.currency)}/mo
                      </p>
                    </td>
                    <td className="px-4 py-3 text-[13px] text-[#475569]">
                      <span className={overLimit ? 'font-semibold text-amber-600' : ''}>
                        {row.collectives_used}
                      </span>
                      <span className="text-[#94A3B8]"> / {row.collective_limit}</span>
                    </td>
                    <td className="px-4 py-3 text-[13px] text-[#475569]">
                      {fmtFee(row.transaction_fee_basis_points)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={row.subscription_status} />
                    </td>
                    <td className="px-4 py-3">
                      <PlanDropdown row={row} onSaved={handleSaved} />
                    </td>
                  </tr>
                )
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-[13px] text-[#94A3B8]">
                    No creators yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Mobile cards */}
        <div className="divide-y divide-[#F1F5F9] lg:hidden">
          {rows.map((row) => {
            const overLimit = row.collectives_used > row.collective_limit
            return (
              <div
                key={row.user_id}
                className="p-4"
                style={{ background: overLimit ? '#FFF7ED' : undefined }}
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[14px] font-semibold text-[#0F172A]">{row.name ?? row.email}</p>
                    <p className="text-[12px] text-[#64748B]">{row.email}</p>
                  </div>
                  <StatusBadge status={row.subscription_status} />
                </div>
                <div className="mb-3 grid grid-cols-3 gap-2 text-[12px]">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Plan</p>
                    <p className="font-medium text-[#0F172A]">{row.current_plan_name}</p>
                    <p className="text-[#94A3B8]">{fmt(row.monthly_price_cents, row.currency)}/mo</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Collectives</p>
                    <p className={overLimit ? 'font-semibold text-amber-600' : 'font-medium text-[#0F172A]'}>
                      {row.collectives_used} / {row.collective_limit}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Fee</p>
                    <p className="font-medium text-[#0F172A]">{fmtFee(row.transaction_fee_basis_points)}</p>
                  </div>
                </div>
                <PlanDropdown row={row} onSaved={handleSaved} />
              </div>
            )
          })}
          {rows.length === 0 && (
            <p className="p-6 text-center text-[13px] text-[#94A3B8]">No creators yet.</p>
          )}
        </div>
      </div>
    </div>
  )
}
