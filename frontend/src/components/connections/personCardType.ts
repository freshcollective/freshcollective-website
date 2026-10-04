/**
 * One typography decision per semantic element on a person card.
 *
 * Why this exists
 * ---------------
 * The card renders six relationship states through six JSX branches,
 * and every branch used to declare its own type inline. The same
 * semantic element therefore drifted between branches, which is
 * exactly what the populated prototype made visible:
 *
 *   * The three relationship-state lines — "✓ Connected", "Hello
 *     sent", "👋 … said hello" — were all 13px serif, in three
 *     different weights (semibold, regular, and regular wrapping an
 *     inner semibold span).
 *   * ``Cancel`` was ``font-medium`` while every other text action was
 *     ``font-semibold``, at the same size and in the same row.
 *   * The serif was requested two ways: the ``font-serif`` utility on
 *     the name, and a literal ``fontFamily: 'Georgia, serif'`` inline
 *     in five branches. Both resolve to Georgia here — ``@theme``
 *     pins ``--font-serif`` to the same stack as ``--fc-font-serif`` —
 *     so this one was latent rather than visible, and would have
 *     diverged the moment either stack was touched.
 *   * Seven distinct sizes (19 / 14 / 13.5 / 13 / 12.5 / 11.5 / 11),
 *     four of them half-pixel values that exist nowhere in the Fresh
 *     Collective scale.
 *
 * So the card gets a role map rather than per-branch styling. A branch
 * names the role it is rendering; it does not get to choose a weight.
 *
 * Sizes come from the Fresh Collective scale — ``--fc-fs-body`` 14px,
 * ``--fc-fs-meta`` 12px, ``--fc-fs-eyebrow`` 11px — so the card sits on
 * the same type system as the rest of the platform. The half-pixel
 * values are gone; each moved by at most 1px, so the card looks as it
 * did while being describable. ``TITLE_PX`` is the one deliberate
 * exception and is commented where it is defined.
 *
 * Colour is not tokenised here. The card's navy tints
 * (``rgba(12,24,38,…)``) are the established Fresh Collective card
 * palette and the ink tokens offer only ``#000`` and one permitted
 * grey, so swapping them would change how the card feels rather than
 * how consistent it is. They are kept exactly as they were — but each
 * is now written once, beside the role that uses it.
 *
 * This file is the card's typography and nothing else: no layout, no
 * spacing between blocks, no colour decisions of its own.
 */

/** Fresh Collective ink, as the card has always used it. */
const INK_HEADING = '#0C1826'
const INK_BODY = 'rgba(12, 24, 38, 0.78)'
const INK_SUPPORTING = 'rgba(12, 24, 38, 0.6)'
const INK_EVIDENCE = 'rgba(12, 24, 38, 0.72)'
const INK_LABEL = 'rgba(12, 24, 38, 0.42)'
const INK_FOOTER = 'rgba(12, 24, 38, 0.45)'
const INK_STATE = '#1E6E6C'
const INK_ACTION = '#2F8F8D'
const INK_ERROR = '#B4483C'

/**
 * The card title size.
 *
 * The one value not on the shared scale, because the scale has no
 * serif step between ``--fc-fs-subsection`` (15px, and sans) and
 * ``--fc-fs-page-title`` (23px, a page heading). A card title is
 * neither. 19px is the proportion the three-card row was designed at,
 * so it stays — named here rather than repeated as a literal, and
 * deliberately not promoted into the global scale: one card is not
 * grounds for a new platform-wide step.
 */
const TITLE_PX = '19px'

const SERIF = 'font-[var(--fc-font-serif)]'
const BODY_SIZE = 'text-[length:var(--fc-fs-body)]'
const META_SIZE = 'text-[length:var(--fc-fs-meta)]'
const REGULAR = 'font-[var(--fc-fw-regular)]'
const SEMIBOLD = 'font-[var(--fc-fw-semibold)]'
const LH_BODY = 'leading-[var(--fc-lh-body)]'
const LH_META = 'leading-[var(--fc-lh-meta)]'

export interface CardTypeRole {
  className: string
  style: { color: string; fontSize?: string }
}

/**
 * Every piece of text on a person card, by what it *is* rather than by
 * which branch happens to render it.
 */
export const personCardType = {
  /** The person's name. The card's focal point. */
  name: {
    className: `${SERIF} ${REGULAR} leading-[var(--fc-lh-heading)] break-words`,
    style: { color: INK_HEADING, fontSize: TITLE_PX },
  },

  /** The human sentence explaining why this person is here. */
  reason: {
    className: `${SERIF} ${BODY_SIZE} ${REGULAR} ${LH_BODY} break-words`,
    style: { color: INK_BODY },
  },

  /** The "Shared" field label. Small, structural, not an eyebrow. */
  sharedLabel: {
    className:
      'text-[length:var(--fc-fs-eyebrow)] font-[var(--fc-fw-semibold)] '
      + 'uppercase tracking-[var(--fc-tracking-eyebrow)] '
      + 'leading-[var(--fc-lh-tight)]',
    style: { color: INK_LABEL },
  },

  /** One shared Gathering or Pathway. */
  evidence: {
    className: `${BODY_SIZE} ${REGULAR} ${LH_META} break-words`,
    style: { color: INK_EVIDENCE },
  },

  /**
   * Where this relationship stands: connected, hello sent, or somebody
   * waiting on you. One treatment for all three — they are the same
   * kind of statement about the same relationship, and reading them in
   * three weights was the clearest inconsistency on the card.
   */
  state: {
    className: `${SERIF} ${BODY_SIZE} ${SEMIBOLD} ${LH_BODY}`,
    style: { color: INK_STATE },
  },

  /** The question asked before a hello is sent. */
  prompt: {
    className: `${SERIF} ${BODY_SIZE} ${REGULAR} ${LH_BODY}`,
    style: { color: INK_HEADING },
  },

  /** What that question means, under it. */
  supporting: {
    className: `${META_SIZE} ${REGULAR} ${LH_META}`,
    style: { color: INK_SUPPORTING },
  },

  /** Something did not work. */
  error: {
    className: `${META_SIZE} ${REGULAR} ${LH_META}`,
    style: { color: INK_ERROR },
  },

  /** A text action: "Say hello", "Message →". */
  action: {
    className: `${BODY_SIZE} ${SEMIBOLD} ${LH_BODY}`,
    style: { color: INK_ACTION },
  },

  /** The filled primary action. Ink is set by the button itself. */
  actionPrimary: {
    className: `${BODY_SIZE} ${SEMIBOLD} ${LH_BODY}`,
    style: { color: '#FFFFFF' },
  },

  /** Stepping back from an action. Same type as any other action — only
   *  its colour says it is the quieter of the two. */
  actionQuiet: {
    className: `${BODY_SIZE} ${SEMIBOLD} ${LH_BODY}`,
    style: { color: INK_SUPPORTING },
  },

  /** Which Collective this person is already visible to you through. */
  footer: {
    className: `${META_SIZE} ${REGULAR} ${LH_META}`,
    style: { color: INK_FOOTER },
  },
} satisfies Record<string, CardTypeRole>

export type PersonCardRole = keyof typeof personCardType
