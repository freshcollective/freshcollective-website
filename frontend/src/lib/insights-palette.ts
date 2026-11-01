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
  /**
   * `--fc-surface-inverse`, the platform's deep navy, used here as a
   * deliberate dark anchor rather than a fourth mid-tone hue.
   *
   * The palette validator FAILs it twice — lightness 0.201 against a
   * 0.43-0.77 band, chroma 0.033 against a 0.1 floor — and both
   * checks are asking "is this a legible mid-tone hue?", which is the
   * wrong question for an ink-dark anchor. The checks that decide
   * whether a reader can tell the series apart both PASS with it, and
   * the worst pair in the palette (watermelon-teal, ΔE 8.4 protan)
   * does not involve navy at all: at L 0.20 against teal, gold and
   * watermelon it is the *most* separable slot, by lightness rather
   * than by hue.
   *
   * The real constraint it has to clear is that a near-black line
   * could read as chart furniture rather than as data. It does not:
   * the grid is 7% ink and the axis 16%, so inside the plot a 2px
   * #071824 line is by far the darkest thing and reads as the series.
   * Verified by rendering, not by assuming.
   *
   * Where navy *cannot* work — a navy dot on a navy card — the
   * exception is ``CARD.hue.navy``, not a second palette.
   */
  navy: '#071824',
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
  /**
   * Supporting lines, captions, axis labels.
   *
   * Both this and ``faint`` below are set by contrast rather than by
   * eye. On white, this hue needs alpha 0.62 to clear WCAG AA for
   * normal text; the airier 0.58 and 0.44 they replaced measured
   * 4.4:1 and 3.3:1, and the lighter of the two was carrying the
   * "What does this mean?" button — interactive text, so the 3:1
   * non-text allowance did not apply to it.
   */
  muted: 'rgba(12, 24, 38, 0.68)', // 6.2:1
  /** Disclosure triggers and the quietest metadata. */
  faint: 'rgba(12, 24, 38, 0.62)', // 5.0:1
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
 * The deep-navy card, and everything that has to be legible on it.
 *
 * The surface is `--fc-surface-inverse` (#071824) — Fresh Collective's
 * existing inverse surface, the one behind every `PageHero` and at the
 * top of the public footer, so the figures band reads as part of the
 * platform rather than as a reporting product's idea of a dark card.
 * Not a new navy, and not `--fc-pathway-navy`, which is a *content*
 * colour for Pathway cards.
 *
 * This is a **selected** dark palette, not the light one inverted.
 * Every value below was measured against #071824, and most of the
 * light-surface colours turned out to be wrong there in both
 * directions: the dark steps chosen to carry a 2px line on white
 * (teal #0E9A95) go muddy, while the deep status red (#B91C1C) falls
 * to 2.79:1 and disappears.
 *
 * Where an existing token already works on navy it is used unchanged —
 * `--fc-accent-400`, gold, watermelon and `--fc-status-warning` all
 * clear AA on this surface. Only two needed a lighter step of a token
 * hue: the series blue (a navy mark on a navy card is invisible) and
 * the error red.
 */
/**
 * The metric-card surfaces: a graduated run through Fresh Collective's
 * navy and teal families.
 *
 * One navy card is calm. Six rows of the same navy is a slab, and the
 * page stopped having a shape — so the colour now moves as you read
 * down it, navy to teal, one step per group of cards.
 *
 * **A group, never a row.** The surface is chosen by what the cards
 * mean and is carried to them by context, so four cards that sit in
 * one row on a desktop and stack into four rows on a phone keep one
 * colour. Binding colour to the physical row CSS happened to produce
 * would repaint the page at every breakpoint.
 *
 * Derived, not invented
 * ---------------------
 * ``navy`` is ``--fc-surface-inverse`` unchanged. The other three walk
 * the OKLab hue from navy's -119° to the Fresh Collective accent hue
 * at -166°, lifting lightness as they go, so the last step lands on
 * the same hue as ``--fc-accent-500`` and ``--fc-accent-700`` — one
 * family, four depths, rather than four colours that happen to sit
 * near each other. Perceptual steps are even (ΔE 11.4, 9.2, 12.9) so
 * no transition reads as a jump.
 *
 * Every surface carries pure white text, and the brightest is the
 * binding one: ``rich`` is as fresh as it can be and still clear AA
 * for body text at 5.31:1. A step brighter (L 0.56) measures 4.48:1
 * and was rejected — the teal is bounded by legibility, not taste.
 */
export type CardSurface = 'navy' | 'midnight' | 'ocean' | 'rich'

/** The order a page walks through, top to bottom. */
export const SURFACE_ORDER: readonly CardSurface[] = [
  'navy',
  'midnight',
  'ocean',
  'rich',
] as const

/**
 * The step the nth group of cards sits on, counting from the top.
 *
 * Sequential and clamped rather than spread across the ramp: a
 * reader learns "it gets greener as I go down", and that stays true
 * whether a page has two groups or five. Spreading instead — always
 * finishing on rich teal — would mean the same group took a different
 * colour on two pages, and a group that disappeared because its data
 * was missing would repaint every group below it.
 *
 * A page longer than the ramp repeats the last step. Four depths is
 * as far as the navy-to-teal family goes before white text stops
 * clearing AA, so the alternative is not a fifth colour.
 */
export function surfaceForGroup(index: number): CardSurface {
  return SURFACE_ORDER[Math.min(index, SURFACE_ORDER.length - 1)]
}

export const CARD_SURFACES: Record<
  CardSurface,
  { surface: string; edge: string; well: string; label: string }
> = {
  /** --fc-surface-inverse, unchanged. White 18.0:1. */
  navy: {
    surface: '#071824',
    edge: 'rgba(255, 255, 255, 0.12)',
    well: 'rgba(255, 255, 255, 0.06)',
    label: 'Deep navy',
  },
  /** White 13.1:1. */
  midnight: {
    surface: '#0D334F',
    edge: 'rgba(255, 255, 255, 0.14)',
    well: 'rgba(255, 255, 255, 0.07)',
    label: 'Midnight blue',
  },
  /** White 9.2:1. */
  ocean: {
    surface: '#0A4F59',
    edge: 'rgba(255, 255, 255, 0.16)',
    well: 'rgba(255, 255, 255, 0.08)',
    label: 'Deep ocean teal',
  },
  /** White 5.3:1 — the brightest the ramp can go and stay AA. */
  rich: {
    surface: '#1E7776',
    edge: 'rgba(255, 255, 255, 0.20)',
    well: 'rgba(255, 255, 255, 0.10)',
    label: 'Rich teal',
  },
}

/**
 * Everything that has to be legible on a coloured card.
 *
 * Named for the job rather than for navy, because the cards stopped
 * being all navy. ``surface``/``edge``/``well`` remain here as the
 * default step so a card with no group around it still renders.
 */
export const CARD = {
  ...CARD_SURFACES.navy,

  /**
   * One ink, and it is pure white, on every surface in the ramp.
   *
   * This replaced a ladder of translucent whites that each cleared AA
   * and still read as grey. Rank is carried by size and weight — a
   * 13.5px semibold heading over a 28px serif figure over 12.5px
   * supporting copy — so nothing on a coloured card is dimmed to
   * signal that it matters less.
   */
  ink: '#FFFFFF',

  /**
   * Identity hues as they appear on a coloured card.
   *
   * Teal, gold and watermelon are token values unchanged. Blue is a
   * lighter step of ``--fc-pathway-blue``, which at 4.17:1 is fine
   * for a dot and not for text.
   */
  hue: {
    teal: '#55B8B6',
    navy: '#6E9BD8',
    gold: '#D4B048',
    watermelon: '#DC6F5C',
  } as Record<InsightHue, string>,

  status: {
    healthy: '#55B8B6',
    warning: '#D97706',
    /** Kept OKLab ΔE 9.6 clear of watermelon. */
    error: '#FF8A80',
  },

  /**
   * The wash that marks an explanatory note among the cards.
   *
   * Composited over whichever surface the group is using, so a note
   * is recognisably the same object at every step of the ramp.
   */
  noteTint: {
    teal: 'rgba(85, 184, 182, 0.10)',
    gold: 'rgba(212, 176, 72, 0.10)',
  },
  noteEdge: {
    teal: 'rgba(85, 184, 182, 0.34)',
    gold: 'rgba(212, 176, 72, 0.34)',
  },

  /**
   * Focus ring. White, because it is the only one that survives the
   * whole ramp: the accent teal reads 7.65:1 on navy and collapses to
   * 2.25:1 on rich teal, which is the surface it would matter on.
   */
  focus: '#FFFFFF',
} as const

/**
 * Full-colour cards, for the few figures that should be found first.
 *
 * A figure that needs attention used to be an amber number on an
 * otherwise ordinary navy card, which read as disconnected — the
 * colour sat on the value alone and the card around it said nothing.
 * These give the whole card the colour instead.
 *
 * The four kinds are kept apart because conflating them is how a
 * dashboard cries wolf. **An outstanding obligation is not overdue**:
 * money owed to a creator that is simply not yet paid is the normal
 * state of a payouts ledger, and colouring it like a failure would
 * teach a caretaker to ignore the colour that means failure.
 *
 * Every surface carries pure white text, so each is a step dark
 * enough for white to clear AA. Watermelon itself (#DC6F5C) is only
 * 3.25:1 against white and cannot host body text — `obligation` uses
 * #A8402C, which is already the palette's readable form of watermelon
 * rather than a new colour.
 */
export type EmphasisKind = 'obligation' | 'overdue' | 'warning' | 'error'

export const EMPHASIS: Record<
  EmphasisKind,
  { surface: string; label: string; hover: string }
> = {
  /** Owed, and not yet due. The normal state of a payouts balance. */
  obligation: {
    surface: '#A8402C', // white 6.1:1
    label: 'Outstanding',
    hover: '#93381D',
  },
  /** Owed past the point it should have been settled. */
  overdue: {
    surface: '#8F2F1C', // white 8.0:1
    label: 'Overdue',
    hover: '#7A2817',
  },
  /** Not money: something a caretaker should look at. */
  warning: {
    surface: '#B45309', // white 5.0:1
    label: 'Needs attention',
    hover: '#92400E',
  },
  /** Something failed. Reserved, and rare. */
  error: {
    surface: '#B91C1C', // white 6.5:1
    label: 'Failed',
    hover: '#991B1B',
  },
}

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
