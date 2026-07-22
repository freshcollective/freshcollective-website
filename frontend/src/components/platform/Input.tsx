import { forwardRef, type InputHTMLAttributes } from 'react'
import { cn } from './utils'

/**
 * Input
 *
 * The canonical single-line text input. Combine with `FormField` for the
 * label + helper + error anatomy.
 *
 * @see docs/fresh-design-language.md §10
 */

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  /** Adds an error border. Prefer setting error via FormField's `error` prop. */
  invalid?: boolean
}

export const Input = forwardRef<HTMLInputElement, Props>(function Input(
  { invalid, className, ...rest }, ref,
) {
  return (
    <input
      ref={ref}
      className={cn(
        'w-full rounded-[var(--fc-radius-md)] bg-[color:var(--fc-surface-card)] px-3 py-2.5',
        'text-[length:var(--fc-fs-body)] leading-[var(--fc-lh-body)] text-[color:var(--fc-ink-primary)]',
        'placeholder:text-[color:var(--fc-ink-disabled)]',
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
    />
  )
})
