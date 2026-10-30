'use client'

import { useId, useState } from 'react'

import {
  type ChartHue,
  type Grouping,
  type HistoryResult,
  type HistorySeries,
  type QualityNote,
  AVAILABILITY_PROSE,
  DATE_BASIS_PROSE,
  QUALITY_LABEL,
  historyQuality,
  populationNotes,
} from '@/lib/insights-history'
import { type ChartKind, TimeSeriesChart } from './charts/TimeSeriesChart'

const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'
const RULE = '#E7EEF0'

/**
 * A chart, and everything that has to be said next to it — in two
 * groups, because they are not the same kind of thing.
 *
 * **Visible, always: what changes the reading.** A gap in the line, a
 * period reconstructed rather than recorded, a classification filter
 * that emptied the chart, a week built from four days. Each of these
 * changes what the picture in front of you means, so none of them is
 * something a reader should have to go looking for.
 *
 * **Behind "What does this chart mean?": the background.** Definitions,
 * the tables a figure comes from, which timestamp dates it, how far
 * back it can be trusted, the registry's own limitations. A curious or
 * sceptical reader wants all of it; nobody needs it to read the chart,
 * and printing it under every graph turned the page into a document
 * with pictures in it.
 *
 * Nothing is dropped in the move. Everything the registry declares is
 * still on the page, one disclosure away, which is also what keeps this
 * honest: the panel does not choose which limitations to mention, it
 * shows all of them.
 *
 * A controlled disclosure rather than `details`/`summary`: the two
 * controls belong on one line, with the panel they open spanning the
 * full width beneath both, and a `details` element cannot be laid out
 * that way without nesting a second interactive control inside its
 * `summary` — which is the one thing a summary must not contain. The
 * button carries `aria-expanded` and `aria-controls`, which is the
 * standard disclosure pattern and announces identically.
 *
 * The figures stay available as a table at the top level rather than
 * inside the disclosure. That is the relief the palette requires for a
 * hue below 3:1 against white, and the only way to read exact values
 * without sight — neither should be nested two interactions deep.
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
  prominent = false,
}: {
  title: string
  /** One short, human sentence. The detail goes in `footnote`. */
  explanation: string
  data: HistoryResult | null
  /** Which of the fetched series this panel draws, in order. */
  keys: string[]
  kind: ChartKind
  hues: ChartHue[]
  height?: number
  /** Calculation rules and historical limits, shown in the disclosure. */
  footnote?: string
  /** The lead chart on a page: taller, and titled a size up. */
  prominent?: boolean
}) {
  const [showTable, setShowTable] = useState(false)
  const [showMeaning, setShowMeaning] = useState(false)
  const meaningId = useId()

  const series = (data?.series ?? []).filter((s) => keys.includes(s.key))
  // Ordered by the panel's own key list rather than by the response, so
  // a series keeps the hue the panel assigned it however the backend
  // happens to order them.
  const ordered = keys
    .map((k) => series.find((s) => s.key === k))
    .filter((s): s is NonNullable<typeof s> => Boolean(s))

  // Two different things, deliberately not one list. A caution says
  // "trust this less"; a note says "here is how this was established".
  // Collapsing them taught the reader to distrust a reconstructed
  // figure that is exact.
  const quality = historyQuality(ordered)
  const cautions = [
    ...populationNotes(ordered).map(
      (text): QualityNote => ({ kind: 'limited', text, caution: true }),
    ),
    ...quality.filter((q) => q.caution),
  ]
  const established = quality.filter((q) => !q.caution)
  const chartHeight = height ?? (prominent ? 320 : 220)

  return (
    <section
      className="rounded-2xl p-5 sm:p-6"
      style={{ background: '#FFFFFF', border: `1px solid ${RULE}` }}
    >
      <h3
        className={`font-serif leading-tight ${
          prominent ? 'text-[19px]' : 'text-[16px]'
        }`}
        style={{ color: INK }}
      >
        {title}
      </h3>
      <p
        className="mb-4 mt-1 max-w-[70ch] text-[13px]"
        style={{ color: INK_MUTED }}
      >
        {explanation}
      </p>

      {!data || ordered.length === 0 ? (
        <p
          className="py-10 text-center text-[13px]"
          style={{ color: INK_MUTED }}
        >
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
            height={chartHeight}
            showTable={showTable}
          />

          {(cautions.length > 0 || established.length > 0) && (
            <ul className="mt-3 list-none space-y-1 p-0">
              {cautions.map((q) => (
                <QualityLine key={q.text} note={q} caution />
              ))}
              {established.map((q) => (
                <QualityLine key={q.text} note={q} />
              ))}
            </ul>
          )}

          <div className="mt-4 border-t pt-3" style={{ borderColor: RULE }}>
            <div className="flex flex-wrap items-center justify-between gap-x-5 gap-y-2">
              <button
                type="button"
                onClick={() => setShowMeaning((v) => !v)}
                aria-expanded={showMeaning}
                aria-controls={meaningId}
                className="inline-flex items-center gap-1.5 rounded-md text-[12.5px] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
                style={{ color: INK_MUTED }}
              >
                <span
                  aria-hidden="true"
                  className="inline-block text-[9px] transition-transform"
                  style={{
                    transform: showMeaning ? 'rotate(90deg)' : 'none',
                  }}
                >
                  ▶
                </span>
                What does this chart mean?
              </button>
              <button
                type="button"
                onClick={() => setShowTable((v) => !v)}
                aria-expanded={showTable}
                className="rounded-md text-[12.5px] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
                style={{ color: INK_MUTED }}
              >
                {showTable ? 'Hide the figures' : 'Show the figures'}
              </button>
            </div>
            {showMeaning && (
              <div id={meaningId} className="mt-3.5">
                <Meaning
                  series={ordered}
                  footnote={footnote}
                  data={data}
                  quality={quality}
                />
              </div>
            )}
          </div>
        </>
      )}
    </section>
  )
}

