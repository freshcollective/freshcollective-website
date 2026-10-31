'use client'

import { useId, useState } from 'react'

import {
  type MetricValue,
  comparisonSentence,
  formatValue,
  qualifierNote,
} from '@/lib/insights'
import {
  HUE_UI,
  INK as FC_INK,
  STATUS,
  SURFACE,
  type InsightHue,
} from '@/lib/insights-palette'

const CARD_BG = SURFACE.card
const CARD_BORDER = `1px solid ${SURFACE.cardEdge}`
const INK = FC_INK.heading
const INK_MUTED = FC_INK.muted
const INK_SOFTER = FC_INK.faint

const SERIF_ITALIC: React.CSSProperties = {
  color: INK_MUTED,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}

/**
 * One figure, and everything needed to trust it.
 *
 * The registry returns each metric's definition, its source, the date it
 * attributes by and what it cannot tell you — so the card shows them
 * rather than discarding them. "What is this number?" is answerable in
 * one click, on the page, which is the difference between a dashboard
 * somebody relies on and one they quietly stop believing.
 *
 * Three states, kept distinct because conflating them is how a
 * dashboard misleads:
 *
 *   a number        — we measured it
 *   "Not yet"       — the metric is unavailable and says why
 *   "—" with a note — nothing to report, which is not the same as zero
 *
 * The caption is written prose rather than an arrow and a percentage: an
 * arrow beside a figure needs a legend, and "$120 more than last month"
 * does not.
 */
