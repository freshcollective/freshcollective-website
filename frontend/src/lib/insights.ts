/**
 * The World Insights client for the shared reporting API.
 *
 * Every figure on a World Insights page comes from
 * `/api/admin/reporting/*`, and every figure arrives with its own
 * definition — the metric registry returns the prose, the source table,
 * the event date it attributes by, how it may be aggregated and what it
 * cannot yet tell you. That is the whole point of the BI-2 design, so
 * this module keeps the definition attached to the value rather than
 * throwing it away at the boundary.
 *
 * There are deliberately no numbers in this file. Nothing is computed
 * client-side: a dashboard that does its own arithmetic is how two
 * surfaces start disagreeing, which is the problem the registry exists
 * to end.
 */

/** How a metric may be combined across periods. Returned by the API. */
export type Aggregation = 'additive' | 'snapshot' | 'distinct_count' | 'ratio'

/** Which timestamp a metric attributes a row to. */
export type DateBasis =
  | 'payment_settled'
  | 'refunded'
  | 'payout_marked'
  | 'created'
  | 'membership_joined'
  | 'business_event'
  | 'none'

export type Availability = 'full' | 'from_instrumentation' | 'partial'

/**
 * How a number reads — declared by the metric, never inferred here.
 *
 * Separate from `Aggregation`, which says how values combine. Treating
 * the two as one thing produced a real misreport: `memberships_per_member`
 * aggregates as a ratio, this module read "ratio" as "percentage", and
 * 1.83 memberships per person was displayed as 183%.
 */
export type Unit = 'count' | 'money_cents' | 'proportion' | 'rate'

export interface MetricDefinition {
  key: string
  display_name: string
  /** Written for the person reading the dashboard, not for a developer. */
  definition: string
  source_of_truth: string
  grain: 'snapshot' | 'period'
  aggregation: Aggregation
  /**
   * What kind of quantity this is. Drives formatting.
   *
   * Optional because the two services deploy independently and in no
   * guaranteed order, so fc-web can briefly be newer than fc-api and
   * receive a definition without it. `formatValue` falls back to the
   * key convention for exactly that window.
   */
  unit?: Unit
  /**
   * True when a past day cannot be reconstructed, only observed.
   *
   * A Collective's status is stored as one value with no history behind
   * it, so its trend begins when nightly recording began. Charts must
   * draw the earlier span as a gap, never as zero. Optional for the same
   * deploy-ordering reason as `unit`.
   */
  observation_only?: boolean
  date_basis: DateBasis
  access: 'platform_only' | 'creator_visible'
  availability: Availability
  /** What this figure cannot tell you. Shown beside it, not buried. */
  limitations: string | null
  dimensions: string[]
  personal_data: boolean
}

export interface MetricValue {
  key: string
  value: number | null
  available: boolean
  /** Why there is no number. Shown instead of a misleading zero. */
  unavailable_reason: string | null
  /** Facts about this particular result — settlement basis, excluded
   *  rows, per-kind breakdowns. Shapes vary by metric. */
  qualifiers: Record<string, unknown>
  definition: MetricDefinition
}

export interface PeriodBounds {
  label: string
  starts_at: string | null
  ends_at: string | null
}

export interface MetricResult {
  period: PeriodBounds
  /** Absent for all-time, where there is nothing to compare against. */
  comparison: PeriodBounds | null
  metrics: MetricValue[]
  comparison_metrics: MetricValue[] | null
}

export type PeriodKey = 'this_month' | 'last_month' | 'this_fy' | 'all_time'

/** The period choices, in the order a caretaker thinks about them. */
export const PERIOD_OPTIONS: [PeriodKey, string][] = [
  ['this_month', 'This month'],
  ['last_month', 'Last month'],
  ['this_fy', 'This financial year'],
  ['all_time', 'All time'],
]

export interface ReportingCheck {
  name: string
  ok: boolean
  missing: number
  pre_activation: number
  unreconstructable: number
  sample_ids: string[]
  note: string | null
}

export interface ReportingHealth {
  recording_enabled: boolean
  activation_floor: string | null
  events_total: number
  latest_event_at: string | null
  event_counts_by_type: Record<string, number>
  ok: boolean
  total_missing: number
  checks: ReportingCheck[]
  aggregates: {
    oldest_latest_reporting_date: string | null
    newest_latest_reporting_date: string | null
    metrics_stored: number
    rows_total: number
    per_metric: Record<
      string,
      { latest_reporting_date: string | null; computed_at: string | null }
    >
  }
  last_run: ReportingJobRun | null
  last_successful_run: ReportingJobRun | null
  incomplete_runs: ReportingJobRun[]
  note: string | null
}

export interface ReportingJobRun {
  job_name: string
  status: 'running' | 'succeeded' | 'failed'
  started_at: string
  finished_at: string | null
  reporting_date_from: string | null
  reporting_date_to: string | null
  days_processed: number
  rows_written: number
  error: string | null
}

