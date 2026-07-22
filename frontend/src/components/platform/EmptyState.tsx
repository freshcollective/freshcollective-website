import type { ReactNode } from 'react'
import { Heading } from './Heading'
import { Text } from './Text'
import { cn } from './utils'

/**
 * EmptyState
 *
 * The canonical empty-state block per §16. Exactly one action. No
 * illustration. Points forward.
 *
 * Rendered on a subtle `elev-1` panel with generous vertical padding.
 *
 * @see docs/fresh-design-language.md §16
 */

interface Props {
  /** Optional small icon (16–24px). */
  icon?: ReactNode
  title: string
  description?: string
  /** A single primary action, typically a `<Button variant="primary">`. */
  action?: ReactNode
  className?: string
}

export function EmptyState({
  icon, title, description, action, className,
}: Props) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-[var(--fc-radius-2xl)]',
        'bg-[color:var(--fc-surface-card)] shadow-[var(--fc-elev-1)]',
        'px-6 py-16 text-center',
        className,
      )}
    >
      {icon && (
        <span
          className="mb-2 text-[color:var(--fc-ink-disabled)]"
          aria-hidden="true"
        >
          {icon}
        </span>
      )}
      <Heading variant="subsection" as="h3">{title}</Heading>
      {description && (
        <Text variant="body" className="max-w-[42ch]">
          {description}
        </Text>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
