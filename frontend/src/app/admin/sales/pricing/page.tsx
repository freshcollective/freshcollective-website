'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  salesApi,
  type Plan,
  type Price,
  type PriceCreate,
  BILLING_INTERVALS,
  fmtDate,
} from '@/lib/adminSalesApi'
import Modal from '@/components/admin/Modal'

export default function PricingPage() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [prices, setPrices] = useState<Price[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [showAddPrice, setShowAddPrice] = useState(false)
  const [selectedPlanId, setSelectedPlanId] = useState('')
  const [priceForm, setPriceForm] = useState<Partial<PriceCreate>>({
    currency: 'AUD',
    billing_interval: 'monthly',
  })
  const [priceSaving, setPriceSaving] = useState(false)
  const [priceError, setPriceError] = useState<string | null>(null)
  const [deactivating, setDeactivating] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([salesApi.listPlans(), salesApi.listPrices()])
      .then(([pl, pr]) => {
        setPlans(pl)
        setPrices(pr)
        if (pl.length > 0 && !selectedPlanId) setSelectedPlanId(pl[0].id)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [selectedPlanId])

  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleAddPrice() {
    if (!priceForm.amount_cents || priceForm.amount_cents <= 0) {
      setPriceError('Amount must be greater than $0')
      return
    }
    setPriceSaving(true)
    setPriceError(null)
    try {
      await salesApi.createPrice({
        plan_id: selectedPlanId,
        currency: priceForm.currency ?? 'AUD',
        amount_cents: priceForm.amount_cents,
        billing_interval: priceForm.billing_interval ?? 'monthly',
      })
      setShowAddPrice(false)
      setPriceForm({ currency: 'AUD', billing_interval: 'monthly' })
      load()
    } catch (e: unknown) {
      setPriceError(e instanceof Error ? e.message : 'Error')
    } finally {
      setPriceSaving(false)
    }
  }

  async function handleDeactivate(priceId: string) {
    if (!confirm('Deactivate this price? Existing subscriptions keep their original price.')) return
    setDeactivating(priceId)
    try {
      await salesApi.deactivatePrice(priceId)
      load()
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Error')
    } finally {
      setDeactivating(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-8 text-[14px] text-[#64748B]">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
        Loading…
      </div>
    )
  }

  if (error) {
    return <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600">{error}</div>
  }

  return (
    <div>
      <h1 className="mb-6 text-[1.5rem] font-bold text-[#0F172A]">Pricing</h1>

      {/* Plans */}
      <section className="mb-8">
        <h2 className="mb-3 text-[14px] font-semibold text-[#0F172A]">Subscription Plans</h2>
        {plans.length === 0 ? (
          <div className="rounded-xl p-4 text-[13px] text-[#94A3B8]" style={{ border: '1px dashed #E2E8F0' }}>
            No plans yet.
          </div>
        ) : (
          <div className="space-y-2">
            {plans.map((plan) => (
              <div
                key={plan.id}
                className="flex items-center justify-between rounded-xl bg-white p-4"
                style={{ border: '1px solid #E2E8F0' }}
              >
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[14px] font-semibold text-[#0F172A]">{plan.name}</p>
                    {plan.is_active ? (
                      <span className="rounded-full bg-green-50 px-2 py-0.5 text-[11px] font-semibold text-green-700">Active</span>
                    ) : (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-500">Inactive</span>
                    )}
                  </div>
                  {plan.description && (
                    <p className="mt-0.5 text-[12px] text-[#64748B]">{plan.description}</p>
                  )}
                  <p className="mt-1 font-mono text-[11px] text-[#94A3B8]">{plan.id}</p>
                </div>
                <button
                  onClick={() => { setSelectedPlanId(plan.id); setShowAddPrice(true); setPriceError(null) }}
                  className="rounded-lg border border-[#E2E8F0] px-3 py-1.5 text-[12px] font-medium text-[#475569] hover:bg-[#F1F5F9]"
                >
                  + Add price
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Prices */}
      <section>
        <h2 className="mb-3 text-[14px] font-semibold text-[#0F172A]">Prices</h2>
        <div className="rounded-lg mb-3 px-3 py-2 text-[12px] text-[#64748B]" style={{ background: '#F8F9FA', border: '1px solid #E2E8F0' }}>
          Note: Existing member subscriptions keep their original price_id — deactivating a price does not affect active subscribers.
        </div>
        {prices.length === 0 ? (
          <div className="rounded-xl p-4 text-[13px] text-[#94A3B8]" style={{ border: '1px dashed #E2E8F0' }}>
            No prices yet.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
            <table className="w-full text-[13px]">
              <thead>
                <tr style={{ borderBottom: '1px solid #E2E8F0', background: '#F8F9FA' }}>
                  {['Amount', 'Interval', 'Currency', 'Active', 'Effective From', 'Effective To', ''].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {prices.map((p) => (
                  <tr key={p.id} className="transition-colors hover:bg-[#F8F9FA]" style={{ borderBottom: '1px solid #F1F5F9' }}>
                    <td className="px-4 py-3">
                      <span className={`font-bold ${p.is_active ? 'text-teal-600' : 'text-[#94A3B8]'}`}>
                        {p.amount_display}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[#475569] capitalize">{p.billing_interval}</td>
                    <td className="px-4 py-3 text-[#475569]">{p.currency}</td>
                    <td className="px-4 py-3">
                      {p.is_active ? (
                        <span className="rounded-full bg-green-50 px-2 py-0.5 text-[11px] font-semibold text-green-700">Active</span>
                      ) : (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">Inactive</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[#94A3B8]">{fmtDate(p.effective_from)}</td>
                    <td className="px-4 py-3 text-[#94A3B8]">{fmtDate(p.effective_to)}</td>
                    <td className="px-4 py-3">
                      {p.is_active && (
                        <button
                          onClick={() => handleDeactivate(p.id)}
                          disabled={deactivating === p.id}
                          className="text-[12px] text-[#94A3B8] hover:text-red-500 disabled:opacity-50"
                        >
                          {deactivating === p.id ? '…' : 'Deactivate'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Add price modal */}
      {showAddPrice && (
        <Modal title="Add price" onClose={() => setShowAddPrice(false)}>
          {priceError && (
            <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{priceError}</div>
          )}
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Plan</span>
              <select
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={selectedPlanId}
                onChange={(e) => setSelectedPlanId(e.target.value)}
              >
                {plans.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Amount (AUD $) <span className="text-red-500">*</span></span>
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  required
                  className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                  placeholder="39.00"
                  value={priceForm.amount_cents != null ? priceForm.amount_cents / 100 : ''}
                  onChange={(e) => {
                    const val = e.target.value ? Math.round(parseFloat(e.target.value) * 100) : undefined
                    setPriceForm((p) => ({ ...p, amount_cents: val }))
                  }}
                />
                <p className="mt-0.5 text-[11px] text-[#94A3B8]">
                  Stored as cents: {priceForm.amount_cents ?? 0}¢
                </p>
              </label>
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Billing interval</span>
                <select
                  className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                  value={priceForm.billing_interval ?? 'monthly'}
                  onChange={(e) => setPriceForm((p) => ({ ...p, billing_interval: e.target.value as Price['billing_interval'] }))}
                >
                  {BILLING_INTERVALS.map((i) => (
                    <option key={i} value={i}>{i}</option>
                  ))}
                </select>
              </label>
            </div>
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Currency</span>
              <input
                maxLength={3}
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] uppercase outline-none focus:border-teal-400"
                value={priceForm.currency ?? 'AUD'}
                onChange={(e) => setPriceForm((p) => ({ ...p, currency: e.target.value.toUpperCase() }))}
              />
            </label>
            <div className="rounded-lg px-3 py-2 text-[12px] text-[#64748B]" style={{ background: '#F8F9FA' }}>
              Creating a new active price for the same plan + billing interval will automatically deactivate the current active price and set its effective_to date.
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setShowAddPrice(false)} className="rounded-lg px-4 py-2 text-[13px] text-[#64748B] hover:bg-[#F1F5F9]">
                Cancel
              </button>
              <button
                onClick={handleAddPrice}
                disabled={priceSaving || !priceForm.amount_cents}
                className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60 hover:bg-teal-600"
              >
                {priceSaving ? 'Adding…' : 'Add price'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
