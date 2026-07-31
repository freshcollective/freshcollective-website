'use client'

import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import EmojiPicker from '@/components/community/EmojiPicker'

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
      className={`flex h-6 w-6 items-center justify-center rounded text-[12px] transition-colors ${
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
// Editor
// ---------------------------------------------------------------------------

interface Props {
  value: string
  onChange: (json: string) => void
  placeholder?: string
  minHeight?: number
}

export default function SimpleRichTextEditor({ value, onChange, placeholder, minHeight = 100 }: Props) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ codeBlock: false, blockquote: false, horizontalRule: false }),
      Link.configure({ openOnClick: false, HTMLAttributes: { rel: 'noopener noreferrer', target: '_blank' } }),
      Placeholder.configure({ placeholder: placeholder ?? 'Add some text…' }),
    ],
    content: parseContent(value),
    onUpdate({ editor }) {
      onChange(JSON.stringify(editor.getJSON()))
    },
    editorProps: {
      attributes: { class: 'focus:outline-none' },
    },
  })

  if (!editor) return null

  function addLink() {
    const url = prompt('Enter URL (include https://):')
    if (!url) return
    const safe = /^https?:\/\//.test(url) ? url : `https://${url}`
    editor?.chain().focus().setLink({ href: safe }).run()
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white focus-within:border-teal-400 focus-within:ring-2 focus-within:ring-teal-100">
      {/* Toolbar */}
      <div className="flex items-center gap-0.5 border-b border-slate-100 bg-slate-50 px-2 py-1.5 rounded-t-xl">
        {/* Block-level style — Paragraph / H1 / H2 / H3. Headings are
            first-class in the Member Hub renderer, so they need to be
            first-class in the toolbar too — a Creator shouldn't have
            to remember a keyboard shortcut to add one. */}
        <select
          value={
            editor.isActive('heading', { level: 1 }) ? 'h1'
            : editor.isActive('heading', { level: 2 }) ? 'h2'
            : editor.isActive('heading', { level: 3 }) ? 'h3'
            : 'p'
          }
          onChange={(e) => {
            const v = e.target.value
            const chain = editor.chain().focus()
            if (v === 'p')       chain.setParagraph().run()
            else if (v === 'h1') chain.toggleHeading({ level: 1 }).run()
            else if (v === 'h2') chain.toggleHeading({ level: 2 }).run()
            else if (v === 'h3') chain.toggleHeading({ level: 3 }).run()
          }}
          title="Text style"
          className="mr-1 h-6 rounded bg-transparent px-1 text-[12px] text-black hover:bg-slate-100 focus:outline-none"
        >
          <option value="p">Paragraph</option>
          <option value="h1">Heading 1</option>
          <option value="h2">Heading 2</option>
          <option value="h3">Heading 3</option>
        </select>

        <span className="mx-1 h-3.5 w-px bg-slate-200" />

        <ToolBtn
          onClick={() => editor.chain().focus().toggleBold().run()}
          active={editor.isActive('bold')}
          title="Bold (Cmd/Ctrl+B)"
        >
          <strong>B</strong>
        </ToolBtn>
        <ToolBtn
          onClick={() => editor.chain().focus().toggleItalic().run()}
          active={editor.isActive('italic')}
          title="Italic (Cmd/Ctrl+I)"
        >
          <em>I</em>
        </ToolBtn>
        {/* Clear formatting — removes marks on the current selection.
            TipTap's toggleBold/toggleItalic can feel unresponsive when
            the selection is collapsed at a mark boundary (it toggles
            "stored marks" for future typing rather than existing
            text). This button gives Creators an unambiguous way to
            strip inline formatting: select the text, click Tx. */}
        <ToolBtn
          onClick={() =>
            editor.chain().focus().unsetAllMarks().run()
          }
          title="Clear formatting"
        >
          Tx
        </ToolBtn>

        <span className="mx-1 h-3.5 w-px bg-slate-200" />

        <ToolBtn
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          active={editor.isActive('bulletList')}
          title="Bullet list"
        >
          •≡
        </ToolBtn>
        <ToolBtn
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
          active={editor.isActive('orderedList')}
          title="Numbered list"
        >
          1≡
        </ToolBtn>

        <span className="mx-1 h-3.5 w-px bg-slate-200" />

        <ToolBtn
          onClick={() => editor.isActive('link') ? editor.chain().focus().unsetLink().run() : addLink()}
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
      </div>

      {/* Editable area */}
      <div style={{ minHeight }} className="px-3.5 py-2.5 text-[14px] leading-relaxed text-slate-800">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Parse stored value — accepts TipTap JSON string or plain text
// ---------------------------------------------------------------------------

function parseContent(value: string): object {
  if (!value) return { type: 'doc', content: [] }
  try {
    const parsed = JSON.parse(value)
    if (parsed?.type === 'doc') return parsed
  } catch {}
  // Wrap plain text as a single paragraph
  return {
    type: 'doc',
    content: [{ type: 'paragraph', content: value ? [{ type: 'text', text: value }] : [] }],
  }
}
