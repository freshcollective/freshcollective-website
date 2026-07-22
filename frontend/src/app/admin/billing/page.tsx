'use client'

import { useEffect, useMemo, useState } from 'react'
import { apiUrl } from '@/lib/api'
import { WM_HUE, type WMHue } from '@/lib/wm-palette'

// ---------------------------------------------------------------------------
// Types — match the extended AdminCreatorSubscriptionRow + CreatorBillingRow.
// ---------------------------------------------------------------------------

interface CreatorBillingRow {
  user_id: string
  name: string | null
  email: string
  current_plan_name: string
  current_plan_slug: string
  monthly_price_cents: number
  currency: string
  transaction_fee_basis_points: number
  // `null` means unlimited (Platform Owner). Sourced from the same
  // `effective_collective_allowance` helper the guard uses, so the
  // number rendered here is the number the guard actually enforces.
  collective_limit: number | null
  subscription_status: string
  collectives_used: number
  pathways_used: number
  joined_at: string
  // True when this row belongs to the platform owner. Owner access
  // is inherent to the account and does not depend on any
  // CreatorSubscription record — the historical row is preserved
  // unchanged but the effective-access cells (Access / Status /
  // Ends) render as owner access, not as the historical cancelled
  // subscription's state.
  is_platform_owner: boolean
}

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
  source: string                  // 'stripe_paid' | 'manual_grant'
  grant_reason: string | null
  granted_by_user_id: string | null
  grant_note: string | null
  revoked_at: string | null
  stripe_subscription_id: string | null
  stripe_customer_id: string | null
  created_at: string
  updated_at: string
}

interface CreatorPlanRow {
  id: string
  slug: string
  name: string
  monthly_price_cents: number
  currency: string
  transaction_fee_basis_points: number
  collective_limit: number
  is_active: boolean
}

interface CreatorRow extends CreatorBillingRow {
  subscription: CreatorSubscriptionRow | null   // most recent by created_at
}

interface GrantResult {
  subscription_id: string
  source: string
  status: string
  reason: string
  note: string | null
  starts_at: string
  ends_at: string | null
  plan_name: string
  plan_slug: string
  creator_name: string | null
  creator_email: string
  reactivated: boolean
}

type ReasonKey =
  | 'comp' | 'beta' | 'migration' | 'correction'
  | 'temporary' | 'replacement' | 'internal' | 'other'

type DurationKey = '1_month' | '3_months' | '6_months' | '12_months' | 'indefinite'

const REASON_OPTIONS: { value: ReasonKey; label: string; hint?: string }[] = [
  { value: 'comp',        label: 'Complimentary plan',   hint: 'A gift on behalf of the platform' },
  { value: 'beta',        label: 'Beta or testing access' },
  { value: 'migration',   label: 'Migration',            hint: 'Migrated in from another system' },
  { value: 'correction',  label: 'Subscription correction' },
  { value: 'temporary',   label: 'Temporary access' },
  { value: 'replacement', label: 'Replacement access',   hint: 'After a refund or lost access' },
  { value: 'internal',    label: 'Internal use',         hint: 'Team or system testing' },
  { value: 'other',       label: 'Other',                hint: 'Note required' },
]

const DURATION_OPTIONS: { value: DurationKey; label: string }[] = [
  { value: '1_month',    label: '1 month' },
  { value: '3_months',   label: '3 months' },
  { value: '6_months',   label: '6 months' },
  { value: '12_months',  label: '12 months' },
  { value: 'indefinite', label: 'Indefinite' },
]

// ---------------------------------------------------------------------------
// Design tokens
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

// ---------------------------------------------------------------------------
// Source / status hue mapping — WM colour hierarchy
// ---------------------------------------------------------------------------

/**
 * Access badge — the single primary pill shown per creator row.
 *
 * Owner is checked FIRST: the platform owner's effective access is
 * inherent to their account and does not depend on any subscription
 * record, so a historical cancelled sub must never surface as their
 * current-access badge.
 *
 * gold  = Owner access (platform owner) or Manual grant (WM-issued)
 * teal  = Paid subscription (Stripe-backed, active)
 * navy  = Trial (Stripe-backed, status=trialing)
 * coral = Past due / unpaid
 * neutral = Expired / cancelled / no plan
 */
