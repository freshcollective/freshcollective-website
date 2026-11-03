'use client'

/**
 * The Creator Studio rich-text toolbar: its chrome and its buttons.
 *
 * Three TipTap editors exist — ``RichTextEditor`` (Pathway step
 * content), ``SimpleRichTextEditor`` (guidance panels) and
 * ``AboutRichTextEditor`` (Collective About, and now Gathering and
 * Series descriptions). The first two already agreed on a flat
 * 28×28 button in a ``bg-slate-50`` bar; the third used bordered text
 * pills, which is why the Gathering description editor read as
 * belonging to a different product.
 *
 * The classes here are copied from ``RichTextEditor`` — the editor with
 * the most surface area and the one a creator meets most often — and
 * ``AboutRichTextEditor`` now renders through them.
 * ``editorToolbar.test.ts`` asserts the two files still agree, so this
 * cannot quietly drift back apart.
 *
 * The older two are deliberately left alone: they are already correct,
 * and ``RichTextEditor`` carries tables, colours and fonts whose
 * editing this change has no business touching. Pointing them at this
 * module is a tidy-up for its own commit.
 */

export const TOOLBAR_CLASS =
  'flex flex-wrap items-center gap-0.5 rounded-t-lg '
  + 'border-b border-slate-100 bg-slate-50 px-2 py-1.5'

export const TOOL_BUTTON_BASE =
  'flex h-7 w-7 items-center justify-center rounded text-[13px] transition-colors'

export const TOOL_BUTTON_ACTIVE = 'bg-teal-600 text-white'

export const TOOL_BUTTON_IDLE =
  'text-black hover:bg-slate-100 hover:text-slate-800'

/** A button wide enough for a short word rather than one glyph. */
export const TOOL_BUTTON_WIDE = 'h-7 w-auto px-1.5'

export function ToolButton({
  onClick,
  active,
  title,
  wide,
  children,
}: {
  onClick: () => void
  active?: boolean
  title: string
  /** For a label like "H2" that needs more than 28px. */
  wide?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      // mousedown + preventDefault keeps the editor selection alive, so a
      // command applies where the caret was rather than at position 0.
      onMouseDown={(e) => {
        e.preventDefault()
        onClick()
      }}
      // Keyboard activation. Enter and Space fire `click` with
      // `detail === 0` and never `mousedown`, so a mousedown-only
      // toolbar button cannot be used without a mouse. Guarded on
      // `detail` so a pointer click is not handled twice.
      onClick={(e) => {
        if (e.detail !== 0) return
        onClick()
      }}
      title={title}
      aria-label={title}
      aria-pressed={active ?? false}
      className={[
        TOOL_BUTTON_BASE,
        wide ? TOOL_BUTTON_WIDE : '',
        active ? TOOL_BUTTON_ACTIVE : TOOL_BUTTON_IDLE,
      ].filter(Boolean).join(' ')}
    >
      {children}
    </button>
  )
}

/** The thin rule that groups the toolbar into text / structure / insert. */
export function ToolDivider() {
  return <span className="mx-1 h-4 w-px bg-slate-200" aria-hidden="true" />
}
