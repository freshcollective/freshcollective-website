/**
 * The World Insights palette — drawn from Fresh Collective's own tokens.
 *
 * World Insights should look like part of the platform rather than a
 * reporting product bolted to it, so every colour here traces to
 * `src/styles/fc-tokens.css` or to the named palette in
 * `docs/fresh-design-language.md`. Nothing is invented.
 *
 * Two families, deliberately separate
 * -----------------------------------
 * **Identity** colours say *which series this is*. They carry no
 * meaning beyond that: watermelon is the fourth line on a chart, not a
 * problem.
 *
 * **Status** colours say *how worried to be*, and are the ones the
 * design language reserves — "status colours only appear inside status
 * badges, dots, and inline validation". They come straight from
 * `--fc-status-*` and are never used for a data series.
 *
 * Keeping them apart is what lets watermelon become an ordinary chart
 * colour without making a genuine warning less recognisable. The
 * earlier World Management palette conflated the two: coral meant both
 * "refunds" and "act on this", so either the chart implied alarm or
 * the alarm looked like a chart.
 *
 * Why these steps and not the tokens exactly
 * ------------------------------------------
 * `--fc-accent-500` (#38A09E) and the design language's navy (#3D6289)
 * are correct for surfaces, borders and UI accents, and both fall
 * below the chroma floor a *data mark* needs — against white they read
 * as grey, which the palette validator reports as a failure rather
 * than a preference. The chart steps below hold the same hues at the
 * saturation a 2px line needs. The UI steps keep the token values,
 * because a chip or a border is a large shape and does not have the
 * same problem.
 *
 * Validated as a categorical palette against a white surface:
 * lightness band, chroma floor, colour-vision separation and
 * normal-vision separation all pass. Gold alone sits below 3:1
 * contrast, which obliges visible labels and a table view — both
 * present on every chart — and the design language already reserves
 * gold for sparing use.
 *
 *   node scripts/validate_palette.js \
 *     "#0E9A95,#1D5390,#D4B048,#DC6F5C" --mode light --surface "#FFFFFF"
 */

export type InsightHue = 'teal' | 'navy' | 'gold' | 'watermelon'

/** Fixed order, never cycled. A fifth series is not a generated hue. */
export const INSIGHT_HUES: readonly InsightHue[] = [
  'teal',
  'navy',
  'gold',
  'watermelon',
] as const

/** Data-mark colours: the hue at the strength a line or bar needs. */
export const HUE_MARK: Record<InsightHue, string> = {
  teal: '#0E9A95',
  navy: '#1D5390',
  gold: '#D4B048',
  watermelon: '#DC6F5C',
}

/**
 * UI steps for chips, dots and borders, at the token values.
 *
 * `text` is the readable-on-white version of each hue, `bg` and
 * `border` the wash and hairline. These are large shapes and short
 * strings, so they keep the gentler token colours.
 */
export const HUE_UI: Record<
  InsightHue,
  { dot: string; text: string; bg: string; border: string }
> = {
  teal: {
    dot: '#0E9A95',
    text: '#246B6A', // --fc-accent-700
    bg: 'rgba(56, 160, 158, 0.10)',
    border: 'rgba(56, 160, 158, 0.28)',
  },
  navy: {
    dot: '#1D5390',
    text: '#2B4A6F',
    bg: 'rgba(61, 98, 137, 0.10)',
    border: 'rgba(61, 98, 137, 0.26)',
  },
  gold: {
    dot: '#D4B048',
    text: '#8A6A15',
    bg: 'rgba(212, 176, 72, 0.12)',
    border: 'rgba(212, 176, 72, 0.30)',
  },
  watermelon: {
    dot: '#DC6F5C',
    text: '#A8402C',
    bg: 'rgba(220, 111, 92, 0.10)',
    border: 'rgba(220, 111, 92, 0.28)',
  },
}

/**
 * Status, from `--fc-status-*`. Never a series colour.
 *
 * Amber for a warning and a deep red for an error are distinct from
 * every identity hue above — in particular from watermelon, so a
 * genuine obligation still reads as one on a page where coral-pink is
 * just the fourth line.
 */
export const STATUS = {
  healthy: { fg: '#246B6A', bg: 'rgba(56, 160, 158, 0.10)', border: 'rgba(56, 160, 158, 0.28)' },
  warning: { fg: '#B45309', bg: 'rgba(217, 119, 6, 0.10)', border: 'rgba(217, 119, 6, 0.30)' },
  error: { fg: '#B91C1C', bg: 'rgba(185, 28, 28, 0.07)', border: 'rgba(185, 28, 28, 0.26)' },
} as const

/** Surfaces, ink and hairlines, from the token layer. */
export const SURFACE = {
  /** Clean white behind the reporting content, not a grey wash. */
  page: '#FFFFFF',
  /** A barely-there tint so a card still separates from the page. */
  cardEdge: 'rgba(15, 30, 55, 0.08)',
  card: '#FFFFFF',
} as const

export const INK = {
  /** --fc-ink-heading. Headings, figures, table keys. */
  heading: '#0C1826',
  /** Body copy on a card. */
  body: 'rgba(12, 24, 38, 0.82)',
  /** Supporting lines, captions, axis labels. */
  muted: 'rgba(12, 24, 38, 0.58)',
  /** Disclosure triggers and the quietest metadata. */
  faint: 'rgba(12, 24, 38, 0.44)',
} as const

/** Chart furniture. Recessive by design — the marks carry the chart. */
export const CHART = {
  grid: 'rgba(15, 30, 55, 0.07)',
  axis: 'rgba(15, 30, 55, 0.16)',
  /** A period nothing is known about. */
  blank: 'rgba(15, 30, 55, 0.13)',
  focus: '#246B6A',
} as const

/**
 * A status *tone* — the vocabulary surfaces use when the colour means
 * "how is this going", not "which series is this".
 *
 * `alert` is deliberately not one of the four identity hues. Before
 * this pass, Data Health drew a failed reporting run in the same coral
 * the Money charts used for refunds, so the page had no colour left
 * that meant *act on this*. It now takes the status red, which no
 * series uses.
 */
export type Tone = 'teal' | 'navy' | 'gold' | 'alert'

export function toneStyle(tone: Tone): {
  dot: string
  text: string
  bg: string
  border: string
} {
  if (tone === 'alert') {
    return {
      dot: STATUS.error.fg,
      text: STATUS.error.fg,
      bg: STATUS.error.bg,
      border: STATUS.error.border,
    }
  }
  return HUE_UI[tone]
}
