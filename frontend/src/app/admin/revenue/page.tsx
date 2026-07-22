'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'
import { WM_HUE, type WMHue } from '@/lib/wm-palette'

// ---------------------------------------------------------------------------
// Types — match `AdminCommerceOverview` on the backend.
// ---------------------------------------------------------------------------

interface PeriodBounds {
  label: string
  starts_at: string | null
  ends_at: string | null
}

interface RevenueSummary {
  total_fc_revenue_cents: number
  subscription_revenue_cents: number
  platform_fee_revenue_cents: number
  total_gross_sales_cents: number
  total_creator_net_cents: number
  paid_out_cents: number
  pending_payout_cents: number
  succeeded_transactions: number
  refunded_transactions: number
  failed_transactions: number
}

interface GrowthSummary {
  new_creators: number
  new_members: number
  new_collectives: number
}

interface CommerceMovementEvent {
  id: string
  label: string
  kind: string
  amount_cents: number
  currency: string
  status: string
  occurred_at: string
  stripe_mode: string
}

interface CommerceWindow {
  bounds: PeriodBounds
  revenue: RevenueSummary
  growth: GrowthSummary
}

interface CommerceOverview {
  period: string
  stripe_mode: string
  test_mode_active: boolean
  current: CommerceWindow
  previous: CommerceWindow | null
  recent_movements: CommerceMovementEvent[]
}

// ---------------------------------------------------------------------------
// Design tokens — inherit from Mother World / Members so the surface reads
// as another chapter of the same book.
// ---------------------------------------------------------------------------
const PAGE_BG      = '#FBFDFC'
const PANEL_BG     = 'rgba(56, 116, 180, 0.10)'
const PANEL_BORDER = '1px solid rgba(56, 116, 180, 0.22)'
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

// Movement-kind hue mapping — sourced from the shared WM palette so the
// hierarchy stays coherent (see `wm-palette.ts`). Adjustment / other
// fall back to a neutral ink dot because they don't belong to any of the
// four canonical categories.
const NEUTRAL_DOT = 'rgba(12, 24, 38, 0.35)'
const KIND_HUES: Record<string, { dot: string }> = {
  subscription: { dot: WM_HUE.teal.dot },   // recurring life — primary/positive
  purchase:     { dot: WM_HUE.navy.dot },   // one-off arrival — neutral info
  ticket:       { dot: WM_HUE.gold.dot },   // event — premium/uncommon
  refund:       { dot: WM_HUE.coral.dot },  // reversal — attention
  adjustment:   { dot: NEUTRAL_DOT },
  other:        { dot: NEUTRAL_DOT },
}

type PeriodKey = 'this_month' | 'last_month' | 'this_fy' | 'all_time'

const PERIOD_OPTIONS: [PeriodKey, string][] = [
  ['this_month', 'This month'],
  ['last_month', 'Last month'],
  ['this_fy',    'This financial year'],
  ['all_time',   'All time'],
]

// ---------------------------------------------------------------------------

export default function CommercePage() {
  const [period, setPeriod] = useState<PeriodKey>('this_month')
  const [data, setData] = useState<CommerceOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch(apiUrl(`/api/admin/commerce/overview?period=${period}`), { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json() as Promise<CommerceOverview>
      })
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e: Error) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [period])

  return (
    <div style={{ background: PAGE_BG, minHeight: '100%' }}>
      <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
        {/* Header */}
        <header className="mb-8">
          <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: INK }}>
            Commerce
          </h1>
          <p className="mt-3 max-w-[620px] text-[15px] leading-relaxed" style={SERIF_ITALIC}>
            How the world is sustaining itself.
          </p>
        </header>

        {/* Controls */}
        <div
          className="mb-6 rounded-2xl p-2.5"
          style={{ background: PANEL_BG, border: PANEL_BORDER }}
        >
          <div className="flex flex-wrap items-center gap-2">
            <PeriodSelect value={period} onChange={setPeriod} />
            <div className="grow" />
          </div>
        </div>

        {loading ? (
          <LoadingState />
        ) : error || !data ? (
          <ErrorState message={error ?? 'No data'} />
        ) : (
          <>
            {data.test_mode_active && <TestModeBand />}

            <FinancialCards
              current={data.current}
              previous={data.previous}
            />

            <GrowthBand
              current={data.current.growth}
              previous={data.previous?.growth ?? null}
              previousLabel={data.previous?.bounds.label ?? null}
              periodLabel={data.current.bounds.label}
            />

            <AttentionBand
              revenue={data.current.revenue}
              periodLabel={data.current.bounds.label}
            />

            <RecentMovement movements={data.recent_movements} />
          </>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

function PeriodSelect({
  value, onChange,
}: {
  value: PeriodKey
  onChange: (v: PeriodKey) => void
}) {
  return (
    <label className="relative inline-flex items-center">
      <span className="sr-only">Period</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as PeriodKey)}
        className="cursor-pointer appearance-none rounded-full py-2 pl-3 pr-8 text-[12.5px] font-medium outline-none transition-colors hover:border-slate-300"
        style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
      >
        {PERIOD_OPTIONS.map(([v, l]) => (
          <option key={v} value={v}>Period: {l}</option>
        ))}
      </select>
      <svg
        aria-hidden
        className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2"
        width="10" height="10" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
        style={{ color: INK_SOFTER }}
      >
        <path d="m6 9 6 6 6-6" />
      </svg>
    </label>
  )
}

