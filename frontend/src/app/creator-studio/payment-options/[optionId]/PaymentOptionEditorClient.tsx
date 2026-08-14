'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { PaymentOptionRow } from '../PaymentOptionsIndexClient'
import ExperiencePickerModal, { type Experience } from './ExperiencePickerModal'

/**
 * Central Payment Option editor.
 *
 * Three sections mirror the U1 brief:
 *
 *   Basics             — name / description / status
 *   What's included    — grants (Pathway / Series / Gathering)
 *   How members can pay — schedules
 *
 * Grants operate on ``PaymentOptionGrant`` exclusively; legacy
 * commercial fields on the option row are never surfaced or
 * written from this editor.
 */

type Grant = PaymentOptionRow['grants'][number]
type Schedule = PaymentOptionRow['schedules'][number]

// Re-export ``Experience`` shape from the picker so this file
// stays the single source of truth for local aliases.
type GrantableExperience = Experience

function formatMoney(cents: number, currency: string): string {
  const symbol = currency === 'AUD' || currency === 'USD' ? '$' : `${currency} `
  const dollars = cents / 100
  return `${symbol}${Number.isInteger(dollars) ? dollars : dollars.toFixed(2)}`
}

export default function PaymentOptionEditorClient({
  spaceSlug, optionId,
}: {
  spaceSlug: string
  optionId: string
}) {
  const router = useRouter()
  const [option, setOption] = useState<PaymentOptionRow | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [experiences, setExperiences] = useState<GrantableExperience[]>([])

  const load = useCallback(async () => {
    setError(null)
    try {
      const [optRes, expRes] = await Promise.all([
        fetch(
          apiUrl(`/api/creator/spaces/${spaceSlug}/commerce/payment-options/${optionId}`),
          { credentials: 'include' },
        ),
        fetch(
          apiUrl(`/api/creator/spaces/${spaceSlug}/commerce/grantable-experiences`),
          { credentials: 'include' },
        ),
      ])
      if (!optRes.ok) throw new Error(`Loading option: ${optRes.status}`)
      const opt = await optRes.json() as PaymentOptionRow
      setOption(opt)
      if (expRes.ok) {
        setExperiences((await expRes.json()) as GrantableExperience[])
      }
    } catch (err) {
      setError(String((err as Error)?.message ?? err))
    }
  }, [spaceSlug, optionId])

  useEffect(() => { void load() }, [load])

  async function apiCall<T>(path: string, init: RequestInit): Promise<T | null> {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(path), {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
        ...init,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail ?? `${res.status} ${res.statusText}`)
      }
      if (res.status === 204) return null
      return await res.json() as T
    } catch (err) {
      setError(String((err as Error)?.message ?? err))
      return null
    } finally {
      setBusy(false)
    }
  }

  if (error && !option) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-[13px] text-red-800">
        Couldn't load this Payment Option: {error}
      </div>
    )
  }
  if (!option) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-6 text-[13px] text-slate-500">
        Loading…
      </div>
    )
  }

  // ───────────────────────────────────────────────────────────────
  // Basics — name / description / status
  // ───────────────────────────────────────────────────────────────
  async function saveBasics(patch: Partial<PaymentOptionRow>) {
    const updated = await apiCall<PaymentOptionRow>(
      `/api/creator/spaces/${spaceSlug}/commerce/payment-options/${optionId}`,
      { method: 'PATCH', body: JSON.stringify(patch) },
    )
    if (updated) setOption(updated)
  }

  // ───────────────────────────────────────────────────────────────
  // Grants
  // ───────────────────────────────────────────────────────────────
  async function addGrant(
    exp: GrantableExperience,
    extras?: { sessions_per_week?: number; total_sessions?: number },
  ) {
    const body: Record<string, unknown> = {
      grant_kind: exp.kind,
      pathway_id: exp.kind === 'pathway' ? exp.id : null,
      series_id: exp.kind === 'event_series' ? exp.id : null,
      event_id: exp.kind === 'gathering' ? exp.id : null,
    }
    if (exp.kind === 'event_series') {
      if (extras?.sessions_per_week != null) body.sessions_per_week = extras.sessions_per_week
      if (extras?.total_sessions != null) body.total_sessions = extras.total_sessions
    }
    const created = await apiCall<Grant>(
      `/api/creator/spaces/${spaceSlug}/commerce/payment-options/${optionId}/grants`,
      { method: 'POST', body: JSON.stringify(body) },
    )
    if (created) await load()
  }

  async function updateGrant(grantId: string, patch: Partial<Grant>) {
    const updated = await apiCall<Grant>(
      `/api/creator/spaces/${spaceSlug}/commerce/payment-options/${optionId}/grants/${grantId}`,
      { method: 'PATCH', body: JSON.stringify(patch) },
    )
    if (updated) await load()
  }

  async function removeGrant(grantId: string) {
    const ok = confirm('Remove this experience from the Payment Option?')
    if (!ok) return
    await apiCall<null>(
      `/api/creator/spaces/${spaceSlug}/commerce/payment-options/${optionId}/grants/${grantId}`,
      { method: 'DELETE' },
    )
    await load()
  }

  // ───────────────────────────────────────────────────────────────
  // Schedules
  // ───────────────────────────────────────────────────────────────
  async function addSchedule(body: Record<string, unknown>) {
    const created = await apiCall<Schedule>(
      `/api/creator/spaces/${spaceSlug}/commerce/payment-options/${optionId}/schedules`,
      { method: 'POST', body: JSON.stringify(body) },
    )
    if (created) await load()
  }

  async function updateSchedule(scheduleId: string, patch: Record<string, unknown>) {
    const updated = await apiCall<Schedule>(
      `/api/creator/spaces/${spaceSlug}/commerce/payment-options/${optionId}/schedules/${scheduleId}`,
      { method: 'PATCH', body: JSON.stringify(patch) },
    )
    if (updated) await load()
  }

  async function removeSchedule(scheduleId: string) {
    const ok = confirm('Remove this payment method?')
    if (!ok) return
    await apiCall<null>(
      `/api/creator/spaces/${spaceSlug}/commerce/payment-options/${optionId}/schedules/${scheduleId}`,
      { method: 'DELETE' },
    )
    await load()
  }

  async function deleteOption() {
    if (!option) return
    const ok = confirm(
      option.status === 'draft'
        ? 'Delete this draft Payment Option? This cannot be undone.'
        : 'Archive this Payment Option? Members will no longer be able to purchase it.',
    )
    if (!ok) return
    await apiCall<null>(
      `/api/creator/spaces/${spaceSlug}/commerce/payment-options/${optionId}`,
      { method: 'DELETE' },
    )
    router.push('/creator-studio/payment-options')
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-[13px] text-red-800">
          {error}
        </div>
      )}

      <PurchasabilityBanner option={option} />

      <BasicsSection option={option} saveBasics={saveBasics} busy={busy} />
      <IncludedSection
        option={option}
        experiences={experiences}
        addGrant={addGrant}
        updateGrant={updateGrant}
        removeGrant={removeGrant}
        busy={busy}
      />
      <PaymentMethodsSection
        option={option}
        addSchedule={addSchedule}
        updateSchedule={updateSchedule}
        removeSchedule={removeSchedule}
        busy={busy}
      />

      <DangerZone option={option} onDelete={deleteOption} busy={busy} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Purchasability banner
