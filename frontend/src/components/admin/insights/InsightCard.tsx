'use client'

import { useId, useState } from 'react'

import {
  type MetricValue,
  comparisonSentence,
  formatValue,
  qualifierNote,
} from '@/lib/insights'
import {
  CARD,
  CARD_SURFACES,
  EMPHASIS,
  type EmphasisKind,
  type InsightHue,
} from '@/lib/insights-palette'
import { useCardSurface } from './InsightsSection'

/**
 * The figures band is dark.
 *
 * On a white page of white chart panels, a white card had nothing to
 * separate it from the page, so the detail under "The figures behind
 * them" dissolved into the background. Inverting just this band gives
 * the page two clear registers — charts on white, the figures behind
 * them on navy — without adding a shadow or a third container.
 *
 * Every colour comes from ``CARD``, which is measured against
 * #071824 rather than inherited from the light palette. Nothing here
 * is a page-level override: this component renders every metric card
 * on all six dashboards, so changing it changes all of them.
 */
/**
 * Rank is type, not opacity. See ``CARD.ink``.
 *
 * The surface itself comes from the group this card sits in rather
 * than from a constant: the figures band runs navy → midnight →
 * ocean → rich teal as a reader moves down the page, and a card does
 * not get to disagree with its group.
 */

/**
 * One ink on a dark card, and it is pure white.
 *
 * Everything here used to sit on a ladder of translucent whites, and
 * the result read as grey. Rank is carried by size and weight now —
 * see ``CardHeading`` (13.5 semibold), the figure (28 serif) and the
 * caption (12.5 regular) — so no line is dimmed to say it matters
 * less. The caption also lost its italic: a whole sentence in italic
 * serif is harder to read than the thing it supports.
 */
