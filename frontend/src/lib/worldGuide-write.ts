/**
 * Converters between the World Guide's canonical Markdown and the
 * intermediate HTML the TipTap Write-mode editor consumes.
 *
 * Design rules:
 *   - Markdown is the only stored format.
 *   - Write mode reads Markdown → HTML → editor on mount.
 *   - Every edit is serialised back to Markdown before touching state.
 *   - Anything Write mode cannot round-trip losslessly (currently just
 *     tables) is preserved inside a MarkdownBlock envelope so the
 *     source text survives the round-trip untouched.
 *
 * The walker uses a duck-typed WNode shape rather than the real DOM
 * so the same code path exercises in the browser (via
 * ``htmlToMarkdown``) and inside the Node test runner (via
 * ``walkWNodeToMarkdown`` + hand-built WNode trees).
 */

// The `.ts` extension is required by Node's native TS stripping used
// by the frontend test script; tsc / Next resolve the same path.
// eslint-disable-next-line @typescript-eslint/consistent-type-imports
import { renderMarkdown } from './worldGuide.ts'


// ---------------------------------------------------------------------------
// Markdown → HTML for TipTap
// ---------------------------------------------------------------------------
//
// The existing ``renderMarkdown`` gets us most of the way. Tables are
// wrapped in a ``<div class="wg-md-block" data-md="...">`` element that
// our MarkdownBlock node parses on load and re-emits verbatim on
// serialisation. Everything else already lands in the shape the custom
// TipTap nodes recognise.

const TABLE_BLOCK_RE = /((?:^\|.*\|\s*\n?){2,})/gm

// Sentinel — alphanumeric only so ``renderMarkdown``'s HTML-escaping
// pass leaves it untouched. We rewrap the sentinel's paragraph back
// into a MarkdownBlock envelope after rendering.
const SENTINEL_PREFIX = 'WGTABLESENTINEL'


function extractTables(md: string): { stripped: string; tables: string[] } {
  const tables: string[] = []
  const stripped = md.replace(TABLE_BLOCK_RE, (match) => {
    const idx = tables.length
    tables.push(match.trim())
    return `\n\n${SENTINEL_PREFIX}${idx}\n\n`
  })
  return { stripped, tables }
}


function wrapTable(rendered: string, md: string): string {
  const encoded = encodeURIComponent(md)
  return (
    `<div class="wg-md-block" data-md-kind="table" data-md="${encoded}">` +
    rendered +
    `</div>`
  )
}


export function markdownToWriteHtml(md: string): string {
  const source = md ?? ''
  const { stripped, tables } = extractTables(source)

  let html = renderMarkdown(stripped)

  const sentinelRe = new RegExp(
    `<p>\\s*${SENTINEL_PREFIX}(\\d+)\\s*</p>`,
    'g',
  )
  html = html.replace(sentinelRe, (_m, i) => {
    const raw = tables[Number(i)]
    const rendered = renderMarkdown(raw)
    return wrapTable(rendered, raw)
  })

  if (!html.trim()) return '<p></p>'
  return html
}


// ---------------------------------------------------------------------------
// HTML → Markdown
// ---------------------------------------------------------------------------


/** Duck-typed element shape that both the real browser DOM and hand-
 *  built test trees satisfy. All fields are optional to keep test
 *  fixtures small — the walker treats absent values sensibly. */
export interface WNode {
  tag: string
  text?: string
  attrs?: Record<string, string>
  classes?: string[]
  children?: WNode[]
}


interface RenderCtx {
  listIndent: number
}


function defaultCtx(): RenderCtx {
  return { listIndent: 0 }
}


function isTextNode(n: WNode): boolean {
  return n.tag === '#text'
}


function hasClass(n: WNode, name: string): boolean {
  return (n.classes ?? []).includes(name)
}


function attr(n: WNode, name: string): string {
  return (n.attrs ?? {})[name] ?? ''
}


function walkChildren(n: WNode, ctx: RenderCtx): string {
  const out: string[] = []
  for (const c of n.children ?? []) out.push(walk(c, ctx))
  return out.join('')
}


function walkInline(n: WNode): string {
  const out: string[] = []
  for (const c of n.children ?? []) {
    out.push(walk(c, defaultCtx()).replace(/^\n+|\n+$/g, ''))
  }
  return out.join('')
}


