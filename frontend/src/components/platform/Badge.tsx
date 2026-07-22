import type { ReactNode } from 'react'
import { cn } from './utils'

/**
 * Badge
 *
 * A generic small pill. Prefer `StatusBadge` for status meaning; use `Badge`
 * for neutral labels (resource type, tag).
 *
 * @see docs/fresh-design-language.md §15
 */

export type BadgeTone =
  | 'neutral'
  | 'accent'   // teal
  | 'audio'    // purple
  | 'video'    // coral
  | 'guide'    // blue
  | 'file'     // navy
  | 'link'     // teal
  | 'other'

interface Props {
  tone?: BadgeTone
  /** Optional leading dot in the same colour as the label. */
  dot?: boolean
  className?: string
  children: ReactNode
}

const TONE: Record<BadgeTone, { bg: string; fg: string }> = {
  neutral: { bg: 'rgba(15,30,55,0.05)',       fg: 'var(--fc-ink-primary)' },
  accent:  { bg: 'var(--fc-accent-50)',    fg: 'var(--fc-accent-700)' },
  audio:   { bg: 'var(--fc-type-audio-bg)',fg: 'var(--fc-type-audio)' },
  video:   { bg: 'var(--fc-type-video-bg)',fg: 'var(--fc-type-video)' },
  guide:   { bg: 'var(--fc-type-guide-bg)',fg: 'var(--fc-type-guide)' },
  file:    { bg: 'var(--fc-type-file-bg)', fg: 'var(--fc-type-file)' },
  link:    { bg: 'var(--fc-type-link-bg)', fg: 'var(--fc-type-link)' },
  other:   { bg: 'var(--fc-type-other-bg)',fg: 'var(--fc-type-other)' },
}

export function Badge({ tone = 'neutral', dot = false, className, children }: Props) {
  const { bg, fg } = TONE[tone]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-[var(--fc-radius-md)] px-2 py-0.5',
        'text-[10px] font-[var(--fc-fw-semibold)] uppercase leading-none tracking-[var(--fc-tracking-eyebrow-tight)]',
        className,
      )}
      style={{ background: bg, color: fg }}
    >
      {dot && (
        <span
          aria-hidden="true"
          className="inline-block h-1.5 w-1.5 rounded-full"
          style={{ background: fg }}
        />
      )}
      {children}
    </span>
  )
}
