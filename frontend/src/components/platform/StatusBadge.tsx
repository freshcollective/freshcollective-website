import { cn } from './utils'

/**
 * StatusBadge
 *
 * Semantic status pill. Each status is mapped to a fixed colour + label.
 * Consumers select the status, not the colour, so meaning stays consistent.
 *
 * @see docs/fresh-design-language.md §15
 */

export type StatusKind =
  | 'published'
  | 'draft'
  | 'archived'
  | 'success'
  | 'pending'
  | 'warning'
  | 'error'

interface Props {
  status: StatusKind
  /** Override the default label ("Published" etc). */
  label?: string
  /** Hide the leading coloured dot. */
  hideDot?: boolean
  className?: string
}

const CONFIG: Record<
  StatusKind,
  { bg: string; fg: string; dot: string; label: string }
> = {
  published: {
    bg: 'var(--fc-status-success-bg)',
    fg: 'var(--fc-accent-700)',
    dot: 'var(--fc-status-success)',
    label: 'Published',
  },
  draft: {
    bg: 'var(--fc-status-pending-bg)',
    fg: 'var(--fc-status-neutral)',
    dot: 'var(--fc-status-pending)',
    label: 'Draft',
  },
  archived: {
    bg: 'var(--fc-status-neutral-bg)',
    fg: 'var(--fc-status-neutral)',
    dot: 'var(--fc-status-neutral)',
    label: 'Archived',
  },
  success: {
    bg: 'var(--fc-status-success-bg)',
    fg: 'var(--fc-accent-700)',
    dot: 'var(--fc-status-success)',
    label: 'Success',
  },
  pending: {
    bg: 'var(--fc-status-pending-bg)',
    fg: 'var(--fc-status-neutral)',
    dot: 'var(--fc-status-pending)',
    label: 'Pending',
  },
  warning: {
    bg: 'var(--fc-status-warning-bg)',
    fg: 'var(--fc-status-warning)',
    dot: 'var(--fc-status-warning)',
    label: 'Warning',
  },
  error: {
    bg: 'var(--fc-status-error-bg)',
    fg: 'var(--fc-status-error)',
    dot: 'var(--fc-status-error)',
    label: 'Error',
  },
}

export function StatusBadge({
  status, label, hideDot = false, className,
}: Props) {
  const c = CONFIG[status]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-[var(--fc-radius-md)] px-2 py-0.5',
        'text-[10px] font-[var(--fc-fw-semibold)] uppercase leading-none tracking-[var(--fc-tracking-eyebrow-tight)]',
        className,
      )}
      style={{ background: c.bg, color: c.fg }}
    >
      {!hideDot && (
        <span
          aria-hidden="true"
          className="inline-block h-1.5 w-1.5 rounded-full"
          style={{ background: c.dot }}
        />
      )}
      {label ?? c.label}
    </span>
  )
}

/**
 * StatusDot — the smaller sibling of StatusBadge used inline with body text
 * (e.g. "● Life in Alignment"). Consumers pass a pathway colour or status.
 */
interface StatusDotProps {
  color: string
  label?: string
  className?: string
}

export function StatusDot({ color, label, className }: StatusDotProps) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <span
        aria-hidden="true"
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: color }}
      />
      {label && <span>{label}</span>}
    </span>
  )
}
