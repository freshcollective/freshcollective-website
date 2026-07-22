'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'
import { WM_HUE } from '@/lib/wm-palette'

/**
 * Fresh Collective Plans — catalogue view.
 *
 * A calm presentation of the ways creators can build in the world.
 * Each plan card leads with what the plan *is for* (four short bullets);
 * live operational metrics (active creators, MRR) sit below a subtle
 * divider, deliberately secondary.
 *
 * Backend is unchanged. Plan capabilities and pricing come straight from
 * `/api/admin/creator-plans` — the API decides which flags apply, this
 * page decides how to present them.
 */

interface CreatorPlanRow {
  id: string
  name: string
  slug: string
  description: string | null
  monthly_price_cents: number | null
  currency: string
  transaction_fee_basis_points: number | null
  collective_limit: number | null
  is_active: boolean
  active_subscriptions: number
  created_at: string | null
  plan_type: 'subscription' | 'enterprise'
  paid_offers_enabled: boolean
  commercial_use: boolean
  is_purchasable: boolean
  // Sourced from PlanCapability on the backend — the same value the
  // enforcement path reads, so this catalogue and the limit checks
  // cannot drift.
  member_allowance_per_collective: number | null
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

// ---------------------------------------------------------------------------
// Design tokens (inherit from Members / Commerce)
// ---------------------------------------------------------------------------
const PAGE_BG      = '#FBFDFC'
const CARD_BG      = '#FFFFFF'
const CARD_BORDER  = '1px solid #E7EEF0'
const CARD_SHADOW  = '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'
const INK          = '#0C1826'
const INK_MUTED    = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER   = 'rgba(12, 24, 38, 0.42)'
const HAIRLINE     = '1px solid rgba(12, 24, 38, 0.06)'

const SERIF_ITALIC: React.CSSProperties = {
  color: INK_MUTED,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}

// Slightly darker italic used specifically for the plan card
// descriptions so they read more comfortably against the white card
// background without losing their elegant serif tone.
const SERIF_ITALIC_STRONG: React.CSSProperties = {
  color: 'rgba(12, 24, 38, 0.72)',
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}

// Tier accent — a thin top strip + matching bullet dots in each plan's
// WM hue. Assignment (per product decision):
//   Community    → deep navy   (INK — #0C1826, the same deep navy
//                               already used throughout World
//                               Management for primary text; the
//                               brighter navy blues from `WM_HUE.navy`
//                               all read as "energetic" in a top-strip
//                               context, so we go one step deeper into
//                               the same palette family)
//   Creator      → teal        (WM_HUE.teal.dot)
//   Pro          → coral       (WM_HUE.coral.dot — premium distinction)
//   Organisation → gold        (WM_HUE.gold.dot)
//
// Pro also carries a slightly thicker (4px vs 3px) strip as its
// "slightly stronger premium emphasis" cue.
type TierAccent = { colour: string; height: number }
function tierAccent(plan: CreatorPlanRow): TierAccent {
  if (plan.plan_type === 'enterprise') return { colour: WM_HUE.gold.dot, height: 3 }
  switch (plan.slug) {
    case 'community':
      return { colour: INK, height: 3 }
    case 'creator':
      return { colour: WM_HUE.teal.dot, height: 3 }
    case 'pro':
      return { colour: WM_HUE.coral.dot, height: 4 }
    default:
      // Any future subscription plan — soft neutral tint so it stays
      // visually calm until a hue is assigned.
      return { colour: 'rgba(12, 24, 38, 0.14)', height: 3 }
  }
}

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------

function fmtMoney(cents: number, currency: string): string {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(cents / 100)
}

function slugify(s: string): string {
  return s.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
}

interface PriceDisplay {
  top: string
  per: string | null
  currency: string | null
}

function priceDisplay(plan: CreatorPlanRow): PriceDisplay {
  if (plan.monthly_price_cents === null) {
    return { top: 'Talk to us', per: null, currency: null }
  }
  if (plan.monthly_price_cents === 0) {
    return { top: 'FREE', per: null, currency: null }
  }
  return {
    top: fmtMoney(plan.monthly_price_cents, plan.currency),
    per: 'per month',
    currency: plan.currency.toUpperCase(),
  }
}

/**
 * Primary bullets — four short phrases that describe what the plan is
 * *for*. Deliberately not a metric grid.
 *
 * Rules for subscription plans:
 *   1. Commercial disposition ("Commercial use" / "Non-commercial")
 *   2. Collective count ("N collective(s)")
 *   3. Non-commercial plans surface a member cap; commercial plans
 *      surface a "Paid offers" line and a transaction fee line
 *      instead. Member allowance for Community is not currently
 *      exposed by the API (`AdminCreatorPlanRow` doesn't include
 *      `member_allowance_per_collective`), so it is applied as a
 *      slug-scoped display rule pending a future backend addition.
 */
function bulletsForPlan(plan: CreatorPlanRow): string[] {
  if (plan.plan_type === 'enterprise') {
    return [
      'Tailored pricing',
      'Enterprise support',
      'Multiple creators',
      'Custom implementation',
    ]
  }
  const bullets: string[] = []
  bullets.push(plan.commercial_use ? 'Commercial use' : 'Non-commercial')
  if (plan.collective_limit !== null) {
    const noun = plan.collective_limit === 1 ? 'collective' : 'collectives'
    bullets.push(`${plan.collective_limit} ${noun}`)
  }
  // Non-commercial plans surface a per-collective member cap so the
  // ceiling reads plainly on the card. Source is the backend's
  // ``member_allowance_per_collective`` (from PlanCapability) — the
  // same value the enforcement path reads, so display and enforcement
  // cannot drift.
  if (!plan.commercial_use && plan.member_allowance_per_collective !== null) {
    bullets.push(`Up to ${plan.member_allowance_per_collective} members`)
  }
  if (plan.paid_offers_enabled) {
    bullets.push('Paid offers')
    if (plan.transaction_fee_basis_points !== null) {
      const pct = (plan.transaction_fee_basis_points / 100).toFixed(0)
      bullets.push(`${pct}% transaction fee`)
    }
  } else {
    bullets.push('No paid offers')
  }
  return bullets
}

interface LiveMetric {
  label: string
  value: string
}

function liveMetricsForPlan(plan: CreatorPlanRow): LiveMetric[] {
  if (plan.plan_type === 'enterprise') {
    // "Custom" is not a revenue value — surface the pricing model
    // itself instead so the label / value pair reads honestly.
    return [
      {
        label: 'Active organisations',
        value: String(plan.active_subscriptions),
      },
      { label: 'Pricing model', value: 'Custom' },
    ]
  }
  const mrrCents = (plan.monthly_price_cents ?? 0) * plan.active_subscriptions
  return [
    { label: 'Active creators', value: String(plan.active_subscriptions) },
    { label: 'Monthly recurring revenue', value: fmtMoney(mrrCents, plan.currency) },
  ]
}

// ---------------------------------------------------------------------------
// Plan card
// ---------------------------------------------------------------------------

function PlanCard({
  plan,
  onEdit,
}: {
  plan: CreatorPlanRow
  onEdit: (plan: CreatorPlanRow) => void
}) {
  const price = priceDisplay(plan)
  const bullets = bulletsForPlan(plan)
  const metrics = liveMetricsForPlan(plan)
  const accent = tierAccent(plan)
  // Editable only for DB-backed plans. Synthesised catalogue entries
  // (Organisation) are not in `creator_plans` and cannot be edited via
  // the plan model — the button is hidden entirely rather than routing
  // to a broken action.
  const editable = plan.plan_type !== 'enterprise' && !plan.id.startsWith('synthetic-')

  return (
    <div
      className="relative overflow-hidden rounded-2xl px-8 py-8 md:px-10 md:py-9"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      {/* Tier accent — thin top strip in the plan's hue. */}
      <span
        aria-hidden
        className="absolute inset-x-0 top-0"
        style={{ height: accent.height, background: accent.colour }}
      />

      {/* Header — plan name + price */}
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0">
          <h2 className="font-serif text-[26px] leading-tight md:text-[30px]" style={{ color: INK }}>
            {plan.name}
          </h2>
          {plan.description && (
            <p
              className="mt-2 max-w-[440px] text-[14px] leading-relaxed"
              style={SERIF_ITALIC_STRONG}
            >
              {plan.description}
            </p>
          )}
        </div>
        <div className="shrink-0 text-right">
          <p className="font-serif text-[32px] leading-none md:text-[36px]" style={{ color: INK }}>
            {price.top}
          </p>
          {(price.per || price.currency) && (
            <p className="mt-2 text-[12.5px]" style={SERIF_ITALIC}>
              {price.per}
              {price.per && price.currency && ' · '}
              {price.currency}
            </p>
          )}
        </div>
      </div>

      {/* Primary bullets — what the plan is for. Dots are intentionally
          quieter than the top-strip accent (same hue, ~65% opacity, one
          pixel smaller) so the hierarchy reads
              Plan name → Price → Description → Features
          without the markers pulling focus. */}
      <ul className="mt-7 grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
        {bullets.map((text) => (
          <li key={text} className="flex items-start gap-2.5 text-[14px]" style={{ color: INK }}>
            <span
              aria-hidden
              className="mt-[8px] inline-block h-1 w-1 shrink-0 rounded-full"
              style={{ background: accent.colour, opacity: 0.65 }}
            />
            <span>{text}</span>
          </li>
        ))}
      </ul>

      {/* Divider — operational metrics below, with Edit action on the right */}
      <div className="mt-8 pt-6" style={{ borderTop: HAIRLINE }}>
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div className="flex flex-wrap gap-x-10 gap-y-3">
            {metrics.map((m) => (
              <div key={m.label} className="min-w-0">
                <p className="text-[11.5px]" style={SERIF_ITALIC}>
                  {m.label}
                </p>
                <p className="mt-0.5 font-serif text-[18px]" style={{ color: INK }}>
                  {m.value}
                </p>
              </div>
            ))}
          </div>
          {editable && <EditPlanButton onClick={() => onEdit(plan)} />}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Add Plan modal — behaviour preserved; container softened to the WM
// surface treatment, primary action re-hued to the shared teal.
// ---------------------------------------------------------------------------

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

  const inputCls = 'w-full rounded-lg px-3 py-2 text-[13px] outline-none focus:border-teal-300'
  const inputStyle: React.CSSProperties = { background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }
  const labelCls = 'mb-1 block text-[11px] font-semibold uppercase tracking-wide'
  const labelStyle: React.CSSProperties = { color: INK_SOFTER }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-md overflow-hidden rounded-2xl"
        style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
      >
        <div className="flex items-start justify-between px-6 py-4" style={{ borderBottom: HAIRLINE }}>
          <h2 className="font-serif text-[18px]" style={{ color: INK }}>Add plan</h2>
          <button
            onClick={onClose}
            className="text-[16px] leading-none transition-opacity hover:opacity-70"
            style={{ color: INK_MUTED }}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="max-h-[70vh] overflow-y-auto px-6 py-5">
          {error && (
            <div
              className="mb-3 rounded-lg px-3 py-2 text-[12.5px]"
              style={{ background: WM_HUE.coral.bg, border: `1px solid ${WM_HUE.coral.border}`, color: WM_HUE.coral.text }}
            >
              {error}
            </div>
          )}
          <div className="space-y-3">
            <label className="block">
              <span className={labelCls} style={labelStyle}>Plan name <span style={{ color: WM_HUE.coral.text }}>*</span></span>
              <input className={inputCls} style={inputStyle} placeholder="e.g. Enterprise" value={form.name} onChange={field('name')} />
            </label>
            <label className="block">
              <span className={labelCls} style={labelStyle}>Slug <span style={{ color: WM_HUE.coral.text }}>*</span></span>
              <input className={`${inputCls} font-mono`} style={inputStyle} placeholder="e.g. enterprise" value={form.slug} onChange={field('slug')} />
              <p className="mt-0.5 text-[10.5px]" style={{ color: INK_MUTED }}>URL-safe, lowercase, hyphens only. Must be unique.</p>
            </label>
            <label className="block">
              <span className={labelCls} style={labelStyle}>Monthly price (cents AUD) <span style={{ color: WM_HUE.coral.text }}>*</span></span>
              <input
                className={inputCls} style={inputStyle}
                type="number" min="0"
                placeholder="e.g. 4900 = $49"
                value={form.monthly_price_cents}
                onChange={field('monthly_price_cents')}
              />
              {form.monthly_price_cents && !isNaN(parseInt(form.monthly_price_cents)) && (
                <p className="mt-0.5 text-[11px]" style={{ color: WM_HUE.teal.text }}>
                  = {fmtMoney(parseInt(form.monthly_price_cents), 'AUD')}/month
                </p>
              )}
            </label>
            <label className="block">
              <span className={labelCls} style={labelStyle}>Transaction fee (basis points) <span style={{ color: WM_HUE.coral.text }}>*</span></span>
              <input
                className={inputCls} style={inputStyle}
                type="number" min="0" max="10000"
                placeholder="e.g. 500 = 5%"
                value={form.transaction_fee_basis_points}
                onChange={field('transaction_fee_basis_points')}
              />
              {form.transaction_fee_basis_points && !isNaN(parseInt(form.transaction_fee_basis_points)) && (
                <p className="mt-0.5 text-[11px]" style={{ color: WM_HUE.teal.text }}>
                  = {(parseInt(form.transaction_fee_basis_points) / 100).toFixed(2)}% of member sales
                </p>
              )}
            </label>
            <label className="block">
              <span className={labelCls} style={labelStyle}>Collective limit <span style={{ color: WM_HUE.coral.text }}>*</span></span>
              <input className={inputCls} style={inputStyle} type="number" min="1" value={form.collective_limit} onChange={field('collective_limit')} />
            </label>
            <label className="block">
              <span className={labelCls} style={labelStyle}>Description</span>
              <textarea
                className={`${inputCls} resize-none`}
                style={inputStyle}
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
                className="h-4 w-4 rounded accent-teal-500"
                style={{ border: '1px solid #E7EEF0' }}
              />
              <span className="text-[13px]" style={{ color: INK }}>Active (available to new creators)</span>
            </label>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 px-6 py-4" style={{ borderTop: HAIRLINE }}>
          <button
            onClick={onClose}
            className="rounded-full px-4 py-1.5 text-[13px] transition-opacity hover:opacity-70"
            style={{ color: INK_MUTED }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-full px-5 py-1.5 text-[13px] font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              background: WM_HUE.teal.bg,
              border: `1px solid ${WM_HUE.teal.border}`,
              color: WM_HUE.teal.text,
            }}
          >
            {saving ? 'Creating…' : 'Create plan'}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * Neutral secondary action for the plan card — mirrors the "Access
 * history" button on Creator Subscriptions: white body, subtle neutral
 * border, ink text, small pencil icon, quiet hover. Deliberately does
 * not compete with the tier accent colour or the price.
 */
function EditPlanButton({ onClick }: { onClick: () => void }) {
  const [hover, setHover] = useState(false)
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors"
      style={{
        background: hover ? 'rgba(12, 24, 38, 0.03)' : '#FFFFFF',
        border: `1px solid ${hover ? 'rgba(12, 24, 38, 0.16)' : '#E7EEF0'}`,
        color: INK,
      }}
    >
      <svg
        aria-hidden
        width="12" height="12" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        style={{ color: INK_MUTED }}
      >
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
      </svg>
      Edit plan
    </button>
  )
}

// ---------------------------------------------------------------------------
// Edit Plan modal — PATCH the DB row. Behaviour: only supplied fields
// change; slug is read-only; a note surfaces that changes apply to
// creators currently on the plan.
// ---------------------------------------------------------------------------

interface EditPlanForm {
  name: string
  description: string
  monthly_price_cents: string
  transaction_fee_basis_points: string
  collective_limit: string
  is_active: boolean
}

function planToEditForm(plan: CreatorPlanRow): EditPlanForm {
  return {
    name: plan.name,
    description: plan.description ?? '',
    monthly_price_cents: String(plan.monthly_price_cents ?? 0),
    transaction_fee_basis_points: String(plan.transaction_fee_basis_points ?? 0),
    collective_limit: String(plan.collective_limit ?? 1),
    is_active: plan.is_active,
  }
}

function EditPlanModal({
  plan,
  onClose,
  onSaved,
}: {
  plan: CreatorPlanRow
  onClose: () => void
  onSaved: (plan: CreatorPlanRow) => void
}) {
  const [form, setForm] = useState<EditPlanForm>(() => planToEditForm(plan))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function field(key: keyof EditPlanForm) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((p) => ({ ...p, [key]: e.target.value }))
  }