// ---------------------------------------------------------------------------

function PurchasabilityBanner({ option }: { option: PaymentOptionRow }) {
  if (option.purchasability === 'ready') {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-[13px] text-emerald-800">
        <strong>Ready to sell.</strong> This Payment Option has a published
        payment method and included experiences. Members can purchase it now.
      </div>
    )
  }
  if (option.purchasability === 'configured_not_yet_checkoutable') {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-800">
        <strong>Configured — checkout coming later.</strong>{' '}
        Only finite instalment / subscription payment methods are set up. The
        unified member checkout doesn't run those yet. Add a "Single payment"
        method to make this option purchasable now.
      </div>
    )
  }
  if (option.purchasability === 'needs_attention') {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-800">
        <strong>Needs attention.</strong>
        {option.purchasability_notes.length > 0 && (
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            {option.purchasability_notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        )}
      </div>
    )
  }
  if (option.purchasability === 'draft' && option.purchasability_notes.length > 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-[13px] text-slate-700">
        <strong>Draft.</strong>
        <ul className="mt-1 list-inside list-disc space-y-0.5">
          {option.purchasability_notes.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      </div>
    )
  }
  return null
}

// ---------------------------------------------------------------------------
// Basics — name / description / status
// ---------------------------------------------------------------------------

function BasicsSection({
  option, saveBasics, busy,
}: {
  option: PaymentOptionRow
  saveBasics: (patch: Partial<PaymentOptionRow>) => Promise<void>
  busy: boolean
}) {
  const [name, setName] = useState(option.name)
  const [description, setDescription] = useState(option.description ?? '')
  const [status, setStatus] = useState(option.status)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setName(option.name)
    setDescription(option.description ?? '')
    setStatus(option.status)
    setDirty(false)
  }, [option])

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6">
      <h2 className="font-serif text-xl text-navy-900">Basics</h2>

      <label className="mt-4 block text-[13px] font-semibold text-navy-900">Name</label>
      <input
        type="text"
        value={name}
        onChange={(e) => { setName(e.target.value); setDirty(true) }}
        className="mt-1.5 w-full rounded-md border border-slate-300 px-3 py-2 text-[14px] focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
      />

      <label className="mt-4 block text-[13px] font-semibold text-navy-900">
        Description <span className="text-slate-400">(optional)</span>
      </label>
      <textarea
        value={description}
        onChange={(e) => { setDescription(e.target.value); setDirty(true) }}
        rows={2}
        className="mt-1.5 w-full rounded-md border border-slate-300 px-3 py-2 text-[14px] focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
      />

      <label className="mt-4 block text-[13px] font-semibold text-navy-900">Status</label>
      <select
        value={status}
        onChange={(e) => { setStatus(e.target.value as PaymentOptionRow['status']); setDirty(true) }}
        className="mt-1.5 rounded-md border border-slate-300 px-3 py-2 text-[14px] focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
      >
        <option value="draft">Draft — only you can see it</option>
        <option value="published">Published — available to members</option>
        <option value="archived">Archived — hidden</option>
      </select>

      <div className="mt-5 flex items-center gap-3">
        <button
          type="button"
          disabled={busy || !dirty}
          onClick={() => saveBasics({
            name: name.trim(),
            description: description.trim() || null,
            status,
          })}
          className="inline-flex items-center rounded-md bg-teal-600 px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Save basics
        </button>
        {dirty && <span className="text-[12px] text-amber-700">Unsaved changes</span>}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// What's included — grants
