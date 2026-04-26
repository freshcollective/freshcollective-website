'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  salesApi,
  adminApi,
  type AdminUser,
  type Plan,
  type Price,
  type Subscription,
  type SubscriptionCreate,
  type SubscriptionUpdate,
  SUBSCRIPTION_STATUSES,
  fmtDate,
  userLabel,
} from '@/lib/adminSalesApi'
import StatusBadge from '@/components/admin/StatusBadge'
import Modal from '@/components/admin/Modal'

export default function SubscriptionsPage() {
  const [subs, setSubs] = useState<Subscription[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('')

  // Lookup data for the create form
  const [users, setUsers] = useState<AdminUser[]>([])
  const [plans, setPlans] = useState<Plan[]>([])
  const [prices, setPrices] = useState<Price[]>([])

  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState<SubscriptionCreate>({
    user_id: '', plan_id: '', price_id: '', status: 'active',
  })
  const [createSaving, setCreateSaving] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const [editing, setEditing] = useState<Subscription | null>(null)
  const [editForm, setEditForm] = useState<SubscriptionUpdate>({})
  const [editSaving, setEditSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  // Prices filtered to the currently selected plan
  const availablePrices = prices.filter(
    (p) => p.plan_id === createForm.plan_id && p.is_active
  )

  // When plan changes, reset price selection
  function handlePlanChange(planId: string) {
    setCreateForm((p) => ({ ...p, plan_id: planId, price_id: '' }))
  }

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      salesApi.listSubscriptions({ status: statusFilter || undefined }),
      adminApi.listUsers(),
      salesApi.listPlans(),
      salesApi.listPrices(),
    ])
      .then(([s, u, pl, pr]) => {
        setSubs(s)
        setUsers(u)
        setPlans(pl)
        setPrices(pr)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [statusFilter])

  useEffect(() => { load() }, [load])

  // Build lookup maps for table display
  const userMap = new Map(users.map((u) => [u.id, u]))
  const planMap = new Map(plans.map((p) => [p.id, p]))
  const priceMap = new Map(prices.map((p) => [p.id, p]))

  async function handleCreate() {
    setCreateSaving(true)
    setCreateError(null)
    try {
      await salesApi.createSubscription(createForm)
      setShowCreate(false)
      setCreateForm({ user_id: '', plan_id: '', price_id: '', status: 'active' })
      load()
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : 'Error')
    } finally {
      setCreateSaving(false)
    }
  }

  async function handleEdit() {
    if (!editing) return
    setEditSaving(true)
    setEditError(null)
    try {
      await salesApi.updateSubscription(editing.id, editForm)
      setEditing(null)
      load()
    } catch (e: unknown) {
      setEditError(e instanceof Error ? e.message : 'Error')
    } finally {
      setEditSaving(false)
    }
  }

  const selectCls = 'w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] bg-white outline-none focus:border-teal-400'
  const labelCls = 'mb-1 block text-[12px] font-medium text-[#64748B]'

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Subscriptions</h1>
        <button
          onClick={() => { setShowCreate(true); setCreateError(null) }}
          className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white hover:bg-teal-600"
        >
          + New subscription
        </button>
      </div>

      <div className="mb-4">
        <select
          className="rounded-lg border border-[#E2E8F0] px-3 py-1.5 text-[13px] bg-white outline-none"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          {SUBSCRIPTION_STATUSES.map((s) => (
            <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-8 text-[14px] text-[#64748B]">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
          Loading…
        </div>
      ) : error ? (
        <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600">{error}</div>
      ) : subs.length === 0 ? (
        <div className="rounded-xl bg-white p-8 text-center text-[14px] text-[#94A3B8]" style={{ border: '1px solid #E2E8F0' }}>
          No subscriptions found.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
          <table className="w-full text-[13px]">
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0', background: '#F8F9FA' }}>
                {['User', 'Plan', 'Price', 'Status', 'Started', 'Period End', 'Cancelled', ''].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {subs.map((s) => {
                const user = userMap.get(s.user_id)
                const plan = planMap.get(s.plan_id)
                const price = priceMap.get(s.price_id)
                return (
                  <tr key={s.id} className="transition-colors hover:bg-[#F8F9FA]" style={{ borderBottom: '1px solid #F1F5F9' }}>
                    <td className="px-4 py-3">
                      {user ? (
                        <span className="text-[#0F172A] font-medium">{userLabel(user)}</span>
                      ) : (
                        <span className="font-mono text-[11px] text-[#94A3B8]">{s.user_id.slice(0, 12)}…</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[#475569]">
                      {plan?.name ?? <span className="font-mono text-[11px] text-[#94A3B8]">{s.plan_id.slice(0, 12)}…</span>}
                    </td>
                    <td className="px-4 py-3 text-[#475569]">
                      {price ? (
                        <span>{price.amount_display} / {price.billing_interval}</span>
                      ) : (
                        <span className="font-mono text-[11px] text-[#94A3B8]">{s.price_id.slice(0, 12)}…</span>
                      )}
                    </td>
                    <td className="px-4 py-3"><StatusBadge value={s.status} /></td>
                    <td className="px-4 py-3 text-[#475569]">{fmtDate(s.started_at)}</td>
                    <td className="px-4 py-3 text-[#475569]">{fmtDate(s.current_period_end)}</td>
                    <td className="px-4 py-3 text-[#475569]">
                      {s.cancelled_at ? <span className="text-red-500">{fmtDate(s.cancelled_at)}</span> : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => { setEditing(s); setEditForm({ status: s.status }); setEditError(null) }}
                        className="text-teal-600 hover:underline text-[12px]"
                      >
                        Edit
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <Modal title="New subscription" onClose={() => setShowCreate(false)}>
          {createError && (
            <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{createError}</div>
          )}
          <div className="space-y-3">
            {/* User */}
            <label className="block">
              <span className={labelCls}>User <span className="text-red-500">*</span></span>
              <select
                required
                className={selectCls}
                value={createForm.user_id}
                onChange={(e) => setCreateForm((p) => ({ ...p, user_id: e.target.value }))}
              >
                <option value="">— select a user —</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>{userLabel(u)}</option>
                ))}
              </select>
            </label>

            {/* Plan */}
            <label className="block">
              <span className={labelCls}>Plan <span className="text-red-500">*</span></span>
              <select
                required
                className={selectCls}
                value={createForm.plan_id}
                onChange={(e) => handlePlanChange(e.target.value)}
              >
                <option value="">— select a plan —</option>
                {plans.filter((p) => p.is_active).map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </label>

            {/* Price — filtered to selected plan */}
            <label className="block">
              <span className={labelCls}>Price <span className="text-red-500">*</span></span>
              <select
                required
                disabled={!createForm.plan_id}
                className={`${selectCls} disabled:opacity-50`}
                value={createForm.price_id}
                onChange={(e) => setCreateForm((p) => ({ ...p, price_id: e.target.value }))}
              >
                <option value="">
                  {createForm.plan_id ? '— select a price —' : '— choose a plan first —'}
                </option>
                {availablePrices.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.amount_display} / {p.billing_interval}
                  </option>
                ))}
              </select>
              {createForm.plan_id && availablePrices.length === 0 && (
                <p className="mt-1 text-[11px] text-orange-500">No active prices for this plan.</p>
              )}
            </label>

            {/* Status */}
            <label className="block">
              <span className={labelCls}>Status</span>
              <select
                className={selectCls}
                value={createForm.status}
                onChange={(e) => setCreateForm((p) => ({ ...p, status: e.target.value as Subscription['status'] }))}
              >
                {SUBSCRIPTION_STATUSES.map((s) => (
                  <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </label>

            {/* Started at */}
            <label className="block">
              <span className={labelCls}>Started at</span>
              <input
                type="datetime-local"
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={createForm.started_at ? createForm.started_at.slice(0, 16) : ''}
                onChange={(e) => setCreateForm((p) => ({ ...p, started_at: e.target.value || undefined }))}
              />
            </label>

            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setShowCreate(false)} className="rounded-lg px-4 py-2 text-[13px] text-[#64748B] hover:bg-[#F1F5F9]">
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={createSaving || !createForm.user_id || !createForm.plan_id || !createForm.price_id}
                className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60 hover:bg-teal-600"
              >
                {createSaving ? 'Creating…' : 'Create'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Edit modal */}
      {editing && (
        <Modal title="Update subscription" onClose={() => setEditing(null)}>
          {editError && (
            <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{editError}</div>
          )}
          <div className="space-y-3">
            <div className="rounded-lg p-3 text-[12px] text-[#64748B]" style={{ background: '#F8F9FA' }}>
              {(() => {
                const u = userMap.get(editing.user_id)
                const pl = planMap.get(editing.plan_id)
                const pr = priceMap.get(editing.price_id)
                return (
                  <>
                    <p>User: <span className="font-medium text-[#0F172A]">{u ? userLabel(u) : editing.user_id}</span></p>
                    <p>Plan: <span className="font-medium text-[#0F172A]">{pl?.name ?? editing.plan_id}</span></p>
                    <p>Price: <span className="font-medium text-[#0F172A]">
                      {pr ? `${pr.amount_display} / ${pr.billing_interval}` : editing.price_id}
                    </span> <span className="text-[11px] text-[#94A3B8]">(locked at join time)</span></p>
                  </>
                )
              })()}
            </div>
            <label className="block">
              <span className={labelCls}>Status</span>
              <select
                className={selectCls}
                value={editForm.status ?? editing.status}
                onChange={(e) => setEditForm((p) => ({ ...p, status: e.target.value as Subscription['status'] }))}
              >
                {SUBSCRIPTION_STATUSES.map((s) => (
                  <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className={labelCls}>Cancel reason</span>
              <input
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={editForm.cancel_reason ?? ''}
                onChange={(e) => setEditForm((p) => ({ ...p, cancel_reason: e.target.value || undefined }))}
              />
            </label>
            <label className="block">
              <span className={labelCls}>Payment provider</span>
              <input
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                placeholder="e.g. stripe"
                value={editForm.payment_provider ?? ''}
                onChange={(e) => setEditForm((p) => ({ ...p, payment_provider: e.target.value || undefined }))}
              />
            </label>
            <label className="block">
              <span className={labelCls}>Provider subscription ID</span>
              <input
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] font-mono outline-none focus:border-teal-400"
                placeholder="e.g. sub_xxx"
                value={editForm.payment_provider_subscription_id ?? ''}
                onChange={(e) => setEditForm((p) => ({ ...p, payment_provider_subscription_id: e.target.value || undefined }))}
              />
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setEditing(null)} className="rounded-lg px-4 py-2 text-[13px] text-[#64748B] hover:bg-[#F1F5F9]">
                Cancel
              </button>
              <button
                onClick={handleEdit}
                disabled={editSaving}
                className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60 hover:bg-teal-600"
              >
                {editSaving ? 'Saving…' : 'Save changes'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