const INK = CARD.ink

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
  emphasis,
}: {
  metric: MetricValue | null
  previous?: MetricValue | null
  previousLabel?: string | null
  hue?: InsightHue
  /** A short line under the figure, in the warm register. */
  caption?: string
  /**
   * Give the whole card a colour, for a figure that should be found
   * first on the page.
   *
   * Colouring the *value* alone was the earlier attempt and it read
   * as disconnected — an amber number floating on a navy card, with
   * the card itself saying nothing. The kinds are distinct because an
   * outstanding obligation is not an overdue one and neither is a
   * failure; see ``EMPHASIS``. Reserve this for figures that genuinely
   * deserve to interrupt someone.
   */
  emphasis?: EmphasisKind
}) {
  const [open, setOpen] = useState(false)
  const detailsId = useId()
  const group = useCardSurface()
  const step = CARD_SURFACES[group]

  if (!metric) {
    return (
      <div
        className="rounded-2xl p-5"
        style={{ background: step.surface, border: `1px solid ${step.edge}` }}
      >
        <p className="text-[12.5px]" style={{ color: INK }}>
          Not available
        </p>
      </div>
    )
  }

  const emph = emphasis ? EMPHASIS[emphasis] : null
  const surface = emph
    ? {
        background: emph.surface,
        border: '1px solid rgba(255, 255, 255, 0.22)',
        // Hover lives in CSS rather than React state so a card that
        // is not interactive does not need a listener to look alive.
        ['--emph-hover' as string]: emph.hover,
      }
    : { background: step.surface, border: `1px solid ${step.edge}` }

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
      className={`flex min-w-0 flex-col rounded-2xl p-5 break-words${
        emph ? ' transition-colors hover:[background:var(--emph-hover)]' : ''
      }`}
      style={surface}
    >
      <CardHeading hue={hue} plain={Boolean(emph)}>
        {def.display_name}
      </CardHeading>

      {emph && (
        // A chip, not an uppercase eyebrow — Fresh Collective's design
        // language rules those out, and this needs to read as a state
        // ("Outstanding", not "Overdue") rather than as a label for
        // the heading above it.
        <p className="mt-2">
          <span
            className="inline-block rounded-full px-2 py-[3px] text-[11.5px] font-semibold"
            // Darkens rather than lightens the surface. A translucent
            // *white* chip read as the obvious choice and took white
            // text below AA on two of the four kinds; going the other
            // way raises contrast instead of eroding it.
            style={{ color: INK, background: 'rgba(0, 0, 0, 0.22)' }}
          >
            {emph.label}
          </span>
        </p>
      )}

      {metric.available ? (
        <p
          className="mt-2.5 font-serif text-[26px] leading-tight md:text-[28px]"
          style={{ color: INK }}
        >
          {formatValue(metric)}
        </p>
      ) : (
        <>
          <p
            className="mt-3 font-serif text-[22px] leading-tight"
            style={{ color: INK }}
          >
            Not yet
          </p>
          <p className="mt-1 text-[12.5px]" style={{ color: INK }}>
            {metric.unavailable_reason}
          </p>
        </>
      )}

      {caption && metric.available && (
        <p className="mt-1.5 text-[12.5px] leading-snug" style={{ color: INK }}>
          {caption}
        </p>
      )}

      {comparison && (
        <p className="mt-3 text-[12.5px]" style={{ color: INK }}>
          {comparison}
        </p>
      )}

      {note && (
        <p className="mt-2 text-[12px]" style={{ color: CARD.hue.gold }}>
          {note}
        </p>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={detailsId}
        className="mt-3 rounded text-[12px] underline decoration-dotted underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2"
        style={{ color: INK, outlineColor: CARD.focus }}
      >
        {open ? 'Hide what this means' : 'What does this mean?'}
      </button>

      {open && (
        <div
          id={detailsId}
          className="mt-3 rounded-lg px-3 py-2.5"
          style={{ background: step.well }}
        >
          <p className="text-[12.5px]" style={{ color: INK }}>
            {def.definition}
          </p>
          {def.limitations && (
            <p className="mt-2 text-[12.5px]" style={{ color: INK }}>
              <strong style={{ fontWeight: 600 }}>Worth knowing: </strong>
              {def.limitations}
            </p>
          )}
          <dl className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11.5px]">
            <dt style={{ color: INK }}>Comes from</dt>
            <dd style={{ color: INK }}>{def.source_of_truth}</dd>
            <dt style={{ color: INK }}>Counted by</dt>
            <dd style={{ color: INK }}>{describeBasis(def.date_basis)}</dd>
            <dt style={{ color: INK }}>Adds up?</dt>
            <dd style={{ color: INK }}>
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
  plain = false,
  children,
}: {
  hue: InsightHue
  /**
   * Drop the dot. On a full-colour card it would be a second colour
   * competing with the surface, and the surface is already the
   * association the dot exists to make.
   */
  plain?: boolean
  children: React.ReactNode
}) {
  return (
    <h4 className="flex items-start gap-1.5 text-[13.5px] font-semibold leading-snug">
      {!plain && (
        <span
          aria-hidden="true"
          className="mt-[5px] inline-block h-[7px] w-[7px] shrink-0 rounded-full"
          style={{ background: CARD.hue[hue] }}
        />
      )}
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
 * composited over ``CARD.surface``, so a teal note and a gold note
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
  const group = useCardSurface()
  const step = CARD_SURFACES[group]
  const tint = accent === 'plain' ? null : CARD.noteTint[accent]
  const edge = accent === 'plain' ? step.edge : CARD.noteEdge[accent]
  return (
    <div
      className={`min-w-0 rounded-2xl p-5 break-words ${span ?? ''}`}
      style={{
        // The accent tints whichever step the group is on rather than
        // replacing it, so a note stays recognisably the same object
        // all the way down the ramp instead of becoming a fifth
        // colour that interrupts the progression.
        background: tint
          ? `linear-gradient(0deg, ${tint}, ${tint}), ${step.surface}`
          : step.surface,
        border: `1px solid ${edge}`,
      }}
    >
      {children}
    </div>
  )
}
