'use client'

import { useState } from 'react'

import { formatCount } from '@/lib/insights'
import {
  type CohortRow,
  type RetentionBasis,
  cohortLabel,
  formatRetention,
  reachedOffsets,
  retentionRate,
} from '@/lib/insights-history'

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'
const RULE = '#E7EEF0'

/**
 * Retention by joining month, as a table rather than a chart.
 *
 * A cohort grid is a triangle of numbers with a deliberate hole in the
 * bottom-right corner, and a chart cannot show the hole — it can only
 * draw a line that stops, which reads as a fall. A table can leave a
 * cell blank and say why, so it is the clearer presentation here and
 * needs no new dependency.
 *
 * **Two bases, switchable, never mixed.** "Still in the Collective
 * they joined" and "still a member of Fresh Collective anywhere"
 * answer different questions, and the second is never smaller than the
 * first. The gap between them is people who moved rather than left —
 * which on a platform of many Collectives is the number that decides
 * whether a departure matters.
 *
 * Each basis has its own denominator, because a person who joined two
 * Collectives in one month is two memberships and one person. Sharing
 * one denominator would push a figure above 100%.
 */
export function CohortTable({
  rows,
  limitation,
  undated,
}: {
  rows: CohortRow[]
  limitation?: string
  undated?: number
}) {
  const [basis, setBasis] = useState<RetentionBasis>('in_collective')
  const offsets = reachedOffsets(rows)

  if (rows.length === 0) {
    return (
      <p className="text-[12.5px]" style={{ color: INK_MUTED }}>
        No cohorts yet — nobody has joined in this population.
      </p>
    )
  }

  return (
    <div>
      <div
        className="mb-3 flex flex-wrap items-center gap-1.5"
        role="group"
        aria-label="Retention basis"
      >
        <span className="mr-0.5 text-[12px]" style={{ color: INK_MUTED }}>
          Still a member
        </span>
        {(
          [
            ['in_collective', 'of the Collective they joined'],
            ['anywhere', 'of Fresh Collective, anywhere'],
          ] as [RetentionBasis, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-pressed={basis === key}
            onClick={() => setBasis(key)}
            className="rounded-lg px-3 py-1.5 text-[12.5px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
            style={
              basis === key
                ? {
                    background: 'rgba(56, 160, 158, 0.10)',
                    border: '1px solid rgba(56, 160, 158, 0.30)',
                    color: '#0f766e',
                    fontWeight: 600,
                  }
                : {
                    background: '#FFFFFF',
                    border: `1px solid ${RULE}`,
                    color: INK_MUTED,
                  }
            }
          >
            {label}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-[12.5px]">
          <caption className="sr-only">
            Membership retention by joining month.{' '}
            {basis === 'anywhere'
              ? 'People still holding a membership somewhere in Fresh Collective.'
              : 'Memberships still held in the Collective they began in.'}{' '}
            A blank cell is a milestone that has not yet been reached, not a
            retention of zero.
          </caption>
          <thead>
            <tr>
              <th
                scope="col"
                className="border-b py-1.5 pr-3 font-semibold"
                style={{ borderColor: RULE, color: INK }}
              >
                Joined
              </th>
              <th
                scope="col"
                className="border-b py-1.5 pr-3 text-right font-semibold"
                style={{ borderColor: RULE, color: INK }}
              >
                {basis === 'anywhere' ? 'People' : 'Memberships'}
              </th>
              {offsets.map((n) => (
                <th
                  key={n}
                  scope="col"
                  className="border-b py-1.5 pr-3 text-right font-semibold"
                  style={{ borderColor: RULE, color: INK }}
                >
                  After {n} {n === 1 ? 'month' : 'months'}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.cohort}>
                <th
                  scope="row"
                  className="border-b py-1.5 pr-3 font-normal"
                  style={{ borderColor: RULE, color: INK }}
                >
                  {cohortLabel(row.cohort)}
                </th>
                <td
                  className="border-b py-1.5 pr-3 text-right tabular-nums"
                  style={{ borderColor: RULE, color: INK_MUTED }}
                >
                  {formatCount(
                    basis === 'anywhere'
                      ? row.people_joined
                      : row.memberships_started,
                  )}
                </td>
                {offsets.map((n) => {
                  const offset = row.offsets.find((o) => o.months_after === n)
                  const rate = offset ? retentionRate(row, offset, basis) : null
                  return (
                    <td
                      key={n}
                      className="border-b py-1.5 pr-3 text-right tabular-nums"
                      style={{
                        borderColor: RULE,
                        color: rate === null ? INK_MUTED : INK,
                        // A wash rather than a heatmap: enough to read
                        // the shape down a column, not enough to turn a
                        // percentage into a colour somebody has to decode.
                        background:
                          rate === null
                            ? undefined
                            : `rgba(34, 165, 152, ${(rate * 0.18).toFixed(3)})`,
                      }}
                      title={
                        rate === null
                          ? 'This milestone has not been reached yet'
                          : undefined
                      }
                    >
                      {formatRetention(rate)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-2.5 text-[12px] leading-snug" style={{ color: INK_MUTED }}>
        A blank cell is a milestone the cohort has not reached yet — not a
        retention of zero. Percentages are of that month&rsquo;s own{' '}
        {basis === 'anywhere' ? 'people' : 'memberships'}.
      </p>
      {undated ? (
        <p className="mt-1 text-[12px] leading-snug" style={{ color: INK_MUTED }}>
          {formatCount(undated)} membership
          {undated === 1 ? '' : 's'} ended on a date nobody recorded. They are
          treated here as still held, so retention is overstated by at most
          that many.
        </p>
      ) : null}
      {limitation ? (
        <p
          className="mt-1 max-w-[80ch] text-[12px] leading-snug"
          style={{
            color: INK_MUTED,
            fontFamily: 'Georgia, serif',
            fontStyle: 'italic',
          }}
        >
          {limitation}
        </p>
      ) : null}
    </div>
  )
}
