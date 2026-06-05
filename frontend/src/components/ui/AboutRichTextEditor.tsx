'use client'

import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import { markdownToHtml } from '@/lib/markdownToHtml'

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
        // Prevent blur before the command fires
        e.preventDefault()
        onClick()
      }}
      title={title}
      className={`rounded-lg border px-3 py-1 text-[12px] font-medium transition-colors ${
        active
          ? 'border-teal-300 bg-teal-50 text-teal-700'
          : 'border-slate-200 bg-white text-slate-600 hover:border-teal-300 hover:bg-teal-50 hover:text-teal-700'
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
  /** Current value — may be legacy markdown or TipTap HTML */
  value: string
  /** Called with TipTap HTML output on every change */
  onChange: (html: string) => void
  id?: string
}

export default function AboutRichTextEditor({ value, onChange, id }: Props) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
        // Disable features not needed for About pages
        italic: false,
        strike: false,
        code: false,
        codeBlock: false,
        blockquote: false,
        horizontalRule: false,
      }),
      Link.configure({
        openOnClick: false,
        HTMLAttributes: {
          target: '_blank',
          rel: 'noopener noreferrer nofollow',
        },
      }),
      Placeholder.configure({
        placeholder:
          'Write your About page content here.\n\nUse the toolbar to add headings, bold text, and bullet lists.',
      }),
    ],
    // Convert markdown → HTML if needed; HTML passes through unchanged
    content: markdownToHtml(value),
    onUpdate({ editor }) {
      onChange(editor.getHTML())
    },
    editorProps: {
      attributes: { class: 'focus:outline-none' },
    },
  })

  if (!editor) {
    return (
      <div
        className="w-full rounded-xl border border-slate-200 bg-slate-50/70"
        style={{ minHeight: '320px' }}
      />
    )
  }

  function handleAddLink() {
    const current = editor?.getAttributes('link').href as string | undefined
    const url = window.prompt('Link URL:', current ?? 'https://')
    if (!url) return
    if (!/^https?:\/\//i.test(url)) {
      window.alert('Please enter a URL starting with https:// or http://')
      return
    }
    editor?.chain().focus().setLink({ href: url }).run()
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white transition-colors focus-within:border-teal-400 focus-within:ring-2 focus-within:ring-teal-400/20">
      {/* ── Toolbar ── */}
      <div className="flex flex-wrap items-center gap-1.5 border-b border-slate-100 bg-slate-50/80 px-3 py-2">
        <ToolBtn
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
          active={editor.isActive('heading', { level: 2 })}
          title="Section heading (##)"
        >
          Heading
        </ToolBtn>

        <ToolBtn
          onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
          active={editor.isActive('heading', { level: 3 })}
          title="Sub-heading (###)"
        >
          Sub-heading
        </ToolBtn>

        <ToolBtn
          onClick={() => editor.chain().focus().toggleBold().run()}
          active={editor.isActive('bold')}
          title="Bold (**text**)"
        >
          <strong>Bold</strong>
        </ToolBtn>

        <ToolBtn
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          active={editor.isActive('bulletList')}
          title="Bullet list"
        >
          List
        </ToolBtn>

        <ToolBtn
          onClick={handleAddLink}
          active={editor.isActive('link')}
          title="Add or edit link"
        >
          Link
        </ToolBtn>

        {editor.isActive('link') && (
          <ToolBtn
            onClick={() => editor.chain().focus().unsetLink().run()}
            title="Remove link"
          >
            Remove link
          </ToolBtn>
        )}

        <span className="mx-1 h-4 w-px bg-slate-200" aria-hidden="true" />

        <ToolBtn onClick={() => editor.chain().focus().undo().run()} title="Undo">
          Undo
        </ToolBtn>
        <ToolBtn onClick={() => editor.chain().focus().redo().run()} title="Redo">
          Redo
        </ToolBtn>
      </div>

      {/* ── Editor area — uses .rich-editor CSS class from globals.css ── */}
      <div
        id={id}
        className="rich-editor px-5 py-4"
        style={{ minHeight: '320px' }}
      >
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}
