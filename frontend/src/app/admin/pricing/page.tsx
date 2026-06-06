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

function fmt(cents: number, currency: string) {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 0,
  }).format(cents / 100)
}

export default function AdminPricingPage() {
  const [plans, setPlans] = useState<CreatorPlanRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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
    <div>
      <h1 className="mb-1 text-[1.5rem] font-bold text-[#0F172A]">Creator Plan Catalogue</h1>
      <p className="mb-6 text-[13px] text-[#64748B]">
        Plans available to creators on Fresh Collective. These determine monthly subscription price,
        transaction fees on member purchases, and collective limits.
      </p>

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
              <div className="rounded-lg bg-[#F8F9FA] px-3 py-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Transaction Fee</p>
                <p className="mt-0.5 text-[16px] font-bold text-[#0F172A]">
                  {(plan.transaction_fee_basis_points / 100).toFixed(0)}%
                </p>
                <p className="text-[11px] text-[#94A3B8]">of member sales</p>
              </div>
              <div className="rounded-lg bg-[#F8F9FA] px-3 py-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Collective Limit</p>
                <p className="mt-0.5 text-[16px] font-bold text-[#0F172A]">{plan.collective_limit}</p>
                <p className="text-[11px] text-[#94A3B8]">collectives</p>
              </div>
              <div className="rounded-lg bg-[#F8F9FA] px-3 py-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Active Subscribers</p>
                <p className="mt-0.5 text-[16px] font-bold text-[#0F172A]">{plan.active_subscriptions}</p>
                <p className="text-[11px] text-[#94A3B8]">creators</p>
              </div>
              <div className="rounded-lg bg-[#F8F9FA] px-3 py-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8]">Monthly MRR</p>
                <p className="mt-0.5 text-[16px] font-bold text-[#0F172A]">
                  {fmt(plan.monthly_price_cents * plan.active_subscriptions, plan.currency)}
                </p>
                <p className="text-[11px] text-[#94A3B8]">from this plan</p>
              </div>
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
        <strong className="text-[#475569]">Note:</strong> Plans are managed via database migrations and seed scripts.
        Contact the developer to add, modify, or retire plans. Existing subscribers are never automatically
        moved between plans — any changes must be applied manually via Creator Billing.
      </div>
    </div>
  )
}
