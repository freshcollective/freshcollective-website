'use client'

import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function parseRichContent(content: string | null): Record<string, unknown> {
  if (!content) return { type: 'doc', content: [] }
  try {
    const parsed = JSON.parse(content)
    if (parsed?.type === 'doc') return parsed
  } catch {}
  // Wrap legacy plain text in TipTap paragraphs
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
    ],
    content: parseRichContent(content),
    onUpdate: ({ editor }) => {
      onChange(JSON.stringify(editor.getJSON()))
    },
    editorProps: {
      attributes: {
        class: 'focus:outline-none',
      },
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

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-0.5 border-b border-slate-100 bg-slate-50 px-2 py-1.5">
        <ToolBtn
          onClick={() => editor.chain().focus().toggleBold().run()}
          active={editor.isActive('bold')}
          title="Bold"
        >
          <strong>B</strong>
        </ToolBtn>
        <ToolBtn
          onClick={() => editor.chain().focus().toggleItalic().run()}
          active={editor.isActive('italic')}
          title="Italic"
        >
          <em>I</em>
        </ToolBtn>
        <ToolBtn
          onClick={() => editor.chain().focus().toggleUnderline().run()}
          active={editor.isActive('underline')}
          title="Underline"
        >
          <span style={{ textDecoration: 'underline' }}>U</span>
        </ToolBtn>

        <span className="mx-1 h-4 w-px bg-slate-200" />

        <ToolBtn
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
          active={editor.isActive('heading', { level: 2 })}
          title="Heading 2"
        >
          H2
        </ToolBtn>
        <ToolBtn
          onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
          active={editor.isActive('heading', { level: 3 })}
          title="Heading 3"
        >
          H3
        </ToolBtn>

        <span className="mx-1 h-4 w-px bg-slate-200" />

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
        <ToolBtn
          onClick={() => editor.chain().focus().toggleBlockquote().run()}
          active={editor.isActive('blockquote')}
          title="Blockquote"
        >
          "
        </ToolBtn>

        <span className="mx-1 h-4 w-px bg-slate-200" />

        <ToolBtn
          onClick={() => editor.isActive('link') ? removeLink() : addLink()}
          active={editor.isActive('link')}
          title={editor.isActive('link') ? 'Remove link' : 'Add link'}
        >
          🔗
        </ToolBtn>

        <span className="mx-1 h-4 w-px bg-slate-200" />

        <ToolBtn
          onClick={() => editor.chain().focus().undo().run()}
          title="Undo"
        >
          ↩
        </ToolBtn>
        <ToolBtn
          onClick={() => editor.chain().focus().redo().run()}
          title="Redo"
        >
          ↪
        </ToolBtn>
      </div>

      {/* Editor area */}
      <div
        className="rich-editor px-4 py-3"
        style={{ minHeight: `${minRows * 1.6}rem` }}
      >
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}
