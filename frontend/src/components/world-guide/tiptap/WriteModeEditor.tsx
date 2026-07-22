'use client'

import { useCallback, useEffect, useImperativeHandle, useMemo, useRef } from 'react'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import { htmlToMarkdown, markdownToWriteHtml } from '@/lib/worldGuide-write'
import { WG } from '@/lib/worldGuide'
import {
  WgCallout,
  WgImage,
  WgMarkdownBlock,
  WgTaskItem,
  WgTaskList,
} from './extensions'


/**
 * WriteMode editor.
 *
 * Consumes Markdown, edits visually via TipTap, emits Markdown on
 * every change. The canonical stored format never leaves this
 * boundary as HTML.
 *
 * The MarkdownBlock node (currently used for tables) preserves its
 * source verbatim through the round-trip. Users wanting to edit a
 * table switch to Markdown mode.
 */


export interface WriteModeHandle {
  focus(): void
  getEditor(): Editor | null
  toggleBold(): void
  toggleItalic(): void
  toggleInlineCode(): void
  setHeading(level: 1 | 2 | 3): void
  toggleBullet(): void
  toggleOrdered(): void
  toggleTaskList(): void
  toggleBlockquote(): void
  insertHorizontalRule(): void
  insertCodeBlock(): void
  insertLink(url: string, text?: string): void
  insertImage(src: string, alt: string): void
  insertCallout(kind?: 'note' | 'tip' | 'warning' | 'info'): void
  insertTable(): void
}


interface Props {
  value: string                     // Markdown
  onChange: (md: string) => void    // fires on debounced editor updates
  disabled?: boolean
  onKeyDown?: (e: KeyboardEvent) => void
  handleRef?: React.Ref<WriteModeHandle>
}


