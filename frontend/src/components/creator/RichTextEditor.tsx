'use client'

import { useState, useRef, useEffect } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import { TextStyle } from '@tiptap/extension-text-style'
import { Color } from '@tiptap/extension-color'
import Highlight from '@tiptap/extension-highlight'
import FontFamily from '@tiptap/extension-font-family'
import { TextAlign } from '@tiptap/extension-text-align'
import { Table } from '@tiptap/extension-table'
import { TableRow } from '@tiptap/extension-table-row'
import { TableCell } from '@tiptap/extension-table-cell'
import { TableHeader } from '@tiptap/extension-table-header'
import EmojiPicker from '@/components/community/EmojiPicker'
import { useCollectivePalette } from '@/components/collective/CollectivePaletteContext'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function parseRichContent(content: string | null): Record<string, unknown> {
  if (!content) return { type: 'doc', content: [] }
  try {
    const parsed = JSON.parse(content)
    if (parsed?.type === 'doc') return parsed
  } catch {}
  return {
    type: 'doc',
    content: content
      .split('\n\n')
      .filter(Boolean)
      .map((para) => ({
        type: 'paragraph',
        content: para ? [{ type: 'text', text: para }] : [],
      })),
  }
}

// Only allow #rgb or #rrggbb — reject everything else (rgb(), url(), expressions, etc.)
function isValidHex(value: string): boolean {
  return /^#[0-9A-Fa-f]{3}([0-9A-Fa-f]{3})?$/.test(value.trim())
}

// ---------------------------------------------------------------------------
// Palettes
// ---------------------------------------------------------------------------

/**
 * Text + heading colour palette. One swatch per Fresh Collective brand family;
 * each is saturated enough to read as a heading on white.
 *
 * The empty-string value clears the colour mark, so headings/text inherit the
 * Tailwind default (navy-900) — i.e. existing content that was never coloured
 * keeps rendering exactly as before.
 *
 * Hex values mirror the callout/container palette families (see
 * `frontend/src/lib/calloutPalette.ts`) but at a darker, text-safe tone.
 */
const TEXT_COLORS = [
  { label: 'Default',  value: '' },
  { label: 'Navy',     value: '#071824' },
  { label: 'Teal',     value: '#38A09E' },
  { label: 'Gold',     value: '#9A7A18' },
  { label: 'Blue',     value: '#3B7BC4' },
  { label: 'Rose',     value: '#B5677D' },
  { label: 'Sage',     value: '#5F8061' },
  { label: 'Lilac',    value: '#8F77B5' },
  { label: 'Orange',   value: '#C26A1F' },
  { label: 'Grey',     value: '#64748B' },
]

const HIGHLIGHT_COLORS = [
  { label: 'None',        value: '' },
  { label: 'Teal light',  value: '#EAF7F6' },
  { label: 'Teal soft',   value: '#DDF4F2' },
  { label: 'Gold light',  value: '#FBF6E8' },
  { label: 'Slate light', value: '#EEF2F5' },
  { label: 'Cream',       value: '#FFF9E8' },
]

