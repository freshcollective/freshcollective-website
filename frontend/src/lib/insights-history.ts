/**
 * The historical charts: fetching, scales, and the rules of honest drawing.
 *
 * Everything a chart needs to decide is decided here, as a pure
 * function, for two reasons. The obvious one is that `npm test` runs
 * `src/**` + `*.test.ts` under the node runner and cannot mount a
 * React tree, so logic left inside a component is logic nothing tests.
 * The less obvious one is that the mistakes available to a chart are
 * arithmetic mistakes — a gap drawn as a zero, a bar scaled against the
 * wrong domain, a partial week drawn at full height — and those are
 * exactly the things a unit test can pin.
 *
 * No figure is computed here. Values arrive from
 * `/api/admin/reporting/history` already aggregated by the metric
 * registry, with their provenance and completeness attached. This file
 * turns numbers into geometry; it never turns numbers into other
 * numbers.
 */

import { formatCount, formatMoney } from './insights.ts'

// ---------------------------------------------------------------------------
// Shapes, mirroring app/reporting/routes.py
// ---------------------------------------------------------------------------

export type Grouping = 'daily' | 'weekly' | 'monthly'

export type HistoryRangeKey =
  | 'last_30_days'
  | 'last_3_months'
  | 'last_12_months'
  | 'this_fy'
  | 'all_time'

export type PopulationKey =
  | 'all'
  | 'production'
  | 'internal_operations'
  | 'demonstration'
  | 'test'
  | 'unclassified'

export interface HistoryPoint {
  label: string
  starts_on: string
  ends_on: string
  value: number | null
  available: boolean
  unavailable_reason: string | null
  provenance: string | null
  complete: boolean
  clipped: boolean
  days_present: number
  days_expected: number
  partial_data: boolean
}

export interface HistorySeries {
  key: string
  display_name: string
  unit: 'count' | 'money_cents' | 'proportion' | 'rate'
  aggregation: string
  source: 'stored' | 'recomputed'
  definition: string
  limitations: string | null
  observation_only: boolean
  qualifiers: Record<string, unknown>
  points: HistoryPoint[]
}

export interface HistoryBucket {
  label: string
  starts_on: string
  ends_on: string
  complete: boolean
  clipped: boolean
}

export interface HistoryResult {
  range: {
    key: string
    label: string
    starts_on: string
    ends_on: string
    days: number
  }
  grouping: Grouping
  population: { key: PopulationKey; label: string; note: string }
  buckets: HistoryBucket[]
  series: HistorySeries[]
  options: {
    ranges: { key: HistoryRangeKey; label: string }[]
    groupings: Grouping[]
    populations: { key: PopulationKey; label: string; note: string }[]
  }
}

export const GROUPING_LABELS: Record<Grouping, string> = {
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
}

// ---------------------------------------------------------------------------
// Series colour
// ---------------------------------------------------------------------------

/**
 * The chart hues, in fixed order, drawn from the four World Management
 * accents and no others.
 *
 * **Fixed order, never cycled.** A series takes the slot its position
 * gives it and keeps it; the palette does not wrap round to teal for a
 * fifth line, because two series sharing a colour is indistinguishable
 * from one series. No chart on these pages needs more than three, and a
 * fourth would need a product conversation rather than a generated hue.
 *
 * **Colour follows the entity, not its rank.** Each panel names its
 * series' hues explicitly, so hiding one does not repaint the others.
 *
 * Validated as a categorical palette against a white chart surface:
 * lightness band, chroma floor, colour-vision separation and
 * normal-vision separation all pass. Gold alone falls below 3:1 contrast
 * against white, which is why every chart here ships a legend, direct
 * labels and a table view — that relief is required, not optional, and
 * darkening gold was tested and rejected because it collapses against
 * coral for a deuteranope.
 */
export const CHART_HUES = ['teal', 'navy', 'gold', 'coral'] as const

