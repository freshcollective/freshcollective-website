'use client'

import { createContext, useContext } from 'react'

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
 */
export function CardGroup({
  title,
  note,
  surface,
  children,
}: {
  title: string
  note: string
  surface: CardSurface
  children: React.ReactNode
}) {
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
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {children}
        </div>
      </section>
    </CardSurfaceContext.Provider>
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
