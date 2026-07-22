import type { ReactNode } from 'react'
import { Heading } from './Heading'
import { Text } from './Text'
import { cn } from './utils'

/**
 * Section
 *
 * A grouped block inside a page. Provides consistent spacing between
 * sections and — when a title is passed — a labelled `<section>` element.
 *
 * @see docs/fresh-design-language.md §4, §22
 */

interface Props {
  title?: string
  description?: string
  /** Small eyebrow above the title — used to label the section context. */
  eyebrow?: string
  /** Right-aligned action(s) beside the title row. */
  actions?: ReactNode
  /** Aria label when no title is rendered but the region is meaningful. */
  ariaLabel?: string
  className?: string
  children: ReactNode
}

export function Section({
  title, description, eyebrow, actions, ariaLabel, className, children,
}: Props) {
  const showHeader = title || eyebrow || actions
  return (
    <section
      aria-label={!title && ariaLabel ? ariaLabel : undefined}
      className={cn('mb-10 last:mb-0', className)}
    >
      {showHeader && (
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            {eyebrow && (
              <Text
                variant="eyebrow"
                className="mb-1.5 text-[color:var(--fc-ink-disabled)]"
              >
                {eyebrow}
              </Text>
            )}
            {title && <Heading variant="section" as="h2">{title}</Heading>}
            {description && (
              <Text variant="body" className="mt-1 max-w-[60ch]">
                {description}
              </Text>
            )}
          </div>
          {actions && (
            <div className="flex shrink-0 items-center gap-2">{actions}</div>
          )}
        </div>
      )}
      {children}
    </section>
  )
}
