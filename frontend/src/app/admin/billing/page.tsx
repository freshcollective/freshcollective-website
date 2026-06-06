'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiUrl } from '@/lib/api'

// ── Types ────────────────────────────────────────────────────────────────────

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

interface CreatorSubscriptionRow {
  id: string
  user_id: string
  plan_slug: string
  starts_at: string
  ends_at: string | null
  stripe_subscription_id: string | null
  stripe_customer_id: string | null
  updated_at: string
}

// Merged view keyed by user_id
interface CreatorRow extends CreatorBillingRow {
  subscription: CreatorSubscriptionRow | null
}

// ── Helpers ──────────────────────────────────────────────────────────────────

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
    active:   'bg-teal-50 text-teal-700 border-teal-200',
    trialing: 'bg-blue-50 text-blue-700 border-blue-200',
    past_due: 'bg-amber-50 text-amber-700 border-amber-200',
    cancelled:'bg-slate-100 text-slate-500 border-slate-200',
    unpaid:   'bg-red-50 text-red-700 border-red-200',
    none:     'bg-slate-100 text-slate-500 border-slate-200',
  }
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${map[status] ?? 'bg-slate-100 text-slate-500 border-slate-200'}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

// ── Plan change dropdown ──────────────────────────────────────────────────────

function PlanDropdown({
  row,
  onSaved,
}: {
  row: CreatorRow
  onSaved: (updated: CreatorBillingRow) => void
}) {
  const [selected, setSelected] = useState(row.current_plan_slug)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dirty = selected !== row.current_plan_slug
  const overLimit = selected === 'creator-basic' && row.collectives_used > 1

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
        throw new Error((data as { detail?: string }).detail ?? `Error ${res.status}`)
      }
      const updated = await res.json() as CreatorBillingRow
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
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <select
          value={selected}
          onChange={(e) => { setSelected(e.target.value); setSaved(false); setError(null) }}
          className="rounded-lg border border-[#E2E8F0] bg-white px-2 py-1 text-[12px] text-[#0F172A] focus:border-teal-400 focus:outline-none"
        >
          <option value="creator-basic">Basic</option>
          <option value="creator-plus">Plus</option>
        </select>
        {dirty && (
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-teal-500 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-teal-600 disabled:opacity-60"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        )}
        {saved && !dirty && (
          <span className="text-[11px] font-medium text-teal-600">Saved ✓</span>
        )}
      </div>
      {overLimit && dirty && (
        <p className="text-[10px] text-amber-600">Creator has {row.collectives_used} collectives — Basic limit is 1.</p>
      )}
      {error && <p className="text-[10px] text-red-600">{error}</p>}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AdminBillingPage() {
  const [rows, setRows] = useState<CreatorRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      fetch(apiUrl('/api/admin/creator-billing'), { credentials: 'include' }).then((r) => {
        if (!r.ok) throw new Error(`Billing: Error ${r.status}`)
        return r.json() as Promise<CreatorBillingRow[]>
      }),
      fetch(apiUrl('/api/admin/creator-subscriptions'), { credentials: 'include' }).then((r) => {
        if (!r.ok) throw new Error(`Subscriptions: Error ${r.status}`)
        return r.json() as Promise<CreatorSubscriptionRow[]>
      }),
    ])
      .then(([billing, subs]) => {
        const subMap = new Map(subs.map((s) => [s.user_id, s]))
        setRows(billing.map((b) => ({ ...b, subscription: subMap.get(b.user_id) ?? null })))
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const handleSaved = useCallback((updated: CreatorBillingRow) => {
    setRows((prev) => prev.map((r) => r.user_id === updated.user_id ? { ...updated, subscription: r.subscription } : r))
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

  const activeCount  = rows.filter((r) => r.subscription_status === 'active').length
  const pastDueCount = rows.filter((r) => r.subscription_status === 'past_due' || r.subscription_status === 'unpaid').length
  const overLimitCount = rows.filter((r) => r.collectives_used > r.collective_limit).length

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Creator Billing</h1>
          <p className="mt-1 text-[13px] text-[#64748B]">
            Plan, subscription record, usage limits, and Stripe status for each creator.
          </p>
        </div>
      </div>

      {/* Summary cards */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: 'Total Creators', value: rows.length },
          { label: 'Active', value: activeCount },
          { label: 'Past Due / Unpaid', value: pastDueCount, warn: pastDueCount > 0 },
          { label: 'Over Limit', value: overLimitCount, warn: overLimitCount > 0 },
        ].map(({ label, value, warn }) => (
          <div
            key={label}
            className="rounded-xl bg-white p-4"
            style={{ border: `1px solid ${warn ? '#FCA5A5' : '#E2E8F0'}` }}
          >
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">{label}</p>
            <p className={`text-[1.5rem] font-bold leading-none ${warn ? 'text-red-600' : 'text-[#0F172A]'}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Plan-change note */}
      <div
        className="mb-5 rounded-xl px-4 py-3 text-[12px] text-[#64748B]"
        style={{ background: '#F8FAFC', border: '1px solid #E2E8F0' }}
      >
        <strong className="text-[#475569]">Plan changes are currently internal only.</strong>{' '}
        Stripe billing updates will be connected automatically once live billing is enabled.
        Changing a plan here updates the platform record immediately but does not alter any Stripe subscription.
      </div>

      {/* Desktop table */}
      <div className="hidden overflow-hidden rounded-xl bg-white lg:block" style={{ border: '1px solid #E2E8F0' }}>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                {[
                  'Creator',
                  'Plan',
                  'Price / Fee',
                  'Sub Status',
                  'Started',
                  'Ends',
                  'Collectives',
                  'Stripe',
                  'Change Plan',
                ].map((h) => (
                  <th key={h} className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const overLimit = row.collectives_used > row.collective_limit
                const isPastDue = row.subscription_status === 'past_due' || row.subscription_status === 'unpaid'
                return (
                  <tr
                    key={row.user_id}
                    style={{
                      borderBottom: i < rows.length - 1 ? '1px solid #F1F5F9' : undefined,
                      background: isPastDue ? '#FFF7ED' : overLimit ? '#FFFBEB' : undefined,
                    }}
                  >
                    {/* Creator */}
                    <td className="px-4 py-3">
                      <p className="text-[13px] font-medium text-[#0F172A]">{row.name ?? '—'}</p>
                      <p className="text-[11px] text-[#94A3B8]">{row.email}</p>
                    </td>
                    {/* Plan */}
                    <td className="px-4 py-3">
                      <p className="text-[13px] font-medium text-[#0F172A]">{row.current_plan_name}</p>
                      <p className="font-mono text-[10px] text-[#CBD5E1]">{row.current_plan_slug}</p>
                    </td>
                    {/* Price + fee */}
                    <td className="px-4 py-3">
                      <p className="text-[13px] font-medium text-[#0F172A]">
                        {fmt(row.monthly_price_cents, row.currency)}/mo
                      </p>
                      <p className="text-[11px] text-[#94A3B8]">
                        {(row.transaction_fee_basis_points / 100).toFixed(0)}% fee
                      </p>
                    </td>
                    {/* Status */}
                    <td className="px-4 py-3">
                      <StatusBadge status={row.subscription_status} />
                    </td>
                    {/* Started */}
                    <td className="px-4 py-3 text-[12px] text-[#94A3B8]">
                      {row.subscription ? fmtDate(row.subscription.starts_at) : '—'}
                    </td>
                    {/* Ends */}
                    <td className="px-4 py-3 text-[12px] text-[#94A3B8]">
                      {row.subscription ? fmtDate(row.subscription.ends_at) : '—'}
                    </td>
                    {/* Collectives */}
                    <td className="px-4 py-3">
                      <span className={overLimit ? 'text-[13px] font-semibold text-amber-600' : 'text-[13px] text-[#475569]'}>
                        {row.collectives_used}
                      </span>
                      <span className="text-[#94A3B8] text-[13px]"> / {row.collective_limit}</span>
                      {overLimit && <p className="text-[10px] text-amber-600">Over limit</p>}
                    </td>
                    {/* Stripe */}
                    <td className="px-4 py-3">
                      {row.subscription?.stripe_subscription_id ? (
                        <div>
                          <p className="font-mono text-[10px] text-[#64748B]">
                            sub: {row.subscription.stripe_subscription_id.slice(0, 14)}…
                          </p>
                          {row.subscription.stripe_customer_id && (
                            <p className="font-mono text-[10px] text-[#94A3B8]">
                              cus: {row.subscription.stripe_customer_id.slice(0, 14)}…
                            </p>
                          )}
                        </div>
                      ) : (
                        <span className="text-[11px] text-[#CBD5E1]">Not connected</span>
                      )}
                    </td>
                    {/* Change plan */}
                    <td className="px-4 py-3">
                      <PlanDropdown row={row} onSaved={handleSaved} />
                    </td>
                  </tr>
                )
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-[13px] text-[#94A3B8]">
                    No creators yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Mobile cards */}
      <div className="space-y-3 lg:hidden">
        {rows.map((row) => {
          const overLimit = row.collectives_used > row.collective_limit
          const isPastDue = row.subscription_status === 'past_due' || row.subscription_status === 'unpaid'
          return (
            <div
              key={row.user_id}
              className="rounded-xl bg-white p-4"
              style={{
                border: '1px solid #E2E8F0',
                background: isPastDue ? '#FFF7ED' : overLimit ? '#FFFBEB' : undefined,
              }}
            >
              <div className="mb-2 flex items-start justify-between gap-2">
                <div>
                  <p className="text-[14px] font-semibold text-[#0F172A]">{row.name ?? row.email}</p>
                  <p className="text-[12px] text-[#64748B]">{row.email}</p>
                </div>
                <StatusBadge status={row.subscription_status} />
              </div>

              <div className="mb-3 grid grid-cols-2 gap-2 text-[12px]">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Plan</p>
                  <p className="font-medium text-[#0F172A]">{row.current_plan_name}</p>
                  <p className="text-[#94A3B8]">{fmt(row.monthly_price_cents, row.currency)}/mo</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Fee</p>
                  <p className="font-medium text-[#0F172A]">{(row.transaction_fee_basis_points / 100).toFixed(0)}%</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Collectives</p>
                  <p className={overLimit ? 'font-semibold text-amber-600' : 'font-medium text-[#0F172A]'}>
                    {row.collectives_used} / {row.collective_limit}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Started</p>
                  <p className="font-medium text-[#0F172A]">{row.subscription ? fmtDate(row.subscription.starts_at) : '—'}</p>
                </div>
              </div>

              {row.subscription?.stripe_subscription_id && (
                <p className="mb-2 font-mono text-[10px] text-[#94A3B8]">
                  Stripe: {row.subscription.stripe_subscription_id.slice(0, 20)}…
                </p>
              )}

              <PlanDropdown row={row} onSaved={handleSaved} />
            </div>
          )
        })}
        {rows.length === 0 && (
          <div className="rounded-xl bg-white p-8 text-center text-[13px] text-[#94A3B8]" style={{ border: '1px solid #E2E8F0' }}>
            No creators yet.
          </div>
        )}
      </div>

      <div
        className="mt-5 rounded-xl px-4 py-3 text-[12px] text-[#64748B]"
        style={{ background: '#F8FAFC', border: '1px solid #E2E8F0' }}
      >
        <strong className="text-[#475569]">Stripe:</strong> Stripe subscription and customer IDs are not yet
        populated — live billing has not been connected. Once Stripe billing is enabled, IDs will appear here
        and plan changes will automatically sync to Stripe.
      </div>
    </div>
  )
}
