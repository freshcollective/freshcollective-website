'use client'

import { useCallback, useEffect, type ReactNode } from 'react'
import { Heading } from './Heading'
import { Text } from './Text'
import { IconButton } from './Button'
import { cn } from './utils'

/**
 * Drawer
 *
 * Right-anchored slide-in surface. The primary detail / management surface
 * in Fresh Collective. Prefer over a modal for review-and-adjust flows.
 *
 * Structure:
 *   [3px pathway accent stripe]
 *   [Header — eyebrow + title + close]
 *   [Body — scrolls independently, composed of DrawerSection blocks]
 *   [Footer — sticky action bar]
 *
 * @see docs/fresh-design-language.md §13
 */

interface DrawerProps {
  open: boolean
  onClose: () => void
  /** Eyebrow shown above the title (e.g. "Resource"). */
  eyebrow?: string
  title: string
  /** Optional 3px accent stripe at the very top (pathway/type colour). */
  accentColor?: string
  /** Max width in pixels. Defaults to 560. */
  maxWidth?: number
  children: ReactNode
  /** Sticky footer content (action buttons). */
  footer?: ReactNode
  /** Screen-reader label if title is empty. */
  ariaLabel?: string
}

export function Drawer({
  open, onClose, eyebrow, title, accentColor,
  maxWidth = 560, children, footer, ariaLabel,
}: DrawerProps) {
  // Close on Escape
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Lock body scroll while open
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [open])

  const handleBackdrop = useCallback(() => onClose(), [onClose])

  if (!open) return null

  return (
    <>
      <div
        onClick={handleBackdrop}
        aria-hidden="true"
        className="fixed inset-0 z-[var(--fc-z-drawer-backdrop)] bg-[rgba(15,30,55,0.25)]"
        style={{ animation: 'fc-fade-in 180ms ease-out' }}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel ?? title}
        className={cn(
          'fixed right-0 top-0 z-[var(--fc-z-drawer)] flex h-full w-full flex-col',
          'bg-[color:var(--fc-surface-card)] shadow-[var(--fc-elev-5)]',
        )}
        style={{
          maxWidth: `${maxWidth}px`,
          animation: 'fc-drawer-in 240ms cubic-bezier(0.22,0.61,0.36,1)',
        }}
      >
        {accentColor && (
          <div
            className="h-[3px] w-full"
            aria-hidden="true"
            style={{ background: accentColor }}
          />
        )}

        <header className="flex items-start justify-between gap-3 px-8 pt-6 pb-5">
          <div className="min-w-0 flex-1">
            {eyebrow && (
              <Text variant="eyebrow" muted className="mb-1">{eyebrow}</Text>
            )}
            <Heading variant="page-title" as="h2" className="truncate">
              {title}
            </Heading>
          </div>
          <IconButton
            ariaLabel="Close"
            variant="tertiary"
            size="md"
            onClick={onClose}
            className="-mr-2 -mt-1"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </IconButton>
        </header>

        <div className="flex-1 overflow-y-auto px-8 pb-8">{children}</div>

        {footer && (
          <div className="flex flex-wrap items-center gap-2 border-t border-[color:var(--fc-border-hairline)] bg-[color:var(--fc-surface-card)] px-8 py-4">
            {footer}
          </div>
        )}
      </aside>
    </>
  )
}

/**
 * DrawerSection — a labelled section inside the drawer body. First section
 * has no top border; subsequent sections carry a hairline above.
 */
interface DrawerSectionProps {
  title: string
  first?: boolean
  children: ReactNode
}

export function DrawerSection({ title, first = false, children }: DrawerSectionProps) {
  return (
    <section
      className={
        first
          ? ''
          : 'mt-9 border-t border-[color:var(--fc-border-hairline)] pt-8'
      }
    >
      <Text variant="eyebrow" className="mb-4 text-[color:var(--fc-ink-disabled)]">
        {title}
      </Text>
      {children}
    </section>
  )
}