/**
 * Fetch several metrics for one period, with the previous period
 * alongside.
 *
 * Batched in one request on purpose. Eight separate calls would each
 * resolve the reporting period separately, and two surfaces resolving
 * the same period independently is exactly how the figures drift apart.
 */
export async function fetchMetrics(
  keys: string[],
  period: PeriodKey,
  signal?: AbortSignal,
): Promise<MetricResult> {
  const query = new URLSearchParams({ keys: keys.join(','), period })
  const res = await fetch(`/api/admin/reporting/query?${query}`, {
    credentials: 'include',
    signal,
  })
  if (!res.ok) throw new Error(await describeFailure(res))
  return (await res.json()) as MetricResult
}

export async function fetchHealth(signal?: AbortSignal): Promise<ReportingHealth> {
  const res = await fetch('/api/admin/reporting/health', {
    credentials: 'include',
    signal,
  })
  if (!res.ok) throw new Error(await describeFailure(res))
  return (await res.json()) as ReportingHealth
}

export async function fetchCatalogue(
  signal?: AbortSignal,
): Promise<MetricDefinition[]> {
  const res = await fetch('/api/admin/reporting/metrics', {
    credentials: 'include',
    signal,
  })
  if (!res.ok) throw new Error(await describeFailure(res))
  return (await res.json()) as MetricDefinition[]
}

/**
 * A message that says what to do, not just what broke.
 *
 * A signed-out session is the common case and reads as a 401, so it gets
 * its own sentence rather than a status code.
 */
async function describeFailure(res: Response): Promise<string> {
  if (res.status === 401 || res.status === 403) {
    return 'Your session has expired. Sign in again to see these figures.'
  }
  const body = (await res.json().catch(() => null)) as { detail?: string } | null
  if (body?.detail) return body.detail
  return `These figures could not be loaded (error ${res.status}).`
}

/** Pick one metric out of a result, by key. */
export function pick(result: MetricResult | null, key: string): MetricValue | null {
  return result?.metrics.find((m) => m.key === key) ?? null
}

/** The same metric from the comparison period, if there is one. */
export function pickPrevious(
  result: MetricResult | null,
  key: string,
): MetricValue | null {
  return result?.comparison_metrics?.find((m) => m.key === key) ?? null
}

/**
 * Whether a metric may be compared across the two periods at all.
 *
 * Ratios and distinct counts are not additive, but they *are* comparable
 * — "12% this month against 9% last month" is meaningful. What is never
 * meaningful is comparing a snapshot of a *period* against a snapshot of
 * another, since both describe a moment rather than a span; those are
 * shown as a single current figure instead.
 */
export function isComparable(definition: MetricDefinition): boolean {
  return definition.grain === 'period'
}

/** Money is stored in cents everywhere. */
export function isMoney(key: string): boolean {
  return key.endsWith('_cents')
}

export function formatMoney(cents: number, currency = 'AUD'): string {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(cents / 100)
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat('en-AU').format(value)
}

/** A proportion of a whole. Arrives as a fraction; people read percent. */
export function formatProportion(value: number): string {
  return `${(value * 100).toFixed(value < 0.1 ? 1 : 0)}%`
}

/**
 * A rate — one quantity per another unlike quantity.
 *
 * Read as a decimal, because it is not a part of anything. 1.83
 * memberships per person is not 183% of a person.
 */
export function formatRate(value: number): string {
  return value.toFixed(2).replace(/\.00$/, '')
}

/**
 * Format by what the metric says it is.
 *
 * The unit comes from the registry, so a new metric cannot be formatted
 * wrongly by this module failing to guess. `isMoney` stays as a fallback
 * for the key convention, in case a figure arrives before its unit does.
 */
export function formatValue(m: MetricValue): string {
  if (m.value === null) return '—'
  switch (m.definition.unit) {
    case 'money_cents':
      return formatMoney(m.value)
    case 'proportion':
      return formatProportion(m.value)
    case 'rate':
      return formatRate(m.value)
    case 'count':
      return formatCount(m.value)
  }
  return isMoney(m.key) ? formatMoney(m.value) : formatCount(m.value)
}

/**
 * A plain sentence comparing this period with the last.
 *
 * Written rather than rendered as an arrow and a percentage: "£120 more
 * than last month" is read correctly at a glance, and an arrow beside a
 * number needs a legend. Returns null when there is nothing honest to
 * say — no comparison period, or a previous value of zero, where a
 * percentage change is undefined rather than infinite.
 */