export type ChartHue = (typeof CHART_HUES)[number]

export const HUE_STROKE: Record<ChartHue, string> = {
  teal: '#22a598',
  navy: '#4c78d4',
  gold: '#d4b048',
  coral: '#d66057',
}

// ---------------------------------------------------------------------------
// Fetching
// ---------------------------------------------------------------------------

export async function fetchHistory(
  keys: string[],
  range: HistoryRangeKey,
  grouping: Grouping,
  population: PopulationKey,
  signal?: AbortSignal,
): Promise<HistoryResult> {
  const params = new URLSearchParams({
    keys: keys.join(','),
    range,
    grouping,
    population,
  })
  const res = await fetch(`/api/admin/reporting/history?${params}`, {
    signal,
    credentials: 'include',
  })
  if (!res.ok) {
    let detail = `Could not load history (${res.status}).`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // Keep the status-code message.
    }
    throw new Error(detail)
  }
  return res.json()
}

// ---------------------------------------------------------------------------
// Scales
// ---------------------------------------------------------------------------

export interface Domain {
  min: number
  max: number
  ticks: number[]
}

/**
 * A rounded axis domain over every value on the chart.
 *
 * Always includes zero. A column chart whose baseline is not zero
 * exaggerates every difference on it, and a membership line starting at
 * 1,180 rather than 0 turns a 2% month into a cliff. Both are in the
 * anti-pattern catalogue and neither is worth the vertical space saved.
 *
 * Negative values are honoured rather than clamped, because
 * contribution after processing costs can genuinely be negative and a
 * chart that floors it at zero would hide the only month worth looking
 * at.
 */
export function niceDomain(values: (number | null)[], targetTicks = 4): Domain {
  const present = values.filter((v): v is number => v !== null && Number.isFinite(v))
  if (present.length === 0) return { min: 0, max: 1, ticks: [0, 1] }

  const lo = Math.min(0, ...present)
  const hi = Math.max(0, ...present)
  if (lo === 0 && hi === 0) return { min: 0, max: 1, ticks: [0, 1] }

  const step = niceStep((hi - lo) / Math.max(1, targetTicks))
  const min = Math.floor(lo / step) * step
  const max = Math.ceil(hi / step) * step
  const ticks: number[] = []
  // Accumulate by index rather than by repeated addition: 0.1 added
  // thirty times is not 3, and a tick labelled 2.9999999999 is a bug
  // the reader sees.
  for (let i = 0; min + i * step <= max + step / 1000; i += 1) {
    ticks.push(round(min + i * step))
  }
  return { min, max, ticks }
}

/** The next 1 / 2 / 5 × 10ⁿ at or above `rough`. */
export function niceStep(rough: number): number {
  if (!(rough > 0)) return 1
  const mag = 10 ** Math.floor(Math.log10(rough))
  const scaled = rough / mag
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10
  return step * mag
}

function round(n: number): number {
  return Math.round(n * 1e6) / 1e6
}

/** Map a value onto a pixel y, top-down, inside a plot of `height`. */
export function scaleY(value: number, domain: Domain, height: number): number {
  const span = domain.max - domain.min || 1
  return height - ((value - domain.min) / span) * height
}

// ---------------------------------------------------------------------------
// Gaps
// ---------------------------------------------------------------------------

/**
 * Contiguous runs of indices that actually have a value.
 *
 * The reason a line chart here is not a single `path`. A metric with no
 * figure for March must show a break in March, not a straight line from
 * February to April — that line is an assertion about March that nobody
 * made. Each run becomes its own path, and a run of one becomes a dot,
 * because a single known point between two gaps is still information.
 */
export function valueSegments(values: (number | null)[]): number[][] {
  const runs: number[][] = []
  let current: number[] = []
  values.forEach((v, i) => {
    if (v === null || !Number.isFinite(v)) {
      if (current.length) runs.push(current)
      current = []
    } else {
      current.push(i)
    }
  })
  if (current.length) runs.push(current)
  return runs
}