function accessBadge(row: CreatorRow): { hue: WMHue | 'neutral'; label: string } {
  if (row.is_platform_owner) return { hue: 'gold', label: 'Owner access' }
  const sub = row.subscription
  if (!sub) return { hue: 'neutral', label: 'No plan' }
  const status = sub.status.toLowerCase()
  if (status === 'past_due' || status === 'unpaid') {
    return { hue: 'coral', label: status === 'past_due' ? 'Past due' : 'Unpaid' }
  }
  if (status === 'cancelled') return { hue: 'neutral', label: 'Expired' }
  if (status === 'trialing') return { hue: 'navy', label: 'Trial' }
  // status is active from here
  if (sub.source === 'stripe_paid') return { hue: 'teal', label: 'Paid subscription' }
  if (sub.source === 'manual_grant') return { hue: 'gold', label: 'Manual grant' }
  return { hue: 'neutral', label: status }
}

const REASON_LABELS: Record<string, string> = {
  comp: 'Complimentary plan',
  beta: 'Beta or testing access',
  migration: 'Migration',
  correction: 'Subscription correction',
  temporary: 'Temporary access',
  replacement: 'Replacement access',
  internal: 'Internal use',
  other: 'Other',
}

// ---------------------------------------------------------------------------

type ModalState =
  | { kind: 'none' }
  | { kind: 'grant' }
  | { kind: 'extend'; row: CreatorRow }
  | { kind: 'revoke'; row: CreatorRow }
  | { kind: 'history'; row: CreatorRow }

