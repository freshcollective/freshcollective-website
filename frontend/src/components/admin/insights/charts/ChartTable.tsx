'use client'

import {
  type HistoryBucket,
  type HistorySeries,
  describeGap,
  formatExactValue,
} from '@/lib/insights-history'

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'
const RULE = '#E7EEF0'

/**
 * The same figures as a table.
 *
 * Not a fallback — a peer view, and a required one. Two separate
 * obligations land on it. Gold sits below 3:1 contrast against white,
 * and the palette rule is that such a hue is only legitimate alongside
 * visible labels or a table; and a line chart cannot be read at all by
 * somebody using a screen reader, however good its description is.
 *
 * It also answers the question a chart is worst at: "what exactly was
 * that number". Every cell is full precision, and a missing figure says
 * why it is missing rather than showing a dash.
 */
export function ChartTable({
  series,
  buckets,
  caption,
}: {
  series: HistorySeries[]
  buckets: HistoryBucket[]
  caption: string
}) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full border-collapse text-left text-[12.5px]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th
              scope="col"
              className="border-b py-1.5 pr-3 font-semibold"
              style={{ borderColor: RULE, color: INK }}
            >
              Period
            </th>
            {series.map((s) => (
              <th
                key={s.key}
                scope="col"
                className="border-b py-1.5 pr-3 text-right font-semibold"
                style={{ borderColor: RULE, color: INK }}
              >
                {s.display_name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {buckets.map((bucket, i) => (
            <tr key={bucket.label}>
              <th
                scope="row"
                className="border-b py-1.5 pr-3 font-normal"
                style={{ borderColor: RULE, color: INK_MUTED }}
              >
                {bucket.label}
                {!bucket.complete && (
                  <span style={{ color: INK_MUTED }}> (in progress)</span>
                )}
                {bucket.clipped && bucket.complete && (
                  <span style={{ color: INK_MUTED }}> (part period)</span>
                )}
              </th>
              {series.map((s) => {
                const point = s.points[i]
                const value =
                  point && point.available && point.value !== null
                    ? formatExactValue(s.unit, point.value)
                    : null
                return (
                  <td
                    key={s.key}
                    className="border-b py-1.5 pr-3 text-right tabular-nums"
                    style={{ borderColor: RULE, color: value ? INK : INK_MUTED }}
                  >
                    {value ?? (
                      <span title={point ? describeGap(point) : undefined}>
                        Not available
                      </span>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