/**
 * One line about how this chart's periods came to be known.
 *
 * A filled gold marker for a caution and a hollow grey one for a
 * statement of fact, so the two are distinguishable before the
 * sentence is read. Shape as well as colour, because a reader who
 * cannot separate the hues must still separate the meanings — and the
 * leading word ("Observed", "Historical limitation") carries it either
 * way.
 */
function QualityLine({
  note,
  caution,
}: {
  note: QualityNote
  caution?: boolean
}) {
  return (
    <li
      className="flex gap-2 text-[12px] leading-snug"
      style={{ color: INK_MUTED }}
    >
      <span
        aria-hidden="true"
        className="mt-[1px] shrink-0"
        style={{ color: caution ? '#d4b048' : 'rgba(12, 24, 38, 0.35)' }}
      >
        {caution ? '\u25cf' : '\u25cb'}
      </span>
      <span>
        <span style={{ color: INK }}>{QUALITY_LABEL[note.kind]}. </span>
        {note.text}
      </span>
    </li>
  )
}

/** Everything the registry declares about the figures on this chart. */
function Meaning({
  series,
  footnote,
  data,
  quality,
}: {
  series: HistorySeries[]
  footnote?: string
  data: HistoryResult
  quality: QualityNote[]
}) {
  const recomputed = [
    ...new Set(
      series
        .map((s) => s.qualifiers?.recompute_note)
        .filter((n): n is string => typeof n === 'string'),
    ),
  ]

  return (
    <div className="max-w-[78ch] space-y-3.5">
      {series.map((s) => (
        <div key={s.key}>
          <p className="text-[12.5px] font-semibold" style={{ color: INK }}>
            {s.display_name}
          </p>
          <p className="text-[12.5px] leading-snug" style={{ color: INK_MUTED }}>
            {s.definition}
          </p>
          <dl className="mt-1.5 space-y-0.5">
            <Fact label="Source">{s.source_of_truth}</Fact>
            <Fact label="Dated by">
              {DATE_BASIS_PROSE[s.date_basis] ?? s.date_basis}
            </Fact>
            <Fact label="How far back">
              {AVAILABILITY_PROSE[s.availability] ?? s.availability}
            </Fact>
            <Fact label="Combined across periods">
              {s.aggregation === 'additive'
                ? 'Added up — each period is its own quantity.'
                : s.aggregation === 'snapshot'
                  ? 'Taken from the end of the period, never added up.'
                  : 'Recomputed for each period, never added up.'}
            </Fact>
            {s.limitations && <Fact label="Limitations">{s.limitations}</Fact>}
          </dl>
        </div>
      ))}

      {quality.length > 0 && (
        <div>
          <p className="text-[12.5px] font-semibold" style={{ color: INK }}>
            How this history was established
          </p>
          <dl className="mt-1.5 space-y-0.5">
            {quality.some((q) => q.kind === 'observed') && (
              <Fact label="Observed">
                Recorded on the day it describes. The figure is what was
                seen at the time.
              </Fact>
            )}
            {quality.some((q) => q.kind === 'reconstructed') && (
              <Fact label="Reconstructed">
                Worked out afterwards from records that carry their own
                dates — a membership&rsquo;s join date, a payment&rsquo;s
                settlement date. Exact rather than estimated: the answer
                is the same one the day itself would have given.
              </Fact>
            )}
            {quality.some((q) => q.kind === 'limited') && (
              <Fact label="Historical limitation">
                Worked out afterwards, but the detail needed to be certain
                was never recorded, so the figure may be incomplete or
                approximate. Treated as a caution rather than a fact.
              </Fact>
            )}
            {quality.some((q) => q.kind === 'incomplete') && (
              <Fact label="Part period">
                Fewer days were recorded than the period covers, so the
                figure understates it.
              </Fact>
            )}
            {quality.some((q) => q.kind === 'unavailable') && (
              <Fact label="Unavailable">
                Cannot be established at all. Drawn as a gap and never as
                a zero, because &ldquo;we do not know&rdquo; and
                &ldquo;there were none&rdquo; are different answers.
              </Fact>
            )}
          </dl>
        </div>
      )}

      {footnote && (
        <p className="text-[12.5px] leading-snug" style={{ color: INK_MUTED }}>
          {footnote}
        </p>
      )}
      {recomputed.map((note) => (
        <p
          key={note}
          className="text-[12.5px] leading-snug"
          style={{ color: INK_MUTED }}
        >
          {note}
        </p>
      ))}
      <p className="text-[12.5px] leading-snug" style={{ color: INK_MUTED }}>
        <span style={{ color: INK }}>Who is counted. </span>
        {data.population.note}
      </p>
    </div>
  )
}

function Fact({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex gap-1.5 text-[12px] leading-snug">
      <dt className="shrink-0" style={{ color: INK }}>
        {label}:
      </dt>
      <dd className="m-0" style={{ color: INK_MUTED }}>
        {children}
      </dd>
    </div>
  )
}
