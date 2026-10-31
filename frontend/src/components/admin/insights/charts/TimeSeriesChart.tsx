'use client'

import { useId, useMemo, useState } from 'react'

import {
  type ChartHue,
  type Grouping,
  type HistoryBucket,
  type HistorySeries,
  HUE_STROKE,
  dashRuns,
  describeGap,
  describeSeries,
  emptyBucketIndices,
  formatAxisValue,
  formatExactValue,
  linePath,
  niceDomain,
  pointCaveats,
  axisLabelSpace,
  directLabelSpace,
  scaleY,
  seriesKey,
  shortBucketLabel,
  spreadLabels,
  xLabelCapacity,
  tooltipLeft,
  stackAt,
  stackTotals,
  valueSegments,
  xTickIndices,
} from '@/lib/insights-history'
import { useChartWidth } from './useChartWidth'
import { ChartTable } from './ChartTable'

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'
const GRID = 'rgba(12, 24, 38, 0.08)'
const AXIS = 'rgba(12, 24, 38, 0.18)'
const SURFACE = '#FFFFFF'

//: Axis type. 11px was legible on a desktop and marginal on a phone at
//: the same physical size, and these are numbers somebody reads rather
//: than glances at.
const AXIS_FONT = 12
const LABEL_FONT = 11.5
const TOOLTIP_W = 250

/**
 * How tall a measured zero is drawn.
 *
 * A column of no height is indistinguishable from a period nobody
 * built, and the two mean opposite things — "we checked and nothing
 * happened" against "we do not know". Gaps carry a hatched band, and
 * this gives the zero its own small positive mark so neither has to be
 * inferred from the absence of the other.
 */
const ZERO_NUB = 2

export type ChartKind = 'line' | 'column' | 'stacked'

/**
 * One chart component for every historical graph on these pages.
 *
 * Three mark types rather than three components, because everything
 * around the marks — the zero-based axis, the thinned tick labels, the
 * gap bands, the partial-period dashing, the tooltip, the keyboard
 * cursor, the accessible description, the table — is identical and is
 * the part that is easy to get subtly wrong. A second implementation
 * would be a second place for a gap to become a zero.
 *
 * What the marks mean is decided by the metric, not by the caller's
 * taste: `line` for snapshots (a state at a moment, joined because the
 * line between two states is meaningful), `column` for additive flows
 * (separate quantities in separate periods, which should not be joined
 * at all), and `stacked` only where the series genuinely partition a
 * whole.
 *
 * Deliberately **one y axis**. Every pair charted here shares a unit —
 * counts with counts, cents with cents — so a second scale is never
 * needed, and a second scale is the single most misleading thing a
 * chart of two series can have.
 */