export function comparisonSentence(
  m: MetricValue,
  previous: MetricValue | null,
  previousLabel: string | null,
): string | null {
  if (!previous || previous.value === null || m.value === null) return null
  if (!previousLabel) return null
  const delta = m.value - previous.value
  if (delta === 0) return `Unchanged from ${previousLabel.toLowerCase()}.`
  const direction = delta > 0 ? 'more than' : 'less than'
  const magnitude = isMoney(m.key)
    ? formatMoney(Math.abs(delta))
    : formatCount(Math.abs(delta))
  if (previous.value === 0) {
    return `${magnitude} ${direction} ${previousLabel.toLowerCase()}, which was none.`
  }
  const pct = Math.round((Math.abs(delta) / previous.value) * 100)
  return `${magnitude} ${direction} ${previousLabel.toLowerCase()} (${pct}%).`
}

/**
 * A short, human note about what a figure cannot tell you.
 *
 * Drawn from the result's own qualifiers rather than from a hand-written
 * caption, so it stays true when the data changes. Returns null when
 * there is nothing to caveat — the common case, and silence is better
 * than a reassurance nobody asked for.
 */
export function qualifierNote(m: MetricValue): string | null {
  const q = m.qualifiers ?? {}
  if (typeof q.approximation_note === 'string') {
    const approximated = typeof q.approximated_rows === 'number' ? q.approximated_rows : 0
    if (approximated > 0) {
      return `${formatCount(approximated)} older ${
        approximated === 1 ? 'payment' : 'payments'
      } are dated by when they were created, not when they settled.`
    }
  }
  if (typeof q.fee_note === 'string') {
    const unknown = typeof q.rows_without_a_known_fee === 'number'
      ? q.rows_without_a_known_fee
      : 0
    if (unknown > 0) {
      return `Stripe has not yet reported a fee for ${formatCount(unknown)} ${
        unknown === 1 ? 'payment' : 'payments'
      }, so this is a lower bound.`
    }
  }
  if (q.provenance === 'reconstructed' && typeof q.caveat === 'string') {
    return 'Reconstructed from current records, so departures before we began recording history are not reflected.'
  }
  return null
}

/**
 * One sentence about whether these figures can be trusted.
 *
 * The order of the checks is the whole design. Awkward states are
 * reported ahead of reassuring ones, because a green light that cannot
 * go amber trains somebody to stop looking at it. Recording being switched
 * off comes first — with no events arriving, every other check is
 * answering a question about a stopped clock.
 *
 * "Nothing built yet" and "no activity yet" are deliberately *not*
 * faults. A quiet week on a small platform is normal, and the live
 * figures never depend on the nightly rebuild, so neither state is worth
 * raising an alarm about.
 */
export function describeHealth(
  health: ReportingHealth | null,
  failed: boolean,
): { hue: 'teal' | 'navy' | 'gold' | 'coral'; label: string } {
  if (failed) return { hue: 'gold', label: 'Data health unavailable' }
  if (!health) return { hue: 'navy', label: 'Checking data health…' }
  if (!health.recording_enabled) {
    return { hue: 'coral', label: 'History recording is off' }
  }
  if (health.incomplete_runs.length > 0) {
    return { hue: 'coral', label: 'A reporting run did not finish' }
  }
  if (health.last_run?.status === 'failed') {
    return { hue: 'coral', label: 'Last reporting run failed' }
  }
  if (health.total_missing > 0) {
    return { hue: 'gold', label: `${health.total_missing} to look at` }
  }
  if (health.aggregates.rows_total === 0) {
    return { hue: 'navy', label: 'Daily trends not built yet' }
  }
  return { hue: 'teal', label: 'Data looks healthy' }
}

/** Who an outstanding balance is actually owed to, and what kind of
 *  activity it came from. Both splits are reporting only — nothing in
 *  them has been treated as settled. */
export interface OutstandingBreakdown {
  externalCents: number
  founderCents: number
  byClass: Record<string, number>
}

/**
 * Read the ownership and classification split off an outstanding figure.
 *
 * Returns null rather than zeroes when the qualifiers are absent, so a
 * page shows nothing instead of asserting that nothing is owed to
 * anybody — a distinction that matters on exactly this figure.
 */
export function outstandingBreakdown(
  m: MetricValue | null,
): OutstandingBreakdown | null {
  const q = m?.qualifiers
  if (!q) return null
  const external = q.owed_to_external_creators_cents
  const founder = q.owed_to_founder_operated_collectives_cents
  if (typeof external !== 'number' || typeof founder !== 'number') return null
  const raw = q.by_reporting_class_cents
  const byClass: Record<string, number> = {}
  if (raw && typeof raw === 'object') {
    for (const [name, amount] of Object.entries(raw as Record<string, unknown>)) {
      if (typeof amount === 'number' && amount > 0) byClass[name] = amount
    }
  }
  return { externalCents: external, founderCents: founder, byClass }
}

/** `internal_operations` → `Internal operations`. */
export function humaniseClass(name: string): string {
  const words = name.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}