/** An SVG path through already-projected points. */
export function linePath(points: { x: number; y: number }[]): string {
  if (points.length === 0) return ''
  return points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${r(p.x)} ${r(p.y)}`)
    .join(' ')
}

function r(n: number): number {
  return Math.round(n * 100) / 100
}

// ---------------------------------------------------------------------------
// Stacking
// ---------------------------------------------------------------------------

export interface StackSegment {
  seriesIndex: number
  from: number
  to: number
}

/**
 * Stack several series at one bucket, skipping the unavailable.
 *
 * Only legitimate where the series genuinely partition a whole — the
 * overlap buckets, which the backend guarantees sum to unique members
 * for the same date. A stack of unrelated metrics invites reading the
 * total as meaningful when it is not.
 *
 * A missing series is omitted rather than treated as zero, so a stack
 * with a hole in it is visibly shorter instead of silently complete.
 */
export function stackAt(
  seriesValues: (number | null)[][],
  index: number,
): StackSegment[] {
  const out: StackSegment[] = []
  let cursor = 0
  seriesValues.forEach((values, seriesIndex) => {
    const v = values[index]
    if (v === null || v === undefined || !Number.isFinite(v)) return
    out.push({ seriesIndex, from: cursor, to: cursor + v })
    cursor += v
  })
  return out
}

/** The stacked total at each bucket, or null where nothing is known. */
export function stackTotals(seriesValues: (number | null)[][]): (number | null)[] {
  const length = Math.max(0, ...seriesValues.map((s) => s.length))
  const out: (number | null)[] = []
  for (let i = 0; i < length; i += 1) {
    const segments = stackAt(seriesValues, i)
    out.push(segments.length ? segments[segments.length - 1].to : null)
  }
  return out
}

// ---------------------------------------------------------------------------
// Axis labels
// ---------------------------------------------------------------------------

/**
 * Which bucket labels to print, so they never collide.
 *
 * Returns indices, always including the first and last. Thinning by a
 * stride rather than by rotating the text: a 365-bucket daily axis
 * cannot be labelled at all, and tilted labels are harder to read than
 * fewer labels.
 */
export function xTickIndices(count: number, maxLabels: number): number[] {
  if (count <= 0) return []
  if (count <= maxLabels) return Array.from({ length: count }, (_, i) => i)
  const stride = Math.ceil(count / Math.max(1, maxLabels))
  const out: number[] = []
  for (let i = 0; i < count; i += stride) out.push(i)

  const last = count - 1
  if (out[out.length - 1] !== last) {
    // The final period is always labelled, but appending it blindly can
    // place it a single bucket from its neighbour — which collides at
    // exactly the narrow widths that forced the thinning. Where it
    // would land too close, it replaces that neighbour instead.
    if (last - out[out.length - 1] < stride / 2) out.pop()
    out.push(last)
  }
  return out
}

/** A bucket's label, shortened for an axis tick. */
export function shortBucketLabel(label: string, grouping: Grouping): string {
  if (grouping === 'monthly') return label.replace(/ \d{4}$/, '')
  const iso = label.replace(/^w\/c /, '')
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return label
  const month = MONTHS[Number(m[2]) - 1]
  return `${Number(m[3])} ${month}`
}

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

// ---------------------------------------------------------------------------
// Value formatting
// ---------------------------------------------------------------------------

/** A compact axis label: `$1.2k`, `1.2k`, `12%`. */
export function formatAxisValue(unit: HistorySeries['unit'], value: number): string {
  if (unit === 'money_cents') return compactMoney(value)
  if (unit === 'proportion') return `${Math.round(value * 100)}%`
  if (unit === 'rate') return String(Math.round(value * 100) / 100)
  return compactCount(value)
}

export function compactMoney(cents: number): string {
  const sign = cents < 0 ? '-' : ''
  const dollars = Math.abs(cents) / 100
  if (dollars >= 1_000_000) return `${sign}$${trim(dollars / 1_000_000)}m`
  if (dollars >= 1_000) return `${sign}$${trim(dollars / 1_000)}k`
  return `${sign}$${Math.round(dollars)}`
}

export function compactCount(value: number): string {
  const sign = value < 0 ? '-' : ''
  const n = Math.abs(value)
  if (n >= 1_000_000) return `${sign}${trim(n / 1_000_000)}m`
  if (n >= 1_000) return `${sign}${trim(n / 1_000)}k`
  return `${sign}${n}`
}

function trim(n: number): string {
  return (Math.round(n * 10) / 10).toString()
}

/** The full-precision value for a tooltip or a table cell. */
export function formatExactValue(
  unit: HistorySeries['unit'],
  value: number,
): string {
  if (unit === 'money_cents') return formatMoney(value)
  if (unit === 'proportion') return `${(value * 100).toFixed(1)}%`
  if (unit === 'rate') return (Math.round(value * 100) / 100).toFixed(2)
  return formatCount(value)
}

// ---------------------------------------------------------------------------
// Saying what the chart shows, in words
// ---------------------------------------------------------------------------

/**
 * Why a point has no value, in one phrase for a tooltip.
 *
 * Three different facts live behind a missing figure and the reader
 * needs to know which: nobody has built that period, the metric cannot
 * be reconstructed for it, or it is still running.
 */
export function describeGap(point: HistoryPoint): string {
  if (point.unavailable_reason) return point.unavailable_reason
  if (!point.complete) return 'This period has not finished yet.'
  return 'No figure is available for this period.'
}

/** The qualification a point carries even when it has a value. */
export function pointCaveats(point: HistoryPoint): string[] {
  const out: string[] = []
  if (!point.complete) out.push('Still in progress — not a full period.')
  if (point.clipped) {
    out.push(
      `Covers ${point.days_expected === 1 ? '1 day' : `${point.days_expected} days`}` +
        ' of a shorter span than the others, because the range starts or ends mid-period.',
    )
  }
  if (point.partial_data) {
    out.push(
      `Built from ${point.days_present} of ${point.days_expected} days — ` +
        'the rest were never recorded.',
    )
  }
  if (point.provenance === 'reconstructed') {
    out.push('Reconstructed from current records, not recorded at the time.')
  }
  if (point.provenance === 'observed_late') {
    out.push('Recorded a day or more after the period it describes.')
  }
  return out
}

/**
 * One sentence per series, for the chart's accessible description.
 *
 * Read by a screen reader in place of the SVG. It names the direction
 * and the endpoints rather than every point, and says outright when
 * periods are missing — a description that implied a complete line
 * would be worse than no description.
 */
export function describeSeries(series: HistorySeries): string {
  const known = series.points.filter((p) => p.available && p.value !== null)
  const gaps = series.points.length - known.length
  if (known.length === 0) {
    return `${series.display_name}: no figures available for this range.`
  }
  const first = known[0]
  const last = known[known.length - 1]
  const from = formatExactValue(series.unit, first.value as number)
  const to = formatExactValue(series.unit, last.value as number)
  const direction =
    known.length === 1
      ? 'a single period'
      : (last.value as number) > (first.value as number)
        ? 'rising'
        : (last.value as number) < (first.value as number)
          ? 'falling'
          : 'flat'
  const gapNote =
    gaps > 0
      ? ` ${gaps} of ${series.points.length} periods have no figure and are shown as gaps.`
      : ''
  return (
    `${series.display_name}: ${direction}, from ${from} (${first.label})` +
    ` to ${to} (${last.label}).${gapNote}`
  )
}

/** The provenance disclosure for a whole series, if it needs one. */
export function seriesProvenanceNote(series: HistorySeries): string | null {
  const points = series.points.filter((p) => p.available)
  if (points.length === 0) return null
  const kinds = new Set(points.map((p) => p.provenance).filter(Boolean))
  if (kinds.size === 0) return null
  const parts: string[] = []
  if (kinds.has('reconstructed')) {
    parts.push(
      'Some periods are reconstructed from current records rather than ' +
        'recorded at the time.',
    )
  }
  if (kinds.has('observed_late')) {
    parts.push(
      'Some periods were recorded a day or more after the day they describe.',
    )
  }
  if (parts.length === 0 && kinds.has('observed')) return null
  return parts.join(' ') || null
}

/** True when any point is missing, so a panel can say so once. */
export function hasGaps(series: HistorySeries[]): boolean {
  return series.some((s) => s.points.some((p) => !p.available))
}

/**
 * Split a run of indices into stretches that share a dash state.
 *
 * A line entering an unfinished period must not look like a finished
 * one: five days of a week drawn solid alongside full weeks reads as a
 * sudden drop. Drawing those joins dashed says "this part is still
 * moving" without removing the information.
 *
 * Grouped rather than emitted per segment because in practice only the
 * first and last buckets of a range are ever partial, so a run of fifty
 * weeks becomes two or three paths instead of fifty.
 */
export function dashRuns(
  indices: number[],
  isPartial: (index: number) => boolean,
): { dashed: boolean; indices: number[] }[] {
  if (indices.length === 0) return []
  if (indices.length === 1) {
    return [{ dashed: isPartial(indices[0]), indices: [...indices] }]
  }
  const out: { dashed: boolean; indices: number[] }[] = []
  for (let i = 0; i < indices.length - 1; i += 1) {
    const a = indices[i]
    const b = indices[i + 1]
    // A join is dashed when either period it connects is partial.
    const dashed = isPartial(a) || isPartial(b)
    const tail = out[out.length - 1]
    if (tail && tail.dashed === dashed) tail.indices.push(b)
    else out.push({ dashed, indices: [a, b] })
  }
  return out
}

/** Buckets where no series has a figure at all — a true blank in the chart. */
export function emptyBucketIndices(series: HistorySeries[]): number[] {
  const length = Math.max(0, ...series.map((s) => s.points.length))
  const out: number[] = []
  for (let i = 0; i < length; i += 1) {
    const anyValue = series.some((s) => {
      const p = s.points[i]
      return p && p.available && p.value !== null
    })
    if (!anyValue) out.push(i)
  }
  return out
}

/**
 * Nudge direct labels apart so two never sit on top of one another.
 *
 * Direct labels are what stop identity resting on colour alone, so they
 * have to stay legible exactly when the series converge — which is
 * precisely when their natural positions collide. Returns a y per
 * label, in the input order, each at least `minGap` from its
 * neighbours and all inside `bounds`.
 *
 * Resolved by sorting, spreading downward, then pulling back if the
 * stack overflows the bottom. Deliberately stable: equal inputs keep
 * their original order, so a label does not swap sides between renders.
 */
export function spreadLabels(
  ys: number[],
  minGap: number,
  bounds: [number, number],
): number[] {
  if (ys.length === 0) return []
  const order = ys
    .map((y, i) => ({ y, i }))
    .sort((a, b) => a.y - b.y || a.i - b.i)

  const [top, bottom] = bounds
  let cursor = top
  for (const item of order) {
    item.y = Math.max(item.y, cursor)
    cursor = item.y + minGap
  }
  // Spreading downward can push the last label past the bottom; walk
  // back up, which cannot reintroduce a collision because every step
  // moves a label earlier by at most the overflow.
  const overflow = order[order.length - 1].y - bottom
  if (overflow > 0) {
    let limit = bottom
    for (let k = order.length - 1; k >= 0; k -= 1) {
      order[k].y = Math.min(order[k].y, limit)
      limit = order[k].y - minGap
    }
  }
  const out = new Array<number>(ys.length)
  for (const item of order) out[item.i] = item.y
  return out
}