const FONT_FAMILIES = [
  { label: 'Default',       value: '' },
  { label: 'Serif',         value: 'Georgia, serif' },
  { label: 'Classic Serif', value: 'Times New Roman, serif' },
  { label: 'Clean Sans',    value: 'Arial, sans-serif' },
  { label: 'Modern Sans',   value: 'Helvetica, Arial, sans-serif' },
  { label: 'Rounded',       value: 'Trebuchet MS, sans-serif' },
  { label: 'Mono',          value: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace' },
]

// ---------------------------------------------------------------------------
// Toolbar button
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// TableMenu — insert-table picker + in-table row/column controls.
// ---------------------------------------------------------------------------


// eslint-disable-next-line @typescript-eslint/no-explicit-any
function TableMenu({ editor }: { editor: any }) {
  const [open, setOpen] = useState(false)
  const inTable = editor.isActive('table')
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        title={inTable ? 'Table settings' : 'Insert table'}
        className={`flex h-7 w-7 items-center justify-center rounded text-[13px] transition-colors ${
          inTable ? 'bg-teal-600 text-white' : 'text-black hover:bg-slate-100'
        }`}
      >
        ⊞
      </button>
      {open && !inTable && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1 w-64 rounded-lg border border-slate-200 bg-white p-2 shadow-lg">
            <p className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Insert table
            </p>
            <div className="grid grid-cols-3 gap-1">
              {[[2, 2], [3, 3], [4, 4], [2, 3], [3, 4], [4, 5]].map(([rows, cols]) => (
                <button
                  key={`${rows}-${cols}`}
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault()
                    editor.chain().focus()
                      .insertTable({ rows, cols, withHeaderRow: true })
                      .run()
                    setOpen(false)
                  }}
                  className="rounded border border-slate-200 px-2 py-2 text-[12px] font-medium text-black transition-colors hover:border-teal-300 hover:bg-teal-50"
                >
                  {rows}×{cols}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}


/**
 * TableToolbar — a second toolbar row that appears only when the caret
 * is inside a table. Surfaces the most-used row + column ops as inline
 * buttons so the writer never has to hunt through a dropdown to add a
 * row or delete a column. Kept visually calmer than the main toolbar
 * (soft teal-tinted background, smaller buttons) to signal "contextual"
 * without disappearing at rest.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function TableToolbar({ editor }: { editor: any }) {
  if (!editor.isActive('table')) return null
  const run = (fn: () => void) => (e: React.MouseEvent) => {
    e.preventDefault()
    fn()
  }
  return (
    <div
      className="flex flex-wrap items-center gap-1 border-b border-slate-200 px-2 py-1.5 text-[12.5px]"
      style={{ background: 'rgba(56,160,158,0.06)' }}
      role="toolbar"
      aria-label="Table controls"
    >
      <span className="mr-1 flex items-center gap-1 text-[10.5px] font-semibold uppercase tracking-widest text-teal-800">
        <span aria-hidden="true">⊞</span>
        Table
      </span>

      <TableInlineBtn onMouseDown={run(() => editor.chain().focus().addRowBefore().run())} title="Add row above">
        <span aria-hidden="true">↑</span> Row
      </TableInlineBtn>
      <TableInlineBtn onMouseDown={run(() => editor.chain().focus().addRowAfter().run())} title="Add row below">
        <span aria-hidden="true">↓</span> Row
      </TableInlineBtn>
      <TableInlineBtn onMouseDown={run(() => editor.chain().focus().deleteRow().run())} title="Delete current row" destructive>
        <span aria-hidden="true">✕</span> Row
      </TableInlineBtn>

      <span className="mx-1 h-4 w-px bg-slate-200" />

      <TableInlineBtn onMouseDown={run(() => editor.chain().focus().addColumnBefore().run())} title="Add column left">
        <span aria-hidden="true">←</span> Col
      </TableInlineBtn>
      <TableInlineBtn onMouseDown={run(() => editor.chain().focus().addColumnAfter().run())} title="Add column right">
        <span aria-hidden="true">→</span> Col
      </TableInlineBtn>
      <TableInlineBtn onMouseDown={run(() => editor.chain().focus().deleteColumn().run())} title="Delete current column" destructive>
        <span aria-hidden="true">✕</span> Col
      </TableInlineBtn>

      <span className="mx-1 h-4 w-px bg-slate-200" />

      <TableInlineBtn onMouseDown={run(() => editor.chain().focus().toggleHeaderRow().run())} title="Toggle header row">
        Header
      </TableInlineBtn>

      <div className="ml-auto" />
      <TableInlineBtn onMouseDown={run(() => editor.chain().focus().deleteTable().run())} title="Delete table" destructive>
        Delete table
      </TableInlineBtn>
    </div>
  )
}


function TableInlineBtn({
  onMouseDown, title, destructive, children,
}: {
  onMouseDown: (e: React.MouseEvent) => void
  title: string
  destructive?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onMouseDown={onMouseDown}
      title={title}
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[12px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${
        destructive
          ? 'border-transparent text-red-600 hover:border-red-200 hover:bg-red-50'
          : 'border-transparent text-navy-900 hover:border-teal-200 hover:bg-white'
      }`}
    >
      {children}
    </button>
  )
}

function ToolBtn({
  onClick,
  active,
  title,
  children,
}: {
  onClick: () => void
  active?: boolean
  title: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onMouseDown={(e) => {
        e.preventDefault()
        onClick()
      }}
      title={title}
      className={`flex h-7 w-7 items-center justify-center rounded text-[13px] transition-colors ${
        active
          ? 'bg-teal-600 text-white'
          : 'text-black hover:bg-slate-100 hover:text-slate-800'
      }`}
    >
      {children}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Popover wrapper
// align='left'  → panel opens left-aligned (default, good for left-side controls)
// align='right' → panel opens right-aligned (prevents clipping for right-side controls)
// ---------------------------------------------------------------------------

function Popover({
  trigger,
  children,
  width = 'w-40',
  align = 'left',
}: {
  trigger: React.ReactNode
  children: React.ReactNode
  width?: string
  align?: 'left' | 'right'
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const posClass = align === 'right' ? 'right-0' : 'left-0'

  return (
    <div className="relative" ref={ref}>
      <div
        onMouseDown={(e) => {
          e.preventDefault()
          setOpen((v) => !v)
        }}
      >
        {trigger}
      </div>
      {open && (
        <div
          className={`absolute ${posClass} top-full z-50 mt-1 rounded-lg border border-slate-200 bg-white p-2 shadow-lg ${width}`}
          onMouseDown={(e) => e.preventDefault()}
        >
          {children}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Color dot grid
// ---------------------------------------------------------------------------

function ColorDots({
  colors,
  current,
  onSelect,
  bordered,
}: {
  colors: { label: string; value: string }[]
  current: string
  onSelect: (v: string) => void
  bordered?: boolean
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {colors.map((c) => (
        <button
          key={c.value || 'none'}
          type="button"
          title={c.label}
          onMouseDown={(e) => {
            e.preventDefault()
            onSelect(c.value)
          }}
          className={`h-5 w-5 rounded-full transition-transform hover:scale-110 ${
            current === c.value ? 'ring-2 ring-offset-1 ring-teal-500' : ''
          } ${bordered || c.value === '' ? 'border border-slate-300' : ''}`}
          style={{ backgroundColor: c.value || '#f1f5f9' }}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Color picker section: preset dots + custom <input type="color">
// The color input needs stopPropagation on mousedown because the popover
// content wrapper calls e.preventDefault() to keep editor focus, which would
// otherwise block the native browser color picker dialog from opening.
// ---------------------------------------------------------------------------

function ColorPickerSection({
  label,
  colors,
  current,
  onSelect,
  bordered,
}: {
  label: string
  colors: { label: string; value: string }[]
  current: string
  onSelect: (v: string) => void
  bordered?: boolean
}) {
  // Safe fallback for <input type="color"> which requires a 6-digit hex
  const pickerValue = isValidHex(current) ? (current.length === 4 ? current + current.slice(1) : current) : '#000000'

  // The collective's active palette gives the writer a one-click way
  // to pick a colour from their brand. Palette picks store the current
  // hex *snapshot* — inline text/highlight colours don't flow through
  // when the palette later changes (this is a deliberate v1 decision;
  // role-tokened TipTap marks are in the backlog).
  const collectivePalette = useCollectivePalette()

  return (
    <>
      {collectivePalette && (
        <>
          <p className="mb-1.5 flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-black">
            <span>Your palette</span>
            {collectivePalette.name && (
              <span className="text-[9.5px] font-normal normal-case italic text-slate-500">
                {collectivePalette.name}
              </span>
            )}
          </p>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {(['primary', 'secondary', 'accent', 'background'] as const).map((role) => {
              const hex = collectivePalette.palette[role]
              const selected = current.toLowerCase() === hex.toLowerCase()
              return (
                <button
                  key={role}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => onSelect(hex)}
                  className={`h-5 w-5 rounded-full border transition-transform hover:scale-110 ${
                    selected ? 'border-navy-900 shadow-inner' : 'border-white shadow-sm'
                  }`}
                  style={{ background: hex }}
                  title={`${role[0].toUpperCase()}${role.slice(1)} · ${hex}`}
                  aria-label={`${role} colour ${hex}`}
                  aria-pressed={selected}
                />
              )
            })}
          </div>
          <div className="mb-2 border-t border-slate-100" />
        </>
      )}

      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-black">{label}</p>
      <ColorDots colors={colors} current={current} onSelect={onSelect} bordered={bordered} />
      <div className="mt-2 border-t border-slate-100 pt-2">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-black">Custom</span>
          <input
            type="color"
            value={pickerValue}
            onMouseDown={(e) => e.stopPropagation()}
            onChange={(e) => {
              const val = e.target.value
              if (isValidHex(val)) onSelect(val)
            }}
            className="h-5 w-8 cursor-pointer rounded border border-slate-200 bg-transparent p-0"
            title="Pick custom colour"
          />
          <span className="font-mono text-[10px] text-black">{current || '—'}</span>
        </div>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Editor
// ---------------------------------------------------------------------------

interface Props {
  content: string | null
  onChange: (json: string) => void
  placeholder?: string
  minRows?: number
}

export default function RichTextEditor({ content, onChange, placeholder, minRows = 4 }: Props) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
      Underline,
      Link.configure({ openOnClick: false }),
      Placeholder.configure({ placeholder: placeholder ?? 'Write here…' }),
      TextStyle,
      Color,
      Highlight.configure({ multicolor: true }),
      FontFamily,
      TextAlign.configure({ types: ['paragraph', 'heading'] }),
      // Tables — the resizable HTML5 draggable behaviour is disabled
      // to avoid the same drag/select conflict we hit at the block
      // level: with resizable columns TipTap installs its own drag
      // handles, and dragging text inside cells becomes unreliable.
      Table.configure({ resizable: false, HTMLAttributes: { class: 'rt-table' } }),
      TableRow,
      TableHeader,
      TableCell,
    ],
    content: parseRichContent(content),
    onUpdate: ({ editor }) => {
      onChange(JSON.stringify(editor.getJSON()))
    },
    editorProps: {
      attributes: { class: 'focus:outline-none' },
    },
  })

  if (!editor) return null

  function addLink() {
    const url = prompt('Enter URL:')
    if (!url) return
    editor?.chain().focus().setLink({ href: url }).run()
  }

  function removeLink() {
    editor?.chain().focus().unsetLink().run()
  }

  const currentColor     = (editor.getAttributes('textStyle').color     as string) ?? ''
  const currentHighlight = (editor.getAttributes('highlight').color     as string) ?? ''
  const currentFont      = (editor.getAttributes('textStyle').fontFamily as string) ?? ''
  const currentFontLabel = FONT_FAMILIES.find((f) => f.value === currentFont)?.label ?? 'Aa'

  return (
    // overflow-visible so popovers are not clipped by the container boundary.
    // Rounded corners are applied to the toolbar and editor area separately.
    <div className="rounded-lg border border-slate-200 bg-white">

      {/* Toolbar — rounded-t-lg keeps bg-slate-50 clipped to rounded corners */}
      <div className="flex flex-wrap items-center gap-0.5 rounded-t-lg border-b border-slate-100 bg-slate-50 px-2 py-1.5">

        {/* Text */}
        <ToolBtn onClick={() => editor.chain().focus().toggleBold().run()} active={editor.isActive('bold')} title="Bold">
          <strong>B</strong>
        </ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().toggleItalic().run()} active={editor.isActive('italic')} title="Italic">
          <em>I</em>
        </ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().toggleUnderline().run()} active={editor.isActive('underline')} title="Underline">
          <span style={{ textDecoration: 'underline' }}>U</span>
        </ToolBtn>

        <span className="mx-1 h-4 w-px bg-slate-200" />

        {/* Structure */}
        <ToolBtn onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} active={editor.isActive('heading', { level: 1 })} title="Heading 1">H1</ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} active={editor.isActive('heading', { level: 2 })} title="Heading 2">H2</ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} active={editor.isActive('heading', { level: 3 })} title="Heading 3">H3</ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().toggleBulletList().run()} active={editor.isActive('bulletList')} title="Bullet list">•≡</ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().toggleOrderedList().run()} active={editor.isActive('orderedList')} title="Numbered list">1≡</ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().toggleBlockquote().run()} active={editor.isActive('blockquote')} title="Blockquote">"</ToolBtn>

        <span className="mx-1 h-4 w-px bg-slate-200" />

        {/* Insert — link + emoji */}
        <ToolBtn
          onClick={() => editor.isActive('link') ? removeLink() : addLink()}
          active={editor.isActive('link')}
          title={editor.isActive('link') ? 'Remove link' : 'Add link'}
        >
          🔗
        </ToolBtn>
        <EmojiPicker
          variant="compact"
          align="bottom"
          onSelect={(emoji) => editor.chain().focus().insertContent(emoji).run()}
        />

        <span className="mx-1 h-4 w-px bg-slate-200" />

        {/* Style — text colour */}
        <Popover
          trigger={
            <button
              type="button"
              title="Text colour"
              className="flex h-7 w-7 items-center justify-center rounded text-[11px] font-bold text-black transition-colors hover:bg-slate-100"
            >
              <span style={{ borderBottom: `3px solid ${currentColor || '#334155'}`, lineHeight: 1 }}>A</span>
            </button>
          }
          width="w-48"
        >
          <ColorPickerSection
            label="Text colour"
            colors={TEXT_COLORS}
            current={currentColor}
            bordered
            onSelect={(v) => {
              if (v) editor.chain().focus().setColor(v).run()
              else editor.chain().focus().unsetColor().run()
            }}
          />
        </Popover>

        {/* Style — highlight — align right to prevent clipping */}
        <Popover
          align="right"
          trigger={
            <button
              type="button"
              title="Highlight colour"
              className="flex h-7 w-7 items-center justify-center rounded text-[11px] font-bold transition-colors hover:bg-slate-100"
            >
              <span
                className="flex h-4 w-4 items-center justify-center rounded text-[10px] font-bold"
                style={{ backgroundColor: currentHighlight || '#FBF6E8', color: '#334155' }}
              >
                H
              </span>
            </button>
          }
          width="w-48"
        >
          <ColorPickerSection
            label="Highlight"
            colors={HIGHLIGHT_COLORS}
            current={currentHighlight}
            onSelect={(v) => {
              if (v) editor.chain().focus().setHighlight({ color: v }).run()
              else editor.chain().focus().unsetHighlight().run()
            }}
          />
        </Popover>

        {/* Style — font family — align right to prevent clipping */}
        <Popover
          align="right"
          trigger={
            <button
              type="button"
              title="Font style"
              className="flex h-7 items-center justify-center gap-0.5 rounded px-1.5 text-[11px] font-medium text-black transition-colors hover:bg-slate-100"
            >
              {currentFontLabel}
              <svg className="h-3 w-3" viewBox="0 0 12 12" fill="currentColor">
                <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
              </svg>
            </button>
          }
          width="w-40"
        >
          <div className="flex flex-col gap-0.5">
            {FONT_FAMILIES.map((f) => (
              <button
                key={f.value || 'default'}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault()
                  if (f.value) editor.chain().focus().setFontFamily(f.value).run()
                  else editor.chain().focus().unsetFontFamily().run()
                }}
                className={`rounded px-2 py-1 text-left text-[13px] transition-colors hover:bg-slate-100 ${
                  currentFont === f.value ? 'bg-teal-50 font-medium text-teal-700' : 'text-black'
                }`}
                style={{ fontFamily: f.value || 'inherit' }}
              >
                {f.label}
              </button>
            ))}
          </div>
        </Popover>

        <span className="mx-1 h-4 w-px bg-slate-200" />

        {/* Alignment */}
        <ToolBtn
          onClick={() => editor.chain().focus().setTextAlign('left').run()}
          active={editor.isActive({ textAlign: 'left' })}
          title="Align left (Ctrl/Cmd + Shift + L)"
        >⇤</ToolBtn>
        <ToolBtn
          onClick={() => editor.chain().focus().setTextAlign('center').run()}
          active={editor.isActive({ textAlign: 'center' })}
          title="Align centre (Ctrl/Cmd + Shift + E)"
        >⇔</ToolBtn>
        <ToolBtn
          onClick={() => editor.chain().focus().setTextAlign('right').run()}
          active={editor.isActive({ textAlign: 'right' })}
          title="Align right (Ctrl/Cmd + Shift + R)"
        >⇥</ToolBtn>

        <span className="mx-1 h-4 w-px bg-slate-200" />

        {/* Insert */}
        <ToolBtn
          onClick={() => editor.chain().focus().setHorizontalRule().run()}
          title="Horizontal divider"
        >—</ToolBtn>
        <TableMenu editor={editor} />

        <span className="mx-1 h-4 w-px bg-slate-200" />

        {/* History */}
        <ToolBtn
          onClick={() => editor.chain().focus().undo().run()}
          title="Undo (Ctrl/Cmd + Z)"
        >↩</ToolBtn>
        <ToolBtn
          onClick={() => editor.chain().focus().redo().run()}
          title="Redo (Ctrl/Cmd + Shift + Z)"
        >↪</ToolBtn>
      </div>

      {/* Contextual table controls — only rendered when the caret is
          inside a table so writers can add or delete rows/columns
          without hunting through a dropdown. */}
      <TableToolbar editor={editor} />

      {/* Editor area */}
      <div
        className="rich-editor rounded-b-lg px-4 py-3"
        style={{ minHeight: `${minRows * 1.6}rem` }}
      >
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}