function walk(node: WNode, ctx: RenderCtx): string {
  if (isTextNode(node)) return node.text ?? ''
  const tag = node.tag.toUpperCase()
  switch (tag) {
    case 'BODY': return walkChildren(node, ctx)

    case 'P': {
      const inner = walkInline(node)
      return inner.trim() ? `\n${inner}\n` : '\n'
    }
    case 'H1': return `\n# ${walkInline(node)}\n`
    case 'H2': return `\n## ${walkInline(node)}\n`
    case 'H3': return `\n### ${walkInline(node)}\n`
    case 'H4': return `\n#### ${walkInline(node)}\n`
    case 'H5': return `\n##### ${walkInline(node)}\n`
    case 'H6': return `\n###### ${walkInline(node)}\n`
    case 'BR': return '  \n'
    case 'HR': return '\n---\n'
    case 'STRONG':
    case 'B':   return `**${walkInline(node)}**`
    case 'EM':
    case 'I':   return `*${walkInline(node)}*`
    case 'CODE': {
      const inside = walkInline(node)
      return `\`${inside}\``
    }
    case 'PRE': {
      // Look for a child <code>; else use the concatenated text of every
      // child so paste from other sources still round-trips.
      const codeChild = (node.children ?? []).find((c) => c.tag.toUpperCase() === 'CODE')
      const body = codeChild ? textOf(codeChild) : textOf(node)
      return `\n\`\`\`\n${body}\n\`\`\`\n`
    }
    case 'A': {
      const href = attr(node, 'href').trim()
      const text = walkInline(node).trim() || href
      if (!href) return text
      return `[${text}](${href})`
    }
    case 'IMG': {
      const src = attr(node, 'src')
      const alt = attr(node, 'alt')
      return src ? `![${alt}](${src})` : ''
    }
    case 'BLOCKQUOTE': {
      const inner = walkChildren(node, ctx).trim()
      const lines = inner.split('\n').map((l) => (l ? `> ${l}` : '>'))
      return `\n${lines.join('\n')}\n`
    }
    case 'ASIDE': {
      if (hasClass(node, 'wg-callout')) {
        const kind = detectCalloutKind(node)
        const title = childrenText(node, 'wg-callout-title').trim()
        const bodyEl = childOfClass(node, 'wg-callout-body')
        const body = bodyEl ? walkChildren(bodyEl, ctx).trim() : ''
        const first = title ? `[!${kind}] ${title}` : `[!${kind}]`
        const bodyLines = body ? body.split('\n') : []
        const all = [first, ...bodyLines].map((l) => (l ? `> ${l}` : '>')).join('\n')
        return `\n${all}\n`
      }
      return walkChildren(node, ctx)
    }
    case 'UL': {
      if (hasClass(node, 'wg-tasklist')) {
        const items: string[] = []
        for (const li of (node.children ?? [])) {
          if (li.tag.toUpperCase() !== 'LI') continue
          const done = attr(li, 'data-checked') === 'true'
          const inner = walkInline(li).trim()
          items.push(`- [${done ? 'x' : ' '}] ${inner}`)
        }
        return `\n${items.join('\n')}\n`
      }
      const nested = ctx.listIndent > 0
      const items: string[] = []
      for (const li of (node.children ?? [])) {
        if (li.tag.toUpperCase() !== 'LI') continue
        const inner = walkListItem(li, { listIndent: ctx.listIndent + 1 })
        items.push(`${' '.repeat(ctx.listIndent * 2)}- ${inner}`)
      }
      return `${nested ? '' : '\n'}${items.join('\n')}${nested ? '' : '\n'}`
    }
    case 'OL': {
      const nested = ctx.listIndent > 0
      const items: string[] = []
      let n = 1
      for (const li of (node.children ?? [])) {
        if (li.tag.toUpperCase() !== 'LI') continue
        const inner = walkListItem(li, { listIndent: ctx.listIndent + 1 })
        items.push(`${' '.repeat(ctx.listIndent * 2)}${n}. ${inner}`)
        n++
      }
      return `${nested ? '' : '\n'}${items.join('\n')}${nested ? '' : '\n'}`
    }
    case 'LI': return walkListItem(node, ctx)
    case 'DIV': {
      if (hasClass(node, 'wg-md-block')) {
        const encoded = attr(node, 'data-md')
        try {
          return `\n${decodeURIComponent(encoded)}\n`
        } catch {
          return ''
        }
      }
      return walkChildren(node, ctx)
    }
    case 'TABLE':  return `\n${tableToMarkdown(node)}\n`
    case 'FIGURE': return walkChildren(node, ctx)
    default:
      return walkChildren(node, ctx)
  }
}


