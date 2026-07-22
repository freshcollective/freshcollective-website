'use client'

import { useId, type ReactNode } from 'react'
import { cn } from './utils'

/**
 * Tabs
 *
 * Secondary navigation using text-only labels with a 2px underline on the
 * active tab per §12.2. For filter chip patterns (segmented controls) use
 * a different primitive — Tabs is nav, not filter.
 *
 * @see docs/fresh-design-language.md §12.2
 */

interface Tab<T extends string> {
  key: T
  label: string
  count?: number
  disabled?: boolean
}

interface Props<T extends string> {
  tabs: readonly Tab<T>[]
  value: T
  onChange: (key: T) => void
  ariaLabel?: string
  className?: string
  /** Right-slot content (actions or search). */
  actions?: ReactNode
}

export function Tabs<T extends string>({
  tabs, value, onChange, ariaLabel, actions, className,
}: Props<T>) {
  const groupId = useId()
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        'flex flex-wrap items-end justify-between gap-3',
        'border-b border-[color:var(--fc-border-hairline)]',
        className,
      )}
    >
      <div className="flex flex-wrap items-end gap-4">
        {tabs.map((tab) => {
          const active = tab.key === value
          const tabId = `${groupId}-${tab.key}`
          return (
            <button
              key={tab.key}
              id={tabId}
              role="tab"
              aria-selected={active}
              aria-disabled={tab.disabled || undefined}
              tabIndex={active ? 0 : -1}
              disabled={tab.disabled}
              onClick={() => !tab.disabled && onChange(tab.key)}
              className={cn(
                'relative -mb-px inline-flex items-center gap-2 pb-3 pt-1',
                'text-[length:var(--fc-fs-body)] font-[var(--fc-fw-semibold)] leading-none',
                'transition-colors duration-[var(--fc-motion-hover)]',
                'focus:outline-none focus-visible:text-[color:var(--fc-accent-700)]',
                active
                  ? 'text-[color:var(--fc-ink-heading)]'
                  : 'text-[color:var(--fc-ink-primary)] opacity-60 hover:opacity-100',
                tab.disabled && 'cursor-not-allowed opacity-30',
              )}
            >
              <span>{tab.label}</span>
              {tab.count !== undefined && (
                <span
                  aria-hidden="true"
                  className="text-[11px] font-[var(--fc-fw-regular)] text-[color:var(--fc-ink-disabled)]"
                >
                  {tab.count}
                </span>
              )}
              {active && (
                <span
                  aria-hidden="true"
                  className="absolute inset-x-0 -bottom-px h-0.5 bg-[color:var(--fc-accent-500)]"
                />
              )}
            </button>
          )
        })}
      </div>
      {actions && (
        <div className="flex items-center gap-2 pb-2">{actions}</div>
      )}
    </div>
  )
}
