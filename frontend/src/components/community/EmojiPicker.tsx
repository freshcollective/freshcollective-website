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

import { useState, useRef, useEffect, useLayoutEffect } from 'react'
import {
  placePopover,
  placementClasses,
  type Placement,
} from '@/lib/popoverPlacement'

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

//: The panel's own size, from the Tailwind classes below. Stated as
//: numbers because placement has to be decided *before* the panel is
//: measurable, from the trigger's position alone — measuring the panel
//: and then moving it would feed its new position back into the next
//: measurement. A test asserts these match the classes.
const PANEL_WIDTH = 288   // w-72
const PANEL_HEIGHT = 320  // max-h-80
export default function EmojiPicker({ onSelect, variant = 'labeled', align = 'top' }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [placement, setPlacement] = useState<Placement>({ x: 'left', y: align })

  /**
   * Which way the panel opens, measured from the trigger.
   *
   * It opened down-and-right unconditionally, which is fine in a wide
   * toolbar and wrong in a narrow one: in the Gathering editor the
   * emoji button sits close to the right edge of a ``max-w-xl`` column,
   * so the panel ran past it. Decided from the trigger's rect rather
   * than the panel's, so there is no feedback loop, and recomputed on
   * every open so a resize or a scroll since last time cannot leave a
   * stale choice.
   */
  useLayoutEffect(() => {
    if (!open) return
    const trigger = triggerRef.current?.getBoundingClientRect()
    if (!trigger) return
    setPlacement(placePopover({
      trigger,
      panel: { width: PANEL_WIDTH, height: PANEL_HEIGHT },
      viewport: { width: window.innerWidth, height: window.innerHeight },
      prefer: align,
    }))
  }, [open, align])

  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return
      setOpen(false)
      // Focus goes back where it came from, so Escape does not drop a
      // keyboard user at the top of the document.
      triggerRef.current?.focus()
    }
    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  // Opened by keyboard: move into the panel so the emoji are reachable
  // without a mouse.
  useEffect(() => {
    if (!open) return
    const byKeyboard = triggerRef.current?.dataset.keyboard === 'true'
    if (!byKeyboard) return
    delete triggerRef.current?.dataset.keyboard
    panelRef.current?.querySelector<HTMLButtonElement>('button')?.focus()
  }, [open, placement])

  const triggerClass =
    variant === 'compact'
      ? 'flex h-7 w-7 items-center justify-center rounded text-[15px] transition-colors hover:bg-slate-100'
      : 'flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-black transition-colors hover:border-[color:var(--fc-accent-ring,rgba(56,160,158,0.40))] hover:text-[color:var(--fc-accent,#0d9488)]'

  const panelPosClass = placementClasses(placement)

  return (
    <div ref={ref} className="relative">
      <button
        ref={triggerRef}
        type="button"
        // mousedown+preventDefault keeps the TipTap editor selection alive so
        // the inserted emoji lands at the previous cursor position, not at 0.
        // Safe for the textarea + contentEditable consumers too.
        onMouseDown={(e) => {
          e.preventDefault()
          setOpen((o) => !o)
        }}
        // Keyboard activation. A browser fires `click` with `detail === 0`
        // for Enter and Space and never fires `mousedown`, so with
        // `onMouseDown` alone this control could not be opened without a
        // mouse at all. Guarded on `detail` so a real pointer click,
        // already handled above, is not toggled twice.
        onClick={(e) => {
          if (e.detail !== 0) return
          e.currentTarget.dataset.keyboard = 'true'
          setOpen((o) => !o)
        }}
        title="Add emoji"
        aria-label="Add emoji"
        aria-haspopup="dialog"
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
          ref={panelRef}
          // ``max-w`` so the panel never exceeds a phone's screen, whichever
          // way it is aligned; ``max-h-80`` with ``overflow-y-auto`` keeps
          // every category scrollable rather than cut off.
          className={`absolute z-30 w-72 max-w-[calc(100vw-1rem)] max-h-80 overflow-y-auto rounded-xl border border-slate-200 bg-white p-3 shadow-lg ${panelPosClass}`}
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
                    // Same reason as the trigger: Enter and Space fire
                    // `click` with `detail === 0` and never `mousedown`,
                    // so without this an emoji could be focused but not
                    // chosen.
                    onClick={(ev) => {
                      if (ev.detail !== 0) return
                      onSelect(e)
                      setOpen(false)
                      triggerRef.current?.focus()
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
