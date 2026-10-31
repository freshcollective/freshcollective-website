'use client'

import { INK, SURFACE } from '@/lib/insights-palette'

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
