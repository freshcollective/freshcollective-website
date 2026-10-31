'use client'

import {
  type CollectiveStanding,
  type HistorySeries,
  MIN_COMPARABLE_PERIODS,
  byGrowth,
  bySize,
  collectiveStandings,
  formatExactValue,
} from '@/lib/insights-history'

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'
const RULE = '#E7EEF0'

export type StandingsMode = 'size' | 'growing' | 'quietening'

const TITLES: Record<StandingsMode, string> = {
  size: 'Largest by membership',
  growing: 'Growing fastest',
  quietening: 'Getting quieter',
}

/**
 * A ranking of Collectives, with the ones that cannot honestly be
 * ranked listed underneath rather than dropped.
 *
 * The distortion this is built around: Collectives launched at
 * different times. A Collective three weeks old that went from one
 * member to two has grown 100%, and in a naive table it tops the list
 * above a community that added forty people. So growth rankings only
 * include Collectives with enough history, and the rest appear below
 * with the reason — because "new" and "not growing" look identical in
 * a table that silently omits one of them, and the omission always
 * reads as the worse of the two.
 *
 * Size is ranked on looser terms, deliberately: being small and new is
 * a fact about a Collective, not an artefact of when it launched.
 */
export function StandingsTable({
  series,
  mode,
  unit,
  metricName,
}: {
  series: HistorySeries[]
  mode: StandingsMode
  unit: HistorySeries['unit']
  metricName: string
}) {
  const standings = collectiveStandings(series)
  if (standings.length === 0) return null

  const { ranked, withheld } =
    mode === 'size'
      ? bySize(standings)
      : byGrowth(standings, mode === 'growing' ? 'up' : 'down')

  const shown =
    mode === 'quietening' ? ranked.filter((s) => (s.change ?? 0) < 0) : ranked

  return (
    <div
      className="rounded-2xl p-5"
      style={{ background: '#FFFFFF', border: `1px solid ${RULE}` }}
    >
      <h3 className="font-serif text-[16px] leading-tight" style={{ color: INK }}>
        {TITLES[mode]}
      </h3>
      <p className="mb-3 mt-1 text-[12.5px]" style={{ color: INK_MUTED }}>
        {mode === 'size'
          ? `By ${metricName.toLowerCase()} at the end of the range.`
          : `Change in ${metricName.toLowerCase()} across the range.`}
      </p>

      {shown.length === 0 ? (
        <p className="text-[12.5px]" style={{ color: INK_MUTED }}>
          {mode === 'quietening'
            ? 'No Collective has gone backwards over this range.'
            : 'Nothing to rank over this range.'}
        </p>
      ) : (
        <ol className="m-0 list-none space-y-1.5 p-0">
          {shown.map((s, i) => (
            <li
              key={s.collectiveId}
              className="flex items-baseline gap-2 text-[13px]"
            >
              <span className="w-4 shrink-0 tabular-nums" style={{ color: INK_MUTED }}>
                {i + 1}
              </span>
              <span style={{ color: INK }}>{s.collectiveName}</span>
              <span className="ml-auto tabular-nums" style={{ color: INK }}>
                {mode === 'size'
                  ? formatExactValue(unit, s.latest as number)
                  : signed(unit, s.change as number)}
              </span>
            </li>
          ))}
        </ol>
      )}

      {withheld.length > 0 && (
        <div className="mt-3 border-t pt-2.5" style={{ borderColor: RULE }}>
          <p className="text-[12px]" style={{ color: INK }}>
            Not ranked here
          </p>
          <ul className="m-0 mt-1 list-none space-y-1 p-0">
            {withheld.map((s) => (
              <li key={s.collectiveId} className="text-[12px]" style={{ color: INK_MUTED }}>
                <span style={{ color: INK }}>{s.collectiveName}</span>
                {' — '}
                {s.reason ?? 'No figures.'}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[11.5px]" style={{ color: INK_MUTED }}>
            Limited history, not poor performance. A Collective needs{' '}
            {MIN_COMPARABLE_PERIODS} complete periods before it is ranked on
            change, so a new one is not flattered by growing from one member
            to two.
          </p>
        </div>
      )}
    </div>
  )
}

function signed(unit: HistorySeries['unit'], value: number): string {
  const text = formatExactValue(unit, Math.abs(value))
  if (value === 0) return `no change`
  return `${value > 0 ? '+' : '−'}${text}`
}

export type { CollectiveStanding }
