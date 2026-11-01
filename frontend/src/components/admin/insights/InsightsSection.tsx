'use client'

import { Children, createContext, isValidElement, useContext } from 'react'

import { type CardSurface, INK, SURFACE } from '@/lib/insights-palette'

/**
 * One major band of a World Insights page.
 *
 * Six pages were each building this from a `<section className="mt-12">`
 * and a hand-styled heading, which is why the sections drifted: the
 * same rank of heading appeared at three sizes, intros at two, and the
 * gaps between bands at whatever the last person typed. One component
 * makes the rhythm a property of the system rather than of each page.
 *
 * The hierarchy it enforces, top to bottom:
 *
 *   page title            — the shell
 *   **section** (here)    — serif, 19px, heading ink, over a hairline
 *   panel title           — serif, 16px (19px when a panel leads)
 *   card heading          — sans, 13.5px semibold
 *
 * Each level differs from the next in size *and* in weight or family,
 * so the rank is legible without reading the words. Before this pass a
 * section heading and a panel heading were both 16–17px serif, which
 * is why a long page read as one undifferentiated stack.
 *
 * The rule between bands is a hairline rather than a tinted block.
 * Separation comes from space; the design language permits exactly one
 * grey and it is for disabled ink, not for striping a page.
 */
export function InsightsSection({
  title,
  intro,
  children,
  /** The first band on a page: no rule above it, since nothing precedes. */
  lead = false,
}: {
  title: string
  intro?: React.ReactNode
  children: React.ReactNode
  lead?: boolean
}) {
  return (
    <section
      className={lead ? 'mt-8' : 'mt-14 border-t pt-10'}
      style={lead ? undefined : { borderColor: SURFACE.cardEdge }}
    >
      <h3
        className="font-serif text-[19px] leading-tight tracking-[-0.01em]"
        style={{ color: INK.heading }}
      >
        {title}
      </h3>
      {intro ? (
        <p
          className="mb-6 mt-1.5 max-w-[76ch] text-[13.5px] leading-relaxed"
          style={{ color: INK.body }}
        >
          {intro}
        </p>
      ) : (
        <div className="mb-6" />
      )}
      {children}
    </section>
  )
}

/**
 * A group of supporting charts beneath a primary one.
 *
 * Only exists to keep the gap between sibling panels identical
 * everywhere; pages were alternating between `space-y-5` and stacking
 * panels with their own margins.
 */
export function PanelGroup({ children }: { children: React.ReactNode }) {
  return <div className="space-y-5">{children}</div>
}

/**
 * The surface a group of metric cards sits on.
 *
 * Context rather than a prop threaded through every card, for one
 * specific reason: the colour belongs to the *group*, and a card
 * should not be able to disagree with the group it is in. A page sets
 * the step once on ``CardGroup`` and every card and note inside picks
 * it up, so four cards that share a row on a desktop and stack into
 * four rows on a phone still share a colour.
 */
export const CardSurfaceContext = createContext<CardSurface>('navy')

export function useCardSurface(): CardSurface {
  return useContext(CardSurfaceContext)
}

/**
 * One logical group of metric cards, on one surface.
 *
 * This replaced a ``Band`` that six pages had each declared for
 * themselves — same shape, three heading sizes between them. Putting
 * it here is also what makes the colour progression maintainable: the
 * step is an argument to the group, not a colour repeated on every
 * card in it.
 *
 * Pages pass the step explicitly rather than having it inferred from
 * position. Inferring it would be tidier to call and wrong the moment
 * a group is added, removed, or hidden because its data is missing —
 * the colours would shift under a reader who had learned them.
 *
 * Emphasis cards drop to their own row
 * ------------------------------------
 * A watermelon card beside a rich teal one makes both harder to read:
 * two saturated surfaces at the same size compete, and the emphasis
 * stops reading as emphasis. So a group puts its ordinary cards in
 * one grid and any emphasis cards in a second grid directly beneath,
 * still in the group and still on the same column track, so the
 * attention card lines up with the row above rather than floating
 * free or stretching across it.
 *
 * The split is computed from the children's actual ``emphasis`` prop
 * rather than declared by the page, because the prop is conditional —
 * outstanding payouts are only an obligation while something is
 * owed. A page declaring the layout would have to repeat that
 * condition, and the two would drift.
 */
export function CardGroup({
  title,
  note,
  surface,
  columns = 4,
  children,
}: {
  title: string
  note: string
  surface: CardSurface
  /**
   * How many cards sit across a wide screen. Four by default.
   *
   * Three is for a short headline band, where six figures wrapping
   * 4+2 leaves a conspicuous hole beside the second row; 3+3 is
   * symmetrical and gives each figure the room a headline deserves.
   * Both rows of a group share whichever track is chosen, so an
   * emphasis card still lines up under the cards above it.
   */
  columns?: 3 | 4
  children: React.ReactNode
}) {
  const grid = columns === 3 ? GRID_3 : GRID_4
  const kids = Children.toArray(children)
  const standard = kids.filter((c) => !isEmphasised(c))
  const emphasised = kids.filter(isEmphasised)

  return (
    <CardSurfaceContext.Provider value={surface}>
      <section className="mb-8">
        <h3
          className="font-serif text-[15.5px] leading-tight"
          style={{ color: INK.heading }}
        >
          {title}
        </h3>
        <p
          className="mb-3 mt-1 max-w-[72ch] text-[12.5px]"
          style={{ color: INK.muted }}
        >
          {note}
        </p>
        {standard.length > 0 && <div className={grid}>{standard}</div>}
        {/*
          Only rendered when something is actually emphasised, so a
          group with no attention card gains no empty row and no extra
          gap — the common case costs nothing.
        */}
        {emphasised.length > 0 && (
          <div className={`${grid}${standard.length > 0 ? ' mt-3' : ''}`}>
            {emphasised}
          </div>
        )}
      </section>
    </CardSurfaceContext.Provider>
  )
}

/** Column tracks. Both rows of a group share one, so they align. */
const GRID_4 = 'grid gap-3 sm:grid-cols-2 lg:grid-cols-4'
const GRID_3 = 'grid gap-3 sm:grid-cols-2 lg:grid-cols-3'

/**
 * Whether a child is asking to be set apart.
 *
 * Reads the rendered element's own prop, so a card that is only
 * sometimes an obligation sits in the ordinary row the rest of the
 * time. A `false` from a `{cond && <Card/>}` is not an element and
 * falls through harmlessly.
 */
function isEmphasised(child: React.ReactNode): boolean {
  return (
    isValidElement(child) &&
    Boolean((child.props as { emphasis?: unknown } | null)?.emphasis)
  )
}

/**
 * The group surface, for content that is not a ``CardGroup``.
 *
 * Some explanatory panels sit between groups rather than inside one —
 * the not-profit note on Money, the development comparison on World
 * Builders. They still belong to a step of the progression, and
 * without this they would silently fall back to navy and interrupt it.
 */
export function CardSurfaceScope({
  surface,
  children,
}: {
  surface: CardSurface
  children: React.ReactNode
}) {
  return (
    <CardSurfaceContext.Provider value={surface}>
      {children}
    </CardSurfaceContext.Provider>
  )
}