  async function handleSave() {
    if (!form.name.trim()) { setError('Name is required.'); return }
    const priceCents = parseInt(form.monthly_price_cents, 10)
    const feeBps = parseInt(form.transaction_fee_basis_points, 10)
    const limit = parseInt(form.collective_limit, 10)
    if (isNaN(priceCents) || priceCents < 0) { setError('Monthly price must be a non-negative number of cents.'); return }
    if (isNaN(feeBps) || feeBps < 0 || feeBps > 10000) { setError('Transaction fee must be 0–10000 basis points.'); return }
    if (isNaN(limit) || limit < 1) { setError('Collective limit must be at least 1.'); return }

    setSaving(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/creator-plans/${plan.id}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name.trim(),
          description: form.description.trim() || null,
          monthly_price_cents: priceCents,
          transaction_fee_basis_points: feeBps,
          collective_limit: limit,
          is_active: form.is_active,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error((data as { detail?: string }).detail ?? `Error ${res.status}`)
      }
      const updated = await res.json() as CreatorPlanRow
      onSaved(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setSaving(false)
    }
  }

  const inputCls = 'w-full rounded-lg px-3 py-2 text-[13px] outline-none focus:border-teal-300'
  const inputStyle: React.CSSProperties = { background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }
  const labelCls = 'mb-1 block text-[11px] font-semibold uppercase tracking-wide'
  const labelStyle: React.CSSProperties = { color: INK_SOFTER }
  const impactMessage =
    plan.active_subscriptions > 0
      ? `${plan.active_subscriptions} creator${plan.active_subscriptions === 1 ? '' : 's'} currently use this plan. Any price, fee or capacity change will apply to them immediately. Existing transactions and subscription records are preserved.`
      : 'No creators are currently on this plan. Changes take effect immediately for anyone assigned in future.'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-md overflow-hidden rounded-2xl"
        style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
      >
        <div className="flex items-start justify-between px-6 py-4" style={{ borderBottom: HAIRLINE }}>
          <div>
            <h2 className="font-serif text-[18px]" style={{ color: INK }}>Edit plan</h2>
            <p className="mt-1 text-[12.5px]" style={SERIF_ITALIC}>Editing the <span style={{ fontStyle: 'normal', color: INK }}>{plan.name}</span> plan.</p>
          </div>
          <button
            onClick={onClose}
            className="text-[16px] leading-none transition-opacity hover:opacity-70"
            style={{ color: INK_MUTED }}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="max-h-[75vh] overflow-y-auto px-6 py-5">
          <div
            className="mb-4 rounded-lg px-3 py-2.5 text-[12.5px]"
            style={{ background: WM_HUE.gold.bg, border: `1px solid ${WM_HUE.gold.border}`, color: WM_HUE.gold.text }}
          >
            {impactMessage}
          </div>