// ---------------------------------------------------------------------------
// Test-mode band — soft warm-gold reminder, not a demand for attention
// ---------------------------------------------------------------------------

function TestModeBand() {
  // Gold — the "Important / Test mode information" band from the WM
  // colour hierarchy. Never coral: test-mode isn't a caretaker action
  // item, just a reminder about the environment.
  return (
    <div
      className="mb-6 flex items-start gap-3 rounded-2xl p-4"
      style={{
        background: WM_HUE.gold.bg,
        border: `1px solid ${WM_HUE.gold.border}`,
      }}
    >
      <svg
        aria-hidden
        width="16" height="16" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        style={{ color: WM_HUE.gold.text, marginTop: 2 }}
      >
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v4" />
        <path d="M12 16h.01" />
      </svg>
      <div className="min-w-0">
        <p className="text-[13.5px] font-semibold" style={{ color: WM_HUE.gold.text }}>
          Viewing test data
        </p>
        <p className="mt-0.5 text-[13px]" style={{ ...SERIF_ITALIC, color: 'rgba(138, 106, 21, 0.78)' }}>
          Figures reflect the sandbox environment. Nothing here is real revenue yet — Stripe will populate live figures once live keys are configured.
        </p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Financial cards — four calm cards, one row
// ---------------------------------------------------------------------------

function FinancialCards({
  current, previous,
}: {
  current: CommerceWindow
  previous: CommerceWindow | null
}) {
  const grossCurrent = current.revenue.total_gross_sales_cents + current.revenue.subscription_revenue_cents
  const grossPrevious = previous
    ? previous.revenue.total_gross_sales_cents + previous.revenue.subscription_revenue_cents
    : null
  const pendingCents = current.revenue.pending_payout_cents

  return (
    <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {/* Neutral information — navy per WM hierarchy */}
      <MoneyCard
        label="Gross volume"
        cents={grossCurrent}
        previousCents={grossPrevious}
        previousLabel={previous?.bounds.label ?? null}
        caption="Money moving through the world"
        hue="navy"
      />
      {/* Primary / Positive — teal */}
      <MoneyCard
        label="Revenue"
        cents={current.revenue.total_fc_revenue_cents}
        previousCents={previous?.revenue.total_fc_revenue_cents ?? null}
        previousLabel={previous?.bounds.label ?? null}
        caption="Fresh Collective's share"
        hue="teal"
      />
      {/* Creators — teal (primary/positive; the world's active work) */}
      <MoneyCard
        label="Creator earnings"
        cents={current.revenue.total_creator_net_cents}
        previousCents={previous?.revenue.total_creator_net_cents ?? null}
        previousLabel={previous?.bounds.label ?? null}
        caption="Creators' share"
        hue="teal"
      />
      {/* Coral always — the label signals "money that needs to leave the
          world" as a permanent category. The value figure only shifts to
          coral when there's a real balance to act on, so the strongest
          signal is reserved for actual pending money. */}
      <MoneyCard
        label="Pending creator payouts"
        cents={pendingCents}
        previousCents={null}   // pending is a current-state snapshot, not a period total
        previousLabel={null}
        caption={pendingCents > 0 ? 'Owed and awaiting payout' : 'Nothing owed right now'}
        hue="coral"
        emphasiseValue={pendingCents > 0}
      />
    </div>
  )
}

function MoneyCard({
  label, cents, previousCents, previousLabel, caption, hue, emphasiseValue,
}: {
  label: string
  cents: number
  previousCents: number | null
  previousLabel: string | null
  caption: string
  hue: WMHue
  /** When true, the value figure inherits the hue's text colour so it
   *  reads as an action item. Reserve for real signal (typically coral).
   */
  emphasiseValue?: boolean
}) {
  const valueColor = emphasiseValue ? WM_HUE[hue].text : INK
  return (
    <div
      className="rounded-2xl p-5"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <HueLabel hue={hue}>{label}</HueLabel>
      <p
        className="mt-3 font-serif text-[26px] leading-tight md:text-[28px]"
        style={{ color: valueColor }}
      >
        {fmtMoney(cents)}
      </p>
      <p className="mt-1 text-[12.5px]" style={SERIF_ITALIC}>
        {caption}
      </p>
      {previousCents !== null && previousLabel !== null && (
        <p className="mt-3 text-[12.5px]" style={{ color: INK_MUTED }}>
          {comparisonSentence(cents, previousCents, previousLabel)}
        </p>
      )}
    </div>
  )
}

/**
 * A soft tinted label pill in the given hue. The same treatment is used
 * on money cards and growth counters so a caretaker can read the WM
 * colour hierarchy at a glance — teal for positive/active, navy for
 * neutral information, gold for premium, coral for attention.
 *
 * Deliberately compact so the pill is visible without dominating the
 * card. Values and captions stay neutral; the pill carries the accent.
 */
function HueLabel({ hue, children }: { hue: WMHue; children: React.ReactNode }) {
  const h = WM_HUE[hue]
  // `w-fit` + `inline-flex` + `whitespace-nowrap` keeps the pill sized
  // exactly to its content so longer labels like "Pending creator
  // payouts" never stretch, wrap, or reach the rounded ends. Horizontal
  // padding stays at 8px so text always clears the pill's rounded arc.
  return (
    <span
      className="inline-flex w-fit items-center whitespace-nowrap rounded-full px-2 py-[1px] text-[8.5px] font-semibold uppercase tracking-[0.06em]"
      style={{
        background: h.bg,
        border: `1px solid ${h.border}`,
        color: h.text,
      }}
    >
      {children}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Growth this period — context, not a KPI
// ---------------------------------------------------------------------------

function GrowthBand({
  current, previous, previousLabel, periodLabel,
}: {
  current: GrowthSummary
  previous: GrowthSummary | null
  previousLabel: string | null
  periodLabel: string
}) {
  return (
    <section className="mb-10">
      <div className="mb-3">
        <h2
          className="font-serif text-[18px] leading-tight"
          style={{ color: INK }}
        >
          Growth this period
        </h2>
        <p className="mt-0.5 text-[13px]" style={SERIF_ITALIC}>
          Who arrived while {periodLabel.toLowerCase()} was passing.
        </p>
      </div>
      <div
        className="grid gap-4 rounded-2xl p-5 sm:grid-cols-3"
        style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
      >
        {/* Members — navy per WM hierarchy (information / neutral). */}
        <GrowthCounter
          label="New members"
          value={current.new_members}
          previousValue={previous?.new_members ?? null}
          previousLabel={previousLabel}
          hue="navy"
        />
        {/* Creators — teal (primary / positive). */}
        <GrowthCounter
          label="New creators"
          value={current.new_creators}
          previousValue={previous?.new_creators ?? null}
          previousLabel={previousLabel}
          hue="teal"
        />
        {/* Collectives — teal (the world's positive activity). */}
        <GrowthCounter
          label="New collectives"
          value={current.new_collectives}
          previousValue={previous?.new_collectives ?? null}
          previousLabel={previousLabel}
          hue="teal"
        />
      </div>
    </section>
  )
}

function GrowthCounter({
  label, value, previousValue, previousLabel, hue,
}: {
  label: string
  value: number
  previousValue: number | null
  previousLabel: string | null
  hue: WMHue
}) {
  return (
    <div>
      <HueLabel hue={hue}>{label}</HueLabel>
      <p
        className="mt-2 font-serif text-[22px] leading-tight"
        style={{ color: INK }}
      >
        {value.toLocaleString('en-AU')}
      </p>
      {previousValue !== null && previousLabel && (
        <p className="mt-1 text-[12px]" style={SERIF_ITALIC}>
          {previousValue.toLocaleString('en-AU')} during {previousLabel.toLowerCase()}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Attention band — only rendered when there is real signal
// ---------------------------------------------------------------------------

function AttentionBand({
  revenue, periodLabel,
}: {
  revenue: RevenueSummary
  periodLabel: string
}) {
  const failed = revenue.failed_transactions
  const refunded = revenue.refunded_transactions
  if (failed === 0 && refunded === 0) return null

  return (
    <section className="mb-10">
      <div
        className="flex items-start gap-3 rounded-2xl p-4"
        style={{
          background: WM_HUE.coral.bg,
          border: `1px solid ${WM_HUE.coral.border}`,
        }}
      >
        <svg
          aria-hidden
          width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          style={{ color: WM_HUE.coral.text, marginTop: 2 }}
        >
          <path d="M12 9v4" />
          <path d="M12 17h.01" />
          <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        </svg>
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-semibold" style={{ color: WM_HUE.coral.text }}>
            Wants attention
          </p>
          <div
            className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]"
            style={{ color: 'rgba(138, 58, 51, 0.85)' }}
          >
            {failed > 0 && (
              <span>
                {failed === 1 ? '1 payment failed' : `${failed} payments failed`} during {periodLabel.toLowerCase()}
              </span>
            )}
            {failed > 0 && refunded > 0 && (
              <span aria-hidden style={{ color: 'rgba(138, 58, 51, 0.5)' }}>·</span>
            )}
            {refunded > 0 && (
              <span>
                {refunded === 1 ? '1 refund' : `${refunded} refunds`} during {periodLabel.toLowerCase()}
              </span>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Recent movement — events, not accounting entries
// ---------------------------------------------------------------------------

function RecentMovement({ movements }: { movements: CommerceMovementEvent[] }) {
  return (
    <section className="mb-6">
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <div>
          <h2
            className="font-serif text-[18px] leading-tight"
            style={{ color: INK }}
          >
            Recent movement
          </h2>
          <p className="mt-0.5 text-[13px]" style={SERIF_ITALIC}>
            Latest activity across the world.
          </p>
        </div>
        <Link
          href="/admin/payments"
          className="shrink-0 text-[12.5px] font-semibold transition-opacity hover:opacity-70"
          style={{ color: INK_MUTED }}
        >
          View all →
        </Link>
      </div>
      {movements.length === 0 ? (
        <div
          className="rounded-2xl px-10 py-12 text-center"
          style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
        >
          <p className="font-serif text-[18px]" style={{ color: INK }}>
            The world was quiet.
          </p>
          <p className="mt-2 text-[13px]" style={SERIF_ITALIC}>
            Nothing has moved through commerce yet.
          </p>
        </div>
      ) : (
        <div
          className="overflow-hidden rounded-2xl"
          style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
        >
          {movements.map((m, i) => (
            <MovementRow key={m.id} event={m} first={i === 0} />
          ))}
        </div>
      )}
    </section>
  )
}

function MovementRow({ event, first }: { event: CommerceMovementEvent; first: boolean }) {
  const hue = KIND_HUES[event.kind] ?? KIND_HUES.other
  const isRefund = event.kind === 'refund'
  return (
    <div
      className="flex items-center gap-4 px-5 py-3.5"
      style={first ? undefined : { borderTop: HAIRLINE }}
    >
      <span
        className="inline-block h-2 w-2 shrink-0 rounded-full"
        style={{ background: hue.dot }}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px]" style={{ color: INK }}>
          {event.label}
        </p>
        <p className="mt-0.5 text-[12px]" style={SERIF_ITALIC}>
          {relativeTime(event.occurred_at)}
        </p>
      </div>
      <div
        className="shrink-0 tabular-nums text-[13px]"
        style={{
          color: isRefund ? WM_HUE.coral.text : INK,
          minWidth: 90,
          textAlign: 'right',
        }}
      >
        {isRefund ? '−' : ''}{fmtMoney(event.amount_cents, event.currency)}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// States
// ---------------------------------------------------------------------------

function LoadingState() {
  return (
    <div
      className="flex items-center gap-3 rounded-2xl px-6 py-8 text-[13.5px]"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW, color: INK_MUTED }}
    >
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      <span style={SERIF_ITALIC}>Reading the ledger…</span>
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  // Coral — the error state is a genuine attention condition.
  return (
    <div
      className="rounded-2xl px-6 py-6 text-[13.5px]"
      style={{ background: WM_HUE.coral.bg, border: `1px solid ${WM_HUE.coral.border}` }}
    >
      <p className="font-serif text-[16px]" style={{ color: WM_HUE.coral.text }}>
        Something went wrong reading commerce.
      </p>
      <p className="mt-1 text-[13px]" style={{ ...SERIF_ITALIC, color: 'rgba(138, 58, 51, 0.72)' }}>
        {message}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function fmtMoney(cents: number, currency = 'AUD'): string {
  const dollars = cents / 100
  const decimals = cents % 100 === 0 ? 0 : 2
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency,
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(dollars)
}

function comparisonSentence(
  current: number,
  previous: number,
  previousLabel: string,
): string {
  const label = previousLabel.toLowerCase()
  if (previous === 0 && current === 0) return `Level with ${label}.`
  if (previous === 0) return `Up from nothing during ${label}.`
  if (previous === current) return `Level with ${label}.`
  return current > previous
    ? `Up from ${fmtMoney(previous)} during ${label}.`
    : `Down from ${fmtMoney(previous)} during ${label}.`
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const now = Date.now()
  const diffMs = now - then
  const mins = Math.floor(diffMs / 60_000)
  const hours = Math.floor(mins / 60)
  const days = Math.floor(hours / 24)
  if (diffMs < 60_000) return 'just now'
  if (mins < 60) return `${mins}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}
