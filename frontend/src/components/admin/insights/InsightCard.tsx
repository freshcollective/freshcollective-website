'use client'

import { useId, useState } from 'react'

import {
  type MetricValue,
  comparisonSentence,
  formatValue,
  qualifierNote,
} from '@/lib/insights'
import { ON_NAVY, type InsightHue } from '@/lib/insights-palette'

/**
 * The figures band is dark.
 *
 * On a white page of white chart panels, a white card had nothing to
 * separate it from the page, so the detail under "The figures behind
 * them" dissolved into the background. Inverting just this band gives
 * the page two clear registers — charts on white, the figures behind
 * them on navy — without adding a shadow or a third container.
 *
 * Every colour comes from ``ON_NAVY``, which is measured against
 * #071824 rather than inherited from the light palette. Nothing here
 * is a page-level override: this component renders every metric card
 * on all six dashboards, so changing it changes all of them.
 */
const CARD_BG = ON_NAVY.surface
const CARD_BORDER = `1px solid ${ON_NAVY.edge}`
const INK = ON_NAVY.ink.heading
const INK_MUTED = ON_NAVY.ink.muted
const INK_SOFTER = ON_NAVY.ink.faint

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
          style={{ color: emphasiseValue ? ON_NAVY.status.warning : INK }}
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
        <p className="mt-2 text-[12px]" style={{ color: ON_NAVY.hue.gold }}>
          {note}
        </p>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={detailsId}
        className="mt-3 rounded text-[12px] underline decoration-dotted underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2"
        style={{ color: INK_SOFTER, outlineColor: ON_NAVY.focus }}
      >
        {open ? 'Hide what this means' : 'What does this mean?'}
      </button>

      {open && (
        <div
          id={detailsId}
          className="mt-3 rounded-lg px-3 py-2.5"
          style={{ background: ON_NAVY.well }}
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
        style={{ background: ON_NAVY.hue[hue] }}
      />
      <span className="min-w-0" style={{ color: INK }}>
        {children}
      </span>
    </h4>
  )
}

/**
 * An explanatory panel that sits among the metric cards.
 *
 * Five of these had grown across three pages, each restating its own
 * wash — two teal, one gold, two plain white. In the dark band a
 * white panel among navy cards reads as a rendering fault, so they
 * share one component and one surface.
 *
 * The accent tints the navy rather than replacing it: a flat overlay
 * composited over ``ON_NAVY.surface``, so a teal note and a gold note
 * are recognisably the same object in two registers, and neither
 * becomes a second kind of card.
 */
export function CardNote({
  accent = 'plain',
  span,
  children,
}: {
  accent?: 'teal' | 'gold' | 'plain'
  /** Grid spans, for a note that should sit wider than one column. */
  span?: string
  children: React.ReactNode
}) {
  const tint = accent === 'plain' ? null : ON_NAVY.noteTint[accent]
  const edge = accent === 'plain' ? ON_NAVY.edge : ON_NAVY.noteEdge[accent]
  return (
    <div
      className={`min-w-0 rounded-2xl p-5 break-words ${span ?? ''}`}
      style={{
        background: tint
          ? `linear-gradient(0deg, ${tint}, ${tint}), ${ON_NAVY.surface}`
          : ON_NAVY.surface,
        border: `1px solid ${edge}`,
      }}
    >
      {children}
    </div>
  )
}
