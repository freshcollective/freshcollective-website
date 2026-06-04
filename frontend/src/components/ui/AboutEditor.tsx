'use client'

import { useRef, useState } from 'react'
import MarkdownBody from './MarkdownBody'

interface Props {
  value: string
  onChange: (value: string) => void
  id?: string
}

// Toolbar button definitions
const TOOLBAR = [
  {
    label: 'Heading',
    title: 'Insert a section heading (##)',
    action: (sel: string) =>
      sel.trim()
        ? { insert: `## ${sel}`, cursorOffset: 3 + sel.length }
        : { insert: '## Section heading', cursorOffset: 18 },
  },
  {
    label: 'Bold',
    title: 'Wrap in bold (**text**)',
    action: (sel: string) =>
      sel.trim()
        ? { insert: `**${sel}**`, cursorOffset: 2 + sel.length }
        : { insert: '**bold text**', cursorOffset: 12 },
  },
  {
    label: 'Bullet list',
    title: 'Insert a bullet list',
    action: (_sel: string) => ({
      insert: '* First point\n* Second point\n* Third point',
      cursorOffset: 42,
    }),
  },
  {
    label: 'Link',
    title: 'Insert a link [text](url)',
    action: (sel: string) =>
      sel.trim()
        ? { insert: `[${sel}](https://example.com)`, cursorOffset: sel.length + 22 }
        : { insert: '[Link text](https://example.com)', cursorOffset: 31 },
  },
]

export default function AboutEditor({ value, onChange, id }: Props) {
  const taRef = useRef<HTMLTextAreaElement>(null)
  const [previewOpen, setPreviewOpen] = useState(false)

  function applyFormat(action: typeof TOOLBAR[0]['action']) {
    const ta = taRef.current
    if (!ta) return

    const start = ta.selectionStart
    const end = ta.selectionEnd
    const selected = value.slice(start, end)
    const { insert } = action(selected)

    // Build new value: prefix + insert + suffix
    const prefix = value.slice(0, start)
    const suffix = value.slice(end)

    // Ensure there's a blank line before a heading or bullet if not at the start
    let before = prefix
    if (prefix.length > 0 && !prefix.endsWith('\n')) {
      before = prefix + '\n'
    }

    const newValue = before + insert + suffix
    onChange(newValue)

    // Restore focus and place cursor after the inserted text
    const newCursor = before.length + insert.length
    requestAnimationFrame(() => {
      ta.focus()
      ta.setSelectionRange(newCursor, newCursor)
    })
  }

  return (
    <div className="space-y-2">
      {/* Toolbar */}
      <div
        className="flex flex-wrap gap-1.5 rounded-xl border border-slate-200 bg-slate-50/80 px-3 py-2"
      >
        {TOOLBAR.map((btn) => (
          <button
            key={btn.label}
            type="button"
            title={btn.title}
            onClick={() => applyFormat(btn.action)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1 text-[12px] font-medium text-slate-600 transition-colors hover:border-teal-300 hover:bg-teal-50 hover:text-teal-700 active:bg-teal-100"
          >
            {btn.label}
          </button>
        ))}
        <span
          className="my-auto ml-1 h-4 w-px bg-slate-200"
          aria-hidden="true"
        />
        <span className="my-auto text-[11px] text-slate-400">
          Markdown supported
        </span>
      </div>

      {/* Textarea */}
      <textarea
        id={id}
        ref={taRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={
          'Write your About page content here.\n\nTip: Use the toolbar above to add headings, bold text, and bullet lists.\n\nExample:\n## What is this collective?\n\nA short description...'
        }
        className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-3 text-[14px] leading-[1.7] text-navy-900 placeholder:text-slate-400 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
        style={{ minHeight: '320px', resize: 'vertical' }}
        spellCheck
      />

      {/* Preview toggle */}
      <div>
        <button
          type="button"
          onClick={() => setPreviewOpen((o) => !o)}
          className="flex items-center gap-1.5 text-[13px] font-medium text-teal-600 transition-colors hover:text-teal-700"
        >
          <span
            className="inline-block transition-transform"
            style={{ transform: previewOpen ? 'rotate(90deg)' : 'rotate(0deg)' }}
            aria-hidden="true"
          >
            ▶
          </span>
          {previewOpen ? 'Hide preview' : 'Preview'}
        </button>

        {previewOpen && (
          <div
            className="mt-3 rounded-xl border border-slate-200 bg-white px-6 py-5"
            aria-label="About page preview"
          >
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
              Preview — how it looks on your About page
            </p>
            {value.trim() ? (
              <MarkdownBody content={value} />
            ) : (
              <p className="text-[14px] text-slate-400">
                Your formatted About page preview will appear here.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
