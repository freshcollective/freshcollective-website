'use client'

import { useId, useState } from 'react'

import {
  type MetricValue,
  comparisonSentence,
  formatValue,
  qualifierNote,
} from '@/lib/insights'
import { WM_HUE, type WMHue } from '@/lib/wm-palette'

const CARD_BG = '#FFFFFF'
const CARD_BORDER = '1px solid #E7EEF0'
const CARD_SHADOW =
  '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'
const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER = 'rgba(12, 24, 38, 0.42)'

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
  hue?: WMHue
  /** A short line under the figure, in the warm register. */
  caption?: string
  /** Let the figure take the hue's colour, so it reads as an action
   *  item. Reserve for real signal — coral should earn its presence. */
  emphasiseValue?: boolean
}) {
  const [open, setOpen] = useState(false)
  const detailsId = useId()

  if (!metric) {
    return (
      <div
        className="rounded-2xl p-5"
        style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
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
      className="rounded-2xl p-5"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <HueLabel hue={hue}>{def.display_name}</HueLabel>

      {metric.available ? (
        <p
          className="mt-3 font-serif text-[26px] leading-tight md:text-[28px]"
          style={{ color: emphasiseValue ? WM_HUE[hue].text : INK }}
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
        <p className="mt-2 text-[12px]" style={{ color: WM_HUE.gold.text }}>
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
export function HueLabel({
  hue,
  children,
}: {
  hue: WMHue
  children: React.ReactNode
}) {
  const h = WM_HUE[hue]
  return (
    <span
      className="inline-flex w-fit items-center whitespace-nowrap rounded-full px-2 py-[1px] text-[8.5px] font-semibold uppercase tracking-[0.06em]"
      style={{ background: h.bg, border: `1px solid ${h.border}`, color: h.text }}
    >
      {children}
    </span>
  )
}
