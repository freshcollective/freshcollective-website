'use client'

/**
 * Lightweight curated emoji picker. No external library — just a static
 * dictionary of Unicode characters grouped into five categories.
 *
 * Used by both:
 *   - Plain text inputs (community textarea, contentEditable post editor)
 *   - TipTap rich-text editors (Content / Callout / About / Settings)
 *
 * The two `variant` and `align` props let it sit naturally in either
 * surface without forcing each caller to reinvent the trigger style.
 */

import { useState, useRef, useEffect } from 'react'

const EMOJI_GROUPS: { label: string; emojis: string[] }[] = [
  {
    label: 'Faces',
    emojis: ['😀', '😄', '😂', '🤣', '😊', '😍', '🥰', '😢', '😭', '😔', '😬', '😅', '🥹'],
  },
  {
    label: 'Nature & Flowers',
    emojis: ['🌸', '🌻', '🌷', '🌹', '🌼', '🌿', '🌱', '🍃'],
  },
  {
    label: 'Leadership',
    emojis: ['✨', '💫', '🌙', '☀️', '🌀', '🪞', '🧭', '👑'],
  },
  {
    label: 'Actions',
    emojis: ['✅', '📌', '📝', '🎧', '🎥', '📣', '🙌', '🙏', '🫶'],
  },
  {
    label: 'Celebration',
    emojis: ['🎉', '💛', '❤️', '🧡', '💜', '🍷', '☕', '🥂'],
  },
]

interface Props {
  onSelect: (emoji: string) => void
  /**
   * `labeled`  — "😊 Emoji" pill button (default; matches the community
   *              editors where the trigger sits on its own).
   * `compact`  — icon-only 28×28 button matching TipTap toolbar buttons.
   */
  variant?: 'labeled' | 'compact'
  /**
   * `top`    — popover opens above the trigger (default; for community
   *            editors whose toolbar is at the top of a box and where
   *            opening downward would clip below the viewport).
   * `bottom` — popover opens below the trigger (TipTap toolbars).
   */
  align?: 'top' | 'bottom'
}

export default function EmojiPicker({ onSelect, variant = 'labeled', align = 'top' }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const triggerClass =
    variant === 'compact'
      ? 'flex h-7 w-7 items-center justify-center rounded text-[15px] transition-colors hover:bg-slate-100'
      : 'flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-black transition-colors hover:border-[color:var(--fc-accent-ring,rgba(56,160,158,0.40))] hover:text-[color:var(--fc-accent,#0d9488)]'

  const panelPosClass = align === 'bottom' ? 'top-full mt-1' : 'bottom-full mb-1'

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        // mousedown+preventDefault keeps the TipTap editor selection alive so
        // the inserted emoji lands at the previous cursor position, not at 0.
        // Safe for the textarea + contentEditable consumers too.
        onMouseDown={(e) => {
          e.preventDefault()
          setOpen((o) => !o)
        }}
        title="Add emoji"
        aria-label="Add emoji"
        aria-expanded={open}
      >
        <span className={triggerClass}>
          {variant === 'compact' ? '😊' : <>
            <span>😊</span>
            <span>Emoji</span>
          </>}
        </span>
      </button>

      {open && (
        <div
          className={`absolute left-0 z-20 w-72 max-h-80 overflow-y-auto rounded-xl border border-slate-200 bg-white p-3 shadow-lg ${panelPosClass}`}
          onMouseDown={(e) => e.preventDefault()}
          role="dialog"
          aria-label="Emoji picker"
        >
          {EMOJI_GROUPS.map((group) => (
            <div key={group.label} className="mb-3 last:mb-0">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-black">
                {group.label}
              </p>
              <div className="grid grid-cols-7 gap-0.5">
                {group.emojis.map((e) => (
                  <button
                    key={e}
                    type="button"
                    onMouseDown={(ev) => {
                      ev.preventDefault()
                      onSelect(e)
                      setOpen(false)
                    }}
                    className="flex h-8 w-8 items-center justify-center rounded text-[18px] hover:bg-[color:var(--fc-accent-tint,rgba(56,160,158,0.06))] transition-colors"
                    title={e}
                  >
                    {e}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
