'use client'

import { useState } from 'react'

import {
  type ChartHue,
  type Grouping,
  type HistoryResult,
  hasGaps,
  seriesProvenanceNote,
} from '@/lib/insights-history'
import {
  type ChartKind,
  TimeSeriesChart,
} from './charts/TimeSeriesChart'

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'

/**
 * A chart, and everything that has to be said next to it.
 *
 * The panel exists because a chart on its own is the easiest place on
 * the platform to mislead somebody. Four things therefore travel with
 * every graph rather than being left to a caption somebody writes once:
 *
 * * the metric's **own limitations**, from the registry — the same
 *   prose the card above it shows, so the constraint is beside the
 *   figure rather than in a document;
 * * the **provenance** of the periods drawn, whenever any of them was
 *   reconstructed or recorded late;
 * * whether the chart contains **gaps**, said in words, because a break
 *   in a line is easy to miss and easy to misread as a fall to zero;
 * * the **population** the figures describe, since "Production" is a
 *   subset and a subset must announce itself.
 *
 * The figures are also always available as a table. That is the relief
 * the palette requires for a hue below 3:1 against white, and it is the
 * only way a screen-reader user can read exact values.
 */
export function HistoryPanel({
  title,
  explanation,
  data,
  keys,
  kind,
  hues,
  height,
  footnote,
}: {
  title: string
  explanation: string
  data: HistoryResult | null
  /** Which of the fetched series this panel draws, in order. */
  keys: string[]
  kind: ChartKind
  hues: ChartHue[]
  height?: number
  footnote?: string
}) {
  const [showTable, setShowTable] = useState(false)

  const series = (data?.series ?? []).filter((s) => keys.includes(s.key))
  // Ordered by the panel's own key list rather than by the response, so
  // a series keeps the hue the panel assigned it however the backend
  // happens to order them.
  const ordered = keys
    .map((k) => series.find((s) => s.key === k))
    .filter((s): s is NonNullable<typeof s> => Boolean(s))

  const limitations = ordered
    .map((s) => s.limitations)
    .filter((l): l is string => Boolean(l))
  const provenance = ordered
    .map((s) => seriesProvenanceNote(s))
    .filter((p): p is string => Boolean(p))
  const unique = (xs: string[]) => [...new Set(xs)]

  const recomputed = unique(
    ordered
      .map((s) => s.qualifiers?.recompute_note)
      .filter((n): n is string => typeof n === 'string'),
  )

  return (
    <section
      className="mb-5 rounded-2xl p-5"
      style={{ background: '#FFFFFF', border: '1px solid #E7EEF0' }}
    >
      <h4
        className="font-serif text-[16px] leading-tight"
        style={{ color: INK }}
      >
        {title}
      </h4>
      <p
        className="mb-3 mt-1 max-w-[78ch] text-[12.5px]"
        style={{ color: INK_MUTED }}
      >
        {explanation}
      </p>

      {!data || ordered.length === 0 ? (
        <p className="py-8 text-center text-[13px]" style={{ color: INK_MUTED }}>
          {data ? 'No figures for this selection.' : 'Drawing the chart…'}
        </p>
      ) : (
        <>
          <TimeSeriesChart
            series={ordered}
            buckets={data.buckets}
            grouping={data.grouping as Grouping}
            kind={kind}
            hues={hues}
            title={title}
            height={height}
            showTable={showTable}
          />

          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
            <button
              type="button"
              onClick={() => setShowTable((v) => !v)}
              aria-expanded={showTable}
              className="rounded-md text-[12px] underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
              style={{ color: INK_MUTED }}
            >
              {showTable ? 'Hide the figures' : 'Show the figures'}
            </button>
            {hasGaps(ordered) && (
              <span className="text-[12px]" style={{ color: INK_MUTED }}>
                Shaded periods have no figure — a gap, not a zero.
              </span>
            )}
          </div>

          {(footnote || limitations.length > 0 || provenance.length > 0 ||
            recomputed.length > 0) && (
            <div className="mt-3 space-y-1.5">
              {footnote && <Note>{footnote}</Note>}
              {unique(provenance).map((p) => (
                <Note key={p}>{p}</Note>
              ))}
              {recomputed.map((p) => (
                <Note key={p}>{p}</Note>
              ))}
              {unique(limitations).map((l) => (
                <Note key={l}>{l}</Note>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p
      className="max-w-[78ch] text-[12px] leading-snug"
      style={{
        color: INK_MUTED,
        fontFamily: 'Georgia, serif',
        fontStyle: 'italic',
      }}
    >
      {children}
    </p>
  )
}
