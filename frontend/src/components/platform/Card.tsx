import { forwardRef, type HTMLAttributes, type ReactNode } from 'react'
import { cn } from './utils'

/**
 * Card
 *
 * The fundamental object surface. Uses shadow for elevation — never a
 * border — per §7 and §9.
 *
 * Variants:
 *   - default     white, elev-1 at rest, elev-3 on hover
 *   - draft       muted background, same elevation, otherwise identical
 *   - archived    72% opacity, muted background
 *   - selected    teal halo (matching Fresh Collective selected-drawer state)
 *   - flat        elev-0 — use only inside another card
 *
 * Padding:
 *   - sm  (px-4 py-3)      compact — for tight list items
 *   - md  (px-5 py-5)      DEFAULT — most cards
 *   - lg  (px-6 py-6)      feature / detail cards
 *
 * @see docs/fresh-design-language.md §9
 */

export type CardVariant = 'default' | 'draft' | 'archived' | 'selected' | 'flat'
export type CardPadding = 'sm' | 'md' | 'lg' | 'none'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant
  padding?: CardPadding
  /** When true, the card gets a hover-lift + shadow raise. */
  interactive?: boolean
  as?: 'div' | 'article' | 'section' | 'button'
  children: ReactNode
}

const VARIANT_STYLE: Record<CardVariant, string> = {
  default:
    'bg-[color:var(--fc-surface-card)] shadow-[var(--fc-elev-1)]',
  draft:
    'bg-[color:var(--fc-surface-muted)] shadow-[var(--fc-elev-1)]',
  archived:
    'bg-[color:var(--fc-surface-muted)] shadow-[var(--fc-elev-1)] opacity-[0.72]',
  selected:
    'bg-[color:var(--fc-surface-card)] shadow-[var(--fc-elev-selected)]',
  flat:
    'bg-[color:var(--fc-surface-card)] shadow-none',
}

const PADDING: Record<CardPadding, string> = {
  none: 'p-0',
  sm:   'px-4 py-3',
  md:   'px-5 py-5',
  lg:   'px-6 py-6',
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  {
    variant = 'default', padding = 'md', interactive = false, as: Tag = 'div',
    className, children, ...rest
  },
  ref,
) {
  const interactiveClasses = interactive
    ? 'cursor-pointer transition-shadow duration-[var(--fc-motion-card)] ease-out hover:shadow-[var(--fc-elev-3)] hover:-translate-y-px focus:outline-none focus-visible:shadow-[var(--fc-elev-3)] focus-visible:ring-2 focus-visible:ring-[color:var(--fc-accent-500)]/40'
    : ''
  const El = Tag as 'div'
  return (
    <El
      ref={ref}
      className={cn(
        'rounded-[var(--fc-radius-2xl)]',
        VARIANT_STYLE[variant],
        PADDING[padding],
        interactiveClasses,
        className,
      )}
      {...rest}
    >
      {children}
    </El>
  )
})

/**
 * Card.Header / Card.Body / Card.Footer — optional composition helpers.
 * A card doesn't have to use these; simple cards can pass children directly.
 */

export function CardHeader({
  children, className,
}: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        'flex items-start justify-between gap-3',
        className,
      )}
    >
      {children}
    </div>
  )
}

export function CardBody({
  children, className,
}: { children: ReactNode; className?: string }) {
  return <div className={cn('mt-3', className)}>{children}</div>
}

export function CardFooter({
  children, className,
}: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        'mt-4 flex flex-wrap items-center justify-between gap-2',
        className,
      )}
    >
      {children}
    </div>
  )
}