export default function WriteModeEditor({ value, onChange, disabled, onKeyDown, handleRef }: Props) {
  // Guard against feedback loops — when we push HTML back into the
  // editor from Markdown, TipTap fires ``onUpdate``. We swallow the
  // next update once, then resume.
  const suppressNext = useRef(false)
  const lastEmitted = useRef<string>('')

  const initialHtml = useMemo(() => markdownToWriteHtml(value), [])   // eslint-disable-line react-hooks/exhaustive-deps

  const editor = useEditor({
    editable: !disabled,
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        codeBlock: {},
        // Task lists — we own our own extension because ours matches
        // the shared renderer's <ul class="wg-tasklist"> output.
      }),
      Link.configure({
        openOnClick: false,
        autolink: true,
        HTMLAttributes: { rel: 'noopener noreferrer', target: '_blank' },
      }),
      WgImage,
      WgCallout,
      WgTaskList,
      WgTaskItem,
      WgMarkdownBlock,
    ],
    content: initialHtml,
    immediatelyRender: false,      // avoid Next SSR hydration warnings
    onUpdate: ({ editor }) => {
      if (suppressNext.current) {
        suppressNext.current = false
        return
      }
      const html = editor.getHTML()
      const md = htmlToMarkdown(html)
      lastEmitted.current = md
      onChange(md)
    },
    editorProps: {
      attributes: {
        class: 'wg-write wg-prose',
        spellcheck: 'true',
      },
      handleKeyDown: (_view, event) => {
        onKeyDown?.(event)
        return false
      },
    },
  })

  // React to external ``value`` changes (e.g. mode switch from
  // Markdown → Write, or an Import Markdown apply). We diff the
  // incoming Markdown against what we last emitted so we do not push
  // stale content over the writer's cursor.
  useEffect(() => {
    if (!editor) return
    if (value === lastEmitted.current) return
    suppressNext.current = true
    editor.commands.setContent(markdownToWriteHtml(value), { emitUpdate: false })
    lastEmitted.current = value
  }, [value, editor])

  // Render preview HTML for MarkdownBlock nodes on every DOM change.
  // TipTap's default renderer places the raw HTML string into a
  // ``data-html`` attribute — we hydrate it into the corresponding
  // preview div so tables show their rendered output.
  const contentRef = useRef<HTMLDivElement | null>(null)
  const hydrateMarkdownBlocks = useCallback(() => {
    const root = contentRef.current
    if (!root) return
    for (const el of Array.from(root.querySelectorAll<HTMLElement>('.wg-md-block-preview[data-html]'))) {
      const html = el.getAttribute('data-html') ?? ''
      if (el.innerHTML !== html) el.innerHTML = html
    }
  }, [])
  useEffect(() => {
    if (!editor) return
    hydrateMarkdownBlocks()
    const unsub = editor.on('transaction', hydrateMarkdownBlocks)
    return () => { unsub.off?.('transaction', hydrateMarkdownBlocks) }
  }, [editor, hydrateMarkdownBlocks])

  useImperativeHandle(handleRef, () => ({
    focus() { editor?.commands.focus() },
    getEditor() { return editor },
    toggleBold() { editor?.chain().focus().toggleBold().run() },
    toggleItalic() { editor?.chain().focus().toggleItalic().run() },
    toggleInlineCode() { editor?.chain().focus().toggleCode().run() },
    setHeading(level) { editor?.chain().focus().toggleHeading({ level }).run() },
    toggleBullet() { editor?.chain().focus().toggleBulletList().run() },
    toggleOrdered() { editor?.chain().focus().toggleOrderedList().run() },
    toggleTaskList() {
      // Insert a starter checklist item; users continue by pressing Enter.
      editor?.chain().focus().insertContent({
        type: 'wgTaskList',
        content: [
          { type: 'wgTaskItem', attrs: { checked: false }, content: [{ type: 'text', text: 'Task' }] },
        ],
      }).run()
    },
    toggleBlockquote() { editor?.chain().focus().toggleBlockquote().run() },
    insertHorizontalRule() { editor?.chain().focus().setHorizontalRule().run() },
    insertCodeBlock() { editor?.chain().focus().toggleCodeBlock().run() },
    insertLink(url, textOverride) {
      if (!editor) return
      if (textOverride && editor.state.selection.empty) {
        editor.chain().focus().insertContent(textOverride).setLink({ href: url }).run()
      } else {
        editor.chain().focus().setLink({ href: url }).run()
      }
    },
    insertImage(src, alt) {
      editor?.chain().focus().insertContent({ type: 'wgImage', attrs: { src, alt } }).run()
    },
    insertCallout(kind = 'note') {
      editor?.chain().focus().insertContent({
        type: 'wgCallout',
        attrs: { kind, title: 'Note' },
        content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Body' }] }],
      }).run()
    },
    insertTable() {
      const md = '| Column | Column |\n| --- | --- |\n| Value | Value |'
      const html = `<table>${md
        .split('\n')
        .slice(0, 1)
        .map((r) => `<tr>${r.split('|').slice(1, -1).map((c) => `<th>${c.trim()}</th>`).join('')}</tr>`)
        .join('')}${md
          .split('\n')
          .slice(2)
          .map((r) => `<tr>${r.split('|').slice(1, -1).map((c) => `<td>${c.trim()}</td>`).join('')}</tr>`)
          .join('')}</table>`
      editor?.chain().focus().insertContent({
        type: 'wgMarkdownBlock',
        attrs: { md, html, kind: 'table' },
      }).run()
    },
  }), [editor])

  return (
    <div
      ref={contentRef}
      className="wg-write-shell"
    >
      <EditorContent editor={editor} />
      <style jsx global>{`
        .wg-write-shell .ProseMirror {
          outline: none;
          min-height: 380px;
          padding: 24px 28px;
          color: ${WG.ink};
        }
        .wg-write-shell .ProseMirror :is(h1, h2, h3) {
          color: ${WG.inkStrong};
          font-family: Georgia, 'Times New Roman', serif;
          font-weight: 600;
          line-height: 1.25;
        }
        .wg-write-shell .ProseMirror h1 { font-size: 26px; margin: 24px 0 10px; }
        .wg-write-shell .ProseMirror h2 { font-size: 21px; margin: 22px 0 10px; }
        .wg-write-shell .ProseMirror h3 { font-size: 17px; margin: 18px 0 8px; }
        .wg-write-shell .ProseMirror p { margin: 10px 0; line-height: 1.7; }
        .wg-write-shell .ProseMirror ul, .wg-write-shell .ProseMirror ol { margin: 10px 0 10px 22px; }
        .wg-write-shell .ProseMirror li { margin: 3px 0; }
        .wg-write-shell .ProseMirror a { color: ${WG.teal}; text-decoration: underline; }
        .wg-write-shell .ProseMirror blockquote { border-left: 3px solid ${WG.teal}; padding: 4px 14px; margin: 12px 0; color: ${WG.inkMuted}; font-style: italic; }
        .wg-write-shell .ProseMirror pre { background: ${WG.surfaceBg}; border: 1px solid rgba(15,23,42,0.08); border-radius: 8px; padding: 12px 14px; font-size: 13.5px; overflow-x: auto; }
        .wg-write-shell .ProseMirror pre code { background: transparent; padding: 0; }
        .wg-write-shell .ProseMirror code { background: rgba(15,23,42,0.06); padding: 1px 5px; border-radius: 3px; font-size: 0.9em; }
        .wg-write-shell .ProseMirror hr { border: none; border-top: 1px solid rgba(15,23,42,0.10); margin: 24px 0; }
        .wg-write-shell .ProseMirror .wg-callout {
          border: none;
          border-left: 3px solid ${WG.teal};
          background: ${WG.tealSoft};
          padding: 12px 16px;
          margin: 14px 0;
          border-radius: 0;
          box-shadow: none;
        }
        .wg-write-shell .ProseMirror .wg-callout .wg-callout-title { color: ${WG.inkStrong}; font-weight: 600; margin-bottom: 4px; }
        .wg-write-shell .ProseMirror .wg-md-block {
          border: 1px dashed rgba(15,23,42,0.16);
          background: ${WG.surfaceBg};
          padding: 10px 14px;
          margin: 14px 0;
          border-radius: 6px;
          position: relative;
        }
        .wg-write-shell .ProseMirror .wg-md-block::before {
          content: 'Table — edit in Markdown mode';
          display: block;
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.06em;
          color: ${WG.inkSofter};
          margin-bottom: 6px;
        }
        .wg-write-shell .ProseMirror .wg-md-block table { border-collapse: collapse; width: 100%; }
        .wg-write-shell .ProseMirror .wg-md-block th, .wg-write-shell .ProseMirror .wg-md-block td {
          border: 1px solid rgba(15,23,42,0.10);
          padding: 6px 10px;
          text-align: left;
        }
        .wg-write-shell .ProseMirror .wg-md-block th { background: ${WG.tealSoft}; color: ${WG.inkStrong}; font-weight: 600; }
      `}</style>
    </div>
  )
}
