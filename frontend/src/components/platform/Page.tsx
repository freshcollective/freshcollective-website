import type { ReactNode } from 'react'
import { cn } from './utils'

/**
 * Page
 *
 * The outermost application shell wrapper for a route. Applies the platform
 * page background, sets a max container width, and pads horizontally by
 * container rule (§5.1).
 *
 * @see docs/fresh-design-language.md §5.1
 */

interface Props {
  /** Container width. Application is 1180px, reading is 720px. */
  width?: 'app' | 'reading'
  /** Suppress vertical padding — useful when the first child is a full-bleed hero. */
  noVerticalPad?: boolean
  className?: string
  children: ReactNode
}

export function Page({
  width = 'app', noVerticalPad = false, className, children,
}: Props) {
  const maxWidth =
    width === 'reading'
      ? 'max-w-[var(--fc-container-reading)]'
      : 'max-w-[var(--fc-container-app)]'
  return (
    <div
      className={cn(
        'mx-auto w-full',
        maxWidth,
        'px-6 md:px-10',
        noVerticalPad ? '' : 'py-8 md:py-10',
        className,
      )}
    >
      {children}
    </div>
  )
}
