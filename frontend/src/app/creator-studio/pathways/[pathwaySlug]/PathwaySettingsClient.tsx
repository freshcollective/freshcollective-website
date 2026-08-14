'use client'

import { useEffect, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import type { CreatorMediaAsset, CreatorPathway } from '@/types/platform'
import ImagePickerField from '@/components/creator/ImagePickerField'
import { apiUrl } from '@/lib/api'
import { formatDisplayDate } from '@/lib/dateTime'
import PathwayPaymentOptionsReference from './PathwayPaymentOptionsReference'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PRICING_MODE_PAYMENT_OPTIONS_VALUE = 'payment_options'

// ---------------------------------------------------------------------------
// AccessPricingSection
// ---------------------------------------------------------------------------

/**
 * Non-commerce access controls only.
 *
 * Paid access (one-off, subscription, "included with a paid offer",
 * multiple payment options, unlock-option checkboxes) moved to
 * Commerce → Payment Options in U1. The Pathway editor now exposes
 * only the two access modes that have no commercial semantics —
 * ``free`` and ``included`` — and shows an explanatory band when
 * the row's stored ``access_type`` / ``pricing_mode`` is a legacy
 * paid value, so the Creator understands why the paid choice they
 * remember isn't listed anymore.
 *
 * The legacy state / setter props are preserved so the parent
 * form can still round-trip the row through PATCH without a data
 * migration. This surface never writes a paid access_type or the
 * payment_options pricing mode; those combinations are managed
 * through the Payment Option editor and its grants.
 */
function AccessPricingSection({
  accessType, setAccessType, pricingMode, setPricingMode,
  // Legacy commerce props — preserved for compatibility with the
  // parent form; unused by the simplified UI. See docstring.
  priceDollars: _priceDollars, setPriceDollars: _setPriceDollars,
  currency: _currency, setCurrency: _setCurrency,
  priceError: _priceError,
  spaceSlug: _spaceSlug,
  unlockOptionIds: _unlockOptionIds, setUnlockOptionIds: _setUnlockOptionIds,
}: {
  accessType: string
  setAccessType: (v: string) => void
  pricingMode: string
  setPricingMode: (v: string) => void
  priceDollars: string
  setPriceDollars: (v: string) => void
  currency: string
  setCurrency: (v: string) => void
  priceError: string | null
  spaceSlug: string
  unlockOptionIds: string[]
  setUnlockOptionIds: (ids: string[]) => void
}) {
  // Legacy paid states that pre-date Commerce → Payment Options.
  // We render them read-only so the Creator understands why the
  // choice they remember isn't shown — but they can switch back to
  // ``free`` / ``included`` to opt out.
  const isPaymentOptionsMode = pricingMode === PRICING_MODE_PAYMENT_OPTIONS_VALUE
  const legacyPaid = isPaymentOptionsMode
    || accessType === 'one_time'
    || accessType === 'subscription'
    || accessType === 'included_with_offer'

  // Both choices are non-commercial and give *members* the same
  // access. They diverge on *public visibility*:
  //   free     — the Pathway is publicly discoverable (unauth
  //              visitors see it and can preview the About page).
  //   included — the Pathway is member-only (unauth visitors see
  //              a "Join to begin" prompt and are redirected to
  //              login; the card is hidden from public lists).
  // Confirmed via backend access resolver in
  // ``spaces/routes.py:599-730`` — keep both to preserve that
  // deliberate distinction.
  const CHOICES: { value: string; label: string; description: string }[] = [
    { value: 'free',     label: 'Public',      description: 'Anyone can find and preview this Pathway on your Collective\u2019s public pages. Members can begin it immediately.' },
    { value: 'included', label: 'Members only', description: 'Only signed-in members of this Collective can see or begin this Pathway. Non-members are prompted to join.' },
  ]

  function handleChoiceClick(value: string) {
    setPricingMode('legacy')
    setAccessType(value)
  }

  return (
    <div>
      <label className="mb-2 block text-[12px] font-semibold text-black">Access</label>

      {legacyPaid && (
        <div className="mb-3 rounded-xl border border-teal-200 bg-teal-50/40 px-4 py-3 text-[12px] leading-relaxed text-teal-900">
          <strong>Paid access is now managed in Commerce → Payment Options.</strong>{' '}
          This Pathway is currently configured with a legacy paid access mode. The
          Payment Options that include this Pathway are shown below. To take
          this Pathway off paid access, choose <em>Free</em> or <em>Included in
          collective access</em>.
        </div>
      )}

      <div className="space-y-2">
        {CHOICES.map((opt) => {
          const selected = !legacyPaid && accessType === opt.value
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => handleChoiceClick(opt.value)}
              className="w-full rounded-xl border px-4 py-3 text-left transition-colors"
              style={
                selected
                  ? { borderColor: 'rgba(56,160,158,0.6)', background: 'rgba(56,160,158,0.05)' }
                  : { borderColor: '#e2e8f0', background: 'white' }
              }
            >
              <div className="flex items-center gap-3">
                <div
                  className="mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 transition-colors"
                  style={selected ? { borderColor: '#38A09E', background: '#38A09E' } : { borderColor: '#cbd5e1', background: 'white' }}
                />
                <div>
                  <p className="text-[14px] font-semibold text-navy-900">{opt.label}</p>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-black">{opt.description}</p>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Payment / pricing helpers
// ---------------------------------------------------------------------------

function centsToDisplay(cents: number | null): string {
  if (cents == null) return ''
  const dollars = cents / 100
  return Number.isInteger(dollars) ? `${dollars}` : dollars.toFixed(2)
}

// ---------------------------------------------------------------------------
// PaymentOptionsSection
// ---------------------------------------------------------------------------

interface PaymentOption {
  id: string
  name: string
  description: string | null
  payment_type: string
  status: string
  term_start_date: string | null
  term_end_date: string | null
  sessions_per_week: number | null
  total_sessions: number | null
  price_per_session_cents: number | null
  calculated_total_cents: number | null
  override_total_cents: number | null
  effective_price_cents: number | null
  currency: string
  buyer_note: string | null
  internal_note: string | null
  position: number
}

function fmtOptionPrice(cents: number | null, currency: string): string {
  if (cents == null) return '—'
  const amount = cents / 100
  return `$${Number.isInteger(amount) ? amount.toFixed(0) : amount.toFixed(2)} ${currency}`
}

interface PaymentSchedule {
  id: string
  payment_option_id: string
  name: string
  description: string | null
  schedule_type: string
  status: string
  total_amount_cents: number | null
  upfront_amount_cents: number | null
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  stripe_interval: string | null
  stripe_interval_count: number | null
  currency: string
  buyer_note: string | null
  internal_note: string | null
  position: number
}

function scheduleTypeLabel(t: string): string {
  if (t === 'pay_in_full') return 'Pay in full'
  if (t === 'recurring_installments') return 'Recurring instalments'
  if (t === 'manual') return 'Manual'
  return t
}

// ---------------------------------------------------------------------------
// PaymentSchedulesSection
// ---------------------------------------------------------------------------

function PaymentSchedulesSection({
  spaceSlug,
  pathwaySlug,
  optionId,
  effectivePrice,
  currency: optCurrency,
}: {
  spaceSlug: string
  pathwaySlug: string
  optionId: string
  effectivePrice: number | null
  currency: string
}) {
  const [schedules, setSchedules] = useState<PaymentSchedule[]>([])
  const [loaded, setLoaded] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  // null = list view; 'new' = adding; <id> = editing
  const [formMode, setFormMode] = useState<'new' | string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)

  // Form fields
  const [sName, setSName] = useState('')
  const [sDesc, setSDesc] = useState('')
  const [sType, setSType] = useState('pay_in_full')
  const [sTotalAmount, setSTotalAmount] = useState('')
  const [sInstAmount, setSInstAmount] = useState('')
  const [sInstCount, setSInstCount] = useState('')
  const [sInterval, setSInterval] = useState('week')
  const [sCurrency, setSCurrency] = useState(optCurrency)
  const [sBuyerNote, setSBuyerNote] = useState('')
  const [sInternalNote, setSInternalNote] = useState('')

  async function loadSchedules() {
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules`),
        { credentials: 'include' },
      )
      if (!res.ok) { setLoadError('Could not load schedules.'); return }
      setSchedules(await res.json())
      setLoaded(true)
    } catch { setLoadError('Could not load schedules.') }
  }

  function toggleExpand() {
    if (!expanded && !loaded) loadSchedules()
    setExpanded(v => !v)
    setFormMode(null)
  }

  function resetSchedForm(s?: PaymentSchedule) {
    setSName(s?.name ?? '')
    setSDesc(s?.description ?? '')
    setSType(s?.schedule_type ?? 'pay_in_full')
    setSTotalAmount(s?.total_amount_cents != null ? String(s.total_amount_cents / 100) : (effectivePrice != null ? String(effectivePrice / 100) : ''))
    setSInstAmount(s?.installment_amount_cents != null ? String(s.installment_amount_cents / 100) : '')
    setSInstCount(s?.installment_count != null ? String(s.installment_count) : '')
    setSInterval(s?.interval ?? 'week')
    setSCurrency(s?.currency ?? optCurrency)
    setSBuyerNote(s?.buyer_note ?? '')
    setSInternalNote(s?.internal_note ?? '')
  }

  function openNew() { resetSchedForm(); setFormMode('new'); setSaveError(null) }
  function openEdit(s: PaymentSchedule) { resetSchedForm(s); setFormMode(s.id); setSaveError(null) }
  function closeForm() { setFormMode(null); setSaveError(null) }

  function buildSchedPayload() {
    return {
      name: sName.trim(),
      description: sDesc.trim() || null,
      schedule_type: sType,
      total_amount_cents: sTotalAmount ? Math.round(parseFloat(sTotalAmount) * 100) : null,
      installment_amount_cents: sInstAmount ? Math.round(parseFloat(sInstAmount) * 100) : null,
      installment_count: sInstCount ? parseInt(sInstCount) : null,
      interval: sType === 'recurring_installments' ? sInterval : null,
      stripe_interval: sType === 'recurring_installments' ? (sInterval === 'fortnight' ? 'week' : sInterval) : null,
      stripe_interval_count: sType === 'recurring_installments' ? (sInterval === 'fortnight' ? 2 : 1) : null,
      currency: sCurrency,
      buyer_note: sBuyerNote.trim() || null,
      internal_note: sInternalNote.trim() || null,
    }
  }

  async function handleCreate() {
    if (!sName.trim()) { setSaveError('Name is required.'); return }
    setSaving(true); setSaveError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules`),
        { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...buildSchedPayload(), status: 'draft' }) },
      )
      if (!res.ok) { const b = await res.json().catch(() => ({})); setSaveError((b as {detail?: string}).detail ?? 'Could not create schedule.'); return }
      await loadSchedules(); closeForm()
    } catch { setSaveError('Could not create schedule.') }
    finally { setSaving(false) }
  }

  async function handleUpdate(schedId: string) {
    if (!sName.trim()) { setSaveError('Name is required.'); return }
    setSaving(true); setSaveError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules/${schedId}`),
        { method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildSchedPayload()) },
      )
      if (!res.ok) { const b = await res.json().catch(() => ({})); setSaveError((b as {detail?: string}).detail ?? 'Could not save changes.'); return }
      await loadSchedules(); closeForm()
    } catch { setSaveError('Could not save changes.') }
    finally { setSaving(false) }
  }

  async function handleStatusChange(schedId: string, newStatus: string) {
    try {
      await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules/${schedId}`),
        { method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: newStatus }) },
      )
      await loadSchedules()
    } catch { /* ignore */ }
  }

  async function handleArchive(schedId: string) {
    if (!confirm('Archive this schedule? It will no longer appear to members.')) return
    try {
      await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules/${schedId}`),
        { method: 'DELETE', credentials: 'include' },
      )
      await loadSchedules()
    } catch { /* ignore */ }
  }

  async function handleGenerate() {
    if (!effectivePrice || effectivePrice <= 0) { alert('This option needs a valid effective price before generating schedules.'); return }
    setGenerating(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optionId}/schedules/generate`),
        { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ weekly_installment_count: 10, fortnightly_installment_count: 5 }) },
      )
      if (!res.ok) { const b = await res.json().catch(() => ({})); alert((b as {detail?: string}).detail ?? 'Could not generate schedules.'); return }
      await loadSchedules()
    } catch { alert('Could not generate schedules.') }
    finally { setGenerating(false) }
  }

  const isEditing = formMode !== null && formMode !== 'new'
  const editingSchedId = isEditing ? formMode : null

  function SchedForm({ schedId }: { schedId: string | null }) {
    return (
      <div className="rounded-lg border border-teal-200 bg-teal-50/30 p-3 space-y-3 mt-2">
        <p className="text-[12px] font-semibold text-navy-900">{schedId ? 'Edit schedule' : 'New schedule'}</p>
        {schedId && <p className="text-[11px] text-black">Changes affect future checkouts only.</p>}

        <div className="grid gap-2 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="mb-1 block text-[11px] font-semibold text-black">Name *</label>
            <input type="text" value={sName} onChange={e => setSName(e.target.value)} placeholder="e.g. Pay in full"
              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-black">Schedule type</label>
            <select value={sType} onChange={e => setSType(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[13px] outline-none focus:border-teal-400">
              <option value="pay_in_full">Pay in full</option>
              <option value="recurring_installments">Recurring instalments</option>
              <option value="manual">Manual</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-black">Currency</label>
            <select value={sCurrency} onChange={e => setSCurrency(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[13px] outline-none focus:border-teal-400">
              <option value="AUD">AUD</option>
              <option value="USD">USD</option>
              <option value="NZD">NZD</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-black">Total amount ($)</label>
            <input type="number" min="0" step="0.01" value={sTotalAmount} onChange={e => setSTotalAmount(e.target.value)}
              placeholder="e.g. 200"
              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
          </div>
          {sType === 'recurring_installments' && (
            <>
              <div>
                <label className="mb-1 block text-[11px] font-semibold text-black">Instalment amount ($)</label>
                <input type="number" min="0" step="0.01" value={sInstAmount} onChange={e => setSInstAmount(e.target.value)}
                  placeholder="e.g. 20"
                  className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-semibold text-black">Number of instalments</label>
                <input type="number" min="1" value={sInstCount} onChange={e => setSInstCount(e.target.value)}
                  placeholder="e.g. 10"
                  className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-semibold text-black">Interval</label>
                <select value={sInterval} onChange={e => setSInterval(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[13px] outline-none focus:border-teal-400">
                  <option value="week">Weekly</option>
                  <option value="fortnight">Fortnightly</option>
                  <option value="month">Monthly</option>
                </select>
              </div>
            </>
          )}
          <div className="sm:col-span-2">
            <label className="mb-1 block text-[11px] font-semibold text-black">Member-facing note</label>
            <input type="text" value={sBuyerNote} onChange={e => setSBuyerNote(e.target.value)}
              placeholder="Short note shown at checkout"
              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
          </div>
          <div className="sm:col-span-2">
            <label className="mb-1 block text-[11px] font-semibold text-black">Internal note</label>
            <input type="text" value={sInternalNote} onChange={e => setSInternalNote(e.target.value)}
              placeholder="Not shown to members"
              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[13px] outline-none focus:border-teal-400" />
          </div>
        </div>

        {saveError && <p className="text-[11px] text-red-600">{saveError}</p>}

        <div className="flex gap-2">
          <button type="button" onClick={schedId ? () => handleUpdate(schedId) : handleCreate} disabled={saving}
            className="rounded-lg px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}>
            {saving ? 'Saving…' : schedId ? 'Save changes' : 'Save as draft'}
          </button>
          <button type="button" onClick={closeForm}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-black transition-colors hover:bg-slate-50">
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-3 border-t border-slate-100 pt-3">
      <button type="button" onClick={toggleExpand}
        className="flex items-center gap-1.5 text-[12px] font-semibold text-teal-700 hover:text-teal-800">
        <span>{expanded ? '▾' : '▸'}</span>
        Payment schedules
        {loaded && schedules.length > 0 && (
          <span className="rounded-full bg-teal-100 px-1.5 py-0.5 text-[10px] text-teal-700">{schedules.length}</span>
        )}
      </button>

      {expanded && (
        <div className="mt-2 space-y-2">
          {loadError && <p className="text-[11px] text-red-600">{loadError}</p>}

          {formMode === 'new' && <SchedForm schedId={null} />}

          {schedules.map(s => (
            <div key={s.id}>
              {editingSchedId === s.id ? (
                <SchedForm schedId={s.id} />
              ) : (
                <div className="rounded-lg border border-slate-100 bg-white px-3 py-2 text-[12px]">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-navy-900">{s.name}</span>
                        <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                          s.status === 'published' ? 'bg-teal-100 text-teal-700'
                          : s.status === 'archived' ? 'bg-slate-200 text-slate-500'
                          : 'bg-amber-100 text-amber-700'
                        }`}>{s.status}</span>
                        <span className="text-black">({scheduleTypeLabel(s.schedule_type)})</span>
                      </div>
                      <div className="mt-0.5 flex flex-wrap gap-2 text-black">
                        {s.total_amount_cents != null && <span>Total: {fmtOptionPrice(s.total_amount_cents, s.currency)}</span>}
                        {s.installment_count != null && s.installment_amount_cents != null && (
                          <span>{s.installment_count} × {fmtOptionPrice(s.installment_amount_cents, s.currency)} {s.interval}</span>
                        )}
                      </div>
                    </div>
                    {formMode === null && (
                      <div className="flex shrink-0 flex-col gap-1 items-end">
                        {s.status !== 'archived' && (
                          <button type="button" onClick={() => openEdit(s)}
                            className="text-[10px] font-semibold text-black hover:text-navy-900">Edit</button>
                        )}
                        {s.status === 'draft' && (
                          <button type="button" onClick={() => handleStatusChange(s.id, 'published')}
                            className="text-[10px] font-semibold text-teal-700 hover:text-teal-800">Publish</button>
                        )}
                        {s.status === 'published' && (
                          <button type="button" onClick={() => handleStatusChange(s.id, 'draft')}
                            className="text-[10px] text-black hover:text-slate-700">Unpublish</button>
                        )}
                        {s.status !== 'archived' && (
                          <button type="button" onClick={() => handleArchive(s.id)}
                            className="text-[10px] text-black hover:text-red-500">Archive</button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}

          {schedules.length === 0 && formMode === null && !loadError && (
            <p className="text-[12px] text-black">No schedules yet.</p>
          )}

          {formMode === null && (
            <div className="flex gap-2 pt-1">
              <button type="button" onClick={openNew}
                className="rounded-lg border border-teal-200 bg-white px-2 py-1 text-[11px] font-semibold text-teal-700 transition-colors hover:bg-teal-50">
                + Add schedule
              </button>
              <button type="button" onClick={handleGenerate} disabled={generating}
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-black transition-colors hover:bg-slate-50 disabled:opacity-50">
                {generating ? 'Generating…' : '⚡ Generate standard'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// resetFormFields — payment option editor helper
// ---------------------------------------------------------------------------

function resetFormFields(
  setters: {
    setName: (v: string) => void
    setDescription: (v: string) => void
    setPaymentType: (v: string) => void
    setSessionsPerWeek: (v: string) => void
    setTotalSessions: (v: string) => void
    setPricePerSession: (v: string) => void
    setOverrideTotal: (v: string) => void
    setTermStart: (v: string) => void
    setTermEnd: (v: string) => void
    setCurrency: (v: string) => void
    setBuyerNote: (v: string) => void
    setInternalNote: (v: string) => void
  },
  opt?: PaymentOption,
) {
  setters.setName(opt?.name ?? '')
  setters.setDescription(opt?.description ?? '')
  setters.setPaymentType(opt?.payment_type ?? 'one_time')
  setters.setSessionsPerWeek(opt?.sessions_per_week != null ? String(opt.sessions_per_week) : '')
  setters.setTotalSessions(opt?.total_sessions != null ? String(opt.total_sessions) : '')
  setters.setPricePerSession(opt?.price_per_session_cents != null ? String(opt.price_per_session_cents / 100) : '')
  setters.setOverrideTotal(opt?.override_total_cents != null ? String(opt.override_total_cents / 100) : '')
  setters.setTermStart(opt?.term_start_date ?? '')
  setters.setTermEnd(opt?.term_end_date ?? '')
  setters.setCurrency(opt?.currency ?? 'AUD')
  setters.setBuyerNote(opt?.buyer_note ?? '')
  setters.setInternalNote(opt?.internal_note ?? '')
}


// ---------------------------------------------------------------------------
// PaymentOptionsSection
// ---------------------------------------------------------------------------

function PaymentOptionsSection({ spaceSlug, pathwaySlug }: { spaceSlug: string; pathwaySlug: string }) {
  const [options, setOptions] = useState<PaymentOption[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  // null = no form open; 'new' = adding; <id> = editing that option
  const [formMode, setFormMode] = useState<'new' | string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Shared form state (used for both add and edit)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [paymentType, setPaymentType] = useState('one_time')
  const [sessionsPerWeek, setSessionsPerWeek] = useState('')
  const [totalSessions, setTotalSessions] = useState('')
  const [pricePerSession, setPricePerSession] = useState('')
  const [overrideTotal, setOverrideTotal] = useState('')
  const [termStart, setTermStart] = useState('')
  const [termEnd, setTermEnd] = useState('')
  const [currency, setCurrency] = useState('AUD')
  const [buyerNote, setBuyerNote] = useState('')
  const [internalNote, setInternalNote] = useState('')

  const fieldSetters = { setName, setDescription, setPaymentType, setSessionsPerWeek, setTotalSessions, setPricePerSession, setOverrideTotal, setTermStart, setTermEnd, setCurrency, setBuyerNote, setInternalNote }

  async function load() {
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options`),
        { credentials: 'include' },
      )
      if (!res.ok) { setLoadError('Could not load payment options.'); return }
      setOptions(await res.json())
    } catch { setLoadError('Could not load payment options.') }
  }

  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function openNew() {
    resetFormFields(fieldSetters)
    setFormMode('new')
    setSaveError(null)
  }

  function openEdit(opt: PaymentOption) {
    resetFormFields(fieldSetters, opt)
    setFormMode(opt.id)
    setSaveError(null)
  }

  function closeForm() {
    setFormMode(null)
    setSaveError(null)
  }

  function buildPayload() {
    const payload: Record<string, unknown> = {
      name: name.trim(),
      description: description.trim() || null,
      payment_type: paymentType,
      currency,
      buyer_note: buyerNote.trim() || null,
      internal_note: internalNote.trim() || null,
      sessions_per_week: sessionsPerWeek ? parseInt(sessionsPerWeek) : null,
      total_sessions: totalSessions ? parseInt(totalSessions) : null,
      price_per_session_cents: pricePerSession ? Math.round(parseFloat(pricePerSession) * 100) : null,
      override_total_cents: overrideTotal ? Math.round(parseFloat(overrideTotal) * 100) : null,
      term_start_date: termStart || null,
      term_end_date: termEnd || null,
    }
    return payload
  }

  async function handleCreate() {
    if (!name.trim()) { setSaveError('Name is required.'); return }
    setSaving(true); setSaveError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options`),
        { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...buildPayload(), status: 'draft' }) },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        setSaveError(typeof b.detail === 'string' ? b.detail : 'Could not create option.')
        return
      }
      await load()
      closeForm()
    } catch { setSaveError('Could not create option.') }
    finally { setSaving(false) }
  }

  async function handleUpdate(optId: string) {
    if (!name.trim()) { setSaveError('Name is required.'); return }
    setSaving(true); setSaveError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optId}`),
        { method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildPayload()) },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        setSaveError(typeof b.detail === 'string' ? b.detail : 'Could not save changes.')
        return
      }
      await load()
      closeForm()
    } catch { setSaveError('Could not save changes.') }
    finally { setSaving(false) }
  }

  async function handleStatusChange(optId: string, newStatus: string) {
    try {
      await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optId}`),
        { method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: newStatus }) },
      )
      await load()
    } catch { /* ignore */ }
  }

  async function handleArchive(optId: string) {
    if (!confirm('Archive this payment option? It will no longer appear to members.')) return
    try {
      await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/payment-options/${optId}`),
        { method: 'DELETE', credentials: 'include' },
      )
      await load()
    } catch { /* ignore */ }
  }

  const isEditing = formMode !== null && formMode !== 'new'
  const editingOptId = isEditing ? formMode : null

  function OptionForm({ optId }: { optId: string | null }) {
    return (
      <div className="rounded-xl border border-teal-200 bg-teal-50/30 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-[13px] font-semibold text-navy-900">
            {optId ? 'Edit payment option' : 'New payment option'}
          </p>
          {optId && (
            <p className="text-[11px] text-black">Changes affect future checkouts only. Existing purchases are not changed.</p>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="mb-1 block text-[12px] font-semibold text-black">Name *</label>
            <input
              type="text" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Weekly membership — 1 session per week"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400"
            />
          </div>

          <div className="sm:col-span-2">
            <label className="mb-1 block text-[12px] font-semibold text-black">Description</label>
            <input
              type="text" value={description} onChange={e => setDescription(e.target.value)} placeholder="Optional short description"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400"
            />
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-black">Payment type</label>
            <select value={paymentType} onChange={e => setPaymentType(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] outline-none focus:border-teal-400">
              <option value="one_time">One-time</option>
              <option value="term_pass">Term pass</option>
              <option value="free">Free</option>
            </select>
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-black">Currency</label>
            <select value={currency} onChange={e => setCurrency(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] outline-none focus:border-teal-400">
              <option value="AUD">AUD</option>
              <option value="USD">USD</option>
              <option value="NZD">NZD</option>
            </select>
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-black">Sessions/week</label>
            <input type="number" min="1" value={sessionsPerWeek} onChange={e => setSessionsPerWeek(e.target.value)}
              placeholder="e.g. 1"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-black">Total sessions</label>
            <input type="number" min="1" value={totalSessions} onChange={e => setTotalSessions(e.target.value)}
              placeholder="e.g. 10"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-black">Price per session ($)</label>
            <input type="number" min="0" step="0.01" value={pricePerSession} onChange={e => setPricePerSession(e.target.value)}
              placeholder="e.g. 20"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-black">Override total ($)</label>
            <input type="number" min="0" step="0.01" value={overrideTotal} onChange={e => setOverrideTotal(e.target.value)}
              placeholder="Leave blank to use calculated"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>

          {paymentType === 'term_pass' && (
            <>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">Term start</label>
                <input type="date" value={termStart} onChange={e => setTermStart(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-semibold text-black">Term end</label>
                <input type="date" value={termEnd} onChange={e => setTermEnd(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
              </div>
            </>
          )}

          <div className="sm:col-span-2">
            <label className="mb-1 block text-[12px] font-semibold text-black">Member-facing note</label>
            <input type="text" value={buyerNote} onChange={e => setBuyerNote(e.target.value)}
              placeholder="Short note shown to members at checkout"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>

          <div className="sm:col-span-2">
            <label className="mb-1 block text-[12px] font-semibold text-black">Internal note</label>
            <input type="text" value={internalNote} onChange={e => setInternalNote(e.target.value)}
              placeholder="Not shown to members"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] outline-none focus:border-teal-400" />
          </div>
        </div>

        {saveError && <p className="text-[12px] text-red-600">{saveError}</p>}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={optId ? () => handleUpdate(optId) : handleCreate}
            disabled={saving}
            className="rounded-lg px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {saving ? 'Saving…' : optId ? 'Save changes' : 'Save as draft'}
          </button>
          <button type="button" onClick={closeForm}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-[13px] font-medium text-black transition-colors hover:bg-slate-50">
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-border bg-white p-6">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[15px] font-semibold text-navy-900">Payment options</h2>
          <p className="mt-1 text-[13px] leading-relaxed text-black">
            Create tiered or term-based pricing options for this pathway.
            Published options appear on the checkout page for members to choose from.
          </p>
        </div>
        {formMode === null && (
          <button
            type="button"
            onClick={openNew}
            className="shrink-0 rounded-xl border border-teal-200 bg-teal-50 px-3 py-1.5 text-[12px] font-semibold text-teal-700 transition-colors hover:bg-teal-100"
          >
            + Add option
          </button>
        )}
      </div>

      {/* Phase A notice */}
      <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[12px] text-amber-800">
        <strong>Phase A:</strong> Booking limits are not enforced yet. Session counts are shown to members for transparency but do not restrict access.
      </div>

      {loadError && <p className="mb-3 text-[12px] text-red-600">{loadError}</p>}

      {/* New option form */}
      {formMode === 'new' && <div className="mb-4"><OptionForm optId={null} /></div>}

      {/* Existing options */}
      {options.length > 0 && (
        <div className="mb-4 space-y-3">
          {options.map(opt => (
            <div key={opt.id}>
              {editingOptId === opt.id ? (
                <OptionForm optId={opt.id} />
              ) : (
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-[14px] font-semibold text-navy-900">{opt.name}</span>
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                          opt.status === 'published' ? 'bg-teal-100 text-teal-700'
                          : opt.status === 'archived' ? 'bg-slate-200 text-slate-500'
                          : 'bg-amber-100 text-amber-700'
                        }`}>
                          {opt.status}
                        </span>
                      </div>
                      {opt.description && <p className="mt-0.5 text-[12px] text-black">{opt.description}</p>}
                      <div className="mt-2 flex flex-wrap gap-3 text-[12px] text-black">
                        <span>Type: {opt.payment_type}</span>
                        {opt.sessions_per_week != null && <span>{opt.sessions_per_week}×/week</span>}
                        {opt.total_sessions != null && <span>{opt.total_sessions} sessions</span>}
                        {opt.price_per_session_cents != null && (
                          <span>{fmtOptionPrice(opt.price_per_session_cents, opt.currency)}/session</span>
                        )}
                        {opt.term_end_date && <span>Until {formatDisplayDate(opt.term_end_date)}</span>}
                      </div>
                      <div className="mt-1 text-[13px] font-semibold text-navy-900">
                        Effective price: {fmtOptionPrice(opt.effective_price_cents, opt.currency)}
                        {opt.calculated_total_cents != null && opt.override_total_cents != null && (
                          <span className="ml-1 text-[11px] font-normal text-black">
                            (override; calculated {fmtOptionPrice(opt.calculated_total_cents, opt.currency)})
                          </span>
                        )}
                      </div>
                      {opt.internal_note && (
                        <p className="mt-1 text-[11px] italic text-black">Note: {opt.internal_note}</p>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-col gap-1.5 items-end">
                      {opt.status !== 'archived' && formMode === null && (
                        <button
                          type="button"
                          onClick={() => openEdit(opt)}
                          className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-black transition-colors hover:bg-slate-50"
                        >
                          Edit
                        </button>
                      )}
                      {opt.status === 'draft' && formMode === null && (
                        <button
                          type="button"
                          onClick={() => handleStatusChange(opt.id, 'published')}
                          className="rounded-lg border border-teal-200 bg-white px-2 py-1 text-[11px] font-semibold text-teal-700 transition-colors hover:bg-teal-50"
                        >
                          Publish
                        </button>
                      )}
                      {opt.status === 'published' && formMode === null && (
                        <button
                          type="button"
                          onClick={() => handleStatusChange(opt.id, 'draft')}
                          className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-black transition-colors hover:bg-slate-50"
                        >
                          Unpublish
                        </button>
                      )}
                      {opt.status !== 'archived' && formMode === null && (
                        <button
                          type="button"
                          onClick={() => handleArchive(opt.id)}
                          className="rounded-lg px-2 py-1 text-[11px] text-black transition-colors hover:text-red-500"
                        >
                          Archive
                        </button>
                      )}
                    </div>
                  </div>
                  {/* Nested payment schedules */}
                  {opt.status !== 'archived' && (
                    <PaymentSchedulesSection
                      spaceSlug={spaceSlug}
                      pathwaySlug={pathwaySlug}
                      optionId={opt.id}
                      effectivePrice={opt.effective_price_cents}
                      currency={opt.currency}
                    />
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {options.length === 0 && formMode === null && (
        <p className="text-[13px] text-black">No payment options yet. Add one above.</p>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Default export — Pathway Settings page
// ---------------------------------------------------------------------------

interface Props {
  pathway: CreatorPathway
  spaceSlug: string
  mediaAssets: CreatorMediaAsset[]
}

/**
 * Pathway Settings page — title, description, status, access + pricing,
 * cover image, and payment options. The sections/steps working area lives
 * on the Content page.
 */
export default function PathwaySettingsClient({ pathway, spaceSlug, mediaAssets }: Props) {
  const router = useRouter()
  const [, startTransition] = useTransition()

  const [title, setTitle]               = useState(pathway.title)
  const [description, setDescription]   = useState(pathway.description ?? '')
  const [status, setStatus]             = useState<string>(pathway.status)
  const [accessType, setAccessType]     = useState<string>(pathway.access_type ?? 'free')
  const [pricingMode, setPricingMode]   = useState<string>(pathway.pricing_mode ?? 'legacy')
  const [priceDollars, setPriceDollars] = useState(centsToDisplay(pathway.price_cents))
  const [currency, setCurrency]         = useState(pathway.currency ?? 'AUD')
  const [pathwayType, setPathwayType]   = useState<'guided_experience' | 'knowledge_guide'>(
    pathway.pathway_type ?? 'guided_experience',
  )
  const [pathwayTypeSaving, setPathwayTypeSaving] = useState(false)
  const [pathwayTypeError, setPathwayTypeError]   = useState<string | null>(null)
  const [pathwayTypeSaved, setPathwayTypeSaved]   = useState(false)
  const [loading, setLoading]           = useState(false)
  const [saved, setSaved]               = useState(false)
  const [error, setError]               = useState<string | null>(null)
  const [priceError, setPriceError]     = useState<string | null>(null)

  const [unlockOptionIds, setUnlockOptionIds] = useState<string[]>([])

  const [coverUrl, setCoverUrl]             = useState<string | null>(pathway.cover_image_url ?? null)
  const [coverError, setCoverError]         = useState<string | null>(null)
  const [coverSaved, setCoverSaved]         = useState(false)

  async function handlePathwayTypeChange(next: 'guided_experience' | 'knowledge_guide') {
    if (next === pathwayType) return

    // Switching type never migrates data — StepProgress rows stay put,
    // enrolments stay valid — but the member surface changes shape.
    // A confirmation goes up when the pathway is live so an operator
    // clicking the wrong radio doesn't quietly flip the experience for
    // real members. Draft/coming-soon/archived pathways switch silently.
    if (pathway.status === 'active') {
      const goingToGuide = next === 'knowledge_guide'
      const warning = goingToGuide
        ? 'Switch this Pathway to a Knowledge Guide?\n\n'
          + 'Members will see one continuous document instead of the step-by-step '
          + 'flow. Progress and reflections are preserved but no longer displayed. '
          + 'Existing step URLs will redirect to the guide.'
        : 'Switch this Pathway to a Guided Experience?\n\n'
          + 'Members will see the step-by-step flow with progress and completion. '
          + 'Any progress recorded from the previous type will reappear.'
      if (!window.confirm(warning)) return
    }

    setPathwayTypeSaving(true)
    setPathwayTypeError(null)
    setPathwayTypeSaved(false)
    const prev = pathwayType
    setPathwayType(next)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}`),
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ pathway_type: next }),
        },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setPathwayTypeError(
          typeof body.detail === 'string' ? body.detail : 'Could not save Pathway Type.',
        )
        setPathwayType(prev)
        return
      }
      setPathwayTypeSaved(true)
      startTransition(() => router.refresh())
      setTimeout(() => setPathwayTypeSaved(false), 3000)
    } catch {
      setPathwayTypeError('Could not save Pathway Type.')
      setPathwayType(prev)
    } finally {
      setPathwayTypeSaving(false)
    }
  }

  async function handleCoverChange(next: string | null) {
    setCoverError(null)
    setCoverSaved(false)
    // Optimistic update so the preview reflects the choice immediately
    setCoverUrl(next)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}`),
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ cover_image_url: next }),
        },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setCoverError(typeof body.detail === 'string' ? body.detail : 'Could not save cover image.')
        // Revert optimistic update on failure
        setCoverUrl(pathway.cover_image_url ?? null)
        return
      }
      const data = await res.json()
      setCoverUrl(data.cover_image_url ?? null)
      setCoverSaved(true)
      startTransition(() => router.refresh())
      setTimeout(() => setCoverSaved(false), 3000)
    } catch {
      setCoverError('Could not save cover image.')
      setCoverUrl(pathway.cover_image_url ?? null)
    }
  }

  // Load existing unlock requirements on mount
  useEffect(() => {
    if (pathway.access_type !== 'included_with_offer') return
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/unlock-requirements`), { credentials: 'include' })
      .then(r => r.ok ? r.json() : [])
      .then((opts: { id: string }[]) => setUnlockOptionIds(opts.map(o => o.id)))
      .catch(() => {})
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const isPaid = accessType === 'one_time' || accessType === 'subscription'
  const needsSinglePrice = isPaid && pricingMode === 'legacy'

  function validate(): boolean {
    if (!title.trim()) { setError('Pathway title is required.'); return false }
    if (needsSinglePrice) {
      const dollars = parseFloat(priceDollars)
      if (!priceDollars.trim() || isNaN(dollars)) { setPriceError('Enter a price for this paid pathway.'); return false }
      if (dollars <= 0) { setPriceError('Price must be greater than 0.'); return false }
    }
    return true
  }

  async function handleSave() {
    setError(null)
    setPriceError(null)
    setSaved(false)
    if (!validate()) return
    const priceCents = needsSinglePrice ? Math.round(parseFloat(priceDollars) * 100) : null
    setLoading(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}`),
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            title: title.trim(),
            description: description.trim() || null,
            status,
            access_type: accessType,
            pricing_mode: pricingMode,
            price_cents: priceCents,
            currency: needsSinglePrice ? currency : 'AUD',
            billing_interval: accessType === 'subscription' ? 'month' : null,
          }),
        },
      )
      if (!res.ok) {
        let detail: string | null = null
        try { const b = await res.json(); if (typeof b.detail === 'string') detail = b.detail } catch { /* ignore */ }
        setError(detail ?? 'Could not save changes. Please try again.')
        return
      }

      // Save unlock requirements when using included_with_offer
      if (accessType === 'included_with_offer') {
        await fetch(
          apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/unlock-requirements`),
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ payment_option_ids: unlockOptionIds }),
          },
        )
      }

      setSaved(true)
      startTransition(() => { router.refresh() })
      setTimeout(() => setSaved(false), 3000)
    } catch {
      setError('Could not save changes. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">

      {/* ── 1. Essential setup — title / short description / status / Save. ── */}
      <div className="rounded-2xl border border-border bg-white p-6">
        <div className="grid gap-5 md:grid-cols-[1fr_220px]">

          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-[12px] font-semibold text-black">
                Pathway title <span className="font-normal text-black">(required)</span>
              </label>
              <input
                type="text" value={title}
                onChange={(e) => { setTitle(e.target.value); setError(null) }}
                placeholder="e.g. Slow Growth Practice"
                className={`w-full rounded-lg border px-3 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400 ${error && !title.trim() ? 'border-red-300' : 'border-slate-200'}`}
              />
            </div>

            <div>
              <label className="mb-1 block text-[12px] font-semibold text-black">
                Short description <span className="font-normal text-black">(optional)</span>
              </label>
              <input
                type="text" value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="A guided pathway for moving slowly, reflecting honestly, and building new rhythm."
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block text-[12px] font-semibold text-black">Status</label>
            <select
              value={status} onChange={(e) => setStatus(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
            >
              <option value="draft">Draft</option>
              <option value="active">Published</option>
              <option value="coming_soon">Coming soon</option>
              <option value="archived">Archived</option>
            </select>
          </div>

        </div>

        {error && <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</p>}
        {saved && (
          <p className="mt-4 rounded-lg px-3 py-2 text-[13px] font-medium" style={{ background: 'rgba(56,160,158,0.08)', color: '#38A09E' }}>
            Changes saved.
          </p>
        )}

        <div className="mt-5 flex justify-end border-t border-border pt-4">
          <button
            type="button"
            disabled={loading || !title.trim()}
            onClick={handleSave}
            className="rounded-xl px-6 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {loading ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>

      {/* ── 1b. Pathway Type — Guided Experience vs Knowledge Guide.
             One choice, saved on change. The content editor is
             identical either way — only how members experience the
             pathway differs. ── */}
      <div className="rounded-2xl border border-border bg-white p-6">
        <h2 className="mb-1 text-[14px] font-semibold text-navy-900">Pathway Type</h2>
        <p className="mb-4 text-[12.5px] text-black">
          How members experience this pathway.
        </p>

        <div className="grid gap-3 md:grid-cols-2">
          <label
            className={`flex cursor-pointer flex-col rounded-xl border p-4 transition-colors ${
              pathwayType === 'guided_experience'
                ? 'border-teal-400 bg-teal-50/40'
                : 'border-slate-200 hover:border-slate-300'
            }`}
          >
            <div className="flex items-start gap-3">
              <input
                type="radio"
                name="pathway_type"
                value="guided_experience"
                checked={pathwayType === 'guided_experience'}
                onChange={() => void handlePathwayTypeChange('guided_experience')}
                disabled={pathwayTypeSaving}
                className="mt-1 h-4 w-4 accent-teal-500"
              />
              <div>
                <span className="block text-[13.5px] font-semibold text-navy-900">
                  Guided Experience
                </span>
                <span className="mt-1 block text-[12.5px] text-black">
                  Steps in order, with progress, reflections, and next / previous
                  navigation. Best for structured journeys.
                </span>
              </div>
            </div>
          </label>

          <label
            className={`flex cursor-pointer flex-col rounded-xl border p-4 transition-colors ${
              pathwayType === 'knowledge_guide'
                ? 'border-teal-400 bg-teal-50/40'
                : 'border-slate-200 hover:border-slate-300'
            }`}
          >
            <div className="flex items-start gap-3">
              <input
                type="radio"
                name="pathway_type"
                value="knowledge_guide"
                checked={pathwayType === 'knowledge_guide'}
                onChange={() => void handlePathwayTypeChange('knowledge_guide')}
                disabled={pathwayTypeSaving}
                className="mt-1 h-4 w-4 accent-teal-500"
              />
              <div>
                <span className="block text-[13.5px] font-semibold text-navy-900">
                  Knowledge Guide
                </span>
                <span className="mt-1 block text-[12.5px] text-black">
                  One continuous document, with sections as chapters. No progress
                  or completion. Best for practical reference material.
                </span>
              </div>
            </div>
          </label>
        </div>

        {pathwayTypeError && (
          <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">
            {pathwayTypeError}
          </p>
        )}
        {pathwayTypeSaved && (
          <p
            className="mt-3 rounded-lg px-3 py-2 text-[13px] font-medium"
            style={{ background: 'rgba(56,160,158,0.08)', color: '#38A09E' }}
          >
            Pathway Type saved.
          </p>
        )}
      </div>

      {/* ── 2. Access & pricing + Pathway cover — side by side on desktop. ── */}
      <div className="grid items-start gap-6 lg:grid-cols-2">

        <div className="rounded-2xl border border-border bg-white p-5">
          <AccessPricingSection
            accessType={accessType}
            setAccessType={(v) => { setAccessType(v); setPriceError(null) }}
            pricingMode={pricingMode}
            setPricingMode={(v) => { setPricingMode(v); setPriceError(null) }}
            priceDollars={priceDollars}
            setPriceDollars={(v) => { setPriceDollars(v); setPriceError(null) }}
            currency={currency}
            setCurrency={setCurrency}
            priceError={priceError}
            spaceSlug={spaceSlug}
            unlockOptionIds={unlockOptionIds}
            setUnlockOptionIds={setUnlockOptionIds}
          />
        </div>

        <div className="rounded-2xl border border-border bg-white p-5">
          <h2 className="mb-0.5 text-[14px] font-semibold text-navy-900">Pathway cover</h2>
          <p className="mb-3 text-[12px] text-black">
            Wide image recommended (16:9). Upload, reuse from Assets, or paste an external URL.
          </p>
          <ImagePickerField
            value={coverUrl}
            onChange={handleCoverChange}
            spaceSlug={spaceSlug}
            initialAssets={mediaAssets}
          />
          {coverError && <p className="mt-2 text-[12px] text-red-600">{coverError}</p>}
          {coverSaved && <p className="mt-2 text-[12px] font-medium" style={{ color: '#38A09E' }}>Cover saved.</p>}
        </div>

      </div>

      {/* ── 3. Payment options — reference block (U1).
             Payment Option CRUD moved to Creator Studio →
             Commerce → Payment Options. This section reads back
             the Options that grant access to this Pathway so the
             Creator can navigate to them without re-authoring here.
             Legacy PaymentOptionsSection / PaymentSchedulesSection
             functions above are retained during the transition
             but no longer rendered. ── */}
      <PathwayPaymentOptionsReference spaceSlug={spaceSlug} pathwaySlug={pathway.slug} />

    </div>
  )
}