function walkListItem(li: WNode, ctx: RenderCtx): string {
  const parts: string[] = []
  for (const child of (li.children ?? [])) {
    const t = child.tag.toUpperCase()
    if (t === 'UL' || t === 'OL') {
      parts.push('\n' + walk(child, ctx).replace(/^\n+|\n+$/g, ''))
    } else if (t === 'P') {
      parts.push(walkInline(child))
    } else {
      parts.push(walk(child, ctx))
    }
  }
  return parts.join('').replace(/\n+$/, '')
}


function detectCalloutKind(el: WNode): string {
  for (const cls of (el.classes ?? [])) {
    const m = /^wg-callout-(note|tip|warning|info)$/.exec(cls)
    if (m) return m[1]
  }
  return 'note'
}


function childOfClass(el: WNode, cls: string): WNode | null {
  for (const c of (el.children ?? [])) {
    if (c.tag !== '#text' && hasClass(c, cls)) return c
    const nested = childOfClass(c, cls)
    if (nested) return nested
  }
  return null
}


function childrenText(el: WNode, cls: string): string {
  const target = childOfClass(el, cls)
  return target ? textOf(target) : ''
}


function textOf(el: WNode): string {
  if (isTextNode(el)) return el.text ?? ''
  return (el.children ?? []).map(textOf).join('')
}


function tableToMarkdown(el: WNode): string {
  const rows: string[][] = []
  const collectRows = (n: WNode) => {
    if (n.tag.toUpperCase() === 'TR') {
      const cells: string[] = []
      for (const cell of (n.children ?? [])) {
        const t = cell.tag.toUpperCase()
        if (t !== 'TD' && t !== 'TH') continue
        cells.push(walkInline(cell).replace(/\|/g, '\\|').trim())
      }
      rows.push(cells)
    } else {
      for (const c of (n.children ?? [])) collectRows(c)
    }
  }
  collectRows(el)
  if (rows.length === 0) return ''
  const header = rows[0]
  const align = header.map(() => '---')
  const body = rows.slice(1)
  return [
    `| ${header.join(' | ')} |`,
    `| ${align.join(' | ')} |`,
    ...body.map((r) => `| ${r.join(' | ')} |`),
  ].join('\n')
}


/** Serialise a hand-built WNode tree to Markdown. Exposed for tests. */
export function walkWNodeToMarkdown(root: WNode): string {
  const out = walk(root, defaultCtx())
  return out.replace(/\n{3,}/g, '\n\n').trim() + '\n'
}


/** Adapter: turn a real DOM element into a WNode tree the walker can
 *  consume. Called from the browser path only. */
export function domToWNode(el: Element): WNode {
  const attrs: Record<string, string> = {}
  for (const a of Array.from(el.attributes)) attrs[a.name] = a.value
  const children: WNode[] = []
  for (const child of Array.from(el.childNodes)) {
    if (child.nodeType === 3 /* text */) {
      children.push({ tag: '#text', text: child.textContent ?? '' })
    } else if (child.nodeType === 1 /* element */) {
      children.push(domToWNode(child as Element))
    }
  }
  return {
    tag: el.tagName.toUpperCase(),
    attrs,
    classes: Array.from(el.classList),
    children,
  }
}


/** Browser entry point. Parses HTML via DOMParser, converts to Markdown. */
export function htmlToMarkdown(html: string): string {
  if (!html || !html.trim()) return ''
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html')
  const body = doc.body
  return walkWNodeToMarkdown(domToWNode(body))
}


// ---------------------------------------------------------------------------
// Small builder used by tests (and callable from any code needing to
// construct WNode trees for other purposes later on).
// ---------------------------------------------------------------------------


export function el(
  tag: string,
  attrsOrChildren?: Record<string, string> | WNode[],
  children?: WNode[],
): WNode {
  if (Array.isArray(attrsOrChildren)) {
    return { tag, children: attrsOrChildren }
  }
  const attrs = attrsOrChildren ?? {}
  const classes = attrs.class ? attrs.class.split(/\s+/).filter(Boolean) : []
  const cleanAttrs = { ...attrs }
  delete cleanAttrs.class
  return { tag, attrs: cleanAttrs, classes, children: children ?? [] }
}


export function text(t: string): WNode {
  return { tag: '#text', text: t }
}
