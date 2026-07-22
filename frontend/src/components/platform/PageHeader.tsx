import type { ReactNode } from 'react'
import { Heading } from './Heading'
import { Text } from './Text'
import { cn } from './utils'

/**
 * PageHeader
 *
 * The canonical header block at the top of an application page:
 *   [optional eyebrow]
 *   Page title
 *   [optional description]
 *   [optional actions on the right]
 *
 * @see docs/fresh-design-language.md §12, §22
 */

interface Props {
  /** Small uppercase eyebrow, e.g. "Creator Studio". */
  eyebrow?: string
  title: string
  description?: string
  /** Action buttons, aligned right on desktop, stacked below on mobile. */
  actions?: ReactNode
  className?: string
}

export function PageHeader({
  eyebrow, title, description, actions, className,
}: Props) {
  return (
    <header
      className={cn(
        'mb-8 flex flex-wrap items-start justify-between gap-4',
        className,
      )}
    >
      <div className="min-w-0 flex-1">
        {eyebrow && (
          <Text
            variant="eyebrow"
            className="mb-2 text-[color:var(--fc-accent-500)]"
          >
            {eyebrow}
          </Text>
        )}
        <Heading variant="page-title" as="h1">{title}</Heading>
        {description && (
          <Text variant="body" className="mt-2 max-w-[60ch]">
            {description}
          </Text>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      )}
    </header>
  )
}