export default function CreatorSubscriptionsPage() {
  const [billing, setBilling] = useState<CreatorBillingRow[]>([])
  const [subs, setSubs] = useState<CreatorSubscriptionRow[]>([])
  const [plans, setPlans] = useState<CreatorPlanRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modal, setModal] = useState<ModalState>({ kind: 'none' })

  function reload() {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      fetch(apiUrl('/api/admin/creator-billing'), { credentials: 'include' })
        .then((r) => { if (!r.ok) throw new Error(`Billing: ${r.status}`); return r.json() as Promise<CreatorBillingRow[]> }),
      fetch(apiUrl('/api/admin/creator-subscriptions'), { credentials: 'include' })
        .then((r) => { if (!r.ok) throw new Error(`Subscriptions: ${r.status}`); return r.json() as Promise<CreatorSubscriptionRow[]> }),
      fetch(apiUrl('/api/admin/creator-plans'), { credentials: 'include' })
        .then((r) => { if (!r.ok) throw new Error(`Plans: ${r.status}`); return r.json() as Promise<CreatorPlanRow[]> }),
    ])
      .then(([b, s, p]) => { if (!cancelled) { setBilling(b); setSubs(s); setPlans(p) } })
      .catch((e: Error) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }
  useEffect(() => reload(), [])

  // Merge subscription info onto each billing row — take the most recent
  // subscription per user (they may have historical cancelled rows).
  const rows: CreatorRow[] = useMemo(() => {
    const latestSubByUser = new Map<string, CreatorSubscriptionRow>()
    for (const s of subs) {
      const existing = latestSubByUser.get(s.user_id)
      if (!existing || Date.parse(s.created_at) > Date.parse(existing.created_at)) {
        latestSubByUser.set(s.user_id, s)
      }
    }
    return billing.map((b) => ({ ...b, subscription: latestSubByUser.get(b.user_id) ?? null }))
  }, [billing, subs])

  return (
    <div style={{ background: PAGE_BG, minHeight: '100%' }}>
      {modal.kind === 'grant' && (
        <GrantPlanAccessModal
          plans={plans.filter((p) => p.is_active)}
          creators={rows}
          onClose={() => setModal({ kind: 'none' })}
          onSuccess={() => { setModal({ kind: 'none' }); reload() }}
        />
      )}
      {modal.kind === 'extend' && modal.row.subscription && (
        <ExtendModal
          row={modal.row}
          onClose={() => setModal({ kind: 'none' })}
          onSuccess={() => { setModal({ kind: 'none' }); reload() }}
        />
      )}
      {modal.kind === 'revoke' && modal.row.subscription && (
        <RevokeModal
          row={modal.row}
          onClose={() => setModal({ kind: 'none' })}
          onSuccess={() => { setModal({ kind: 'none' }); reload() }}
        />
      )}
      {modal.kind === 'history' && modal.row.subscription && (
        <HistoryModal
          subscriptionId={modal.row.subscription.id}
          creator={modal.row}
          onClose={() => setModal({ kind: 'none' })}
        />
      )}

      <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
        <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: INK }}>
              Creator Subscriptions
            </h1>
            <p className="mt-3 max-w-[620px] text-[15px] leading-relaxed" style={SERIF_ITALIC}>
              Who has access to which creator plan.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setModal({ kind: 'grant' })}
            className="shrink-0 inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-[13px] font-semibold transition-opacity hover:opacity-90"
            style={{
              background: WM_HUE.teal.bg,
              border: `1px solid ${WM_HUE.teal.border}`,
              color: WM_HUE.teal.text,
            }}
          >
            <svg aria-hidden width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14" /><path d="M5 12h14" />
            </svg>
            Grant plan access
          </button>
        </header>

        {loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState message={error} />
        ) : rows.length === 0 ? (
          <EmptyState />
        ) : (
          <SubscriptionsTable rows={rows} onAction={setModal} />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

function SubscriptionsTable({
  rows,
  onAction,
}: {
  rows: CreatorRow[]
  onAction: (m: ModalState) => void
}) {
  return (
    <div
      className="overflow-hidden rounded-2xl"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full text-left">
          <thead>
            <tr>
              {['Creator', 'Plan', 'Access', 'Status', 'Starts', 'Ends', 'Usage', ''].map((h) => (
                <th
                  key={h}
                  className="px-4 py-3.5 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
                  style={{ color: INK_SOFTER, borderBottom: HAIRLINE }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <SubscriptionRow key={row.user_id} row={row} first={i === 0} onAction={onAction} />
            ))}
          </tbody>
        </table>
      </div>
      <div className="lg:hidden">
        {rows.map((row, i) => (
          <SubscriptionMobileRow key={row.user_id} row={row} first={i === 0} onAction={onAction} />
        ))}
      </div>
    </div>
  )
}

function SubscriptionRow({
  row,
  first,
  onAction,
}: {
  row: CreatorRow
  first: boolean
  onAction: (m: ModalState) => void
}) {
  const sub = row.subscription
  const badge = accessBadge(row)
  // Owner rows short-circuit the sub-record cells: platform-owner access
  // is inherent to the account, not derived from a historical
  // subscription row (which may legitimately be cancelled). Non-owner
  // rows continue to render whatever is on their sub.
  const statusText = row.is_platform_owner
    ? 'Active'
    : sub ? sub.status.replace(/_/g, ' ') : '—'
  const startsText = row.is_platform_owner
    ? '—'
    : sub ? fmtDate(sub.starts_at) : '—'
  const endsText = row.is_platform_owner
    ? 'Ongoing'
    : sub ? (sub.ends_at ? fmtDate(sub.ends_at) : 'Ongoing') : '—'
  return (
    <tr
      className="transition-colors hover:bg-slate-50/60"
      style={first ? undefined : { borderTop: HAIRLINE }}
    >
      <td className="px-4 py-3.5 align-top">
        <div className="font-serif text-[15px] leading-tight" style={{ color: INK }}>
          {row.name ?? '—'}
        </div>
        <div className="mt-0.5 text-[12px]" style={{ color: INK_MUTED }}>{row.email}</div>
      </td>
      <td className="px-4 py-3.5 align-top text-[13px]" style={{ color: INK }}>
        {row.current_plan_name}
      </td>
      <td className="px-4 py-3.5 align-top">
        <AccessPill hue={badge.hue}>{badge.label}</AccessPill>
      </td>
      <td className="px-4 py-3.5 align-top text-[13px]" style={{ color: INK_MUTED }}>
        {statusText}
      </td>
      <td className="px-4 py-3.5 align-top text-[12.5px] whitespace-nowrap" style={{ color: INK_MUTED }}>
        {startsText}
      </td>
      <td className="px-4 py-3.5 align-top text-[12.5px] whitespace-nowrap" style={{ color: INK_MUTED }}>
        {endsText}
      </td>
      <td className="px-4 py-3.5 align-top text-[12.5px] tabular-nums" style={{ color: INK }}>
        {formatUsage(row.collectives_used, row.collective_limit)}
      </td>
      <td className="px-4 py-3.5 align-top">
        <RowActions row={row} onAction={onAction} />
      </td>
    </tr>
  )
}

function SubscriptionMobileRow({
  row,
  first,
  onAction,
}: {
  row: CreatorRow
  first: boolean
  onAction: (m: ModalState) => void
}) {
  const sub = row.subscription
  const badge = accessBadge(row)
  return (
    <div className="px-5 py-4" style={first ? undefined : { borderTop: HAIRLINE }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-serif text-[15px] leading-tight" style={{ color: INK }}>
            {row.name ?? '—'}
          </div>
          <div className="mt-0.5 truncate text-[12px]" style={{ color: INK_MUTED }}>{row.email}</div>
        </div>
        <AccessPill hue={badge.hue}>{badge.label}</AccessPill>
      </div>
      <div className="mt-2 text-[13px]" style={{ color: INK }}>{row.current_plan_name}</div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px]" style={{ color: INK_MUTED }}>
        {row.is_platform_owner ? (
          <>
            <span>Ongoing</span>
            <span aria-hidden style={{ color: INK_SOFTER }}>·</span>
          </>
        ) : sub ? (
          <>
            <span>Starts {fmtDate(sub.starts_at)}</span>
            <span aria-hidden style={{ color: INK_SOFTER }}>·</span>
            <span>{sub.ends_at ? `Ends ${fmtDate(sub.ends_at)}` : 'Ongoing'}</span>
            <span aria-hidden style={{ color: INK_SOFTER }}>·</span>
          </>
        ) : null}
        <span>{formatUsage(row.collectives_used, row.collective_limit)}</span>
      </div>
      <div className="mt-2"><RowActions row={row} onAction={onAction} /></div>
    </div>
  )
}

/** Row actions — deliberately Stripe-safe. Only manual grants get
 *  Extend / Revoke. Paid subscriptions get no admin actions per Stage 4
 *  scope. Everyone can view history. */
function RowActions({
  row, onAction,
}: {
  row: CreatorRow
  onAction: (m: ModalState) => void
}) {
  const sub = row.subscription
  const isManual = sub?.source === 'manual_grant'
  const isActive = sub?.status === 'active' || sub?.status === 'trialing'
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {sub && (
        <AccessHistoryButton onClick={() => onAction({ kind: 'history', row })} />
      )}
      {isManual && isActive && (
        <>
          <button
            type="button"
            onClick={() => onAction({ kind: 'extend', row })}
            className="rounded-full px-2.5 py-1 text-[11.5px] font-medium transition-opacity hover:opacity-90"
            style={{ background: WM_HUE.teal.bg, border: `1px solid ${WM_HUE.teal.border}`, color: WM_HUE.teal.text }}
          >
            Extend
          </button>
          <button
            type="button"
            onClick={() => onAction({ kind: 'revoke', row })}
            className="rounded-full px-2.5 py-1 text-[11.5px] font-medium transition-opacity hover:opacity-90"
            style={{ background: WM_HUE.coral.bg, border: `1px solid ${WM_HUE.coral.border}`, color: WM_HUE.coral.text }}
          >
            Revoke
          </button>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pill + small components
// ---------------------------------------------------------------------------

/**
 * Row action for viewing plan-access history. Soft-navy pill per the WM
 * hierarchy — informational, not attention-seeking. Uses `rounded-lg`
 * rather than `rounded-full` so the label reads as a clear action
 * instead of getting squeezed into a circle when it wraps.
 */
function AccessHistoryButton({ onClick }: { onClick: () => void }) {
  const [hover, setHover] = useState(false)
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="inline-flex w-fit items-center whitespace-nowrap rounded-lg px-3 py-1 text-[11.5px] font-medium transition-colors"
      style={{
        background: hover ? 'rgba(56, 116, 180, 0.18)' : WM_HUE.navy.bg,
        border: `1px solid ${WM_HUE.navy.border}`,
        color: WM_HUE.navy.text,
      }}
    >
      Access history
    </button>
  )
}

function AccessPill({ hue, children }: { hue: WMHue | 'neutral'; children: React.ReactNode }) {
  const style: React.CSSProperties =
    hue === 'neutral'
      ? { background: '#F1F3F5', border: '1px solid rgba(12, 24, 38, 0.14)', color: INK_MUTED }
      : { background: WM_HUE[hue].bg, border: `1px solid ${WM_HUE[hue].border}`, color: WM_HUE[hue].text }
  return (
    <span
      className="inline-flex w-fit items-center whitespace-nowrap rounded-full px-2 py-[1px] text-[9.5px] font-semibold uppercase tracking-[0.06em]"
      style={style}
    >
      {children}
    </span>
  )
}

function LoadingState() {
  return (
    <div
      className="flex items-center gap-3 rounded-2xl px-6 py-8 text-[13.5px]"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW, color: INK_MUTED }}
    >
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      <span style={SERIF_ITALIC}>Reading the subscription roster…</span>
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
        Something went wrong reading subscriptions.
      </p>
      <p className="mt-1 text-[13px]" style={{ ...SERIF_ITALIC, color: 'rgba(138, 58, 51, 0.72)' }}>{message}</p>
    </div>
  )
}

function EmptyState() {
  return (
    <div
      className="rounded-2xl px-10 py-16 text-center"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <p className="font-serif text-[20px]" style={{ color: INK }}>No creators here yet.</p>
      <p className="mt-2 text-[13px]" style={SERIF_ITALIC}>Creators will appear once anyone joins with a paid plan or receives a manual grant.</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------

function ModalShell({
  title, subtitle, onClose, children,
}: {
  title: string
  subtitle?: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-2xl"
        style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
      >
        <div className="flex items-start justify-between px-6 py-4" style={{ borderBottom: HAIRLINE }}>
          <div>
            <h2 className="font-serif text-[18px]" style={{ color: INK }}>{title}</h2>
            {subtitle && <p className="mt-1 text-[12.5px]" style={SERIF_ITALIC}>{subtitle}</p>}
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
        {children}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Grant plan access modal
// ---------------------------------------------------------------------------

function GrantPlanAccessModal({
  plans, creators, onClose, onSuccess,
}: {
  plans: CreatorPlanRow[]
  creators: CreatorRow[]
  onClose: () => void
  onSuccess: () => void
}) {
  const [creatorId, setCreatorId] = useState('')
  const [planSlug, setPlanSlug] = useState('')
  const [reason, setReason] = useState<ReasonKey>('comp')
  const [duration, setDuration] = useState<DurationKey>('3_months')
  const [note, setNote] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [conflictHint, setConflictHint] = useState<string | null>(null)
  const [result, setResult] = useState<GrantResult | null>(null)

  const noteRequired = reason === 'other'
  const trimmedNote = note.trim()
  const submitDisabled =
    !creatorId || !planSlug || submitting ||
    (noteRequired && trimmedNote.length === 0)

  async function handleSubmit() {
    if (submitDisabled) return
    setSubmitting(true); setSubmitError(null); setConflictHint(null)
    try {
      const res = await fetch(apiUrl('/api/admin/creator-subscriptions/grant'), {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          creator_user_id: creatorId,
          plan_slug: planSlug,
          reason, note: trimmedNote || null,
          duration,
        }),
      })
      if (res.status === 409) {
        const data = await res.json().catch(() => ({}))
        setConflictHint((data as { detail?: string }).detail ?? 'Conflicts with existing plan access.')
        return
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error((data as { detail?: string }).detail ?? `Error ${res.status}`)
      }
      const data = await res.json() as GrantResult
      setResult(data)
    } catch (e) {
      setSubmitError((e as Error).message)
    } finally { setSubmitting(false) }
  }

  if (result) {
    return (
      <ModalShell title={result.reactivated ? 'Plan access restored' : 'Plan access granted'} onClose={onClose}>
        <div className="px-6 py-6 text-center">
          <div
            className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
            style={{ background: WM_HUE.teal.bg }}
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={WM_HUE.teal.text} strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <p className="text-[14px]" style={{ color: INK }}>
            {result.creator_name ?? result.creator_email} now has the{' '}
            <span style={{ fontStyle: 'italic' }}>{result.plan_name}</span> plan.
          </p>
          <p className="mt-1 text-[13px]" style={SERIF_ITALIC}>
            {result.ends_at ? `Until ${fmtDate(result.ends_at)}` : 'Ongoing access'} · {REASON_LABELS[result.reason] ?? result.reason}
          </p>
          <button
            onClick={() => { onSuccess() }}
            className="mt-6 rounded-full px-6 py-2 text-[13px] font-semibold transition-opacity hover:opacity-90"
            style={{
              background: WM_HUE.teal.bg,
              border: `1px solid ${WM_HUE.teal.border}`,
              color: WM_HUE.teal.text,
            }}
          >
            Done
          </button>
        </div>
      </ModalShell>
    )
  }

  return (
    <ModalShell
      title="Grant plan access"
      subtitle="Provide plan access without recording a payment or creating subscription revenue."
      onClose={onClose}
    >
      <div className="max-h-[75vh] space-y-4 overflow-y-auto px-6 py-5">
        {/* Creator */}
        <div>
          <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
            Creator
          </label>
          <select
            className="w-full rounded-lg px-3 py-2 text-[14px] outline-none focus:border-teal-300"
            style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            value={creatorId}
            onChange={(e) => { setCreatorId(e.target.value); setConflictHint(null) }}
          >
            <option value="">Select a creator…</option>
            {creators.map((c) => (
              <option key={c.user_id} value={c.user_id}>
                {c.name ? `${c.name} (${c.email})` : c.email}
              </option>
            ))}
          </select>
        </div>

        {/* Plan */}
        <div>
          <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
            Plan
          </label>
          <select
            className="w-full rounded-lg px-3 py-2 text-[14px] outline-none focus:border-teal-300"
            style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            value={planSlug}
            onChange={(e) => { setPlanSlug(e.target.value); setConflictHint(null) }}
          >
            <option value="">Select a plan…</option>
            {plans.map((p) => (
              <option key={p.slug} value={p.slug}>{p.name}</option>
            ))}
          </select>
        </div>

        {/* Reason */}
        <div>
          <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
            Reason
          </label>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {REASON_OPTIONS.map((opt) => {
              const active = reason === opt.value
              return (
                <label
                  key={opt.value}
                  className="flex cursor-pointer items-start gap-2 rounded-xl px-3 py-2 transition-colors"
                  style={{
                    background: active ? WM_HUE.teal.bg : '#FFFFFF',
                    border: `1px solid ${active ? WM_HUE.teal.border : '#E7EEF0'}`,
                  }}
                >
                  <input
                    type="radio" name="grant-reason"
                    checked={active}
                    onChange={() => setReason(opt.value)}
                    className="mt-0.5 accent-teal-500"
                  />
                  <span>
                    <span className="block text-[12.5px] font-semibold" style={{ color: active ? WM_HUE.teal.text : INK }}>
                      {opt.label}
                    </span>
                    {opt.hint && (
                      <span className="mt-0.5 block text-[11px]" style={SERIF_ITALIC}>{opt.hint}</span>
                    )}
                  </span>
                </label>
              )
            })}
          </div>
        </div>

        {/* Duration */}
        <div>
          <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
            Duration
          </label>
          <div className="flex flex-wrap gap-1.5">
            {DURATION_OPTIONS.map((opt) => {
              const active = duration === opt.value
              const isIndefinite = opt.value === 'indefinite'
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setDuration(opt.value)}
                  className="rounded-full px-3 py-1.5 text-[12px] font-medium transition-colors"
                  style={{
                    background: active
                      ? (isIndefinite ? WM_HUE.gold.bg : WM_HUE.teal.bg)
                      : '#FFFFFF',
                    border: `1px solid ${active
                      ? (isIndefinite ? WM_HUE.gold.border : WM_HUE.teal.border)
                      : '#E7EEF0'}`,
                    color: active
                      ? (isIndefinite ? WM_HUE.gold.text : WM_HUE.teal.text)
                      : INK_MUTED,
                  }}
                >
                  {opt.label}
                </button>
              )
            })}
          </div>
          {duration === 'indefinite' && (
            <p className="mt-1.5 text-[11.5px]" style={SERIF_ITALIC}>
              Indefinite grants never expire on their own — revoke explicitly to end access.
            </p>
          )}
        </div>

        {/* Note */}
        <div>
          <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
            Internal note {noteRequired
              ? <span className="font-normal normal-case" style={{ color: WM_HUE.coral.text }}>(required)</span>
              : <span className="font-normal normal-case" style={{ color: INK_MUTED }}>(optional — never shared with the creator)</span>}
          </label>
          <input
            type="text"
            className="w-full rounded-lg px-3 py-2 text-[14px] outline-none focus:border-teal-300"
            style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            placeholder={noteRequired ? 'Explain the reason' : 'Context for the audit trail'}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>

        {conflictHint && (
          <div
            className="rounded-lg px-4 py-3 text-[13px]"
            style={{ background: WM_HUE.gold.bg, border: `1px solid ${WM_HUE.gold.border}`, color: WM_HUE.gold.text }}
          >
            {conflictHint}
          </div>
        )}
        {submitError && (
          <div
            className="rounded-lg px-4 py-3 text-[13px]"
            style={{ background: WM_HUE.coral.bg, border: `1px solid ${WM_HUE.coral.border}`, color: WM_HUE.coral.text }}
          >
            {submitError}
          </div>
        )}

        <div className="flex items-center justify-end gap-3 pt-3" style={{ borderTop: HAIRLINE }}>
          <button
            onClick={onClose}
            className="rounded-full px-4 py-1.5 text-[13px] transition-opacity hover:opacity-70"
            style={{ color: INK_MUTED }}
          >
            Cancel
          </button>
          <button
            disabled={submitDisabled}
            onClick={handleSubmit}
            className="rounded-full px-5 py-1.5 text-[13px] font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              background: WM_HUE.teal.bg,
              border: `1px solid ${WM_HUE.teal.border}`,
              color: WM_HUE.teal.text,
            }}
          >
            {submitting ? 'Granting…' : 'Grant access'}
          </button>
        </div>
      </div>
    </ModalShell>
  )
}

