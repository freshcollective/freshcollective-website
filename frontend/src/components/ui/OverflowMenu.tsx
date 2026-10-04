'use client'

import { useEffect, useRef, useState } from 'react'

export interface OverflowMenuItem {
  label: string
  onClick: () => void
  /** Visual accent — 'danger' turns the row red. */
  tone?: 'default' | 'danger'
  /** Optional divider line above this item. */
  dividerAbove?: boolean
  disabled?: boolean
}

interface Props {
  items: OverflowMenuItem[]
  /** Screen-reader label for the trigger button. */
  ariaLabel?: string
  /** Menu horizontal alignment relative to the trigger. */
  align?: 'left' | 'right'
  /**
   * How much the trigger announces itself at rest.
   *
   * ``bare`` is the original: grey dots on nothing until hovered. It
   * works where the surrounding card already frames it as a control —
   * a row in a list of Pathways, say.
   *
   * ``outlined`` gives it a border and a surface, for somewhere the
   * dots stand alone next to body content. Without one they read as
   * decorative punctuation, which is how the safety menu on a
   * conversation went unfound during review.
   */
  appearance?: 'bare' | 'outlined'
  /**
   * Visible text beside the dots, shown from ``sm`` up. Off on small
   * screens, where a header has no room for it and the outline is
   * doing the work.
   */
  triggerLabel?: string
  /** Render the menu already open. The admin preview harness only — it
   *  needs the panel visible without a click to screenshot. */
  defaultOpen?: boolean
}

/**
 * A small ⋯ overflow menu. Closes on outside click or Escape.
 * Kept lightweight so it can drop into any card without pulling in a full
 * headless-ui / radix dependency.
 */
export default function OverflowMenu({
  items,
  ariaLabel = 'Actions',
  align = 'right',
  appearance = 'bare',
  triggerLabel,
  defaultOpen = false,
}: Props) {
  const [open, setOpen] = useState(defaultOpen)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        className={
          appearance === 'outlined'
            // 36px tall, so it is a comfortable target on a phone
            // without becoming a primary action. Focus is visible for
            // keyboard users and the border makes it legible as a
            // control before anyone hovers it.
            ? 'inline-flex h-9 min-w-9 items-center justify-center gap-1.5 rounded-full'
              + ' border bg-white px-2.5 transition-colors'
              + ' hover:border-teal-300 hover:text-teal-700'
              + ' focus-visible:outline-none focus-visible:ring-2'
              + ' focus-visible:ring-teal-400/40 focus-visible:ring-offset-2'
            : 'inline-flex h-8 w-8 items-center justify-center rounded-full'
              + ' text-slate-400 transition-colors hover:bg-slate-100 hover:text-navy-900'
        }
        style={
          appearance === 'outlined'
            ? { borderColor: 'rgba(12,24,38,0.16)', color: 'rgba(12,24,38,0.62)' }
            : undefined
        }
      >
        {triggerLabel && (
          <span className="hidden text-[13px] font-medium sm:inline">
            {triggerLabel}
          </span>
        )}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <circle cx="5" cy="12" r="1.75" />
          <circle cx="12" cy="12" r="1.75" />
          <circle cx="19" cy="12" r="1.75" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          className={`absolute z-30 mt-1 min-w-[160px] rounded-xl bg-white py-1 shadow-lg ${
            align === 'right' ? 'right-0' : 'left-0'
          }`}
          style={{
            border: '1px solid rgba(0,0,0,0.08)',
            boxShadow: '0 6px 24px rgba(15,30,55,0.10)',
            animation: 'fcMenuFade 140ms ease-out',
          }}
        >
          {items.map((item, i) => (
            <div key={i}>
              {item.dividerAbove && <div className="my-1 h-px bg-slate-100" />}
              <button
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  if (item.disabled) return
                  setOpen(false)
                  item.onClick()
                }}
                className="block w-full px-3.5 py-2 text-left text-[13px] font-medium transition-colors disabled:opacity-40"
                style={{
                  color: item.tone === 'danger' ? '#B91C1C' : '#000000',
                }}
                onMouseEnter={(e) => {
                  if (item.disabled) return
                  e.currentTarget.style.background =
                    item.tone === 'danger' ? 'rgba(185,28,28,0.06)' : 'rgba(56,160,158,0.06)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent'
                }}
              >
                {item.label}
              </button>
            </div>
          ))}
        </div>
      )}

      <style jsx>{`
        @keyframes fcMenuFade {
          from { opacity: 0; transform: translateY(-2px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}
