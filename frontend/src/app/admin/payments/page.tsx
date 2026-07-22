'use client'

import { useEffect, useMemo, useState } from 'react'
import { apiUrl } from '@/lib/api'
import { WM_HUE, type WMHue } from '@/lib/wm-palette'
import {
  CSV_MULTI_DELIMITER,
  downloadCsv,
  todayIsoDate,
  type CsvColumn,
} from '@/lib/csvExport'

// ---------------------------------------------------------------------------
// Types — match backend AdminPeriodicRevenueSummary + LedgerRow.
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

interface PeriodicRevenueSummary {
  period: string
  stripe_mode: string | null
  current_bounds: PeriodBounds
  current: RevenueSummary
  previous_bounds: PeriodBounds | null
  previous: RevenueSummary | null
}

interface LedgerRow {
  id: string
  created_at: string
  transaction_type: string
  status: string
  payout_status: string
  provider: string
  stripe_mode: string
  payer_name: string | null
  payer_email: string | null
  creator_id: string | null
  creator_name: string | null
  creator_email: string | null
  space_name: string | null
  pathway_title: string | null
  currency: string
  gross_amount_cents: number
  platform_fee_cents: number
  net_creator_amount_cents: number | null
}

interface PlatformStatus {
  stripe_enabled: boolean
  stripe_test_mode: boolean
}

interface SimpleUser {
  id: string
  name: string | null
  email: string
}

interface SimplePaidPathway {
  id: string
  title: string
  space_id: string
  space_name: string
  space_slug: string
  access_type: string
  price_cents: number
  currency: string
  billing_interval: string | null
  creator_fee_basis_points: number
}

interface GrantAccessResult {
  entitlement_id: string
  entitlement_source: string
  reactivated: boolean
  reason: string
  note: string | null
  member_name: string | null
  member_email: string
  pathway_title: string
  space_name: string
  space_slug: string
}

type GrantReason = 'comp' | 'beta' | 'migration' | 'correction' | 'replacement' | 'other'

const GRANT_REASON_OPTIONS: { value: GrantReason; label: string; hint?: string }[] = [
  { value: 'comp',        label: 'Complimentary access', hint: 'A gift on behalf of the platform' },
  { value: 'beta',        label: 'Beta or testing access' },
  { value: 'migration',   label: 'Migration',            hint: 'Previously held access from another system' },
  { value: 'correction',  label: 'Purchase correction',  hint: 'Fixes a broken paid purchase' },
  { value: 'replacement', label: 'Replacement access',   hint: 'After a refund or lost entitlement' },
  { value: 'other',       label: 'Other',                hint: 'Note required' },
]

// ---------------------------------------------------------------------------
// Design tokens — inherit from Members / Commerce.
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

type PeriodKey = 'this_month' | 'last_month' | 'this_fy' | 'all_time'

const PERIOD_OPTIONS: [PeriodKey, string][] = [
  ['this_month', 'This month'],
  ['last_month', 'Last month'],
  ['this_fy',    'This financial year'],
  ['all_time',   'All time'],
]

// ---------------------------------------------------------------------------
// Status & payout hue mapping — sourced from WM_HUE per the hierarchy:
//   teal  = positive / successful / paid
//   navy  = neutral information (Test mode marker, manual, etc.)
//   gold  = important-but-not-urgent (pending)
//   coral = attention (failed / refunded / awaiting payout / disputed)
// ---------------------------------------------------------------------------

const STATUS_HUE: Record<string, WMHue> = {
  succeeded:          'teal',
  pending:            'gold',
  failed:             'coral',
  refunded:           'coral',
  partially_refunded: 'coral',
  disputed:           'coral',
  cancelled:          'navy',
}

const PAYOUT_HUE: Record<string, WMHue> = {
  paid:           'teal',
  pending:        'coral',   // awaiting payout — action required
  held:           'coral',
  cancelled:      'navy',
  not_applicable: 'navy',
}