          {error && (
            <div
              className="mb-3 rounded-lg px-3 py-2 text-[12.5px]"
              style={{ background: WM_HUE.coral.bg, border: `1px solid ${WM_HUE.coral.border}`, color: WM_HUE.coral.text }}
            >
              {error}
            </div>
          )}

          <div className="space-y-3">
            <div>
              <span className={labelCls} style={labelStyle}>Slug</span>
              <input
                className={`${inputCls} font-mono`}
                style={{ ...inputStyle, color: INK_MUTED }}
                value={plan.slug}
                readOnly
              />
              <p className="mt-0.5 text-[10.5px]" style={{ color: INK_MUTED }}>Slug is a stable system identifier and cannot be changed here.</p>
            </div>

            <label className="block">
              <span className={labelCls} style={labelStyle}>Plan name <span style={{ color: WM_HUE.coral.text }}>*</span></span>
              <input className={inputCls} style={inputStyle} value={form.name} onChange={field('name')} />
            </label>

            <label className="block">
              <span className={labelCls} style={labelStyle}>Monthly price (cents AUD) <span style={{ color: WM_HUE.coral.text }}>*</span></span>
              <input
                className={inputCls} style={inputStyle}
                type="number" min="0"
                value={form.monthly_price_cents}
                onChange={field('monthly_price_cents')}
              />
              {form.monthly_price_cents && !isNaN(parseInt(form.monthly_price_cents)) && (
                <p className="mt-0.5 text-[11px]" style={{ color: WM_HUE.teal.text }}>
                  = {fmtMoney(parseInt(form.monthly_price_cents), plan.currency)}/month
                </p>
              )}
            </label>

