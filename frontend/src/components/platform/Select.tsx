import { forwardRef, type SelectHTMLAttributes, type ReactNode } from 'react'
import { cn } from './utils'

/**
 * Select
 *
 * Native `<select>` styled per the design language. Combine with `FormField`.
 *
 * @see docs/fresh-design-language.md §10
 */

interface Props extends SelectHTMLAttributes<HTMLSelectElement> {
  invalid?: boolean
  children: ReactNode
}

export const Select = forwardRef<HTMLSelectElement, Props>(function Select(
  { invalid, className, children, ...rest }, ref,
) {
  return (
    <div className="relative">
      <select
        ref={ref}
        className={cn(
          'w-full appearance-none rounded-[var(--fc-radius-md)] bg-[color:var(--fc-surface-card)] pl-3 pr-9 py-2.5',
          'text-[length:var(--fc-fs-body)] leading-[var(--fc-lh-body)] text-[color:var(--fc-ink-primary)]',
          'border transition-colors duration-[var(--fc-motion-hover)]',
          invalid
            ? 'border-[color:var(--fc-status-error)]'
            : 'border-[color:var(--fc-border-input)] hover:border-[color:var(--fc-border-input-hover)]',
          'focus:outline-none focus:border-[color:var(--fc-accent-500)]',
          'focus:shadow-[var(--fc-focus-ring-input)]',
          'disabled:cursor-not-allowed disabled:bg-[color:var(--fc-surface-muted)] disabled:text-[color:var(--fc-ink-disabled)]',
          className,
        )}
        aria-invalid={invalid || rest['aria-invalid']}
        {...rest}
      >
        {children}
      </select>
      <svg
        aria-hidden="true"
        width="12" height="12" viewBox="0 0 12 12" fill="none"
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[color:var(--fc-ink-primary)]"
      >
        <path d="M2.5 4l3.5 4 3.5-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  )
})