// ---------------------------------------------------------------------------
// Extend modal
// ---------------------------------------------------------------------------

function ExtendModal({
  row, onClose, onSuccess,
}: {
  row: CreatorRow
  onClose: () => void
  onSuccess: () => void
}) {
  const sub = row.subscription!
  const [duration, setDuration] = useState<DurationKey>('3_months')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  async function handleSubmit() {
    setSubmitting(true); setSubmitError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/creator-subscriptions/${sub.id}/extend`), {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ duration, note: note.trim() || null }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error((data as { detail?: string }).detail ?? `Error ${res.status}`)
      }
      onSuccess()
    } catch (e) {
      setSubmitError((e as Error).message)
    } finally { setSubmitting(false) }
  }

  return (
    <ModalShell
      title="Extend plan access"
      subtitle={`Extending ${row.name ?? row.email}'s ${sub.plan_name} grant.`}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-5">
        <div>
          <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
            New duration (from current start date)
          </label>
          <div className="flex flex-wrap gap-1.5">
            {DURATION_OPTIONS.map((opt) => {
              const active = duration === opt.value
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setDuration(opt.value)}
                  className="rounded-full px-3 py-1.5 text-[12px] font-medium transition-colors"
                  style={{
                    background: active ? WM_HUE.teal.bg : '#FFFFFF',
                    border: `1px solid ${active ? WM_HUE.teal.border : '#E7EEF0'}`,
                    color: active ? WM_HUE.teal.text : INK_MUTED,
                  }}
                >
                  {opt.label}
                </button>
              )
            })}
          </div>
        </div>
        <div>
          <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
            Internal note <span className="font-normal normal-case" style={{ color: INK_MUTED }}>(optional)</span>
          </label>
          <input
            type="text"
            className="w-full rounded-lg px-3 py-2 text-[14px] outline-none focus:border-teal-300"
            style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            placeholder="Why the extension?"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        {submitError && (
          <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: WM_HUE.coral.bg, border: `1px solid ${WM_HUE.coral.border}`, color: WM_HUE.coral.text }}>
            {submitError}
          </div>
        )}
        <div className="flex items-center justify-end gap-3 pt-3" style={{ borderTop: HAIRLINE }}>
          <button
            onClick={onClose}
            className="rounded-full px-4 py-1.5 text-[13px] transition-opacity hover:opacity-70"
            style={{ color: INK_MUTED }}
          >Cancel</button>
          <button
            disabled={submitting}
            onClick={handleSubmit}
            className="rounded-full px-5 py-1.5 text-[13px] font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            style={{ background: WM_HUE.teal.bg, border: `1px solid ${WM_HUE.teal.border}`, color: WM_HUE.teal.text }}
          >
            {submitting ? 'Extending…' : 'Extend'}
          </button>
        </div>
      </div>
    </ModalShell>
  )
}

