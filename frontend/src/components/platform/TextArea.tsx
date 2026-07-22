import { forwardRef, type TextareaHTMLAttributes } from 'react'
import { cn } from './utils'

/**
 * TextArea
 *
 * Multi-line text input. Combine with `FormField`.
 *
 * @see docs/fresh-design-language.md §10
 */

interface Props extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean
  /** Prevent user resize. Defaults to true for consistent layouts. */
  resizable?: boolean
}

export const TextArea = forwardRef<HTMLTextAreaElement, Props>(function TextArea(
  { invalid, resizable = false, rows = 3, className, ...rest }, ref,
) {
  return (
    <textarea
      ref={ref}
      rows={rows}
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
        resizable ? 'resize-y' : 'resize-none',
        className,
      )}
      aria-invalid={invalid || rest['aria-invalid']}
      {...rest}
    />
  )
})