export function InsightCard({
  metric,
  previous,
  previousLabel,
  hue = 'teal',
  caption,
  emphasiseValue,
}: {
  metric: MetricValue | null
  previous?: MetricValue | null
  previousLabel?: string | null
  hue?: InsightHue
  /** A short line under the figure, in the warm register. */
  caption?: string
  /**
   * Render the figure in the **status** colour rather than the card's
   * hue, for a genuine obligation or alarm.
   *
   * Deliberately not one of the four chart hues. Now that watermelon
   * is an ordinary series colour, an obligation drawn in it would be
   * indistinguishable from the fourth line on a chart — so it takes
   * the amber from ``--fc-status-warning``, which no series uses.
   * Reserve it for something a caretaker should actually act on.
   */
  emphasiseValue?: boolean
}) {
  const [open, setOpen] = useState(false)
  const detailsId = useId()

  if (!metric) {
    return (
      <div
        className="rounded-2xl p-5"
        style={{ background: CARD_BG, border: CARD_BORDER }}
      >
        <p className="text-[12.5px]" style={{ color: INK_SOFTER }}>
          Not available
        </p>
      </div>
    )
  }

  const def = metric.definition
  const note = qualifierNote(metric)
  const comparison = previous
    ? comparisonSentence(metric, previous, previousLabel ?? null)
    : null

  return (
    <div
      // ``min-w-0`` matters: a grid item defaults to ``min-width:auto``,
      // which refuses to shrink below its content and pushes the card
      // past the column it sits in. ``break-words`` is the backstop for
      // a single long token with nowhere to wrap.
      className="flex min-w-0 flex-col rounded-2xl p-5 break-words"
      style={{ background: CARD_BG, border: CARD_BORDER }}
    >
      <CardHeading hue={hue}>{def.display_name}</CardHeading>

      {metric.available ? (
        <p
          className="mt-2.5 font-serif text-[26px] leading-tight md:text-[28px]"
          style={{ color: emphasiseValue ? STATUS.warning.fg : INK }}
        >
          {formatValue(metric)}
        </p>
      ) : (
        <>
          <p
            className="mt-3 font-serif text-[22px] leading-tight"
            style={{ color: INK_SOFTER }}
          >
            Not yet
          </p>
          <p className="mt-1 text-[12.5px]" style={{ color: INK_MUTED }}>
            {metric.unavailable_reason}
          </p>
        </>
      )}

      {caption && metric.available && (
        <p className="mt-1 text-[12.5px]" style={SERIF_ITALIC}>
          {caption}
        </p>
      )}

      {comparison && (
        <p className="mt-3 text-[12.5px]" style={{ color: INK_MUTED }}>
          {comparison}
        </p>
      )}

      {note && (
        <p className="mt-2 text-[12px]" style={{ color: HUE_UI.gold.text }}>
          {note}
        </p>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={detailsId}
        className="mt-3 rounded text-[12px] underline decoration-dotted underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
        style={{ color: INK_SOFTER }}
      >
        {open ? 'Hide what this means' : 'What does this mean?'}
      </button>

      {open && (
        <div
          id={detailsId}
          className="mt-3 rounded-lg px-3 py-2.5"
          style={{ background: 'rgba(12, 24, 38, 0.03)' }}
        >
          <p className="text-[12.5px]" style={{ color: INK }}>
            {def.definition}
          </p>
          {def.limitations && (
            <p className="mt-2 text-[12.5px]" style={{ color: INK_MUTED }}>
              <strong style={{ fontWeight: 600 }}>Worth knowing: </strong>
              {def.limitations}
            </p>
          )}
          <dl className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11.5px]">
            <dt style={{ color: INK_SOFTER }}>Comes from</dt>
            <dd style={{ color: INK_MUTED }}>{def.source_of_truth}</dd>
            <dt style={{ color: INK_SOFTER }}>Counted by</dt>
            <dd style={{ color: INK_MUTED }}>{describeBasis(def.date_basis)}</dd>
            <dt style={{ color: INK_SOFTER }}>Adds up?</dt>
            <dd style={{ color: INK_MUTED }}>
              {describeAggregation(def.aggregation)}
            </dd>
          </dl>
        </div>
      )}
    </div>
  )
}

/**
 * Which timestamp decides the period a figure belongs to, in plain words.
 *
 * Worth surfacing because it is the thing that used to be inconsistent:
 * two endpoints attributed the same payment to different months. Saying
 * it out loud on the card is how that stays fixed in the open.
 */
function describeBasis(basis: string): string {
  switch (basis) {
    case 'payment_settled':
      return 'when the payment settled'
    case 'refunded':
      return 'when the refund happened'
    case 'payout_marked':
      return 'when the payout was recorded'
    case 'created':
      return 'when the record was created'
    case 'membership_joined':
      return 'when the membership began'
    case 'business_event':
      return 'when the activity happened'
    default:
      return 'measured at a moment, not over a period'
  }
}

function describeAggregation(aggregation: string): string {
  switch (aggregation) {
    case 'additive':
      return 'Yes — periods can be added together'
    case 'snapshot':
      return 'No — this is a count at a moment in time'
    case 'distinct_count':
      return 'No — counts people, who would be counted twice'
    case 'ratio':
      return 'No — a rate, recalculated for each period'
    default:
      return 'See the definition'
  }
}

/**
 * The tinted label pill, matching Commerce and Mother World so the World
 * Management colour hierarchy reads the same on every page.
 */
/**
 * A metric's name, as a heading rather than an eyebrow.
 *
 * It used to be a 8.5px uppercase letter-spaced pill with
 * ``whitespace-nowrap``, which is the design language's own worked
 * example of what *not* to do — "a section titled in bold uppercase
 * teal 12px" — and was also the cause of the overflow: a name like
 * "Contribution after processing costs" cannot fit one line in a
 * quarter-width card, so it ran out of the card instead of wrapping.
 *
 * Now it is what the language prescribes: a small coloured dot beside
 * a readable heading in heading ink, wrapping onto as many lines as it
 * needs. The dot keeps the colour association with the chart series
 * the card sits beneath, which is the only job the pill was really
 * doing.
 */
export function CardHeading({
  hue,
  children,
}: {
  hue: InsightHue
  children: React.ReactNode
}) {
  return (
    <h4 className="flex items-start gap-1.5 text-[13.5px] font-semibold leading-snug">
      <span
        aria-hidden="true"
        className="mt-[5px] inline-block h-[7px] w-[7px] shrink-0 rounded-full"
        style={{ background: HUE_UI[hue].dot }}
      />
      <span className="min-w-0" style={{ color: INK }}>
        {children}
      </span>
    </h4>
  )
}
