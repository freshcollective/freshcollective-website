import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react'
import { cn } from './utils'

/**
 * Switch
 *
 * A toggle switch backed by a native checkbox for accessibility. Uses
 * `role="switch"` for correct screen-reader semantics.
 *
 * Geometry
 * --------
 * Track 40×24 (`w-10 h-6`), thumb 20×20 (`h-5 w-5`), inset 2px on all
 * four sides. Those four numbers are not independent — the travel has
 * to be whatever keeps the inset equal at both ends:
 *
 *     travel = track width − thumb width − 2 × inset
 *            = 40 − 20 − 4 = 16px = `translate-x-4`
 *
 * Which is why the thumb is anchored at `left-0.5` (2px) rather than at
 * 0: anchoring at 0 and translating by 16 leaves 2px on the left and
 * 4px on the right, and a thumb sitting off-centre in its track is
 * exactly how three hand-rolled copies of this switch read on review.
 * Change any one of the four and `translate-x-4` has to change with it.
 *
 * `top-0.5` is stated rather than inferred. It used to be left to the
 * parent's `items-center`, which does centre an absolutely-positioned
 * flex child — but only because the spec says a flex container's
 * alignment properties set the static position of such a child. That is
 * a real rule and a fragile thing to rest on: it quietly stops applying
 * the moment anybody changes the wrapper's display or alignment.
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
          'pointer-events-none absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-[color:var(--fc-surface-card)]',
          'shadow-[0_1px_2px_rgba(15,30,55,0.20)]',
          'transition-transform duration-[var(--fc-motion-hover)]',
          checked && 'translate-x-4',
        )}
      />
    </span>
  )

  // Even when there's no visible label/description, wrap the control
  // in a <label htmlFor>. The native checkbox is `sr-only`, so without
  // an enclosing label the visual track/thumb has no mouse click
  // target — only keyboard toggle would work. The label restores
  // pointer parity with keyboard.
  if (!label && !description) {
    return (
      <label htmlFor={inputId} className="inline-flex cursor-pointer items-center">
        {control}
      </label>
    )
  }

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
