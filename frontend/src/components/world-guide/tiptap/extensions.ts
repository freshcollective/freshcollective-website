/**
 * Custom TipTap nodes for World Guide Write mode.
 *
 * The World Guide's canonical format is Markdown. Each of these
 * extensions has been designed so its ``parseHTML`` matches the shape
 * emitted by our shared ``renderMarkdown`` renderer, and its
 * ``renderHTML`` matches what our Markdown serialiser
 * (``worldGuide-write.ts``) expects. The two ends meet in the middle
 * without any custom conversion tables.
 *
 * The custom nodes intentionally cover only the shapes the World Guide
 * schema declares — everything else is left to StarterKit's built-in
 * extensions (paragraph, heading, bold, italic, code, blockquote,
 * bullet/ordered lists, horizontal rule, code block).
 */

import { Node, mergeAttributes } from '@tiptap/core'


// ---------------------------------------------------------------------------
// Image — inline block image sourced from the World Guide upload endpoint.
// ---------------------------------------------------------------------------


export const WgImage = Node.create({
  name: 'wgImage',
  group: 'block',
  atom: true,
  draggable: true,
  addAttributes() {
    return {
      src: { default: '' },
      alt: { default: '' },
    }
  },
  parseHTML() {
    return [{ tag: 'img[src]' }]
  },
  renderHTML({ HTMLAttributes }) {
    return ['img', mergeAttributes(HTMLAttributes, {
      style: 'max-width:100%;height:auto;border-radius:6px;margin:12px 0;',
    })]
  },
})


// ---------------------------------------------------------------------------
// Callout — editable teal-tinted flat block that round-trips to
// ``> [!kind] title\n> body``.
// ---------------------------------------------------------------------------


const CALLOUT_KINDS = ['note', 'tip', 'warning', 'info'] as const


export const WgCallout = Node.create({
  name: 'wgCallout',
  group: 'block',
  content: 'block+',
  defining: true,

  addAttributes() {
    return {
      kind: {
        default: 'note',
        parseHTML: (el: HTMLElement) => {
          for (const c of Array.from(el.classList)) {
            const m = /^wg-callout-(note|tip|warning|info)$/.exec(c)
            if (m) return m[1]
          }
          return 'note'
        },
        renderHTML: (attrs: Record<string, unknown>) => {
          const kind = String(attrs.kind ?? 'note')
          return { class: `wg-callout wg-callout-${kind}` }
        },
      },
      title: {
        default: '',
        parseHTML: (el: HTMLElement) => el.querySelector('.wg-callout-title')?.textContent?.trim() ?? '',
        renderHTML: () => ({}),
      },
    }
  },

  parseHTML() {
    return [
      {
        tag: 'aside.wg-callout',
        // The editable content sits inside .wg-callout-body — telling
        // TipTap this keeps the title as a node attribute and lets the
        // body's children become the callout's inner content.
        contentElement: 'div.wg-callout-body',
      } as unknown as { tag: string },
    ]
  },

  renderHTML({ HTMLAttributes, node }) {
    const kind = String((node.attrs as { kind?: string }).kind ?? 'note')
    const title = String((node.attrs as { title?: string }).title ?? '')
    const attrs = mergeAttributes(HTMLAttributes, { class: `wg-callout wg-callout-${kind}` })
    return [
      'aside',
      attrs,
      title ? ['div', { class: 'wg-callout-title' }, title] : ['div', { class: 'wg-callout-title', style: 'display:none' }, ''],
      ['div', { class: 'wg-callout-body' }, 0],
    ]
  },
})


// ---------------------------------------------------------------------------
// TaskList / TaskItem — checklist support.
//
// Rendered as ``<ul class="wg-tasklist">`` matching the output of the
// shared ``renderMarkdown``. Each ``<li>`` carries ``data-checked``
// which our serialiser reads to emit ``- [ ]`` / ``- [x]``.
// ---------------------------------------------------------------------------


export const WgTaskList = Node.create({
  name: 'wgTaskList',
  group: 'block',
  content: 'wgTaskItem+',
  parseHTML() {
    return [{ tag: 'ul.wg-tasklist' }]
  },
  renderHTML({ HTMLAttributes }) {
    return ['ul', mergeAttributes(HTMLAttributes, {
      class: 'wg-tasklist',
      style: 'list-style:none;margin-left:0;padding-left:0;',
    }), 0]
  },
})


export const WgTaskItem = Node.create({
  name: 'wgTaskItem',
  group: 'wgTaskItem',
  content: 'inline*',
  defining: true,
  addAttributes() {
    return {
      checked: {
        default: false,
        parseHTML: (el: HTMLElement) => el.getAttribute('data-checked') === 'true',
        renderHTML: (attrs: Record<string, unknown>) => ({ 'data-checked': attrs.checked ? 'true' : 'false' }),
      },
    }
  },
  parseHTML() {
    return [{
      tag: 'li[data-checked]',
      getAttrs: (node: HTMLElement) => ({ checked: node.getAttribute('data-checked') === 'true' }),
    }]
  },
  renderHTML({ HTMLAttributes, node }) {
    const done = !!(node.attrs as { checked?: boolean }).checked
    const attrs = mergeAttributes(HTMLAttributes, {
      style: 'display:flex;gap:8px;align-items:flex-start;margin:4px 0;',
    })
    // A checkbox + inner content span. The checkbox is a display-only
    // toggle here — the actual state lives on the node attribute and
    // is round-tripped via the walker.
    return [
      'li',
      attrs,
      ['input', {
        type: 'checkbox',
        checked: done ? 'true' : undefined,
        style: 'margin-top:4px;',
        contenteditable: 'false',
      }],
      ['span', { style: done ? 'text-decoration:line-through;opacity:0.65;' : '' }, 0],
    ]
  },
})


// ---------------------------------------------------------------------------
// MarkdownBlock — read-only preserved fragment. Used for tables and any
// future Markdown feature Write mode does not natively edit.
// ---------------------------------------------------------------------------


export const WgMarkdownBlock = Node.create({
  name: 'wgMarkdownBlock',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      md: {
        default: '',
        parseHTML: (el: HTMLElement) => {
          const raw = el.getAttribute('data-md') ?? ''
          try { return decodeURIComponent(raw) }
          catch { return '' }
        },
        renderHTML: (attrs: Record<string, unknown>) => ({
          'data-md': encodeURIComponent(String(attrs.md ?? '')),
        }),
      },
      html: {
        default: '',
        parseHTML: (el: HTMLElement) => el.innerHTML,
        renderHTML: () => ({}),
      },
      kind: {
        default: 'table',
        parseHTML: (el: HTMLElement) => el.getAttribute('data-md-kind') ?? 'table',
        renderHTML: (attrs: Record<string, unknown>) => ({ 'data-md-kind': String(attrs.kind ?? 'table') }),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'div.wg-md-block' }]
  },

  renderHTML({ node, HTMLAttributes }) {
    const html = String((node.attrs as { html?: string }).html ?? '')
    return [
      'div',
      mergeAttributes(HTMLAttributes, { class: 'wg-md-block' }),
      // TipTap does not support a raw-HTML inner render slot directly;
      // the DOMSerializer walks the render-tree and stops at strings.
      // We attach the rendered HTML through a data attribute the
      // NodeView reads at runtime — see WriteModeEditor.tsx.
      ['div', { class: 'wg-md-block-preview', 'data-html': html }],
    ]
  },
})