            <label className="block">
              <span className={labelCls} style={labelStyle}>Transaction fee (basis points) <span style={{ color: WM_HUE.coral.text }}>*</span></span>
              <input
                className={inputCls} style={inputStyle}
                type="number" min="0" max="10000"
                value={form.transaction_fee_basis_points}
                onChange={field('transaction_fee_basis_points')}
              />
              {form.transaction_fee_basis_points && !isNaN(parseInt(form.transaction_fee_basis_points)) && (
                <p className="mt-0.5 text-[11px]" style={{ color: WM_HUE.teal.text }}>
                  = {(parseInt(form.transaction_fee_basis_points) / 100).toFixed(2)}% of member sales
                </p>
              )}
            </label>

            <label className="block">
              <span className={labelCls} style={labelStyle}>Collective limit <span style={{ color: WM_HUE.coral.text }}>*</span></span>
              <input
                className={inputCls} style={inputStyle}
                type="number" min="1"
                value={form.collective_limit}
                onChange={field('collective_limit')}
              />
            </label>

            <label className="block">
              <span className={labelCls} style={labelStyle}>Description</span>
              <textarea
                className={`${inputCls} resize-none`}
                style={inputStyle}
                rows={2}
                value={form.description}
                onChange={field('description')}
              />
            </label>

