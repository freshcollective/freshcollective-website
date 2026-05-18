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

const TEXT_COLORS = [
  { label: 'Default',    value: '' },
  { label: 'Navy',       value: '#071824' },
  { label: 'Forest',     value: '#073B3A' },
  { label: 'Teal',       value: '#38A09E' },
  { label: 'Aqua',       value: '#55D7D2' },
  { label: 'Gold',       value: '#E7C65A' },
  { label: 'Amber',      value: '#9A7A18' },
  { label: 'Slate',      value: '#334155' },
  { label: 'Muted',      value: '#64748B' },
  { label: 'White',      value: '#FFFFFF' },
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
          : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
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

  return (
    <>
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</p>
      <ColorDots colors={colors} current={current} onSelect={onSelect} bordered={bordered} />
      <div className="mt-2 border-t border-slate-100 pt-2">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-400">Custom</span>
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
          <span className="font-mono text-[10px] text-slate-400">{current || '—'}</span>
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
      StarterKit.configure({ heading: { levels: [2, 3] } }),
      Underline,
      Link.configure({ openOnClick: false }),
      Placeholder.configure({ placeholder: placeholder ?? 'Write here…' }),
      TextStyle,
      Color,
      Highlight.configure({ multicolor: true }),
      FontFamily,
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
        <ToolBtn onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} active={editor.isActive('heading', { level: 2 })} title="Heading 2">H2</ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} active={editor.isActive('heading', { level: 3 })} title="Heading 3">H3</ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().toggleBulletList().run()} active={editor.isActive('bulletList')} title="Bullet list">•≡</ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().toggleOrderedList().run()} active={editor.isActive('orderedList')} title="Numbered list">1≡</ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().toggleBlockquote().run()} active={editor.isActive('blockquote')} title="Blockquote">"</ToolBtn>

        <span className="mx-1 h-4 w-px bg-slate-200" />

        {/* Insert — link only; emojis are typed/pasted natively via the OS picker */}
        <ToolBtn
          onClick={() => editor.isActive('link') ? removeLink() : addLink()}
          active={editor.isActive('link')}
          title={editor.isActive('link') ? 'Remove link' : 'Add link'}
        >
          🔗
        </ToolBtn>

        <span className="mx-1 h-4 w-px bg-slate-200" />

        {/* Style — text colour */}
        <Popover
          trigger={
            <button
              type="button"
              title="Text colour"
              className="flex h-7 w-7 items-center justify-center rounded text-[11px] font-bold text-slate-600 transition-colors hover:bg-slate-100"
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
              className="flex h-7 items-center justify-center gap-0.5 rounded px-1.5 text-[11px] font-medium text-slate-500 transition-colors hover:bg-slate-100"
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
                  currentFont === f.value ? 'bg-teal-50 font-medium text-teal-700' : 'text-slate-700'
                }`}
                style={{ fontFamily: f.value || 'inherit' }}
              >
                {f.label}
              </button>
            ))}
          </div>
        </Popover>

        <span className="mx-1 h-4 w-px bg-slate-200" />

        {/* History */}
        <ToolBtn onClick={() => editor.chain().focus().undo().run()} title="Undo">↩</ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().redo().run()} title="Redo">↪</ToolBtn>
      </div>

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
