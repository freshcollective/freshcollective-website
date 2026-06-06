'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface CreatorPlanRow {
  id: string
  name: string
  slug: string
  description: string | null
  monthly_price_cents: number
  currency: string
  transaction_fee_basis_points: number
  collective_limit: number
  is_active: boolean
  active_subscriptions: number
  created_at: string
}

interface PlanCreateForm {
  name: string
  slug: string
  description: string
  monthly_price_cents: string
  transaction_fee_basis_points: string
  collective_limit: string
  is_active: boolean
}

const EMPTY_FORM: PlanCreateForm = {
  name: '',
  slug: '',
  description: '',
  monthly_price_cents: '',
  transaction_fee_basis_points: '',
  collective_limit: '1',
  is_active: true,
}

function fmt(cents: number, currency: string) {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 0,
  }).format(cents / 100)
}

function slugify(s: string) {
  return s.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
}

// ── Add Plan modal ────────────────────────────────────────────────────────────

function AddPlanModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (plan: CreatorPlanRow) => void
}) {
  const [form, setForm] = useState<PlanCreateForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function field(key: keyof PlanCreateForm) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((p) => ({
        ...p,
        [key]: e.target.value,
        ...(key === 'name' ? { slug: slugify(e.target.value) } : {}),
      }))
  }

  async function handleSave() {
    if (!form.name.trim() || !form.slug.trim()) { setError('Name and slug are required.'); return }
    const priceCents = parseInt(form.monthly_price_cents, 10)
    const feeBps = parseInt(form.transaction_fee_basis_points, 10)
    const limit = parseInt(form.collective_limit, 10)
    if (isNaN(priceCents) || priceCents < 0) { setError('Monthly price must be a non-negative number of cents.'); return }
    if (isNaN(feeBps) || feeBps < 0 || feeBps > 10000) { setError('Transaction fee must be 0–10000 basis points.'); return }
    if (isNaN(limit) || limit < 1) { setError('Collective limit must be at least 1.'); return }

    setSaving(true)
    setError(null)
    try {
      const res = await fetch(apiUrl('/api/admin/creator-plans'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name.trim(),
          slug: form.slug.trim(),
          description: form.description.trim() || null,
          monthly_price_cents: priceCents,
          currency: 'AUD',
          transaction_fee_basis_points: feeBps,
          collective_limit: limit,
          is_active: form.is_active,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error((data as { detail?: string }).detail ?? `Error ${res.status}`)
      }
      const created = await res.json() as CreatorPlanRow
      onCreated(created)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setSaving(false)
    }
  }

  const inputCls = 'w-full rounded-lg border border-[#E2E8F0] bg-white px-3 py-2 text-[13px] text-[#0F172A] placeholder-[#CBD5E1] focus:border-teal-400 focus:outline-none'
  const labelCls = 'mb-1 block text-[11px] font-semibold uppercase tracking-wide text-[#64748B]'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-md overflow-hidden rounded-2xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
        <div className="flex items-center justify-between border-b px-5 py-4" style={{ borderColor: '#E2E8F0' }}>
          <h2 className="text-[15px] font-bold text-[#0F172A]">Add Creator Plan</h2>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]" aria-label="Close">✕</button>
        </div>

        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">
          {error && (
            <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600" style={{ border: '1px solid #FCA5A5' }}>
              {error}
            </div>
          )}

          <div className="space-y-3">
            <label className="block">
              <span className={labelCls}>Plan name <span className="text-red-500">*</span></span>
              <input className={inputCls} placeholder="e.g. Creator Enterprise" value={form.name} onChange={field('name')} />
            </label>

            <label className="block">
              <span className={labelCls}>Slug <span className="text-red-500">*</span></span>
              <input
                className={`${inputCls} font-mono`}
                placeholder="e.g. creator-enterprise"
                value={form.slug}
                onChange={field('slug')}
              />
              <p className="mt-0.5 text-[10px] text-[#94A3B8]">URL-safe, lowercase, hyphens only. Must be unique.</p>
            </label>

            <label className="block">
              <span className={labelCls}>Monthly price (cents AUD) <span className="text-red-500">*</span></span>
              <input
                className={inputCls}
                type="number"
                min="0"
                placeholder="e.g. 4900 = $49"
                value={form.monthly_price_cents}
                onChange={field('monthly_price_cents')}
              />
              {form.monthly_price_cents && !isNaN(parseInt(form.monthly_price_cents)) && (
                <p className="mt-0.5 text-[11px] text-teal-600">
                  = {fmt(parseInt(form.monthly_price_cents), 'AUD')}/month
                </p>
              )}
            </label>

            <label className="block">
              <span className={labelCls}>Transaction fee (basis points) <span className="text-red-500">*</span></span>
              <input
                className={inputCls}
                type="number"
                min="0"
                max="10000"
                placeholder="e.g. 500 = 5%"
                value={form.transaction_fee_basis_points}
                onChange={field('transaction_fee_basis_points')}
              />
              {form.transaction_fee_basis_points && !isNaN(parseInt(form.transaction_fee_basis_points)) && (
                <p className="mt-0.5 text-[11px] text-teal-600">
                  = {(parseInt(form.transaction_fee_basis_points) / 100).toFixed(2)}% of member sales
                </p>
              )}
            </label>

            <label className="block">
              <span className={labelCls}>Collective limit <span className="text-red-500">*</span></span>
              <input
                className={inputCls}
                type="number"
                min="1"
                value={form.collective_limit}
                onChange={field('collective_limit')}
              />
            </label>

            <label className="block">
              <span className={labelCls}>Description</span>
              <textarea
                className={`${inputCls} resize-none`}
                rows={2}
                placeholder="Brief description for admin reference"
                value={form.description}
                onChange={field('description')}
              />
            </label>

            <label className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => setForm((p) => ({ ...p, is_active: e.target.checked }))}
                className="h-4 w-4 rounded border-[#E2E8F0] accent-teal-500"
              />
              <span className="text-[13px] text-[#475569]">Active (available to new creators)</span>
            </label>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t px-5 py-4" style={{ borderColor: '#E2E8F0' }}>
          <button
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-[12px] text-[#64748B] hover:bg-[#F1F5F9]"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-teal-500 px-4 py-2 text-[12px] font-semibold text-white hover:bg-teal-600 disabled:opacity-60"
          >
            {saving ? 'Creating…' : 'Create plan'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AdminPricingPage() {
  const [plans, setPlans] = useState<CreatorPlanRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)

  useEffect(() => {
    fetch(apiUrl('/api/admin/creator-plans'), { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json()
      })
      .then(setPlans)
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

  return (
    <>
      {showAdd && (
        <AddPlanModal
          onClose={() => setShowAdd(false)}
          onCreated={(plan) => setPlans((prev) => [...prev, plan])}
        />
      )}

      <div>
        <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Creator Plan Catalogue</h1>
            <p className="mt-1 text-[13px] text-[#64748B]">
              Plans available to creators. These determine monthly fee, transaction fee rate, and collective limits.
            </p>
          </div>
          <button
            onClick={() => setShowAdd(true)}
            className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white hover:bg-teal-600"
          >
            + Add plan
          </button>
        </div>

        <div className="space-y-4">
          {plans.map((plan) => (
            <div
              key={plan.id}
              className="rounded-xl bg-white p-5"
              style={{
                border: `1px solid ${plan.is_active ? 'rgba(56,160,158,0.25)' : '#E2E8F0'}`,
                opacity: plan.is_active ? 1 : 0.65,
              }}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-[17px] font-bold text-[#0F172A]">{plan.name}</h2>
                    <span className="font-mono text-[11px] text-[#94A3B8]">{plan.slug}</span>
                    {plan.is_active ? (
                      <span className="rounded-full bg-teal-50 px-2 py-0.5 text-[11px] font-semibold text-teal-700" style={{ border: '1px solid rgba(56,160,158,0.25)' }}>
                        Active
                      </span>
                    ) : (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-500" style={{ border: '1px solid #E2E8F0' }}>
                        Inactive
                      </span>
                    )}
                  </div>
                  {plan.description && (
                    <p className="mt-1 text-[13px] text-[#64748B]">{plan.description}</p>
                  )}
                </div>

                <div className="text-right">
                  <p className="text-[22px] font-bold text-[#0F172A]">
                    {fmt(plan.monthly_price_cents, plan.currency)}
                    <span className="text-[14px] font-normal text-[#94A3B8]">/month</span>
                  </p>
                  <p className="text-[12px] text-[#64748B]">{plan.currency}</p>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  {
                    label: 'Transaction Fee',
                    value: `${(plan.transaction_fee_basis_points / 100).toFixed(0)}%`,
                    sub: 'of member sales',
                  },
                  {
                    label: 'Collective Limit',
                    value: String(plan.collective_limit),
                    sub: 'collectives',
                  },
                  {
                    label: 'Active Subscribers',
                    value: String(plan.active_subscriptions),
                    sub: 'creators',
                  },
                  {
                    label: 'Monthly MRR',
                    value: fmt(plan.monthly_price_cents * plan.active_subscriptions, plan.currency),
                    sub: 'from this plan',
                  },
                ].map(({ label, value, sub }) => (
                  <div key={label} className="rounded-lg bg-[#F8F9FA] px-3 py-2.5">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">{label}</p>
                    <p className="mt-0.5 text-[16px] font-bold text-[#0F172A]">{value}</p>
                    <p className="text-[11px] text-[#94A3B8]">{sub}</p>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {plans.length === 0 && (
            <div className="rounded-xl bg-white p-8 text-center text-[14px] text-[#94A3B8]" style={{ border: '1px solid #E2E8F0' }}>
              No creator plans found.
            </div>
          )}
        </div>

        <div
          className="mt-6 rounded-xl bg-slate-50 px-4 py-3 text-[12px] text-[#64748B]"
          style={{ border: '1px solid #E2E8F0' }}
        >
          <strong className="text-[#475569]">Note:</strong> Plans can be added here or via database seed scripts.
          Existing subscribers are never automatically moved between plans — changes must be applied
          manually via Creator Billing. Do not duplicate existing plan slugs.
        </div>
      </div>
    </>
  )
}