// ---------------------------------------------------------------------------
// Revoke modal
// ---------------------------------------------------------------------------

function RevokeModal({
  row, onClose, onSuccess,
}: {
  row: CreatorRow
  onClose: () => void
  onSuccess: () => void
}) {
  const sub = row.subscription!
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  async function handleSubmit() {
    setSubmitting(true); setSubmitError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/creator-subscriptions/${sub.id}/revoke`), {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason.trim() || null, note: note.trim() || null }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error((data as { detail?: string }).detail ?? `Error ${res.status}`)
      }
      onSuccess()
    } catch (e) {
      setSubmitError((e as Error).message)
    } finally { setSubmitting(false) }
  }

  return (
    <ModalShell
      title="Revoke plan access"
      subtitle={`Revoking ${row.name ?? row.email}'s ${sub.plan_name} grant.`}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-5">
        <p className="text-[13px]" style={{ color: INK_MUTED }}>
          Revoking will end this grant now and set its status to <em>Cancelled</em>. The grant history remains recorded.
        </p>
        <div>
          <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
            Reason
          </label>
          <input
            type="text"
            className="w-full rounded-lg px-3 py-2 text-[14px] outline-none focus:border-teal-300"
            style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            placeholder="e.g. beta ended, plan corrected"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
            Internal note <span className="font-normal normal-case" style={{ color: INK_MUTED }}>(optional)</span>
          </label>
          <input
            type="text"
            className="w-full rounded-lg px-3 py-2 text-[14px] outline-none focus:border-teal-300"
            style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        {submitError && (
          <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: WM_HUE.coral.bg, border: `1px solid ${WM_HUE.coral.border}`, color: WM_HUE.coral.text }}>
            {submitError}
          </div>
        )}
        <div className="flex items-center justify-end gap-3 pt-3" style={{ borderTop: HAIRLINE }}>
          <button
            onClick={onClose}
            className="rounded-full px-4 py-1.5 text-[13px] transition-opacity hover:opacity-70"
            style={{ color: INK_MUTED }}
          >Cancel</button>
          <button
            disabled={submitting}
            onClick={handleSubmit}
            className="rounded-full px-5 py-1.5 text-[13px] font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            style={{ background: WM_HUE.coral.bg, border: `1px solid ${WM_HUE.coral.border}`, color: WM_HUE.coral.text }}
          >
            {submitting ? 'Revoking…' : 'Revoke'}
          </button>
        </div>
      </div>
    </ModalShell>
  )
}

