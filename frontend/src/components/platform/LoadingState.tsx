import { Text } from './Text'
import { cn } from './utils'

/**
 * LoadingState
 *
 * A calm spinner + optional label. Two modes:
 *   - inline    small, sits within existing content
 *   - panel     centred inside its own card-height container
 *
 * Motion respects `prefers-reduced-motion`.
 *
 * @see docs/fresh-design-language.md §17, §20
 */

interface Props {
  mode?: 'inline' | 'panel'
  label?: string
  className?: string
}

export function LoadingState({
  mode = 'inline', label = 'Loading…', className,
}: Props) {
  if (mode === 'panel') {
    return (
      <div
        role="status"
        aria-live="polite"
        className={cn(
          'flex flex-col items-center justify-center gap-3 rounded-[var(--fc-radius-2xl)]',
          'bg-[color:var(--fc-surface-card)] shadow-[var(--fc-elev-1)]',
          'px-6 py-16',
          className,
        )}
      >
        <Spinner size={22} />
        <Text variant="meta" muted>{label}</Text>
      </div>
    )
  }
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn('inline-flex items-center gap-2', className)}
    >
      <Spinner size={14} />
      <Text as="span" variant="meta" muted>{label}</Text>
    </div>
  )
}

function Spinner({ size }: { size: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size} height={size} viewBox="0 0 24 24" fill="none"
      className="text-[color:var(--fc-accent-500)]"
      style={{ animation: 'fc-spin 900ms linear infinite' }}
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.4" opacity="0.22" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  )
}
