import { cloneElement, isValidElement, useId, type ReactElement } from 'react'
import { Text } from './Text'
import { cn } from './utils'

/**
 * FormField
 *
 * Wraps any single input control (Input, TextArea, Select, Checkbox, Switch)
 * with the canonical label + helper + error anatomy per §10.
 *
 * Behaviour:
 *   - Passes a generated id to the child input via cloning.
 *   - When `error` is present, the input's `aria-invalid` is set and the
 *     error message is associated via `aria-describedby`.
 *   - Otherwise `helper` is associated via `aria-describedby`.
 *
 * @see docs/fresh-design-language.md §10
 */

interface Props {
  label: string
  /** Marks the field as required. Renders the teal asterisk per §10.3. */
  required?: boolean
  helper?: string
  error?: string
  /** Hide the label visually while keeping it available to screen readers. */
  hideLabel?: boolean
  className?: string
  /** Exactly one input control (Input / TextArea / Select / etc). */
  children: ReactElement<{
    id?: string
    'aria-invalid'?: boolean
    'aria-describedby'?: string
  }>
}

export function FormField({
  label, required = false, helper, error, hideLabel = false,
  className, children,
}: Props) {
  const generated = useId()
  const inputId = generated + '-input'
  const helperId = helper ? generated + '-helper' : undefined
  const errorId = error ? generated + '-error' : undefined
  const describedBy = errorId || helperId

  const clonedChild = isValidElement(children)
    ? cloneElement(children, {
        id: inputId,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': describedBy,
      })
    : children

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <label
        htmlFor={inputId}
        className={cn(
          hideLabel && 'sr-only',
          'text-[12px] font-[var(--fc-fw-semibold)] uppercase tracking-[var(--fc-tracking-eyebrow-tight)] text-[color:var(--fc-ink-primary)]',
        )}
      >
        {label}
        {required && (
          <span
            aria-hidden="true"
            className="ml-1 text-[color:var(--fc-accent-500)]"
          >
            *
          </span>
        )}
      </label>

      {clonedChild}

      {error ? (
        <p
          id={errorId}
          role="alert"
          className="rounded-[var(--fc-radius-md)] px-2 py-1 text-[12px] font-[var(--fc-fw-regular)] leading-[var(--fc-lh-meta)] text-[color:var(--fc-status-error-text)]"
          style={{ background: 'var(--fc-status-error-bg)' }}
        >
          {error}
        </p>
      ) : helper ? (
        <Text as="p" variant="meta" id={helperId}>{helper}</Text>
      ) : null}
    </div>
  )
}