// ---------------------------------------------------------------------------

function IncludedSection({
  option, experiences, addGrant, updateGrant, removeGrant, busy,
}: {
  option: PaymentOptionRow
  experiences: GrantableExperience[]
  addGrant: (exp: GrantableExperience, extras?: { sessions_per_week?: number; total_sessions?: number }) => Promise<void>
  updateGrant: (grantId: string, patch: Partial<Grant>) => Promise<void>
  removeGrant: (grantId: string) => Promise<void>
  busy: boolean
}) {
  const alreadyGranted = new Set(
    option.grants
      .map((g) => g.pathway_id ?? g.series_id ?? g.event_id)
      .filter(Boolean) as string[],
  )
  const [pickerOpen, setPickerOpen] = useState(false)

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-xl text-navy-900">What's included</h2>
          <p className="mt-1 text-[13px] text-slate-600">
            Pick one or more experiences from this Collective. Members who buy
            this Payment Option get access to all of them.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setPickerOpen(true)}
          disabled={busy}
          className="inline-flex items-center rounded-md bg-slate-800 px-3.5 py-1.5 text-[12.5px] font-semibold text-white hover:bg-slate-900 disabled:opacity-50"
        >
          Add an experience
        </button>
      </div>

      {option.grants.length > 0 ? (
        <ul className="mt-5 space-y-3">
          {option.grants.map((g) => (
            <GrantRow key={g.id} grant={g} onSave={updateGrant} onRemove={removeGrant} busy={busy} />
          ))}
        </ul>
      ) : (
        <p className="mt-5 rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 text-[13px] italic text-slate-500">
          Nothing selected yet — use “Add an experience” above.
        </p>
      )}

      <ExperiencePickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        experiences={experiences}
        alreadyGrantedIds={alreadyGranted}
        onAdd={addGrant}
      />
    </section>
  )
}

