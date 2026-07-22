import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react'
import { cn } from './utils'

/**
 * Switch
 *
 * A toggle switch backed by a native checkbox for accessibility. Uses
 * `role="switch"` for correct screen-reader semantics.
 *
 * @see docs/fresh-design-language.md §10
 */

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: ReactNode
  description?: ReactNode
}

export const Switch = forwardRef<HTMLInputElement, Props>(function Switch(
  { label, description, checked, className, id, ...rest }, ref,
) {
  const generated = useId()
  const inputId = id ?? generated

  const control = (
    <span className="relative inline-flex h-6 w-10 shrink-0 items-center">
      <input
        ref={ref}
        type="checkbox"
        role="switch"
        id={inputId}
        checked={checked}
        aria-checked={checked}
        className={cn(
          'peer sr-only',
          className,
        )}
        {...rest}
      />
      {/* Track */}
      <span
        aria-hidden="true"
        className={cn(
          'block h-6 w-10 rounded-full transition-colors duration-[var(--fc-motion-hover)]',
          'bg-[rgba(15,30,55,0.14)]',
          'peer-checked:bg-[color:var(--fc-accent-500)]',
          'peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-[color:var(--fc-accent-500)]/40 peer-focus-visible:ring-offset-2',
          'peer-disabled:opacity-50 peer-disabled:cursor-not-allowed',
        )}
      />
      {/* Thumb */}
      <span
        aria-hidden="true"
        className={cn(
          'pointer-events-none absolute left-0.5 h-5 w-5 rounded-full bg-[color:var(--fc-surface-card)]',
          'shadow-[0_1px_2px_rgba(15,30,55,0.20)]',
          'transition-transform duration-[var(--fc-motion-hover)]',
          checked && 'translate-x-4',
        )}
      />
    </span>
  )

  if (!label && !description) return control

  return (
    <label htmlFor={inputId} className="flex cursor-pointer items-start gap-3">
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
