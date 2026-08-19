'use client'

/**
 * FIP4C — Creator Studio Payment Plans view.
 *
 * Plan-level companion to Payments received. Answers "what agreement
 * is this member in?" and "how far through it are they?" — kept
 * deliberately compact so it doesn't compete with the ledger.
 *
 * No provider ids ever reach this UI. No member-recovery / retry
 * actions surface here; member repair remains member-led via the
 * FIP4B2 flow.
 *
 * "Paid to date" reflects the CONTRACTUAL sum of succeeded
 * instalment amounts (FIP4A: PaymentTransaction.gross_amount_cents
 * is the contractual instalment amount even when Stripe customer-
 * balance credit contributed to settlement). It is deliberately NOT
 * labelled "Cash received"; a cash-settlement view would need a
 * separate accounting model and is out of scope for FIP4C.
 */

import { useEffect, useMemo, useState } from 'react'
import { apiUrl } from '@/lib/api'

interface CreatorPurchasePlanSummary {
  id: string
  status:
    | 'pending_setup'
    | 'active'
    | 'payment_problem'
    | 'suspended'
    | 'completed'
    | 'failed'
    | 'cancelled'
  member_user_id: string
  member_name: string | null
  member_email: string | null
  space_id: string
  space_name: string | null
  payment_option_id: string
  payment_option_name: string | null
  payment_option_schedule_id: string | null
  installments_paid: number
  installments_expected: number
  currency: string
  total_amount_cents: number
  paid_amount_cents: number
  remaining_amount_cents: number
  created_at: string
  activated_at: string | null
  payment_problem_started_at: string | null
  grace_expires_at: string | null
  suspended_at: string | null
  reinstated_at: string | null
  completed_at: string | null
  cancelled_at: string | null
}

const STATUS_LABEL: Record<CreatorPurchasePlanSummary['status'], string> = {
  active: 'Active',
  payment_problem: 'Payment problem',
  suspended: 'Suspended',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  pending_setup: 'Pending setup',
}

const STATUS_BADGE_CLASS: Record<CreatorPurchasePlanSummary['status'], string> = {
  active:          'bg-teal-50 text-teal-700 border-teal-200',
  // Stronger contrast for attention states (amber for grace,
  // terracotta for suspended) so the badge reads clearly even at
  // a glance across a long table.
  payment_problem: 'bg-amber-100 text-amber-900 border-amber-300',
  suspended:       'bg-orange-100 text-orange-900 border-orange-300',
  completed:       'bg-slate-100 text-slate-600 border-slate-200',
  failed:          'bg-red-50 text-red-700 border-red-200',
  cancelled:       'bg-slate-100 text-slate-500 border-slate-200',
  pending_setup:   'bg-slate-100 text-slate-500 border-slate-200',
}

// Per-row background tint + left accent for attention states. The
// tint is deliberately subtle — enough that the row stands out from
// Active/Completed neighbours without dominating the page. Non-
// attention rows return empty style so nothing else changes visually.
function attentionRowStyle(status: CreatorPurchasePlanSummary['status']): React.CSSProperties {
  if (status === 'payment_problem') {
    return {
      background: 'rgba(212, 176, 72, 0.05)',
      boxShadow: 'inset 3px 0 0 0 #B45309',
    }
  }
  if (status === 'suspended') {
    return {
      background: 'rgba(180, 83, 9, 0.05)',
      boxShadow: 'inset 3px 0 0 0 #B45309',
    }
  }
  return {}
}

// One-line explanatory secondary text under the status badge for
// attention states. Uses "member is …" framing to keep it truthful:
// FIP4B2 makes recovery member-led, so nothing here should imply the
// creator has an action to take.
function attentionExplanation(status: CreatorPurchasePlanSummary['status']): string | null {
  if (status === 'payment_problem') {
    return 'Member is within their grace period.'
  }
  if (status === 'suspended') {
    return 'Member access is currently paused.'
  }
  return null
}