function GrantRow({
  grant, onSave, onRemove, busy,
}: {
  grant: Grant
  onSave: (grantId: string, patch: Partial<Grant>) => Promise<void>
  onRemove: (grantId: string) => Promise<void>
  busy: boolean
}) {
  const [spw, setSpw] = useState<string>(grant.sessions_per_week?.toString() ?? '')
  const [tot, setTot] = useState<string>(grant.total_sessions?.toString() ?? '')
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setSpw(grant.sessions_per_week?.toString() ?? '')
    setTot(grant.total_sessions?.toString() ?? '')
    setDirty(false)
  }, [grant])

  const kindLabel =
    grant.grant_kind === 'pathway' ? 'Pathway' :
    grant.grant_kind === 'event_series' ? 'Gathering Series' :
    'Gathering'

  return (
    <li className="rounded-lg border border-slate-200 bg-slate-50/50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-teal-700">
            {kindLabel}
          </div>
          <div className="mt-0.5 text-[15px] font-medium text-navy-900">
            {grant.target?.title ?? <em className="text-red-600">Missing target</em>}
          </div>
        </div>
        <button
          type="button"
          onClick={() => void onRemove(grant.id)}
          disabled={busy}
          className="text-[12px] text-slate-500 hover:text-red-600 disabled:opacity-40"
        >
          Remove
        </button>
      </div>

      {grant.grant_kind === 'event_series' && (
        <div className="mt-4">
          <p className="text-[12px] font-semibold text-navy-900">Gathering allowance</p>
          <p className="mt-0.5 text-[11.5px] text-slate-500">
            How many Gatherings from this Series the member can book.
            Leave blank to grant unlimited access for the Series's period.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-[11.5px] font-medium text-slate-700">Sessions each week</span>
              <input
                type="number"
                min={0}
                value={spw}
                onChange={(e) => { setSpw(e.target.value); setDirty(true) }}
                className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px] focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
              />
            </label>
            <label className="block">
              <span className="text-[11.5px] font-medium text-slate-700">Total sessions</span>
              <input
                type="number"
                min={0}
                value={tot}
                onChange={(e) => { setTot(e.target.value); setDirty(true) }}
                className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px] focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
              />
            </label>
          </div>
          {dirty && (
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void onSave(grant.id, {
                  sessions_per_week: spw === '' ? null : Number(spw),
                  total_sessions: tot === '' ? null : Number(tot),
                })}
                className="rounded-md bg-teal-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-teal-700 disabled:opacity-60"
              >
                Save allowance
              </button>
              <span className="text-[11px] text-amber-700">Unsaved changes</span>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

// (Legacy ``AddGrantPicker`` removed — replaced by
//  ``ExperiencePickerModal`` in the Includes section.)

// ---------------------------------------------------------------------------
// How members can pay — schedules
// ---------------------------------------------------------------------------

function PaymentMethodsSection({
  option, addSchedule, updateSchedule, removeSchedule, busy,
}: {
  option: PaymentOptionRow
  addSchedule: (body: Record<string, unknown>) => Promise<void>
  updateSchedule: (id: string, patch: Record<string, unknown>) => Promise<void>
  removeSchedule: (id: string) => Promise<void>
  busy: boolean
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6">
      <h2 className="font-serif text-xl text-navy-900">How members can pay</h2>
      <p className="mt-1 text-[13px] text-slate-600">
        Set one or more payment methods for this option. Only "Single payment"
        methods can be checked out through the member flow today — instalments
        and subscriptions can be authored but are marked <em>coming later</em>.
      </p>

      {option.schedules.length > 0 ? (
        <ul className="mt-5 space-y-3">
          {option.schedules.map((s) => (
            <ScheduleRow
              key={s.id}
              schedule={s}
              currency={option.currency}
              onSave={updateSchedule}
              onRemove={removeSchedule}
              busy={busy}
            />
          ))}
        </ul>
      ) : (
        <p className="mt-5 rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 text-[13px] italic text-slate-500">
          No payment methods yet.
        </p>
      )}

      <div className="mt-6 border-t border-slate-100 pt-5">
        <h3 className="text-[12px] font-semibold uppercase tracking-wider text-slate-500">
          Add a payment method
        </h3>
        <AddSchedulePicker currency={option.currency} onAdd={addSchedule} busy={busy} />
      </div>
    </section>
  )
}

function ScheduleRow({
  schedule, currency, onSave, onRemove, busy,
}: {
  schedule: Schedule
  currency: string
  onSave: (id: string, patch: Record<string, unknown>) => Promise<void>
  onRemove: (id: string) => Promise<void>
  busy: boolean
}) {
  const [name, setName] = useState(schedule.name)
  const [status, setStatus] = useState(schedule.status)
  const [total, setTotal] = useState<string>(schedule.total_amount_cents != null ? (schedule.total_amount_cents / 100).toString() : '')
  const [each, setEach] = useState<string>(schedule.installment_amount_cents != null ? (schedule.installment_amount_cents / 100).toString() : '')
  const [count, setCount] = useState<string>(schedule.installment_count?.toString() ?? '')
  const [interval, setInterval] = useState<string>(schedule.interval ?? 'week')
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setName(schedule.name)
    setStatus(schedule.status)
    setTotal(schedule.total_amount_cents != null ? (schedule.total_amount_cents / 100).toString() : '')
    setEach(schedule.installment_amount_cents != null ? (schedule.installment_amount_cents / 100).toString() : '')
    setCount(schedule.installment_count?.toString() ?? '')
    setInterval(schedule.interval ?? 'week')
    setDirty(false)
  }, [schedule])

  const typeLabel =
    schedule.schedule_type === 'pay_in_full' ? 'Single payment' :
    schedule.schedule_type === 'recurring_installments' ? 'Payment plan' :
    'Manual'

  const statusLabel: Record<Schedule['status'], string> = {
    draft: 'Draft', published: 'Published', archived: 'Archived',
  }

  const isFree = schedule.total_amount_cents === 0 && schedule.schedule_type === 'pay_in_full'
  const summary = schedule.schedule_type === 'pay_in_full'
    ? (isFree ? 'Free' : `${schedule.total_amount_cents != null ? formatMoney(schedule.total_amount_cents, currency) : '—'} once`)
    : schedule.schedule_type === 'recurring_installments'
      ? `${schedule.installment_amount_cents != null ? formatMoney(schedule.installment_amount_cents, currency) : '—'}/${schedule.interval ?? 'week'} × ${schedule.installment_count ?? '—'}`
      : 'Manual arrangement'

  const disabledNonPayFullNote = schedule.status === 'published'
    && schedule.schedule_type !== 'pay_in_full'

  return (
    <li className="rounded-lg border border-slate-200 bg-slate-50/50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-teal-700">
            {typeLabel}
          </div>
          <div className="mt-0.5 text-[15px] font-medium text-navy-900">{summary}</div>
          <div className="mt-0.5 text-[12px] text-slate-500">{schedule.name}</div>
          {disabledNonPayFullNote && (
            <div className="mt-1.5 text-[11.5px] text-amber-700">
              Checkout for this schedule type is coming later.
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => void onRemove(schedule.id)}
          disabled={busy}
          className="text-[12px] text-slate-500 hover:text-red-600 disabled:opacity-40"
        >
          Remove
        </button>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="block">
          <span className="text-[11.5px] font-medium text-slate-700">Label</span>
          <input
            type="text" value={name}
            onChange={(e) => { setName(e.target.value); setDirty(true) }}
            className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
          />
        </label>
        <label className="block">
          <span className="text-[11.5px] font-medium text-slate-700">Status</span>
          <select
            value={status}
            onChange={(e) => { setStatus(e.target.value as Schedule['status']); setDirty(true) }}
            className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
          >
            <option value="draft">{statusLabel.draft}</option>
            <option value="published">{statusLabel.published}</option>
            <option value="archived">{statusLabel.archived}</option>
          </select>
        </label>
        {schedule.schedule_type === 'pay_in_full' && (
          <label className="block">
            <span className="text-[11.5px] font-medium text-slate-700">Amount ({currency})</span>
            <input
              type="number" min={0} step="0.01" value={total}
              onChange={(e) => { setTotal(e.target.value); setDirty(true) }}
              className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
            />
          </label>
        )}
        {schedule.schedule_type === 'recurring_installments' && (
          <>
            <label className="block">
              <span className="text-[11.5px] font-medium text-slate-700">Per payment ({currency})</span>
              <input
                type="number" min={0} step="0.01" value={each}
                onChange={(e) => { setEach(e.target.value); setDirty(true) }}
                className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
              />
            </label>
            <label className="block">
              <span className="text-[11.5px] font-medium text-slate-700">Cadence</span>
              <select
                value={interval}
                onChange={(e) => { setInterval(e.target.value); setDirty(true) }}
                className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
              >
                <option value="week">Weekly</option>
                <option value="fortnight">Fortnightly</option>
                <option value="month">Monthly</option>
              </select>
            </label>
            <label className="block">
              <span className="text-[11.5px] font-medium text-slate-700">Number of payments</span>
              <input
                type="number" min={1} value={count}
                onChange={(e) => { setCount(e.target.value); setDirty(true) }}
                className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
              />
            </label>
          </>
        )}
      </div>

      {dirty && (
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button" disabled={busy}
            onClick={() => {
              const patch: Record<string, unknown> = {
                name: name.trim(),
                status,
              }
              if (schedule.schedule_type === 'pay_in_full') {
                patch.total_amount_cents = total === '' ? null : Math.round(Number(total) * 100)
              }
              if (schedule.schedule_type === 'recurring_installments') {
                patch.installment_amount_cents = each === '' ? null : Math.round(Number(each) * 100)
                patch.installment_count = count === '' ? null : Number(count)
                patch.interval = interval
              }
              void onSave(schedule.id, patch)
            }}
            className="rounded-md bg-teal-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-teal-700 disabled:opacity-60"
          >
            Save payment method
          </button>
          <span className="text-[11px] text-amber-700">Unsaved changes</span>
        </div>
      )}
    </li>
  )
}

function AddSchedulePicker({
  currency, onAdd, busy,
}: {
  currency: string
  onAdd: (body: Record<string, unknown>) => Promise<void>
  busy: boolean
}) {
  const [kind, setKind] = useState<'free' | 'once' | 'plan'>('once')
  const [amount, setAmount] = useState('')
  const [each, setEach] = useState('')
  const [count, setCount] = useState('')
  const [interval, setInterval] = useState('week')

  async function submit() {
    if (kind === 'free') {
      await onAdd({
        name: 'Free',
        schedule_type: 'pay_in_full',
        status: 'draft',
        total_amount_cents: 0,
        currency,
      })
    } else if (kind === 'once') {
      const cents = amount === '' ? null : Math.round(Number(amount) * 100)
      await onAdd({
        name: 'Pay in full',
        schedule_type: 'pay_in_full',
        status: 'draft',
        total_amount_cents: cents,
        currency,
      })
      setAmount('')
    } else {
      const cents = each === '' ? null : Math.round(Number(each) * 100)
      await onAdd({
        name: `${interval[0].toUpperCase() + interval.slice(1)}ly payments`,
        schedule_type: 'recurring_installments',
        status: 'draft',
        installment_amount_cents: cents,
        installment_count: count === '' ? null : Number(count),
        interval,
        currency,
      })
      setEach(''); setCount('')
    }
  }

  return (
    <div className="mt-3 space-y-3">
      <div className="flex flex-wrap gap-2">
        <PickerButton active={kind === 'free'} onClick={() => setKind('free')}>Free</PickerButton>
        <PickerButton active={kind === 'once'} onClick={() => setKind('once')}>Single payment</PickerButton>
        <PickerButton active={kind === 'plan'} onClick={() => setKind('plan')}>Payment plan</PickerButton>
      </div>

      {kind === 'free' && (
        <p className="text-[12px] text-slate-500">$0 — no payment required.</p>
      )}
      {kind === 'once' && (
        <label className="block">
          <span className="text-[11.5px] font-medium text-slate-700">Amount ({currency})</span>
          <input
            type="number" min={0} step="0.01" value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="mt-1 w-40 rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
          />
        </label>
      )}
      {kind === 'plan' && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <label className="block">
              <span className="text-[11.5px] font-medium text-slate-700">Per payment ({currency})</span>
              <input
                type="number" min={0} step="0.01" value={each}
                onChange={(e) => setEach(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
              />
            </label>
            <label className="block">
              <span className="text-[11.5px] font-medium text-slate-700">Cadence</span>
              <select
                value={interval}
                onChange={(e) => setInterval(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
              >
                <option value="week">Weekly</option>
                <option value="fortnight">Fortnightly</option>
                <option value="month">Monthly</option>
              </select>
            </label>
            <label className="block">
              <span className="text-[11.5px] font-medium text-slate-700">Number of payments</span>
              <input
                type="number" min={1} value={count}
                onChange={(e) => setCount(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-[13px]"
              />
            </label>
          </div>
          <p className="text-[11.5px] text-amber-700">
            Payment-plan checkout is not yet active for members — this will
            save as <strong>Draft</strong> so you can author it now and turn
            it on later.
          </p>
        </>
      )}

      <button
        type="button"
        onClick={() => void submit()}
        disabled={busy}
        className="rounded-md bg-slate-800 px-3.5 py-1.5 text-[12.5px] font-semibold text-white hover:bg-slate-900 disabled:opacity-50"
      >
        Add payment method
      </button>
    </div>
  )
}

function PickerButton({
  active, onClick, children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-[12px] font-semibold transition-colors ${
        active
          ? 'bg-teal-600 text-white'
          : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
      }`}
    >
      {children}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Danger zone
// ---------------------------------------------------------------------------

function DangerZone({
  option, onDelete, busy,
}: {
  option: PaymentOptionRow
  onDelete: () => Promise<void>
  busy: boolean
}) {
  const isDraft = option.status === 'draft'
  return (
    <section className="rounded-xl border border-red-100 bg-red-50/40 p-6">
      <h2 className="font-serif text-lg text-red-900">
        {isDraft ? 'Delete this draft' : 'Archive this Payment Option'}
      </h2>
      <p className="mt-1 text-[13px] text-red-800">
        {isDraft
          ? 'Only draft Payment Options with no purchases can be deleted permanently.'
          : 'Once purchased, a Payment Option cannot be deleted — archiving hides it from members while preserving purchase history.'}
      </p>
      <button
        type="button"
        onClick={() => void onDelete()}
        disabled={busy}
        className="mt-3 inline-flex items-center rounded-md border border-red-300 bg-white px-3.5 py-1.5 text-[12.5px] font-semibold text-red-700 hover:bg-red-100 disabled:opacity-50"
      >
        {isDraft ? 'Delete permanently' : 'Archive'}
      </button>
    </section>
  )
}