export function TimeSeriesChart({
  series,
  buckets,
  grouping,
  kind,
  hues,
  title,
  height = 220,
  showTable = false,
}: {
  series: HistorySeries[]
  buckets: HistoryBucket[]
  grouping: Grouping
  kind: ChartKind
  /** Explicit per series, so hiding one never repaints the others. */
  hues: ChartHue[]
  title: string
  height?: number
  showTable?: boolean
}) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '')
  const { ref, width, measured } = useChartWidth()
  const [active, setActive] = useState<number | null>(null)

  const unit = series[0]?.unit ?? 'count'
  const multi = series.length > 1

  const seriesValues = useMemo(
    () => series.map((s) => s.points.map((p) => (p.available ? p.value : null))),
    [series],
  )

  const domain = useMemo(() => {
    // Counts are whole things, so the axis steps in whole things.
    // Money is already an integer number of cents and its labels are
    // formatted as dollars, so it needs no such constraint.
    const opts = { integer: unit === 'count' }
    if (kind === 'stacked') {
      return niceDomain(stackTotals(seriesValues), 4, opts)
    }
    return niceDomain(seriesValues.flat(), 4, opts)
  }, [kind, seriesValues, unit])

  // Both paddings are measured from the text that will actually go in
  // them rather than guessed. A fixed 52px left margin is too much for
  // "40" and too little for "$2.5m"; a fixed right margin either
  // truncates a long series name or wastes plot on a short one.
  const padLeft = axisLabelSpace(
    domain.ticks.map((t) => formatAxisValue(unit, t)),
    AXIS_FONT,
  )
  const labelSpace = directLabelSpace(
    series.map((s) => s.display_name),
    width,
    LABEL_FONT,
  )
  const directLabels = labelSpace.show
  const pad = {
    top: 12,
    right: labelSpace.padRight,
    bottom: AXIS_FONT + 16,
    left: padLeft,
  }
  const plotW = Math.max(40, width - pad.left - pad.right)
  const plotH = Math.max(60, height - pad.top - pad.bottom)

  const n = buckets.length
  const bandW = n > 0 ? plotW / n : plotW
  const x = (i: number) => pad.left + bandW * (i + 0.5)
  const y = (v: number) => pad.top + scaleY(v, domain, plotH)
  const zeroY = y(0)

  const xLabels = useMemo(
    () => buckets.map((b) => shortBucketLabel(b.label, grouping)),
    [buckets, grouping],
  )
  const maxLabels = xLabelCapacity(xLabels, plotW, AXIS_FONT)
  const ticks = useMemo(() => xTickIndices(n, maxLabels), [n, maxLabels])
  const blanks = useMemo(() => emptyBucketIndices(series), [series])
  const isPartial = (i: number) => {
    const b = buckets[i]
    if (!b) return false
    if (!b.complete || b.clipped) return true
    return series.some((s) => s.points[i]?.partial_data)
  }

  const titleId = `chart-title-${uid}`
  const descId = `chart-desc-${uid}`

  const labelPositions = (() => {
    if (!directLabels) {
      return [] as ({ key: string; name: string; y: number } | null)[]
    }
    const raw = series.map((s, i) => {
      const values = seriesValues[i]
      const lastIndex = [...values.keys()].reverse().find((k) => values[k] !== null)
      if (lastIndex === undefined) return null
      if (kind === 'stacked') {
        const seg = stackAt(seriesValues, lastIndex).find((sg) => sg.seriesIndex === i)
        if (!seg) return null
        return { key: seriesKey(s), name: s.display_name, y: y((seg.from + seg.to) / 2) }
      }
      return { key: seriesKey(s), name: s.display_name, y: y(values[lastIndex] as number) }
    })
    const present = raw.filter((r): r is NonNullable<typeof r> => r !== null)
    const spread = spreadLabels(
      present.map((r) => r.y),
      LABEL_FONT + 3,
      [pad.top + 6, pad.top + plotH - 2],
    )
    let k = 0
    return raw.map((r) => (r === null ? null : { ...r, y: spread[k++] }))
  })()

  const announcement =
    active !== null && buckets[active]
      ? `${buckets[active].label}. ` +
        series
          .map((s) => {
            const p = s.points[active]
            return `${s.display_name}: ${
              p && p.available && p.value !== null
                ? formatExactValue(s.unit, p.value)
                : 'not available'
            }`
          })
          .join('. ')
      : ''

  function onKeyDown(e: React.KeyboardEvent) {
    if (n === 0) return
    const step = (delta: number) => {
      e.preventDefault()
      setActive((prev) => {
        const next = prev === null ? (delta > 0 ? 0 : n - 1) : prev + delta
        return Math.min(n - 1, Math.max(0, next))
      })
    }
    if (e.key === 'ArrowRight') step(1)
    else if (e.key === 'ArrowLeft') step(-1)
    else if (e.key === 'Home') {
      e.preventDefault()
      setActive(0)
    } else if (e.key === 'End') {
      e.preventDefault()
      setActive(n - 1)
    } else if (e.key === 'Escape') setActive(null)
  }

  return (
    <figure className="m-0">
      {/*
        The palette's own requirement, not decoration. Gold falls below
        3:1 against white, and such a hue is only legitimate beside
        visible labels or a table — both of which are here.
      */}
      {multi && (
        <ul className="mb-2 flex list-none flex-wrap gap-x-4 gap-y-1 p-0">
          {series.map((s, i) => (
            <li key={seriesKey(s)} className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: HUE_STROKE[hues[i] ?? 'teal'] }}
              />
              <span className="text-[12.5px]" style={{ color: INK_MUTED }}>
                {s.display_name}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div ref={ref} className="relative w-full" style={{ minHeight: height }}>
        {!measured ? (
          // Reserving the height means no layout shift when the real
          // chart replaces this, and no undersized chart in the frame
          // before the container has been measured.
          <div style={{ height }} aria-hidden="true" />
        ) : (
        <svg
          width="100%"
          height={height}
          viewBox={`0 0 ${Math.max(width, 1)} ${height}`}
          role="img"
          aria-labelledby={titleId}
          aria-describedby={descId}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onBlur={() => setActive(null)}
          className="block touch-pan-y outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
          style={{ overflow: 'hidden' }}
        >
          <title id={titleId}>{title}</title>

          <defs>
            {/* The CVD / print / forced-colours relief: a hatch per hue,
                used for periods that are not full periods. */}
            {(['teal', 'navy', 'gold', 'coral'] as ChartHue[]).map((hue) => (
              <pattern
                key={hue}
                id={`hatch-${hue}-${uid}`}
                width="5"
                height="5"
                patternTransform="rotate(45)"
                patternUnits="userSpaceOnUse"
              >
                <rect width="5" height="5" fill={SURFACE} />
                <line
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="5"
                  stroke={HUE_STROKE[hue]}
                  strokeWidth="2.5"
                />
              </pattern>
            ))}
            <pattern
              id={`blank-${uid}`}
              width="6"
              height="6"
              patternTransform="rotate(45)"
              patternUnits="userSpaceOnUse"
            >
              <rect width="6" height="6" fill={SURFACE} />
              <line
                x1="0"
                y1="0"
                x2="0"
                y2="6"
                stroke="rgba(12, 24, 38, 0.14)"
                strokeWidth="1.5"
              />
            </pattern>
          </defs>

          {/* Gridlines and y labels — recessive, behind everything. */}
          {domain.ticks.map((t) => (
            <g key={t}>
              <line
                x1={pad.left}
                x2={pad.left + plotW}
                y1={y(t)}
                y2={y(t)}
                stroke={t === 0 ? AXIS : GRID}
                strokeWidth={1}
              />
              <text
                x={pad.left - 8}
                y={y(t) + AXIS_FONT / 3}
                textAnchor="end"
                fontSize={AXIS_FONT}
                fill={INK_MUTED}
              >
                {formatAxisValue(unit, t)}
              </text>
            </g>
          ))}

          {/* A period nothing is known about is shown as a blank band
              rather than as an absence, which would be invisible. */}
          {blanks.map((i) => (
            <rect
              key={`blank-${i}`}
              x={pad.left + bandW * i}
              y={pad.top}
              width={bandW}
              height={plotH}
              fill={`url(#blank-${uid})`}
              opacity={0.7}
            />
          ))}

          {/* The active period's crosshair, under the marks. */}
          {active !== null && (
            <rect
              x={pad.left + bandW * active}
              y={pad.top}
              width={bandW}
              height={plotH}
              fill="rgba(12, 24, 38, 0.04)"
            />
          )}

          {kind === 'line' && (
            <LineMarks
              series={series}
              seriesValues={seriesValues}
              hues={hues}
              x={x}
              y={y}
              isPartial={isPartial}
              active={active}
              bandW={bandW}
            />
          )}

          {kind === 'column' && (
            <ColumnMarks
              seriesValues={seriesValues}
              hues={hues}
              uid={uid}
              x={x}
              y={y}
              zeroY={zeroY}
              bandW={bandW}
              isPartial={isPartial}
            />
          )}

          {kind === 'stacked' && (
            <StackedMarks
              seriesValues={seriesValues}
              hues={hues}
              uid={uid}
              x={x}
              y={y}
              bandW={bandW}
              isPartial={isPartial}
            />
          )}

          {/* Direct labels at the right edge: identity without relying
              on the reader matching a colour to a legend. Spread apart
              where the series converge, which is exactly where a legend
              is least help. */}
          {directLabels &&
            labelPositions.map((label) =>
              label === null ? null : (
                <text
                  key={`dl-${label.key}`}
                  x={pad.left + plotW + 8}
                  y={label.y + LABEL_FONT / 3}
                  fontSize={LABEL_FONT}
                  fill={INK_MUTED}
                >
                  {label.name}
                </text>
              ),
            )}

          {/* X axis labels, thinned so they cannot collide. */}
          {ticks.map((i) => (
            <text
              key={`xt-${i}`}
              x={x(i)}
              y={pad.top + plotH + AXIS_FONT + 5}
              textAnchor="middle"
              fontSize={AXIS_FONT}
              fill={INK_MUTED}
            >
              {xLabels[i]}
            </text>
          ))}

          {/* Hit targets: a full-height band per period, so the target
              is always far bigger than the mark inside it. */}
          {buckets.map((b, i) => (
            <rect
              key={`hit-${b.label}`}
              x={pad.left + bandW * i}
              y={pad.top}
              width={bandW}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setActive(i)}
              onMouseLeave={() => setActive((prev) => (prev === i ? null : prev))}
            />
          ))}
        </svg>
        )}

        {measured && active !== null && buckets[active] && (
          <Tooltip
            bucket={buckets[active]}
            series={series}
            index={active}
            hues={hues}
            left={x(active)}
            width={width}
          />
        )}

        <p id={descId} className="sr-only">
          {series.map((s) => describeSeries(s)).join(' ')} Use the left and right
          arrow keys to move through periods.
        </p>
        <p aria-live="polite" className="sr-only">
          {announcement}
        </p>
      </div>

      {showTable && (
        <ChartTable series={series} buckets={buckets} caption={title} />
      )}
    </figure>
  )
}

function LineMarks({
  series,
  seriesValues,
  hues,
  x,
  y,
  isPartial,
  active,
  bandW,
}: {
  series: HistorySeries[]
  seriesValues: (number | null)[][]
  hues: ChartHue[]
  x: (i: number) => number
  y: (v: number) => number
  isPartial: (i: number) => boolean
  active: number | null
  bandW: number
}) {
  return (
    <>
      {seriesValues.map((values, si) => {
        const stroke = HUE_STROKE[hues[si] ?? 'teal']
        const runs = valueSegments(values)
        return (
          <g key={seriesKey(series[si])}>
            {runs.map((run, ri) => {
              if (run.length === 1) {
                // A single known period between two gaps is still a
                // fact, and a path of one point draws nothing.
                const i = run[0]
                return (
                  <circle
                    key={`solo-${ri}`}
                    cx={x(i)}
                    cy={y(values[i] as number)}
                    r={3.5}
                    fill={stroke}
                    stroke={SURFACE}
                    strokeWidth={2}
                  />
                )
              }
              return dashRuns(run, isPartial).map((stretch, di) => (
                <path
                  key={`run-${ri}-${di}`}
                  d={linePath(
                    stretch.indices.map((i) => ({
                      x: x(i),
                      y: y(values[i] as number),
                    })),
                  )}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeDasharray={stretch.dashed ? '4 3' : undefined}
                />
              ))
            })}
            {/* Markers only where they can be told apart, plus always
                on the period being inspected. */}
            {values.map((v, i) =>
              v === null ? null : bandW > 24 || i === active ? (
                <circle
                  key={`pt-${i}`}
                  cx={x(i)}
                  cy={y(v)}
                  r={i === active ? 4.5 : 3}
                  fill={i === active ? stroke : SURFACE}
                  stroke={stroke}
                  strokeWidth={2}
                />
              ) : null,
            )}
          </g>
        )
      })}
    </>
  )
}

function ColumnMarks({
  seriesValues,
  hues,
  uid,
  x,
  y,
  zeroY,
  bandW,
  isPartial,
}: {
  seriesValues: (number | null)[][]
  hues: ChartHue[]
  uid: string
  x: (i: number) => number
  y: (v: number) => number
  zeroY: number
  bandW: number
  isPartial: (i: number) => boolean
}) {
  const count = seriesValues.length
  // A 2px surface gap between neighbours, and a thin mark: a column
  // that fills its band reads as a continuous area rather than as a
  // quantity in a period.
  const groupW = Math.max(3, bandW * 0.62)
  const barW = Math.max(2, (groupW - 2 * (count - 1)) / count)

  return (
    <>
      {seriesValues.map((values, si) => {
        const hue = hues[si] ?? 'teal'
        return (
          <g key={`col-${si}`}>
            {values.map((v, i) => {
              if (v === null) return null
              const left =
                x(i) - groupW / 2 + si * (barW + 2)
              const top = Math.min(y(v), zeroY)
              const h = Math.abs(y(v) - zeroY)
              return (
                <rect
                  key={`bar-${i}`}
                  x={left}
                  y={top}
                  width={barW}
                  height={v === 0 ? ZERO_NUB : Math.max(h, 1)}
                  rx={Math.min(4, barW / 2)}
                  fill={
                    isPartial(i)
                      ? `url(#hatch-${hue}-${uid})`
                      : HUE_STROKE[hue]
                  }
                />
              )
            })}
          </g>
        )
      })}
    </>
  )
}

function StackedMarks({
  seriesValues,
  hues,
  uid,
  x,
  y,
  bandW,
  isPartial,
}: {
  seriesValues: (number | null)[][]
  hues: ChartHue[]
  uid: string
  x: (i: number) => number
  y: (v: number) => number
  bandW: number
  isPartial: (i: number) => boolean
}) {
  const barW = Math.max(3, bandW * 0.62)
  const length = Math.max(0, ...seriesValues.map((s) => s.length))
  return (
    <>
      {Array.from({ length }, (_, i) => {
        const segments = stackAt(seriesValues, i)
        return (
          <g key={`stack-${i}`}>
            {segments.map((seg) => {
              const hue = hues[seg.seriesIndex] ?? 'teal'
              const top = y(seg.to)
              // A 2px surface gap between segments, so two adjacent
              // fills never read as one.
              const h = Math.max(0, y(seg.from) - top - 2)
              if (h <= 0) return null
              return (
                <rect
                  key={`seg-${seg.seriesIndex}`}
                  x={x(i) - barW / 2}
                  y={top}
                  width={barW}
                  height={h}
                  rx={seg.to === segments[segments.length - 1].to ? Math.min(4, barW / 2) : 0}
                  fill={
                    isPartial(i) ? `url(#hatch-${hue}-${uid})` : HUE_STROKE[hue]
                  }
                />
              )
            })}
          </g>
        )
      })}
    </>
  )
}

function Tooltip({
  bucket,
  series,
  index,
  hues,
  left,
  width,
}: {
  bucket: HistoryBucket
  series: HistorySeries[]
  index: number
  hues: ChartHue[]
  left: number
  width: number
}) {
  // Clamped to the container rather than flipped at a fraction of it.
  // The box is 250px and a phone is 390px, so a flip rule only chose
  // which edge to overflow; clamping cannot overflow at any width.
  const boxWidth = Math.min(TOOLTIP_W, Math.max(140, width - 16))
  return (
    <div
      role="presentation"
      className="pointer-events-none absolute z-10 rounded-xl p-2.5 shadow-sm"
      style={{
        left: tooltipLeft(left, width, boxWidth),
        width: boxWidth,
        top: 4,
        background: SURFACE,
        border: '1px solid #E7EEF0',
      }}
    >
      <p className="mb-1 text-[12px] font-semibold" style={{ color: INK }}>
        {bucket.label}
      </p>
      {series.map((s, i) => {
        const p = s.points[index]
        return (
          <div key={seriesKey(s)} className="flex items-baseline gap-1.5">
            <span
              aria-hidden="true"
              className="mt-[5px] inline-block h-2 w-2 shrink-0 rounded-full"
              style={{ background: HUE_STROKE[hues[i] ?? 'teal'] }}
            />
            <span className="text-[12px]" style={{ color: INK_MUTED }}>
              {s.display_name}
            </span>
            <span
              className="ml-auto text-[12px] tabular-nums"
              style={{ color: INK }}
            >
              {p && p.available && p.value !== null
                ? formatExactValue(s.unit, p.value)
                : '—'}
            </span>
          </div>
        )
      })}
      {series.map((s) => {
        const p = s.points[index]
        if (!p) return null
        const notes = p.available ? pointCaveats(p, s) : [describeGap(p)]
        if (notes.length === 0) return null
        return (
          <p
            key={`note-${seriesKey(s)}`}
            className="mt-1.5 text-[11.5px] leading-snug"
            style={{ color: INK_MUTED }}
          >
            {notes.join(' ')}
          </p>
        )
      })}
    </div>
  )
}
