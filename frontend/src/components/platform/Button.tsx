import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cn } from './utils'

/**
 * Button
 *
 * Three-level hierarchy per §8. One primary per view. Destructive actions
 * are secondary buttons with a red label — not a fourth style.
 *
 * @see docs/fresh-design-language.md §8
 */

export type ButtonVariant = 'primary' | 'secondary' | 'tertiary' | 'danger'
export type ButtonSize = 'sm' | 'md' | 'lg'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Renders a spinner in place of the label. Also disables the button. */
  loading?: boolean
  /** Left-slot content (icon). */
  iconStart?: ReactNode
  /** Right-slot content (icon). */
  iconEnd?: ReactNode
  /** Stretch to full width of parent. */
  fullWidth?: boolean
  children?: ReactNode
}

const BASE =
  'inline-flex items-center justify-center gap-2 whitespace-nowrap font-[var(--fc-fw-semibold)] transition-opacity duration-[var(--fc-motion-hover)] ease-out focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-[color:var(--fc-accent-500)]/40 focus-visible:ring-offset-[color:var(--fc-surface-page)] disabled:cursor-not-allowed disabled:opacity-50'

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    'text-[color:var(--fc-ink-inverse)] [background:var(--fc-accent-gradient)] hover:opacity-90',
  secondary:
    'text-[color:var(--fc-ink-primary)] bg-transparent border border-[color:var(--fc-border-input)] hover:border-[color:var(--fc-border-input-hover)]',
  tertiary:
    'text-[color:var(--fc-accent-700)] bg-transparent hover:underline underline-offset-2',
  danger:
    'text-[color:var(--fc-status-error)] bg-transparent border border-[color:var(--fc-border-input)] hover:bg-[color:var(--fc-status-error-bg)]',
}

const SIZE: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-[12px] rounded-[var(--fc-radius-md)]',
  md: 'h-10 px-4 text-[13px] rounded-[var(--fc-radius-md)]',
  lg: 'h-12 px-5 text-[14px] rounded-[var(--fc-radius-lg)]',
}

function Spinner({ size }: { size: ButtonSize }) {
  const s = size === 'sm' ? 12 : size === 'md' ? 14 : 16
  return (
    <svg
      width={s} height={s} viewBox="0 0 24 24" fill="none"
      aria-hidden="true"
      style={{ animation: 'fc-spin 900ms linear infinite' }}
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.4" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  )
}

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  {
    variant = 'secondary', size = 'md', loading = false,
    iconStart, iconEnd, fullWidth = false,
    disabled, className, children, type = 'button', ...rest
  },
  ref,
) {
  const isDisabled = disabled || loading
  return (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={cn(
        BASE,
        VARIANT[variant],
        SIZE[size],
        fullWidth && 'w-full',
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner size={size} /> : iconStart}
      {children && <span>{children}</span>}
      {!loading && iconEnd}
    </button>
  )
})

/**
 * IconButton — a square variant of Button for icon-only controls. Always
 * requires an aria-label per §21.4.
 */
interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  ariaLabel: string
  size?: ButtonSize
  variant?: ButtonVariant
  children: ReactNode
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  function IconButton(
    {
      ariaLabel, size = 'md', variant = 'tertiary',
      className, children, type = 'button', ...rest
    },
    ref,
  ) {
    const dim = size === 'sm' ? 'h-8 w-8' : size === 'md' ? 'h-9 w-9' : 'h-11 w-11'
    // Colour + hover come from the variant, but padding is removed since the
    // control is square.
    const variantMinusPadding =
      VARIANT[variant].replace(/\bpx-\d+\b/g, '').replace(/\bhover:underline\b/g, '')
    return (
      <button
        ref={ref}
        type={type}
        aria-label={ariaLabel}
        className={cn(
          BASE,
          variantMinusPadding,
          dim,
          'rounded-[var(--fc-radius-md)]',
          className,
        )}
        {...rest}
      >
        {children}
      </button>
    )
  },
)
