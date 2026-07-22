import { createElement, type ElementType, type ReactNode } from 'react'
import { cn } from './utils'

/**
 * Text
 *
 * The canonical body / meta / eyebrow / caption type primitive. Colour
 * defaults to `ink/primary` on light surfaces; pass `inverse` for dark.
 * `muted` renders `ink/disabled` and is ONLY for disabled or inactive UI
 * states — never for regular body copy.
 *
 * @see docs/fresh-design-language.md §3
 */

export type TextVariant =
  | 'body'
  | 'body-strong'
  | 'meta'
  | 'eyebrow'
  | 'caption'
  | 'stat'

interface Props {
  as?: ElementType
  variant?: TextVariant
  inverse?: boolean
  /** Renders in `ink/disabled`. Reserved for disabled/inactive UI. */
  muted?: boolean
  className?: string
  id?: string
  title?: string
  children: ReactNode
}

const VARIANT: Record<TextVariant, string> = {
  body:
    'text-[length:var(--fc-fs-body)] font-[var(--fc-fw-regular)] leading-[var(--fc-lh-body)] tracking-[var(--fc-tracking-body)]',
  'body-strong':
    'text-[length:var(--fc-fs-body)] font-[var(--fc-fw-semibold)] leading-[var(--fc-lh-body)] tracking-[var(--fc-tracking-body)]',
  meta:
    'text-[length:var(--fc-fs-meta)] font-[var(--fc-fw-regular)] leading-[var(--fc-lh-meta)]',
  eyebrow:
    'text-[length:var(--fc-fs-eyebrow)] font-[var(--fc-fw-bold)] leading-[var(--fc-lh-tight)] uppercase tracking-[var(--fc-tracking-eyebrow)]',
  caption:
    'text-[length:var(--fc-fs-meta)] font-[var(--fc-fw-regular)] leading-[var(--fc-lh-meta)]',
  stat:
    'font-[var(--fc-font-serif)] text-[length:var(--fc-fs-stat-figure)] font-[var(--fc-fw-regular)] leading-[var(--fc-lh-tight)] tracking-[var(--fc-tracking-heading)]',
}

const DEFAULT_TAG: Record<TextVariant, ElementType> = {
  body:          'p',
  'body-strong': 'p',
  meta:          'p',
  eyebrow:       'p',
  caption:       'span',
  stat:          'p',
}

export function Text({
  as, variant = 'body', inverse = false, muted = false,
  className, id, title, children,
}: Props) {
  const Tag = as ?? DEFAULT_TAG[variant]
  const color = muted
    ? 'text-[color:var(--fc-ink-disabled)]'
    : inverse
    ? 'text-[color:var(--fc-ink-inverse)]'
    : 'text-[color:var(--fc-ink-primary)]'
  return createElement(
    Tag,
    { id, title, className: cn(VARIANT[variant], color, className) },
    children,
  )
}
