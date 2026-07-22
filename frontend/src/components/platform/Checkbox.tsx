import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react'
import { cn } from './utils'

/**
 * Checkbox
 *
 * Accessible checkbox with an inline label. When rendered inside a
 * `FormField` for form context, pass `label` here for the inline label.
 *
 * @see docs/fresh-design-language.md §10
 */

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: ReactNode
  /** Optional supporting description below the label. */
  description?: ReactNode
}

export const Checkbox = forwardRef<HTMLInputElement, Props>(function Checkbox(
  { label, description, className, id, ...rest }, ref,
) {
  const generated = useId()
  const inputId = id ?? generated

  const control = (
    <input
      ref={ref}
      type="checkbox"
      id={inputId}
      className={cn(
        'mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded-[var(--fc-radius-sm)]',
        'border border-[color:var(--fc-border-input)]',
        'accent-[color:var(--fc-accent-500)]',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--fc-accent-500)]/40 focus-visible:ring-offset-2',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...rest}
    />
  )

  if (!label && !description) return control

  return (
    <label
      htmlFor={inputId}
      className="flex cursor-pointer items-start gap-2.5"
    >
      {control}
      <span className="min-w-0 flex-1">
        {label && (
          <span className="block text-[length:var(--fc-fs-body)] font-[var(--fc-fw-regular)] leading-[var(--fc-lh-body)] text-[color:var(--fc-ink-primary)]">
            {label}
          </span>
        )}
        {description && (
          <span className="mt-0.5 block text-[length:var(--fc-fs-meta)] text-[color:var(--fc-ink-primary)]">
            {description}
          </span>
        )}
      </span>
    </label>
  )
})