// Order of the filter pills. Non-terminal / interesting states first.
const FILTER_PILLS: Array<{ key: string; label: string; statuses: CreatorPurchasePlanSummary['status'][] }> = [
  { key: 'default', label: 'Active view', statuses: ['active', 'payment_problem', 'suspended', 'completed'] },
  // A convenience pill for the attention states: same set the
  // "Needs attention" summary panel filters into.
  { key: 'attention', label: 'Needs attention', statuses: ['payment_problem', 'suspended'] },
  { key: 'active', label: 'Active', statuses: ['active'] },
  { key: 'payment_problem', label: 'Payment problem', statuses: ['payment_problem'] },
  { key: 'suspended', label: 'Suspended', statuses: ['suspended'] },
  { key: 'completed', label: 'Completed', statuses: ['completed'] },
  { key: 'failed', label: 'Failed', statuses: ['failed'] },
  { key: 'cancelled', label: 'Cancelled', statuses: ['cancelled'] },
  { key: 'pending_setup', label: 'Pending setup', statuses: ['pending_setup'] },
  { key: 'all', label: 'All', statuses: [] }, // empty means "all"
]

function fmt(cents: number, currency: string): string {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: 2,
  }).format(cents / 100)
}

function fmtDate(iso: string | null): string | null {
  if (!iso) return null
  return new Date(iso).toLocaleDateString('en-AU', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

function StatusBadge({ status }: { status: CreatorPurchasePlanSummary['status'] }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${STATUS_BADGE_CLASS[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  )
}

function ProgressBar({ paid, expected, status }: {
  paid: number; expected: number; status: CreatorPurchasePlanSummary['status']
}) {
  const pct = expected > 0 ? Math.round((paid / expected) * 100) : 0
  const barColour =
    status === 'suspended' ? '#B45309'
    : status === 'payment_problem' ? '#8A6A15'
    : status === 'completed' ? '#94A3B8'
    : '#38A09E'
  return (
    <div className="w-full">
      <div className="mb-1 text-[11px] text-black">
        {paid} of {expected} paid
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full transition-all"
          style={{ width: `${pct}%`, background: barColour }}
        />
      </div>
    </div>
  )
}

/**
 * The most useful "when" for each status — shown as a small
 * secondary line so creators don't need to expand a row to see it.
 * All values are optional; renders empty when the timestamp is null.
 */
function KeyDate({ plan }: { plan: CreatorPurchasePlanSummary }): React.ReactNode {
  if (plan.status === 'payment_problem') {
    const d = fmtDate(plan.grace_expires_at)
    if (d) return <span className="text-amber-800">Grace until {d}</span>
  }
  if (plan.status === 'suspended') {
    const d = fmtDate(plan.suspended_at)
    if (d) return <span className="text-orange-700">Suspended {d}</span>
  }
  if (plan.status === 'completed') {
    const d = fmtDate(plan.completed_at)
    if (d) return <span className="text-slate-500">Completed {d}</span>
  }
  if (plan.status === 'cancelled') {
    const d = fmtDate(plan.cancelled_at)
    if (d) return <span className="text-slate-500">Cancelled {d}</span>
  }
  if (plan.status === 'failed') {
    const d = fmtDate(plan.cancelled_at) ?? fmtDate(plan.created_at)
    if (d) return <span className="text-red-600">Ended {d}</span>
  }
  if (plan.status === 'active') {
    const d = fmtDate(plan.activated_at ?? plan.created_at)
    if (d) return <span className="text-slate-500">Since {d}</span>
  }
  if (plan.status === 'pending_setup') {
    const d = fmtDate(plan.created_at)
    if (d) return <span className="text-slate-500">Started {d}</span>
  }
  return null
}

export default function CreatorPaymentPlansClient() {
  const [rows, setRows] = useState<CreatorPurchasePlanSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Filter state — all client-side after a single server fetch.
  // A creator's plan volume is bounded enough that server filtering
  // is unnecessary; keeping the endpoint stateless makes the API
  // simpler and reuses one dataset for pill-switches and searches.
  const [pill, setPill] = useState<string>('default')
  const [optionFilter, setOptionFilter] = useState<string>('')
  const [memberSearch, setMemberSearch] = useState<string>('')

  useEffect(() => {
    // Fetch every visible-by-default status in one go so the pill
    // switches feel instant. The "failed"/"cancelled"/"pending_setup"
    // pills need a follow-up fetch on demand — see below.
    const params = new URLSearchParams()
    for (const s of ['active', 'payment_problem', 'suspended', 'completed']) {
      params.append('status', s)
    }
    fetch(apiUrl(`/api/creator/payment-plans?${params.toString()}`), {
      credentials: 'include',
    })
      .then((r) => {
        if (!r.ok) throw new Error(`Error ${r.status}`)
        return r.json() as Promise<CreatorPurchasePlanSummary[]>
      })
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  // Lazy-fetch terminal statuses only when their pill is selected.
  const [terminalLoaded, setTerminalLoaded] = useState<Record<string, boolean>>({})
  useEffect(() => {
    const pillEntry = FILTER_PILLS.find((p) => p.key === pill)
    if (!pillEntry) return
    // If this pill selects a status we didn't fetch above and we
    // haven't already loaded it, fetch and merge.
    const need = pillEntry.statuses.filter(
      (s) => !terminalLoaded[s] && !['active', 'payment_problem', 'suspended', 'completed'].includes(s),
    )
    if (need.length === 0) return
    const params = new URLSearchParams()
    for (const s of need) params.append('status', s)
    fetch(apiUrl(`/api/creator/payment-plans?${params.toString()}`), {
      credentials: 'include',
    })
      .then((r) => (r.ok ? (r.json() as Promise<CreatorPurchasePlanSummary[]>) : []))
      .then((extra) => {
        setRows((prev) => {
          const seen = new Set(prev.map((p) => p.id))
          return [...prev, ...extra.filter((p) => !seen.has(p.id))]
        })
        setTerminalLoaded((prev) => ({ ...prev, ...Object.fromEntries(need.map((s) => [s, true])) }))
      })
      .catch(() => {/* non-fatal — pill will show empty */})
  }, [pill, terminalLoaded])

  // The "all" pill needs the terminal fetches too.
  useEffect(() => {
    if (pill !== 'all') return
    const need = ['failed', 'cancelled', 'pending_setup'].filter((s) => !terminalLoaded[s])
    if (need.length === 0) return
    const params = new URLSearchParams()
    for (const s of need) params.append('status', s)
    fetch(apiUrl(`/api/creator/payment-plans?${params.toString()}`), {
      credentials: 'include',
    })
      .then((r) => (r.ok ? (r.json() as Promise<CreatorPurchasePlanSummary[]>) : []))
      .then((extra) => {
        setRows((prev) => {
          const seen = new Set(prev.map((p) => p.id))
          return [...prev, ...extra.filter((p) => !seen.has(p.id))]
        })
        setTerminalLoaded((prev) => ({ ...prev, ...Object.fromEntries(need.map((s) => [s, true])) }))
      })
      .catch(() => {/* non-fatal */})
  }, [pill, terminalLoaded])

  // Options for the option-filter dropdown — derived from loaded data.
  const optionChoices = useMemo(() => {
    const map = new Map<string, string>()
    for (const r of rows) {
      map.set(r.payment_option_id, r.payment_option_name ?? '(Unnamed option)')
    }
    return Array.from(map.entries()).sort((a, b) => a[1].localeCompare(b[1]))
  }, [rows])

  // Attention counts driven by the loaded dataset. Both attention
  // states (payment_problem + suspended) are always included in the
  // default fetch, so this reflects the true total for the caller's
  // authorised scope without needing a separate endpoint call.
  // A dedicated backend attention-count endpoint powers the sidebar
  // badge — see CreatorStudioSidebar. This local count is just the
  // in-page total for the summary panel.
  const attention = useMemo(() => {
    const paymentProblem = rows.filter((r) => r.status === 'payment_problem').length
    const suspended = rows.filter((r) => r.status === 'suspended').length
    return { paymentProblem, suspended, total: paymentProblem + suspended }
  }, [rows])

  const filtered = useMemo(() => {
    const pillEntry = FILTER_PILLS.find((p) => p.key === pill) ?? FILTER_PILLS[0]
    let out = rows
    if (pillEntry.statuses.length > 0) {
      const allowed = new Set(pillEntry.statuses)
      out = out.filter((r) => allowed.has(r.status))
    }
    if (optionFilter) out = out.filter((r) => r.payment_option_id === optionFilter)
    if (memberSearch.trim()) {
      const needle = memberSearch.trim().toLowerCase()
      out = out.filter(
        (r) =>
          (r.member_name ?? '').toLowerCase().includes(needle) ||
          (r.member_email ?? '').toLowerCase().includes(needle),
      )
    }
    return out
  }, [rows, pill, optionFilter, memberSearch])

  return (
    <div className="mx-auto max-w-[1200px] px-5 py-6 md:px-8 md:py-10">
      <div className="mb-6">
        <h1 className="font-serif text-[1.8rem] leading-tight text-navy-900">Payment Plans</h1>
        <p className="mt-1 text-[13px] text-black">
          Member finite-instalment agreements. See who is on a plan,
          how far through they are, and whether a plan needs attention.
          Individual instalment payments live on{' '}
          <span className="font-medium">Payments received</span>; member
          card-repair is member-led.
        </p>
      </div>

      {loading && (
        <p className="text-[13px] text-slate-500">Loading…</p>
      )}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">
          Failed to load payment plans: {error}
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Needs-attention summary — compact panel above the
              filters, only when at least one plan in the caller's
              authorised scope is in payment_problem or suspended.
              Uses the same amber/terracotta palette as the member-
              facing FIP4B1 recovery banner. Deliberately no red
              error styling — this is an awareness signal, not an
              alarm. Clicking jumps the pill filter to the two
              attention states. */}
          {attention.total > 0 && (
            <div
              className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl px-4 py-3"
              style={{
                background: 'rgba(212, 176, 72, 0.10)',
                border: '1px solid rgba(180, 83, 9, 0.24)',
              }}
              role="status"
            >
              <div>
                <p
                  className="text-[13px] font-semibold"
                  style={{ color: '#8A6A15' }}
                >
                  {attention.total === 1
                    ? '1 payment plan needs attention'
                    : `${attention.total} payment plans need attention`}
                </p>
                <p className="mt-0.5 text-[12px] text-navy-900">
                  {attention.paymentProblem > 0 && (
                    <>
                      {attention.paymentProblem} payment problem
                      {attention.paymentProblem === 1 ? '' : 's'}
                    </>
                  )}
                  {attention.paymentProblem > 0 && attention.suspended > 0 && ' · '}
                  {attention.suspended > 0 && (
                    <>
                      {attention.suspended} suspended
                    </>
                  )}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setPill('attention')}
                className="inline-flex items-center rounded-full px-4 py-2 text-[12px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: '#8A6A15' }}
              >
                Show these plans
              </button>
            </div>
          )}

          {/* Filters */}
          <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex flex-wrap gap-1.5">
              {FILTER_PILLS.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => setPill(p.key)}
                  className={`rounded-full border px-3 py-1 text-[12px] font-medium transition-colors ${
                    pill === p.key
                      ? 'border-teal-500 bg-teal-50 text-teal-700'
                      : 'border-slate-200 bg-white text-black hover:border-slate-300'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <input
                type="search"
                value={memberSearch}
                onChange={(e) => setMemberSearch(e.target.value)}
                placeholder="Search member…"
                className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-[12px] text-navy-900 placeholder:text-slate-400 focus:border-teal-400 focus:outline-none"
              />
              <select
                value={optionFilter}
                onChange={(e) => setOptionFilter(e.target.value)}
                className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-[12px] text-navy-900 focus:border-teal-400 focus:outline-none"
              >
                <option value="">All Payment Options</option>
                {optionChoices.map(([id, name]) => (
                  <option key={id} value={id}>{name}</option>
                ))}
              </select>
            </div>
          </div>

          {filtered.length === 0 ? (
            <div
              className="rounded-2xl border border-dashed border-slate-200 bg-white px-6 py-10 text-center"
            >
              <p className="text-[14px] text-navy-900">No payment plans in this view.</p>
              <p className="mt-2 text-[12px] text-black">
                Payment plans appear here as soon as members purchase a
                Payment Option with a recurring-instalment schedule.
              </p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-2xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
              {/* Desktop table */}
              <div className="hidden overflow-x-auto lg:block">
                <table className="w-full text-left">
                  <thead>
                    <tr style={{ borderBottom: '1px solid #E2E8F0' }}>
                      {['Member', 'Payment Option', 'Status', 'Progress', 'Total', 'Paid to date', 'Remaining', 'Key date'].map((h) => (
                        <th key={h} className="px-3 py-3 text-[11px] font-semibold uppercase tracking-wider text-black">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((plan, i) => (
                      <tr
                        key={plan.id}
                        style={{
                          borderBottom: i < filtered.length - 1 ? '1px solid #F1F5F9' : undefined,
                          ...attentionRowStyle(plan.status),
                        }}
                      >
                        <td className="px-3 py-3">
                          <div className="text-[12.5px] font-medium text-navy-900">
                            {plan.member_name || plan.member_email || <span className="italic text-slate-400">Unknown</span>}
                          </div>
                          {plan.member_name && plan.member_email && (
                            <div className="text-[11px] text-black">{plan.member_email}</div>
                          )}
                        </td>
                        <td className="px-3 py-3">
                          <div className="text-[12.5px] text-navy-900">
                            {plan.payment_option_name || <span className="italic text-slate-400">—</span>}
                          </div>
                          <div className="text-[11px] text-black">
                            {plan.space_name}
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <StatusBadge status={plan.status} />
                          {attentionExplanation(plan.status) && (
                            <p className="mt-1 text-[11px] leading-snug text-navy-900">
                              {attentionExplanation(plan.status)}
                            </p>
                          )}
                        </td>
                        <td className="px-3 py-3 min-w-[140px]">
                          <ProgressBar
                            paid={plan.installments_paid}
                            expected={plan.installments_expected}
                            status={plan.status}
                          />
                        </td>
                        <td className="px-3 py-3 text-[12.5px] font-semibold text-navy-900 whitespace-nowrap">
                          {fmt(plan.total_amount_cents, plan.currency)}
                        </td>
                        <td className="px-3 py-3 text-[12.5px] text-navy-900 whitespace-nowrap">
                          {fmt(plan.paid_amount_cents, plan.currency)}
                        </td>
                        <td className="px-3 py-3 text-[12.5px] text-black whitespace-nowrap">
                          {fmt(plan.remaining_amount_cents, plan.currency)}
                        </td>
                        <td className="px-3 py-3 text-[11.5px] whitespace-nowrap">
                          <KeyDate plan={plan} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="divide-y divide-[#F1F5F9] lg:hidden">
                {filtered.map((plan) => (
                  <div key={plan.id} className="p-4" style={attentionRowStyle(plan.status)}>
                    <div className="mb-2 flex items-start justify-between gap-2">
                      <div>
                        <p className="text-[13px] font-medium text-navy-900">
                          {plan.member_name || plan.member_email || 'Unknown'}
                        </p>
                        <p className="text-[11px] text-black">
                          {plan.payment_option_name}
                          {plan.space_name ? ` · ${plan.space_name}` : ''}
                        </p>
                        {attentionExplanation(plan.status) && (
                          <p className="mt-1 text-[11px] leading-snug text-navy-900">
                            {attentionExplanation(plan.status)}
                          </p>
                        )}
                      </div>
                      <StatusBadge status={plan.status} />
                    </div>
                    <div className="mb-2">
                      <ProgressBar
                        paid={plan.installments_paid}
                        expected={plan.installments_expected}
                        status={plan.status}
                      />
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-[12px]">
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-black">Total</p>
                        <p className="font-semibold text-navy-900">{fmt(plan.total_amount_cents, plan.currency)}</p>
                      </div>
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-black">Paid</p>
                        <p className="text-navy-900">{fmt(plan.paid_amount_cents, plan.currency)}</p>
                      </div>
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-black">Remaining</p>
                        <p className="text-black">{fmt(plan.remaining_amount_cents, plan.currency)}</p>
                      </div>
                    </div>
                    <div className="mt-2 text-[11.5px]">
                      <KeyDate plan={plan} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
