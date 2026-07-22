'use client'

import { forwardRef, type InputHTMLAttributes } from 'react'
import { cn } from './utils'

/**
 * SearchInput
 *
 * A text input with a magnifying-glass affordance on the left and an
 * optional clear button on the right when a value is present.
 *
 * @see docs/fresh-design-language.md §10, §12
 */

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  /** Called when the clear (×) button is clicked. */
  onClear?: () => void
}

export const SearchInput = forwardRef<HTMLInputElement, Props>(function SearchInput(
  { value, onClear, className, placeholder = 'Search…', ...rest }, ref,
) {
  const hasValue = typeof value === 'string' && value.length > 0
  return (
    <div className={cn('relative min-w-[240px]', className)}>
      <svg
        aria-hidden="true"
        width="15" height="15" viewBox="0 0 24 24" fill="none"
        className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[color:var(--fc-ink-primary)]/50"
      >
        <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.6" />
        <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      <input
        ref={ref}
        type="search"
        value={value}
        placeholder={placeholder}
        className={cn(
          'w-full rounded-[var(--fc-radius-md)] bg-[color:var(--fc-surface-card)] py-2.5 pl-10 pr-9',
          'text-[length:var(--fc-fs-body)] leading-[var(--fc-lh-body)] text-[color:var(--fc-ink-primary)]',
          'placeholder:text-[color:var(--fc-ink-disabled)]',
          'border border-[color:var(--fc-border-input)] transition-colors duration-[var(--fc-motion-hover)]',
          'hover:border-[color:var(--fc-border-input-hover)]',
          'focus:outline-none focus:border-[color:var(--fc-accent-500)]',
          'focus:shadow-[var(--fc-focus-ring-input)]',
        )}
        {...rest}
      />
      {hasValue && onClear && (
        <button
          type="button"
          onClick={onClear}
          aria-label="Clear search"
          className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex h-6 w-6 items-center justify-center rounded-full text-[color:var(--fc-ink-primary)]/50 transition-colors hover:bg-[color:var(--fc-surface-muted)] hover:text-[color:var(--fc-ink-primary)]"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      )}
    </div>
  )
})