// ---------------------------------------------------------------------------
// History modal
// ---------------------------------------------------------------------------

interface HistoryRow {
  id: string
  action: string
  plan_slug: string
  plan_name: string
  starts_at: string | null
  ends_at: string | null
  reason: string | null
  note: string | null
  actor_user_id: string | null
  actor_name: string | null
  created_at: string
}

function HistoryModal({
  subscriptionId, creator, onClose,
}: {
  subscriptionId: string
  creator: CreatorRow
  onClose: () => void
}) {
  const [rows, setRows] = useState<HistoryRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(apiUrl(`/api/admin/creator-subscriptions/${subscriptionId}/history`), { credentials: 'include' })
      .then((r) => { if (!r.ok) throw new Error(`Error ${r.status}`); return r.json() as Promise<HistoryRow[]> })
      .then(setRows)
      .catch((e: Error) => setError(e.message))
  }, [subscriptionId])

  return (
    <ModalShell
      title="Access history"
      subtitle={`Plan-access events for ${creator.name ?? creator.email}`}
      onClose={onClose}
    >
      <div className="max-h-[70vh] overflow-y-auto px-6 py-5">
        {error && (
          <p className="text-[13px]" style={{ color: WM_HUE.coral.text }}>{error}</p>
        )}
        {rows === null && !error && (
          <p className="text-[13px]" style={SERIF_ITALIC}>Loading…</p>
        )}
        {rows && rows.length === 0 && (
          <p className="text-[13px]" style={SERIF_ITALIC}>No grant events recorded for this subscription.</p>
        )}
        {rows && rows.length > 0 && (
          <ol className="space-y-3">
            {rows.map((r) => {
              const actionHue: WMHue = r.action === 'granted' ? 'teal' : r.action === 'extended' ? 'navy' : 'coral'
              return (
                <li key={r.id} className="rounded-xl p-3" style={{ background: PAGE_BG, border: HAIRLINE }}>
                  <div className="flex items-baseline justify-between gap-3">
                    <AccessPill hue={actionHue}>{r.action}</AccessPill>
                    <span className="text-[11.5px]" style={{ color: INK_MUTED }}>{fmtDate(r.created_at)}</span>
                  </div>
                  <p className="mt-1.5 text-[13px]" style={{ color: INK }}>
                    {r.plan_name}
                    {r.ends_at ? ` · until ${fmtDate(r.ends_at)}` : r.action === 'granted' ? ' · ongoing' : ''}
                  </p>
                  {r.reason && (
                    <p className="mt-0.5 text-[12px]" style={SERIF_ITALIC}>
                      Reason: {REASON_LABELS[r.reason] ?? r.reason}
                    </p>
                  )}
                  {r.note && (
                    <p className="mt-0.5 text-[12px]" style={{ color: INK_MUTED }}>Note: {r.note}</p>
                  )}
                  {r.actor_name && (
                    <p className="mt-0.5 text-[11.5px]" style={{ color: INK_SOFTER }}>By {r.actor_name}</p>
                  )}
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </ModalShell>
  )
}

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

function fmtDate(s: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** `2 / 3 collectives` · `1 / 1 collective` · `3 / ∞ collectives`.
 *  Denominator comes from the backend `effective_collective_allowance`
 *  helper — the same value the guard enforces — so the display and the
 *  rule never disagree. Singular when the enforced limit is exactly 1. */
function formatUsage(current: number, limit: number | null): string {
  const cap = limit === null ? '∞' : String(limit)
  const noun = limit === 1 ? 'collective' : 'collectives'
  return `${current} / ${cap} ${noun}`
}
