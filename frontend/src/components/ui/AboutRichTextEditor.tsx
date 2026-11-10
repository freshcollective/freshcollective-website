'use client'

import { Node, mergeAttributes } from '@tiptap/core'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import { markdownToHtml } from '@/lib/markdownToHtml'
import EmojiPicker from '@/components/community/EmojiPicker'
import {
  TOOLBAR_CLASS,
  ToolButton,
  ToolDivider,
} from '@/components/creator/EditorToolbar'

/**
 * An inline image, as a ten-line node rather than a new dependency.
 *
 * ``@tiptap/extension-image`` is not installed and is not needed: the
 * World Guide's ``WgImage`` already proves the shape, and this is the
 * same thing with one difference. ``WgImage`` bakes an inline
 * ``style`` attribute into its ``renderHTML``; this emits a bare
 * ``<img src alt>`` because the Guides sanitiser allows no ``style``
 * attribute and would strip it on the next save. Appearance belongs
 * to the renderer, and the stored HTML stays content.
 */
const InlineImage = Node.create({
  name: 'inlineImage',
  group: 'block',
  atom: true,
  draggable: true,
  addAttributes() {
    return { src: { default: '' }, alt: { default: '' } }
  },
  parseHTML() {
    return [{ tag: 'img[src]' }]
  },
  renderHTML({ HTMLAttributes }) {
    return ['img', mergeAttributes(HTMLAttributes)]
  },
})

// ---------------------------------------------------------------------------
// Editor
// ---------------------------------------------------------------------------

interface Props {
  /** Current value — may be legacy markdown or TipTap HTML */
  value: string
  /** Called with TipTap HTML output on every change */
  onChange: (html: string) => void
  id?: string
  /**
   * Offer italic and numbered lists.
   *
   * Opt-in so the Collective About page's *capabilities* are
   * unchanged: it has never had either, and adding them there is a
   * separate decision. Its toolbar does now look different — flat
   * squares in the shared Creator Studio chrome rather than bordered
   * text pills — which is the point: it was the only editor of the
   * three that disagreed.
   */
  extendedMarks?: boolean
  /** Replaces the About-page placeholder. */
  placeholder?: string
  /** Editing area height. About pages want a tall canvas; a Gathering
   *  description is usually a few paragraphs. */
  minHeight?: string
  /**
   * Offer block quotes.
   *
   * Opt-in for the same reason ``extendedMarks`` is: the Collective
   * About page and Gathering descriptions have never had one, their
   * renderer does not display one, and adding it there is a separate
   * decision from adding it to Guides.
   */
  blockquote?: boolean
  /**
   * Offer inline images.
   *
   * The handler uploads and returns a URL, or ``null`` if the author
   * cancelled or the upload failed. Absent means no image button and
   * no image node registered at all — a surface that cannot store an
   * image should not be able to produce one.
   */
  onRequestImage?: () => Promise<{ src: string; alt: string } | null>
}

export default function AboutRichTextEditor({
  value, onChange, id, extendedMarks = false, placeholder, minHeight,
  blockquote = false, onRequestImage,
}: Props) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
        // Disable features not needed for About pages
        italic: extendedMarks ? undefined : false,
        strike: false,
        code: false,
        codeBlock: false,
        blockquote: blockquote ? undefined : false,
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
        placeholder: placeholder
          ?? 'Write your About page content here.\n\nUse the toolbar to add headings, bold text, and bullet lists.',
      }),
      // Registered only where images can actually be stored.
      ...(onRequestImage ? [InlineImage] : []),
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
        className="w-full rounded-lg border border-slate-200 bg-slate-50/70"
        style={{ minHeight: minHeight ?? '320px' }}
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

  async function handleAddImage() {
    if (!onRequestImage) return
    const picked = await onRequestImage()
    if (!picked?.src) return
    editor
      ?.chain()
      .focus()
      .insertContent({ type: 'inlineImage', attrs: picked })
      .run()
  }

  return (
    // No ``overflow-hidden``. It was clipping the emoji panel at the
    // container's edge — the exact problem ``RichTextEditor`` documents
    // solving the same way: rounding goes on the toolbar and the editor
    // area separately, so the corners still look right while a popover
    // can leave the box.
    <div className="rounded-lg border border-slate-200 bg-white transition-colors focus-within:border-teal-400 focus-within:ring-2 focus-within:ring-teal-400/20">
      {/* ── Toolbar — shared Creator Studio chrome ── */}
      <div className={TOOLBAR_CLASS}>
        {/* Text */}
        <ToolButton
          onClick={() => editor.chain().focus().toggleBold().run()}
          active={editor.isActive('bold')}
          title="Bold"
        >
          <strong>B</strong>
        </ToolButton>

        {extendedMarks && (
          <ToolButton
            onClick={() => editor.chain().focus().toggleItalic().run()}
            active={editor.isActive('italic')}
            title="Italic"
          >
            <em>I</em>
          </ToolButton>
        )}

        <ToolDivider />

        {/* Structure */}
        <ToolButton
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
          active={editor.isActive('heading', { level: 2 })}
          title="Heading 2"
          wide
        >
          H2
        </ToolButton>
        <ToolButton
          onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
          active={editor.isActive('heading', { level: 3 })}
          title="Heading 3"
          wide
        >
          H3
        </ToolButton>
        <ToolButton
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          active={editor.isActive('bulletList')}
          title="Bullet list"
          wide
        >
          •≡
        </ToolButton>

        {extendedMarks && (
          <ToolButton
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
            active={editor.isActive('orderedList')}
            title="Numbered list"
            wide
          >
            1≡
          </ToolButton>
        )}

        {blockquote && (
          <ToolButton
            onClick={() => editor.chain().focus().toggleBlockquote().run()}
            active={editor.isActive('blockquote')}
            title="Block quote"
            wide
          >
            &rdquo;
          </ToolButton>
        )}

        <ToolDivider />

        {/* Insert */}
        <ToolButton
          onClick={() => (editor.isActive('link')
            ? editor.chain().focus().unsetLink().run()
            : handleAddLink())}
          active={editor.isActive('link')}
          title={editor.isActive('link') ? 'Remove link' : 'Add link'}
        >
          🔗
        </ToolButton>

        {onRequestImage && (
          <ToolButton onClick={handleAddImage} title="Insert image" wide>
            🖼
          </ToolButton>
        )}

        <EmojiPicker
          variant="compact"
          align="bottom"
          onSelect={(emoji) => editor.chain().focus().insertContent(emoji).run()}
        />

        <ToolDivider />

        <ToolButton
          onClick={() => editor.chain().focus().undo().run()}
          title="Undo"
          wide
        >
          ↶
        </ToolButton>
        <ToolButton
          onClick={() => editor.chain().focus().redo().run()}
          title="Redo"
          wide
        >
          ↷
        </ToolButton>
      </div>

      {/* ── Editor area — uses .rich-editor CSS class from globals.css ── */}
      <div
        id={id}
        className="rich-editor rounded-b-lg px-5 py-4"
        style={{ minHeight: minHeight ?? '320px' }}
      >
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}