            <label className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => setForm((p) => ({ ...p, is_active: e.target.checked }))}
                className="h-4 w-4 rounded accent-teal-500"
                style={{ border: '1px solid #E7EEF0' }}
              />
              <span className="text-[13px]" style={{ color: INK }}>Active (available to new creators)</span>
            </label>

            <div className="pt-2" style={{ borderTop: HAIRLINE }}>
              <p className="text-[11px]" style={SERIF_ITALIC}>
                Capability fields (commercial use, paid offers, member allowance, plan type) are defined at the plan-configuration layer and cannot be edited here.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 px-6 py-4" style={{ borderTop: HAIRLINE }}>
          <button
            onClick={onClose}
            className="rounded-full px-4 py-1.5 text-[13px] transition-opacity hover:opacity-70"
            style={{ color: INK_MUTED }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-full px-5 py-1.5 text-[13px] font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              background: WM_HUE.teal.bg,
              border: `1px solid ${WM_HUE.teal.border}`,
              color: WM_HUE.teal.text,
            }}
          >
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function FreshCollectivePlansPage() {
  const [plans, setPlans] = useState<CreatorPlanRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState<CreatorPlanRow | null>(null)

  useEffect(() => {
    fetch(apiUrl('/api/admin/creator-plans'), { credentials: 'include' })
      .then((r) => { if (!r.ok) throw new Error(`Error ${r.status}`); return r.json() as Promise<CreatorPlanRow[]> })
      .then(setPlans)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div style={{ background: PAGE_BG, minHeight: '100%' }}>
      {showAdd && (
        <AddPlanModal
          onClose={() => setShowAdd(false)}
          onCreated={(plan) => setPlans((prev) => [...prev, plan])}
        />
      )}
      {editing && (
        <EditPlanModal
          plan={editing}
          onClose={() => setEditing(null)}
          onSaved={(updated) => {
            setPlans((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
            setEditing(null)
          }}
        />
      )}

      <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
        <header className="mb-10 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: INK }}>
              Fresh Collective Plans
            </h1>
            <p className="mt-3 max-w-[620px] text-[15px] leading-relaxed" style={SERIF_ITALIC}>
              The ways creators can build in Fresh Collective.
            </p>
          </div>
          <button
            onClick={() => setShowAdd(true)}
            className="shrink-0 inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-[13px] font-semibold transition-opacity hover:opacity-90"
            style={{
              background: WM_HUE.teal.bg,
              border: `1px solid ${WM_HUE.teal.border}`,
              color: WM_HUE.teal.text,
            }}
          >
            <svg
              aria-hidden
              width="12" height="12" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
            >
              <path d="M12 5v14" />
              <path d="M5 12h14" />
            </svg>
            Add plan
          </button>
        </header>

        {loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState message={error} />
        ) : plans.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="space-y-5">
            {plans.map((plan) => (
              <PlanCard key={plan.id} plan={plan} onEdit={setEditing} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function LoadingState() {
  return (
    <div
      className="flex items-center gap-3 rounded-2xl px-6 py-8 text-[13.5px]"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW, color: INK_MUTED }}
    >
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      <span style={SERIF_ITALIC}>Reading the plan catalogue…</span>
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  return (
    <div
      className="rounded-2xl px-6 py-6 text-[13.5px]"
      style={{ background: WM_HUE.coral.bg, border: `1px solid ${WM_HUE.coral.border}` }}
    >
      <p className="font-serif text-[16px]" style={{ color: WM_HUE.coral.text }}>
        Something went wrong reading the plan catalogue.
      </p>
      <p className="mt-1 text-[13px]" style={{ ...SERIF_ITALIC, color: 'rgba(138, 58, 51, 0.72)' }}>
        {message}
      </p>
    </div>
  )
}

function EmptyState() {
  return (
    <div
      className="rounded-2xl px-10 py-16 text-center"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <p className="font-serif text-[20px]" style={{ color: INK }}>No plans in the catalogue yet.</p>
    </div>
  )
}
