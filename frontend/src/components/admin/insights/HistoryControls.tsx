'use client'

import {
  type Grouping,
  type HistoryRangeKey,
  type HistoryResult,
  type PopulationKey,
  GROUPING_LABELS,
} from '@/lib/insights-history'
import { WM_HUE } from '@/lib/wm-palette'

const INK_MUTED = 'rgba(12, 24, 38, 0.60)'

const RANGE_FALLBACK: { key: HistoryRangeKey; label: string }[] = [
  { key: 'last_30_days', label: 'Last 30 days' },
  { key: 'last_3_months', label: 'Last 3 months' },
  { key: 'last_12_months', label: 'Last 12 months' },
  { key: 'this_fy', label: 'This financial year' },
  { key: 'all_time', label: 'All time' },
]

/**
 * The shared controls for every historical chart.
 *
 * One component for the same reason there is one `PeriodSelect`: a
 * range and a grouping must mean the same span on every page, and two
 * pages each rolling their own is the first step back towards two
 * surfaces disagreeing about where October begins. The options come
 * from the response — the backend's own range, grouping and
 * classification vocabularies — so a reporting class added later
 * appears here without a second list to keep in step.
 *
 * The classification control carries its prose rather than only its
 * name. "Production" is a narrowing with real consequences, including
 * on money, and a reader who cannot see what was left out cannot
 * read the figure.
 */
export function HistoryControls({
  range,
  grouping,
  population,
  onRange,
  onGrouping,
  onPopulation,
  options,
  disabled,
  populationNote,
}: {
  range: HistoryRangeKey
  grouping: Grouping
  population: PopulationKey
  onRange: (next: HistoryRangeKey) => void
  onGrouping: (next: Grouping) => void
  onPopulation: (next: PopulationKey) => void
  options?: HistoryResult['options']
  disabled?: boolean
  populationNote?: string
}) {
  const ranges = options?.ranges ?? RANGE_FALLBACK
  const groupings = options?.groupings ?? (['daily', 'weekly', 'monthly'] as Grouping[])
  const populations = options?.populations ?? []

  return (
    <div className="mb-5 flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2.5">
        <Group label="Period">
          {ranges.map((r) => (
            <Chip
              key={r.key}
              active={r.key === range}
              disabled={disabled}
              onClick={() => onRange(r.key)}
            >
              {r.label}
            </Chip>
          ))}
        </Group>

        <Group label="Grouped by">
          {groupings.map((g) => (
            <Chip
              key={g}
              active={g === grouping}
              disabled={disabled}
              onClick={() => onGrouping(g)}
            >
              {GROUPING_LABELS[g]}
            </Chip>
          ))}
        </Group>
      </div>

      {populations.length > 0 && (
        <Group label="Activity">
          {populations.map((p) => (
            <Chip
              key={p.key}
              active={p.key === population}
              disabled={disabled}
              onClick={() => onPopulation(p.key)}
              title={p.note}
            >
              {p.label}
            </Chip>
          ))}
        </Group>
      )}

      {populationNote && (
        <p className="max-w-[78ch] text-[12.5px]" style={{ color: INK_MUTED }}>
          {populationNote}
        </p>
      )}
    </div>
  )
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      role="group"
      aria-label={label}
    >
      <span className="mr-0.5 text-[12px]" style={{ color: INK_MUTED }}>
        {label}
      </span>
      {children}
    </div>
  )
}

function Chip({
  active,
  disabled,
  onClick,
  title,
  children,
}: {
  active: boolean
  disabled?: boolean
  onClick: () => void
  title?: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={active}
      title={title}
      onClick={onClick}
      className="rounded-lg px-3 py-1.5 text-[12.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
      style={
        active
          ? {
              background: WM_HUE.teal.bg,
              border: `1px solid ${WM_HUE.teal.border}`,
              color: WM_HUE.teal.text,
              fontWeight: 600,
            }
          : {
              background: '#FFFFFF',
              border: '1px solid #E7EEF0',
              color: INK_MUTED,
            }
      }
    >
      {children}
    </button>
  )
}