const STATUS_OPTIONS: [string, string][] = [
  ['all',                'All statuses'],
  ['succeeded',          'Succeeded'],
  ['pending',            'Pending'],
  ['failed',             'Failed'],
  ['refunded',           'Refunded'],
  ['partially_refunded', 'Partially refunded'],
  ['cancelled',          'Cancelled'],
]

const TYPE_OPTIONS: [string, string][] = [
  ['all',                              'All types'],
  ['creator_subscription_payment',     'Creator subscription'],
  ['member_collective_purchase',       'Collective purchase'],
  ['member_collective_subscription',   'Collective subscription'],
  ['member_pathway_purchase',          'Pathway purchase'],
  ['member_pathway_subscription',      'Pathway subscription'],
  ['gathering_ticket_purchase',        'Gathering ticket'],
  ['refund',                           'Refund'],
  ['adjustment',                       'Adjustment'],
]

const PAYOUT_OPTIONS: [string, string][] = [
  ['all',            'All payouts'],
  ['paid',           'Paid out'],
  ['pending',        'Awaiting payout'],
  ['held',           'Held'],
  ['not_applicable', 'N/A'],
  ['cancelled',      'Cancelled'],
]

// ---------------------------------------------------------------------------

export default function TransactionsPage() {
  const [period, setPeriod] = useState<PeriodKey>('this_month')
  const [rows, setRows] = useState<LedgerRow[]>([])
  const [summary, setSummary] = useState<PeriodicRevenueSummary | null>(null)
  const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)

  // Filters (all client-side over the fetched period slice)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<string>('all')
  const [type, setType] = useState<string>('all')
  const [payout, setPayout] = useState<string>('all')
  const [creator, setCreator] = useState<string>('all')

  function reload() {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      fetch(apiUrl(`/api/admin/payments/ledger?period=${period}`), { credentials: 'include' })
        .then((r) => { if (!r.ok) throw new Error(`Ledger: ${r.status}`); return r.json() as Promise<LedgerRow[]> }),
      fetch(apiUrl(`/api/admin/revenue/summary/periodic?period=${period}`), { credentials: 'include' })
        .then((r) => { if (!r.ok) throw new Error(`Summary: ${r.status}`); return r.json() as Promise<PeriodicRevenueSummary> }),
      fetch(apiUrl('/api/checkout/status'), { credentials: 'include' })
        .then((r) => r.ok ? r.json() as Promise<PlatformStatus> : null),
    ])
      .then(([l, s, st]) => { if (!cancelled) { setRows(l); setSummary(s); if (st) setPlatformStatus(st) } })
      .catch((e: Error) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }

  useEffect(() => reload(), [period])   // eslint-disable-line react-hooks/exhaustive-deps

  const creatorOptions = useMemo(() => {
    const map = new Map<string, string>()
    for (const r of rows) {
      if (r.creator_id) map.set(r.creator_id, r.creator_name ?? r.creator_email ?? '—')
    }
    return Array.from(map.entries()).sort((a, b) => a[1].localeCompare(b[1]))
  }, [rows])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows.filter((r) => {
      if (status !== 'all' && r.status !== status) return false
      if (type !== 'all' && r.transaction_type !== type) return false
      if (payout !== 'all' && r.payout_status !== payout) return false
      if (creator !== 'all' && r.creator_id !== creator) return false
      if (q) {
        const hay = [
          r.payer_name, r.payer_email,
          r.creator_name, r.creator_email,
          r.space_name, r.pathway_title,
        ].filter(Boolean).join(' ').toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [rows, search, status, type, payout, creator])

  const hasFilters =
    search.trim() !== '' || status !== 'all' || type !== 'all' ||
    payout !== 'all' || creator !== 'all'

  const clearFilters = () => {
    setSearch(''); setStatus('all'); setType('all'); setPayout('all'); setCreator('all')
  }

  return (
    <div style={{ background: PAGE_BG, minHeight: '100%' }}>
      {showModal && (
        <GrantAccessModal
          onClose={() => setShowModal(false)}
          onSuccess={reload}
        />
      )}

      <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
        {/* Header */}
        <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: INK }}>
              Transactions
            </h1>
            <p className="mt-3 max-w-[620px] text-[15px] leading-relaxed" style={SERIF_ITALIC}>
              Every payment that has moved through the world.
            </p>
          </div>
          <GrantAccessButton onClick={() => setShowModal(true)} />
        </header>

        {/* Stripe status — compact badge row */}
        <StripeStatusRow status={platformStatus} />

        {/* Controls */}
        <div
          className="mb-6 rounded-2xl p-2.5"
          style={{ background: PANEL_BG, border: PANEL_BORDER }}
        >
          <div className="flex flex-wrap items-center gap-2">
            <SearchInput value={search} onChange={setSearch} />
            <FilterSelect label="Period" value={period}
              onChange={(v) => setPeriod(v as PeriodKey)}
              options={PERIOD_OPTIONS as [string, string][]} />
            <FilterSelect label="Status" value={status} onChange={setStatus} options={STATUS_OPTIONS} />
            <FilterSelect label="Type" value={type} onChange={setType} options={TYPE_OPTIONS} />
            <FilterSelect label="Payout" value={payout} onChange={setPayout} options={PAYOUT_OPTIONS} />
            <FilterSelect
              label="Creator"
              value={creator}
              onChange={setCreator}
              options={[['all', 'All creators'], ...creatorOptions.map(([id, name]): [string, string] => [id, name])]}
            />
            <div className="grow" />
            <ExportCsvButton
              onExport={() =>
                downloadCsv(
                  filtered,
                  TRANSACTIONS_CSV_COLUMNS,
                  `fresh-collective-transactions-${todayIsoDate()}.csv`,
                )
              }
              disabled={filtered.length === 0}
            />
          </div>

          {hasFilters && (
            <div className="mt-2.5 flex flex-wrap items-center gap-2 px-1">
              <button
                type="button"
                onClick={clearFilters}
                className="text-[12.5px] font-semibold transition-opacity hover:opacity-70"
                style={{ color: INK_MUTED }}
              >
                Clear filters
              </button>
            </div>
          )}
        </div>

        {loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState message={error} />
        ) : (
          <>
            {summary && <SummaryCards summary={summary.current} />}

            {filtered.length === 0 ? (
              <EmptyState hasFilters={hasFilters} periodLabel={summary?.current_bounds.label ?? 'this period'} />
            ) : (
              <TransactionsTable rows={filtered} />
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stripe status row — compact, calm, no big card
// ---------------------------------------------------------------------------

function StripeStatusRow({ status }: { status: PlatformStatus | null }) {
  if (status === null) return null   // status endpoint failed silently — no clutter

  const modeHue: WMHue = status.stripe_test_mode ? 'gold' : 'teal'
  const modeLabel = status.stripe_enabled
    ? (status.stripe_test_mode ? 'Test mode' : 'Live mode')
    : 'Not configured'
  const stripeHue: WMHue = status.stripe_enabled ? 'teal' : 'coral'
  const stripeLabel = status.stripe_enabled ? 'Stripe configured' : 'Stripe not configured'
  const webhookHue: WMHue = status.stripe_enabled ? 'teal' : 'navy'
  const webhookLabel = status.stripe_enabled ? 'Webhook configured' : 'Webhook not configured'

  return (
    <div className="mb-4 flex flex-wrap items-center gap-1.5">
      <StatusPill hue={modeHue}>{modeLabel}</StatusPill>
      <StatusPill hue={stripeHue}>{stripeLabel}</StatusPill>
      <StatusPill hue={webhookHue}>{webhookLabel}</StatusPill>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Summary cards — same layout as Commerce, same hue treatment
// ---------------------------------------------------------------------------

function SummaryCards({ summary }: { summary: RevenueSummary }) {
  const gross = summary.total_gross_sales_cents + summary.subscription_revenue_cents
  return (
    <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <MoneyCard label="Gross volume"           cents={gross}                                caption="Money moving through the world" hue="navy" />
      <MoneyCard label="Fresh Collective revenue" cents={summary.total_fc_revenue_cents}     caption="Fresh Collective's share"        hue="teal" />
      <MoneyCard label="Creator earnings"       cents={summary.total_creator_net_cents}      caption="Creators' share"                 hue="teal" />
      <MoneyCard label="Pending creator payouts" cents={summary.pending_payout_cents}         caption={summary.pending_payout_cents > 0 ? 'Owed and awaiting payout' : 'Nothing owed right now'} hue="coral" emphasiseValue={summary.pending_payout_cents > 0} />
    </div>
  )
}

function MoneyCard({
  label, cents, caption, hue, emphasiseValue,
}: {
  label: string
  cents: number
  caption: string
  hue: WMHue
  emphasiseValue?: boolean
}) {
  const valueColor = emphasiseValue ? WM_HUE[hue].text : INK
  return (
    <div className="rounded-2xl p-5" style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}>
      <HueLabel hue={hue}>{label}</HueLabel>
      <p className="mt-3 font-serif text-[26px] leading-tight md:text-[28px]" style={{ color: valueColor }}>
        {fmtMoney(cents)}
      </p>
      <p className="mt-1 text-[12.5px]" style={SERIF_ITALIC}>
        {caption}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

function TransactionsTable({ rows }: { rows: LedgerRow[] }) {
  return (
    <div
      className="overflow-hidden rounded-2xl"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      {/* Desktop */}
      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full text-left">
          <thead>
            <tr>
              {['Date', 'Type', 'Status', 'Buyer', 'Creator', 'Collective / item', 'Gross', 'FC fee', 'Creator earnings', 'Payout'].map((h) => (
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
            {rows.map((r, i) => (
              <TransactionRow key={r.id} row={r} first={i === 0} />
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile */}
      <div className="lg:hidden">
        {rows.map((r, i) => (
          <TransactionMobileRow key={r.id} row={r} first={i === 0} />
        ))}
      </div>
    </div>
  )
}

function TransactionRow({ row, first }: { row: LedgerRow; first: boolean }) {
  const item = row.pathway_title ?? row.space_name ?? itemFallback(row.transaction_type)
  return (
    <tr
      className="transition-colors hover:bg-slate-50/60"
      style={first ? undefined : { borderTop: HAIRLINE }}
    >
      <td className="px-4 py-3.5 align-top whitespace-nowrap text-[12.5px]" style={{ color: INK_MUTED }}>
        {fmtDate(row.created_at)}
      </td>
      <td className="px-4 py-3.5 align-top text-[13px]" style={{ color: INK }}>
        {labelType(row.transaction_type)}
      </td>
      <td className="px-4 py-3.5 align-top">
        <StatusPill hue={STATUS_HUE[row.status] ?? 'navy'}>{prettify(row.status)}</StatusPill>
      </td>
      <td className="px-4 py-3.5 align-top">
        <PersonCell name={row.payer_name} email={row.payer_email} />
      </td>
      <td className="px-4 py-3.5 align-top">
        <PersonCell name={row.creator_name} email={row.creator_email} />
      </td>
      <td className="px-4 py-3.5 align-top text-[13px]" style={{ color: INK }}>
        {item}
      </td>
      <td className="px-4 py-3.5 align-top whitespace-nowrap tabular-nums text-[13px]" style={{ color: INK }}>
        {fmtMoney(row.gross_amount_cents, row.currency)}
      </td>
      <td className="px-4 py-3.5 align-top whitespace-nowrap tabular-nums text-[13px]" style={{ color: WM_HUE.teal.text }}>
        {fmtMoney(row.platform_fee_cents, row.currency)}
      </td>
      <td className="px-4 py-3.5 align-top whitespace-nowrap tabular-nums text-[13px]" style={{ color: INK }}>
        {row.net_creator_amount_cents != null ? fmtMoney(row.net_creator_amount_cents, row.currency) : '—'}
      </td>
      <td className="px-4 py-3.5 align-top">
        <StatusPill hue={PAYOUT_HUE[row.payout_status] ?? 'navy'}>{prettify(row.payout_status)}</StatusPill>
      </td>
    </tr>
  )
}

function TransactionMobileRow({ row, first }: { row: LedgerRow; first: boolean }) {
  const item = row.pathway_title ?? row.space_name ?? itemFallback(row.transaction_type)
  return (
    <div
      className="px-5 py-4"
      style={first ? undefined : { borderTop: HAIRLINE }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[13.5px]" style={{ color: INK }}>
            {labelType(row.transaction_type)}
          </div>
          <div className="mt-0.5 text-[12px]" style={{ color: INK_MUTED }}>
            {fmtDate(row.created_at)} · {item}
          </div>
        </div>
        <StatusPill hue={STATUS_HUE[row.status] ?? 'navy'}>{prettify(row.status)}</StatusPill>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]" style={{ color: INK_MUTED }}>
        {row.payer_name && <span style={{ color: INK }}>{row.payer_name}</span>}
        {row.payer_name && row.creator_name && <span aria-hidden style={{ color: INK_SOFTER }}>·</span>}
        {row.creator_name && <span>by {row.creator_name}</span>}
      </div>
      <div className="mt-2 flex items-baseline justify-between gap-3">
        <span className="text-[12.5px]" style={{ color: INK_MUTED }}>
          Gross <span className="tabular-nums" style={{ color: INK }}>{fmtMoney(row.gross_amount_cents, row.currency)}</span>
        </span>
        <StatusPill hue={PAYOUT_HUE[row.payout_status] ?? 'navy'}>{prettify(row.payout_status)}</StatusPill>
      </div>
    </div>
  )
}

function PersonCell({ name, email }: { name: string | null; email: string | null }) {
  if (!name && !email) return <span style={{ color: INK_SOFTER }}>—</span>
  return (
    <div>
      <div className="text-[13px]" style={{ color: INK }}>{name ?? '—'}</div>
      {email && <div className="mt-0.5 text-[11.5px]" style={{ color: INK_MUTED }}>{email}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Small components — pills, controls, buttons
// ---------------------------------------------------------------------------

/** Shared tinted-label pill — same treatment as the WM cards. */
function HueLabel({ hue, children }: { hue: WMHue; children: React.ReactNode }) {
  const h = WM_HUE[hue]
  return (
    <span
      className="inline-flex w-fit items-center whitespace-nowrap rounded-full px-2 py-[1px] text-[8.5px] font-semibold uppercase tracking-[0.06em]"
      style={{ background: h.bg, border: `1px solid ${h.border}`, color: h.text }}
    >
      {children}
    </span>
  )
}

/** Status pill — slightly larger than the category HueLabel; used for
 *  succeeded/failed/pending/paid state indicators. */
function StatusPill({ hue, children }: { hue: WMHue; children: React.ReactNode }) {
  const h = WM_HUE[hue]
  return (
    <span
      className="inline-flex w-fit items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
      style={{ background: h.bg, border: `1px solid ${h.border}`, color: h.text }}
    >
      {children}
    </span>
  )
}

function SearchInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative min-w-[220px] flex-1 basis-[240px]">
      <svg
        aria-hidden
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2"
        width="14" height="14" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        style={{ color: INK_SOFTER }}
      >
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" />
      </svg>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search by name, email, collective or pathway…"
        className="w-full rounded-full py-2 pl-9 pr-3 text-[13px] outline-none transition-colors focus:border-teal-300"
        style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
      />
    </div>
  )
}

function FilterSelect({
  label, value, onChange, options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: [string, string][]
}) {
  return (
    <label className="relative inline-flex items-center">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="cursor-pointer appearance-none rounded-full py-2 pl-3 pr-8 text-[12.5px] font-medium outline-none transition-colors hover:border-slate-300"
        style={{
          background: '#FFFFFF',
          border: '1px solid #E7EEF0',
          color: value === 'all' ? INK_MUTED : INK,
        }}
      >
        {options.map(([v, l]) => (
          <option key={v} value={v}>{v === 'all' ? l : `${label}: ${l}`}</option>
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

function ExportCsvButton({ onExport, disabled }: { onExport: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onExport}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-2 text-[12.5px] font-medium outline-none transition-colors hover:border-slate-300 disabled:cursor-not-allowed disabled:opacity-50"
      style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
      aria-label="Export the current filtered result set to CSV"
    >
      <svg
        aria-hidden
        width="12" height="12" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        style={{ color: INK_SOFTER }}
      >
        <path d="M12 3v12" />
        <path d="m7 10 5 5 5-5" />
        <path d="M5 21h14" />
      </svg>
      Export CSV
    </button>
  )
}

/**
 * Grant access — teal-tinted primary button in the WM style. Opens the
 * non-financial grant modal (see GrantAccessModal). Deliberately no
 * "purchase" or "payment" language: this action creates an entitlement
 * only, and touches no revenue.
 */
function GrantAccessButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="shrink-0 inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-[13px] font-semibold transition-colors hover:opacity-90"
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
      Grant access
    </button>
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
      <span style={SERIF_ITALIC}>Gathering the financial record…</span>
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
        Something went wrong reading transactions.
      </p>
      <p className="mt-1 text-[13px]" style={{ ...SERIF_ITALIC, color: 'rgba(138, 58, 51, 0.72)' }}>
        {message}
      </p>
    </div>
  )
}

function EmptyState({ hasFilters, periodLabel }: { hasFilters: boolean; periodLabel: string }) {
  return (
    <div
      className="rounded-2xl px-10 py-16 text-center"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <p className="font-serif text-[20px] leading-tight" style={{ color: INK }}>
        {hasFilters
          ? 'Nothing matches those filters.'
          : `No transactions moved through the world during ${periodLabel.toLowerCase()}.`}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// CSV export — reflects current filter + sort. Reads friendly names, not
// internal IDs.
// ---------------------------------------------------------------------------

const TRANSACTIONS_CSV_COLUMNS: CsvColumn<LedgerRow>[] = [
  { header: 'Date',              value: (r) => fmtDate(r.created_at) },
  { header: 'Type',              value: (r) => labelType(r.transaction_type) },
  { header: 'Status',            value: (r) => prettify(r.status) },
  { header: 'Buyer',             value: (r) => r.payer_name ?? '' },
  { header: 'Buyer email',       value: (r) => r.payer_email ?? '' },
  { header: 'Creator',           value: (r) => r.creator_name ?? '' },
  { header: 'Creator email',     value: (r) => r.creator_email ?? '' },
  { header: 'Collective / item', value: (r) => [r.space_name, r.pathway_title].filter(Boolean).join(CSV_MULTI_DELIMITER) },
  { header: 'Currency',          value: (r) => r.currency },
  { header: 'Gross',             value: (r) => (r.gross_amount_cents / 100).toFixed(2) },
  { header: 'FC fee',            value: (r) => (r.platform_fee_cents / 100).toFixed(2) },
  { header: 'Creator earnings',  value: (r) => r.net_creator_amount_cents != null ? (r.net_creator_amount_cents / 100).toFixed(2) : '' },
  { header: 'Payout',            value: (r) => prettify(r.payout_status) },
]

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function fmtMoney(cents: number, currency = 'AUD'): string {
  const decimals = cents % 100 === 0 ? 0 : 2
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(cents / 100)
}

function fmtDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('en-AU', { day: '2-digit', month: 'short', year: 'numeric' })
}

function labelType(t: string): string {
  const map: Record<string, string> = {
    creator_subscription_payment:   'Creator subscription',
    member_collective_purchase:     'Collective purchase',
    member_collective_subscription: 'Collective subscription',
    member_pathway_purchase:        'Pathway purchase',
    member_pathway_subscription:    'Pathway subscription',
    gathering_ticket_purchase:      'Gathering ticket',
    refund:                         'Refund',
    adjustment:                     'Adjustment',
  }
  return map[t] ?? prettify(t)
}

function prettify(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function itemFallback(ttype: string): string {
  if (ttype === 'gathering_ticket_purchase') return 'Gathering ticket'
  if (ttype === 'creator_subscription_payment') return 'Creator subscription'
  return '—'
}

// ---------------------------------------------------------------------------
// Grant access modal — non-financial replacement for the old "Manual
// purchase" flow. Creates or reactivates a PathwayEntitlement only. No
// PaymentTransaction is created; no revenue is fabricated.
// ---------------------------------------------------------------------------

function GrantAccessModal({
  onClose,
  onSuccess,
}: {
  onClose: () => void
  onSuccess: () => void
}) {
  const [users, setUsers] = useState<SimpleUser[]>([])
  const [pathways, setPathways] = useState<SimplePaidPathway[]>([])
  const [loadingOptions, setLoadingOptions] = useState(true)
  const [optionsError, setOptionsError] = useState<string | null>(null)

  const [memberUserId, setMemberUserId] = useState('')
  const [pathwayId, setPathwayId] = useState('')
  const [reason, setReason] = useState<GrantReason>('comp')
  const [note, setNote] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [duplicateHint, setDuplicateHint] = useState<string | null>(null)
  const [result, setResult] = useState<GrantAccessResult | null>(null)

  useEffect(() => {
    Promise.all([
      fetch(apiUrl('/api/admin/users/simple'), { credentials: 'include' }).then((r) => r.json()),
      fetch(apiUrl('/api/admin/pathways/paid-simple'), { credentials: 'include' }).then((r) => r.json()),
    ])
      .then(([u, p]) => {
        setUsers(u as SimpleUser[])
        setPathways(p as SimplePaidPathway[])
      })
      .catch((e: Error) => setOptionsError(e.message))
      .finally(() => setLoadingOptions(false))
  }, [])

  const noteRequired = reason === 'other'
  const trimmedNote = note.trim()
  const submitDisabled =
    !memberUserId ||
    !pathwayId ||
    submitting ||
    (noteRequired && trimmedNote.length === 0)

  async function handleSubmit() {
    if (submitDisabled) return
    setSubmitting(true)
    setSubmitError(null)
    setDuplicateHint(null)
    try {
      const res = await fetch(apiUrl('/api/admin/entitlements/grant'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          member_user_id: memberUserId,
          pathway_id: pathwayId,
          reason,
          note: trimmedNote || null,
        }),
      })
      if (res.status === 409) {
        // Duplicate — surface as a friendly caretaker message, not an error tone.
        const data = await res.json().catch(() => ({}))
        setDuplicateHint(
          (data as { detail?: string }).detail
            ?? 'Member already has active access to this pathway.',
        )
        return
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error((data as { detail?: string }).detail ?? `Error ${res.status}`)
      }
      const data = await res.json() as GrantAccessResult
      setResult(data)
    } catch (e) {
      setSubmitError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

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
            <h2 className="font-serif text-[18px]" style={{ color: INK }}>Grant pathway access</h2>
            <p className="mt-1 text-[12.5px]" style={SERIF_ITALIC}>
              Provide access without recording a payment or creating creator earnings.
            </p>
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

        {result ? (
          <div className="px-6 py-8 text-center">
            <div
              className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
              style={{ background: WM_HUE.teal.bg }}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={WM_HUE.teal.text} strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <p className="font-serif text-[17px]" style={{ color: INK }}>
              {result.reactivated ? 'Access restored' : 'Access granted'}
            </p>
            <p className="mt-1 text-[13px]" style={SERIF_ITALIC}>
              {result.member_name ?? result.member_email} now has access to{' '}
              <span style={{ color: INK, fontStyle: 'normal' }}>{result.pathway_title}</span>
              {' '}in {result.space_name}.
            </p>
            <div className="mx-auto mt-4 max-w-xs rounded-xl p-4 text-left text-[13px]" style={{ background: PAGE_BG, border: HAIRLINE }}>
              <div className="flex justify-between py-1">
                <span style={{ color: INK_MUTED }}>Reason</span>
                <span style={{ color: INK }}>{reasonLabel(result.reason)}</span>
              </div>
              {result.note && (
                <div className="mt-1 flex justify-between gap-3 py-1">
                  <span style={{ color: INK_MUTED }}>Note</span>
                  <span style={{ color: INK, textAlign: 'right' }}>{result.note}</span>
                </div>
              )}
            </div>
            <button
              onClick={() => { onSuccess(); onClose() }}
              className="mt-5 inline-block rounded-full px-6 py-2 text-[13px] font-semibold transition-opacity hover:opacity-90"
              style={{
                background: WM_HUE.teal.bg,
                border: `1px solid ${WM_HUE.teal.border}`,
                color: WM_HUE.teal.text,
              }}
            >
              Done
            </button>
          </div>
        ) : loadingOptions ? (
          <div className="flex items-center justify-center gap-2 px-6 py-10 text-[14px]" style={{ color: INK_MUTED }}>
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
            Loading…
          </div>
        ) : optionsError ? (
          <div className="px-6 py-6 text-[14px]" style={{ color: WM_HUE.coral.text }}>{optionsError}</div>
        ) : (
          <div className="px-6 py-5 space-y-4">
            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
                Member
              </label>
              <select
                className="w-full rounded-lg px-3 py-2 text-[14px] outline-none focus:border-teal-300"
                style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
                value={memberUserId}
                onChange={(e) => { setMemberUserId(e.target.value); setDuplicateHint(null) }}
              >
                <option value="">Select a member…</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name ? `${u.name} (${u.email})` : u.email}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
                Pathway
              </label>
              <select
                className="w-full rounded-lg px-3 py-2 text-[14px] outline-none focus:border-teal-300"
                style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
                value={pathwayId}
                onChange={(e) => { setPathwayId(e.target.value); setDuplicateHint(null) }}
              >
                <option value="">Select a paid pathway…</option>
                {pathways.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.space_name} — {p.title}
                  </option>
                ))}
              </select>
              {pathways.length === 0 && (
                <p className="mt-1 text-[12px]" style={{ color: INK_MUTED }}>No paid pathways found.</p>
              )}
            </div>

            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
                Reason
              </label>
              <div className="space-y-1.5">
                {GRANT_REASON_OPTIONS.map((opt) => {
                  const active = reason === opt.value
                  return (
                    <label
                      key={opt.value}
                      className="flex cursor-pointer items-start gap-2.5 rounded-xl px-3 py-2 transition-colors"
                      style={{
                        background: active ? WM_HUE.teal.bg : '#FFFFFF',
                        border: `1px solid ${active ? WM_HUE.teal.border : '#E7EEF0'}`,
                      }}
                    >
                      <input
                        type="radio"
                        name="grant-reason"
                        checked={active}
                        onChange={() => setReason(opt.value)}
                        className="mt-1 accent-teal-500"
                      />
                      <span>
                        <span className="block text-[13px] font-semibold" style={{ color: active ? WM_HUE.teal.text : INK }}>
                          {opt.label}
                        </span>
                        {opt.hint && (
                          <span className="mt-0.5 block text-[11.5px]" style={SERIF_ITALIC}>
                            {opt.hint}
                          </span>
                        )}
                      </span>
                    </label>
                  )
                })}
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
                Note {noteRequired
                  ? <span className="font-normal normal-case" style={{ color: WM_HUE.coral.text }}>(required)</span>
                  : <span className="font-normal normal-case" style={{ color: INK_MUTED }}>(optional but recommended)</span>}
              </label>
              <input
                type="text"
                className="w-full rounded-lg px-3 py-2 text-[14px] outline-none focus:border-teal-300"
                style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
                placeholder={noteRequired ? 'Explain the reason for this grant' : 'Optional context for the audit trail'}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </div>

            {duplicateHint && (
              <div
                className="rounded-lg px-4 py-3 text-[13px]"
                style={{ background: WM_HUE.gold.bg, border: `1px solid ${WM_HUE.gold.border}`, color: WM_HUE.gold.text }}
              >
                {duplicateHint}
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
        )}
      </div>
    </div>
  )
}

function reasonLabel(reason: string): string {
  return GRANT_REASON_OPTIONS.find((r) => r.value === reason)?.label ?? reason
}
