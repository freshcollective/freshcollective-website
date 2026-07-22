import { createElement, type ReactNode } from 'react'
import { cn } from './utils'

/**
 * Heading
 *
 * Renders a semantic heading (h1–h4) with a fixed Fresh Collective type variant.
 * Weight, family, tracking and line-height are locked to the variant —
 * consumers cannot override them via `fontWeight` because Fresh Collective permits
 * only three weights and hides that decision here.
 *
 * @see docs/fresh-design-language.md §3
 */

export type HeadingVariant =
  | 'display-xl'
  | 'display-l'
  | 'display-m'
  | 'page-title'
  | 'section'
  | 'subsection'

interface Props {
  as?: 'h1' | 'h2' | 'h3' | 'h4'
  variant?: HeadingVariant
  /** Renders on a dark surface. Ink becomes white. */
  inverse?: boolean
  className?: string
  id?: string
  children: ReactNode
}

const VARIANT: Record<HeadingVariant, string> = {
  'display-xl':
    'font-[var(--fc-font-serif)] text-[length:var(--fc-fs-display-xl)] font-[var(--fc-fw-semibold)] leading-[var(--fc-lh-display)] tracking-[var(--fc-tracking-display)]',
  'display-l':
    'font-[var(--fc-font-serif)] text-[length:var(--fc-fs-display-l)] font-[var(--fc-fw-semibold)] leading-[var(--fc-lh-display)] tracking-[var(--fc-tracking-display)]',
  'display-m':
    'font-[var(--fc-font-serif)] text-[length:var(--fc-fs-display-m)] font-[var(--fc-fw-semibold)] leading-[var(--fc-lh-display)] tracking-[var(--fc-tracking-display)]',
  'page-title':
    'font-[var(--fc-font-serif)] text-[length:var(--fc-fs-page-title)] font-[var(--fc-fw-semibold)] leading-[var(--fc-lh-heading)] tracking-[var(--fc-tracking-heading)]',
  section:
    'text-[length:var(--fc-fs-section)] font-[var(--fc-fw-semibold)] leading-[var(--fc-lh-heading)] tracking-[var(--fc-tracking-heading)]',
  subsection:
    'text-[length:var(--fc-fs-subsection)] font-[var(--fc-fw-semibold)] leading-[var(--fc-lh-heading)] tracking-[var(--fc-tracking-heading)]',
}

const DEFAULT_TAG: Record<HeadingVariant, 'h1' | 'h2' | 'h3' | 'h4'> = {
  'display-xl': 'h1',
  'display-l':  'h1',
  'display-m':  'h2',
  'page-title': 'h1',
  section:      'h2',
  subsection:   'h3',
}

export function Heading({
  as, variant = 'section', inverse = false, className, id, children,
}: Props) {
  const Tag = as ?? DEFAULT_TAG[variant]
  const color = inverse
    ? 'text-[color:var(--fc-ink-heading-inverse)]'
    : 'text-[color:var(--fc-ink-heading)]'
  return createElement(
    Tag,
    { id, className: cn(VARIANT[variant], color, className) },
    children,
  )
}
